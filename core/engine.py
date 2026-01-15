import time
import traceback
from datetime import datetime, timedelta
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
        self.state_mgr = StateManager()  # 状态与持久化
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
    # 🛠️ 辅助函数: 获取当前余额
    # ==================================================================
    def _get_available_balance(self, symbol):
        """获取可用 USDT"""
        if self.run_mode == "PAPER":
            # 影子模式：从本地 json 读取
            return self.state_mgr.get_balance()
        else:
            # 实盘模式：从交易所获取 (建议对接 exchange.fetch_free_balance)
            # 暂时返回预设值或报错，防止实盘裸奔
            logger.warning("实盘余额接口需对接 exchange，暂时返回 0")
            return 0.0

    # ==================================================================
    # 🚀 主循环
    # ==================================================================
    def start(self):
        logger.info(f"🚀 引擎运行中... 当前虚拟净值: {self.state_mgr.get_balance():.2f} U")
        while True:
            try:
                for symbol in self.symbols:
                    self._process_symbol_tick(symbol)
                time.sleep(20)  # 轮询间隔
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"❌ 循环异常: {e}")
                traceback.print_exc()
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

        # 2. 实时风控 (每20秒检查一次)
        self._check_risk_management(symbol, current_price)

        # 3. 信号决策 (仅在 K线收盘时触发)
        if current_candle_ts > self.last_candle_time[symbol]:
            logger.info(f"🕯️ [{symbol}] K线收盘确认 -> AI 介入分析...")

            confirmed_df = df_candles.iloc[:-1]
            df_ind = strategy.calculate_indicators(confirmed_df)
            confirmed_row = df_ind.iloc[-1]

            # 生成 AI 摘要
            tech_summary = {
                'trend': 'UP' if confirmed_row['EMA_55'] > confirmed_row['EMA_200'] else 'DOWN',
                'rsi': round(confirmed_row['RSI_14'], 2),
                'price_loc': 'ABOVE' if confirmed_row['close'] > confirmed_row['EMA_200'] else 'BELOW'
            }

            news = self.news_loader.get_latest_news(limit=5)
            ai_res = self.ai_analyzer.analyze(symbol, confirmed_row['close'], tech_summary, news)

            logger.info(f"🧠 [AI结果] {ai_res.get('regime')} (信心:{ai_res.get('confidence')})")

            # 注入 AI 信号供策略使用
            row_for_strategy = confirmed_row.copy()
            row_for_strategy['AI_REGIME'] = ai_res.get('regime', 'SHOCK_SIDEWAYS')

            # 策略计算 (这里会包含 趋势否决/状态锁定 逻辑)
            signal = strategy.check_signal(row_for_strategy)
            raw_action = signal.get('action')

            if not raw_action or raw_action == "WAIT":
                wait_reason = signal.get('reason', '未触发开仓条件')
                logger.info(f"🚦 [策略判定] 观望 (WAIT) - {wait_reason}")
            else:
                regime_used = signal.get('regime', 'UNKNOWN')
                logger.info(f"🚦 [策略判定] 信号触发: {raw_action} | 模式: {regime_used}")

            # 执行交易
            if raw_action == "BUY":
                self._execute_open(symbol, current_price, signal, ai_res.get('reasoning'))
            elif raw_action == "SELL":
                # 注意：策略发出的 SELL 通常是反转信号，非止盈止损
                self._execute_close(symbol, current_price, f"策略反转卖出: {raw_action}")

            self.last_candle_time[symbol] = current_candle_ts

    def _check_risk_management(self, symbol, current_price):
        position = self.state_mgr.get_position(symbol)
        if not position: return

        # === 基础数据读取 ===
        entry_price = float(position['entry_price'])
        sl_pct = position.get('sl_pct', 0.05)

        # 读取移动止盈配置 (默认开启，参数与 backtest 默认值保持一致)
        # 注意：这些参数最好在 _execute_open 时存入 position，这里简化处理用默认值
        use_trailing = True
        trailing_start = 0.03  # 盈利 3% 后激活
        trailing_drop = 0.02  # 回撤 2% 触发

        # 读取历史最高价 (从 state 中恢复，如果没有则默认为开仓价)
        highest_price = float(position.get('highest_price', entry_price))

        # ============================================================
        # 1. 硬止损检查 (Hard Stop Loss)
        # ============================================================
        pnl_pct = (current_price - entry_price) / entry_price
        if pnl_pct <= -sl_pct:
            logger.warning(f"🛑 [{symbol}] 触发硬止损! 当前跌幅: {pnl_pct * 100:.2f}%")
            self._execute_close(symbol, current_price, "硬止损触发 (STOP_LOSS)")
            return

        # ============================================================
        # 2. 移动止盈检查 (Trailing Profit) - 补全这一块！
        # ============================================================
        if use_trailing:
            # A. 更新最高价 (High Water Mark)
            if current_price > highest_price:
                highest_price = current_price
                # 🔥 关键：必须持久化保存最高价，防止程序重启丢失
                self.state_mgr.update_position_high(symbol, highest_price)
                # (可选) 打印日志太频繁可注释掉
                # logger.info(f"📈 [{symbol}] 创新高: {highest_price} (浮盈 {(highest_price/entry_price-1)*100:.1f}%)")

            # B. 检查是否满足激活条件
            activation_price = entry_price * (1 + trailing_start)

            if highest_price >= activation_price:
                # C. 计算回撤触发价
                stop_price = highest_price * (1 - trailing_drop)

                # D. 触发卖出
                if current_price < stop_price:
                    drop_pct = (highest_price - current_price) / highest_price
                    logger.warning(f"🏄 [{symbol}] 触发移动止盈! 最高: {highest_price}, 回撤: {drop_pct * 100:.2f}%")
                    self._execute_close(symbol, current_price, "移动止盈 (TRAILING_PROFIT)")
                    return

    # ==================================================================
    # 💰 开仓执行 (同步了 动态仓位 + 冷却机制)
    # ==================================================================
    def _execute_open(self, symbol, price, signal, reason):
        if self.state_mgr.get_position(symbol): return

        # 🔥 [新增] 1. 检查止损冷却
        # StateManager 需要实现 get_cooldown 方法
        cooldown_ts = self.state_mgr.get_cooldown(symbol)
        if cooldown_ts and time.time() < cooldown_ts:
            remaining = int(cooldown_ts - time.time())
            logger.warning(f"❄️ [冷却中] 拒绝开仓 (上次止损后冷静期，剩余 {remaining // 60} 分钟)")
            return

        # 2. 获取基础余额
        balance = self._get_available_balance(symbol)

        # ============================================================
        # 🔥 [新增] 2. 动态仓位权重 (Winter Mode)
        # ============================================================
        # 获取经过策略修正后的 Regime (例如已被降级为 BEAR_CRASH)
        strategy_regime = signal.get('regime', 'SHOCK_SIDEWAYS')
        size_multiplier = 1.0

        if strategy_regime == 'BULL_TREND':
            size_multiplier = 1.0  # 满仓
        elif strategy_regime == 'SHOCK_SIDEWAYS':
            size_multiplier = 0.5  # 半仓
        elif strategy_regime == 'BEAR_CRASH':
            size_multiplier = 0.25  # 极寒模式 1/4仓

        # 计算有效可用资金
        effective_balance = balance * size_multiplier
        logger.info(f"⚖️ 动态仓位控制: {strategy_regime} -> 权重 {size_multiplier} -> 可用 {effective_balance:.2f} U")
        # ============================================================

        # 3. 计算买入数量
        qty = self.pos_manager.calculate_buy_size(price, effective_balance)
        if qty <= 0:
            logger.warning(f"⚠️ 余额不足或仓位过小，无法开仓")
            return

        cost = qty * price
        sl_pct = signal.get('sl_pct', 0.05)

        logger.info(f"🚀 [SIGNAL] {symbol} 买入执行")
        logger.info(f"   💵 价格: {price} | 数量: {qty:.4f}")
        logger.info(f"   💳 消耗: {cost:.2f} U")

        # 4. 执行分支
        if self.run_mode == "PAPER":
            new_balance = balance - cost
            self.state_mgr.update_balance(new_balance)
        else:
            # 实盘接口
            pass

        # 5. 记录持仓 & 清除冷却
        self.state_mgr.update_position(symbol, price, qty, sl_pct=sl_pct)
        # 开仓成功，清除之前的冷却记录
        self.state_mgr.set_cooldown(symbol, 0)

        self.notifier.send_alert(f"🚀 {symbol} 开仓 ({strategy_regime})",
                                 f"AI: {reason}\n权重: {size_multiplier}\n消耗: {cost:.2f} U")
        self.recorder.log_trade(
            mode=self.run_mode, symbol=symbol, action="BUY", price=price, qty=qty,
            balance=new_balance if self.run_mode == "PAPER" else 0,
            reason=reason, ai_regime=strategy_regime, fee=cost * 0.001
        )

    # ==================================================================
    # 📉 平仓执行 (同步了 冷却设置)
    # ==================================================================
    def _execute_close(self, symbol, price, reason):
        position = self.state_mgr.get_position(symbol)
        if not position: return

        qty = float(position['qty'])
        entry_price = float(position['entry_price'])

        revenue = qty * price
        pnl = revenue - (qty * entry_price)
        pnl_pct = pnl / (qty * entry_price)

        logger.info(f"📉 [CLOSE] {symbol} 卖出执行")
        logger.info(f"   💵 价格: {price} | 盈亏: {pnl_pct * 100:.2f}% ({pnl:+.2f} U)")

        # ============================================================
        # 🔥 [新增] 止损后设置 12小时 冷却
        # ============================================================
        if "STOP_LOSS" in reason or "止损" in reason:
            cooldown_until = datetime.now() + timedelta(hours=12)
            # 存入 StateManager 持久化，防止重启失效
            self.state_mgr.set_cooldown(symbol, cooldown_until.timestamp())
            logger.warning(f"❄️ 触发止损，进入冷却期直到 {cooldown_until.strftime('%Y-%m-%d %H:%M')}")
        # ============================================================

        # 1. 执行分支
        if self.run_mode == "PAPER":
            current_balance = self.state_mgr.get_balance()
            new_balance = current_balance + revenue
            self.state_mgr.update_balance(new_balance)
        else:
            # 实盘接口
            pass

        # 2. 清除持仓
        self.state_mgr.clear_position(symbol)

        self.notifier.send_alert(
            f"📉 {symbol} 平仓",
            f"盈亏: {pnl:+.2f} U ({pnl_pct * 100:.2f}%)\n原因: {reason}\n余额: {self.state_mgr.get_balance():.2f}"
        )

        self.recorder.log_trade(
            mode=self.run_mode, symbol=symbol, action="SELL", price=price, qty=qty,
            balance=new_balance if self.run_mode == "PAPER" else 0,
            reason=reason, pnl=pnl, pnl_pct=pnl_pct, fee=revenue * 0.001
        )