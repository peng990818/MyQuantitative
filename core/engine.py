import time
import traceback
from datetime import datetime
from utils.config_loader import ConfigLoader
from utils.logger import logger

# === 基础组件 ===
from modules.market.stream import MarketStream
from modules.sentiment.news import RSSNewsLoader
from modules.sentiment.recorder import TradeRecorder
from modules.analysis.analyzer import MarketRegimeAnalyzer
from strategies.sniper_router import SniperRouterStrategy

# === 管理组件 ===
from core.position import PositionManager
from utils.state_manager import StateManager
from modules.notification.sender import EmailNotifier


class TradingEngine:
    def __init__(self):
        self.cfg = ConfigLoader()

        # 1. 关键配置
        self.run_mode = self.cfg.get("run_mode", "PAPER").upper()  # REAL 或 PAPER
        self.symbols = self.cfg.get("symbols", ["BTC/USDT"])
        self.timeframe = self.cfg.get("timeframe", "1h")

        logger.info(
            f"⚙️ 启动交易引擎 | 模式: 【{self.run_mode}】 (影子模式)" if self.run_mode == "PAPER" else f"⚠️ 启动交易引擎 | 模式: 【实盘金钱模式】")

        # 2. 初始化组件
        self.news_loader = RSSNewsLoader()
        self.ai_analyzer = MarketRegimeAnalyzer()
        self.pos_manager = PositionManager()
        self.state_mgr = StateManager()  # 现在的 StateManager 支持余额管理了
        self.notifier = EmailNotifier()

        self.recorder = TradeRecorder("data/trade_history.csv")

        self.streams = {}
        self.strategies = {}
        self.last_candle_time = {}

        self._init_components()

    def _init_components(self):
        for symbol in self.symbols:
            self.streams[symbol] = MarketStream(symbol=symbol, timeframe=self.timeframe)
            self.strategies[symbol] = SniperRouterStrategy(symbol=symbol)
            self.last_candle_time[symbol] = None

    # ==================================================================
    # 🛠️ 辅助函数: 获取当前余额 (兼容 实盘/模拟)
    # ==================================================================
    def _get_available_balance(self, symbol):
        """获取可用 USDT"""
        if self.run_mode == "PAPER":
            # 影子模式：从本地 json 读取
            return self.state_mgr.get_balance()
        else:
            # 实盘模式：从交易所获取 (需要 streams 支持 fetch_balance)
            # 这里简化处理，实盘暂未对接 fetch_balance，你可以后续加上
            # return self.streams[symbol].exchange.fetch_free_balance()['USDT']
            logger.warning("实盘余额接口未对接，暂时返回 0")
            return 0.0

    # ==================================================================
    # 🚀 主循环 (保持不变)
    # ==================================================================
    def start(self):
        logger.info(f"🚀 引擎运行中... 当前虚拟净值: {self.state_mgr.get_balance():.2f} U")
        while True:
            try:
                for symbol in self.symbols:
                    self._process_symbol_tick(symbol)
                time.sleep(20)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"❌ 循环异常: {e}")
                time.sleep(10)

    def _process_symbol_tick(self, symbol):
        stream = self.streams[symbol]
        strategy = self.strategies[symbol]

        # 1. 获取行情
        df_candles = stream.get_latest_candles(limit=300)
        if df_candles is None or df_candles.empty: return

        current_active_candle = df_candles.iloc[-1]
        current_price = current_active_candle['close']
        current_candle_ts = current_active_candle['timestamp']

        # 初始化时间戳
        if self.last_candle_time[symbol] is None:
            self.last_candle_time[symbol] = current_candle_ts
            return

        # 2. 实时风控
        self._check_risk_management(symbol, current_price)

        # 3. 信号决策 (K线收盘)
        if current_candle_ts > self.last_candle_time[symbol]:
            logger.info(f"🕯️ [{symbol}] K线收盘确认 -> AI 介入分析...")

            confirmed_df = df_candles.iloc[:-1]
            df_ind = strategy.calculate_indicators(confirmed_df)
            confirmed_row = df_ind.iloc[-1]

            tech_summary = {
                'trend': 'UP' if confirmed_row['EMA_55'] > confirmed_row['EMA_200'] else 'DOWN',
                'rsi': round(confirmed_row['RSI_14'], 2),
                'price_loc': 'ABOVE' if confirmed_row['close'] > confirmed_row['EMA_200'] else 'BELOW'
            }

            news = self.news_loader.get_latest_news(limit=5)
            ai_res = self.ai_analyzer.analyze(symbol, confirmed_row['close'], tech_summary, news)

            regime = ai_res.get('regime', 'SHOCK_SIDEWAYS')
            confidence = ai_res.get('confidence', 0)
            reason = ai_res.get('reasoning', '无理由')
            logger.info(f"🧠 [AI结果] {regime} (信心:{confidence})")
            logger.info(f"   📝 理由: {reason}")

            row_for_strategy = confirmed_row.copy()
            row_for_strategy['AI_REGIME'] = ai_result = ai_res.get('regime', 'SHOCK_SIDEWAYS')

            signal = strategy.check_signal(row_for_strategy)

            # 🔥🔥🔥 [修正] 处理 None 值的打印逻辑 🔥🔥🔥
            raw_action = signal.get('action')

            # 如果 raw_action 是 None (空) 或者 "WAIT" (字符串)，都算观望
            if not raw_action or raw_action == "WAIT":
                # 尝试获取拒绝理由 (部分策略逻辑可能会返回 reason)
                wait_reason = signal.get('reason', '未触发开仓条件')
                logger.info(f"🚦 [策略判定] 观望 (WAIT) - {wait_reason}")
            else:
                logger.info(f"🚦 [策略判定] 信号触发: {raw_action} !!!")
            # 🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥

            # 下面的判断也要跟着改，用 raw_action
            if raw_action == "BUY":
                self._execute_open(symbol, current_price, signal, ai_res.get('reasoning'))
            elif raw_action == "SELL":
                self._execute_close(symbol, current_price, f"策略卖出: {regime}")

            self.last_candle_time[symbol] = current_candle_ts

    def _check_risk_management(self, symbol, current_price):
        position = self.state_mgr.get_position(symbol)
        if not position: return

        entry_price = float(position['entry_price'])
        sl_pct = position.get('sl_pct', 0.05)
        pnl_pct = (current_price - entry_price) / entry_price

        if pnl_pct <= -sl_pct:
            logger.warning(f"🛑 [{symbol}] 触发风控止损! 跌幅: {pnl_pct * 100:.2f}%")
            self._execute_close(symbol, current_price, "硬止损触发")

    # ==================================================================
    # 💰 影子模式核心：开仓执行
    # ==================================================================
    def _execute_open(self, symbol, price, signal, reason):
        if self.state_mgr.get_position(symbol): return

        # 1. 获取余额 (如果是 PAPER，就是虚拟余额)
        balance = self._get_available_balance(symbol)

        # 2. 计算买入数量
        qty = self.pos_manager.calculate_buy_size(price, balance)
        if qty <= 0:
            logger.warning(f"⚠️ 余额不足 ({balance:.2f} U)，无法开仓")
            return

        cost = qty * price
        sl_pct = signal.get('sl_pct', 0.05)

        logger.info(f"🚀 [SIGNAL] {symbol} 买入执行")
        logger.info(f"   💵 价格: {price} | 数量: {qty:.4f}")
        logger.info(f"   💳 消耗: {cost:.2f} U")

        # 3. 分支执行
        if self.run_mode == "PAPER":
            # --- 影子模式 ---
            new_balance = balance - cost
            self.state_mgr.update_balance(new_balance)
            logger.info(f"   📝 [影子] 虚拟余额更新: {balance:.2f} -> {new_balance:.2f}")
        else:
            # --- 实盘模式 ---
            # self.streams[symbol].exchange.create_market_buy_order(...)
            pass

        # 4. 记录持仓 (通用)
        self.state_mgr.update_position(symbol, price, qty, sl_pct=sl_pct)
        self.notifier.send_alert(f"🚀 {symbol} 开仓 (模拟)", f"AI: {reason}\n消耗: {cost:.2f} U")

        self.recorder.log_trade(
            mode=self.run_mode,
            symbol=symbol,
            action="BUY",
            price=price,
            qty=qty,
            balance=new_balance,
            reason=reason,
            ai_regime=signal.get('AI_REGIME', 'N/A'),
            fee=qty * price * 0.001  # 估算千1手续费
        )

    # ==================================================================
    # 💰 影子模式核心：平仓执行
    # ==================================================================
    def _execute_close(self, symbol, price, reason):
        position = self.state_mgr.get_position(symbol)
        if not position: return

        qty = float(position['qty'])
        entry_price = float(position['entry_price'])

        revenue = qty * price  # 卖出得到的钱
        pnl = revenue - (qty * entry_price)
        pnl_pct = pnl / (qty * entry_price)

        logger.info(f"📉 [CLOSE] {symbol} 卖出执行")
        logger.info(f"   💵 价格: {price} | 盈亏: {pnl_pct * 100:.2f}% ({pnl:+.2f} U)")

        # 1. 分支执行
        if self.run_mode == "PAPER":
            # --- 影子模式 ---
            current_balance = self.state_mgr.get_balance()
            new_balance = current_balance + revenue
            self.state_mgr.update_balance(new_balance)
            logger.info(f"   📝 [影子] 资金回笼: {new_balance:.2f} U")
        else:
            # --- 实盘模式 ---
            # self.streams[symbol].exchange.create_market_sell_order(...)
            pass

        # 2. 清除持仓 (通用)
        self.state_mgr.clear_position(symbol)

        self.notifier.send_alert(
            f"📉 {symbol} 平仓 (模拟)",
            f"卖出价: {price}\n盈亏: {pnl:+.2f} U ({pnl_pct * 100:.2f}%)\n原因: {reason}\n当前余额: {self.state_mgr.get_balance():.2f}"
        )

        # 🔥 2. 写入 CSV 日志
        # 这里我们需要获取当时的 AI 状态，或者简单记录原因
        self.recorder.log_trade(
            mode=self.run_mode,
            symbol=symbol,
            action="SELL",
            price=price,
            qty=qty,
            balance=new_balance,
            reason=reason,
            pnl=pnl,
            pnl_pct=pnl_pct,
            fee=revenue * 0.001
        )