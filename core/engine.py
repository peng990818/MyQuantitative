import traceback
from datetime import datetime, timedelta
from utils.config_loader import ConfigLoader
from utils.logger import logger

# === 引入模块 ===
from modules.market.loader import MarketDataLoader
from modules.analysis.technical import TechnicalAnalyzer
from modules.sentiment.news import NewsFetcher
from modules.llm.factory import LLMFactory
from modules.strategy.evaluator import StrategyEvaluator
from core.position import PositionManager

# 🔥 新增的两个模块
from utils.state_manager import StateManager
from modules.notification.sender import EmailNotifier


class TradingEngine:
    def __init__(self):
        logger.info("⚙️ 正在启动核心交易引擎 (v2.0 Gmail版)...")
        self.cfg = ConfigLoader()

        # 初始化各子模块
        self.market = MarketDataLoader()
        self.tech_analyzer = TechnicalAnalyzer()
        self.news_fetcher = NewsFetcher()
        self.llm = LLMFactory.create_llm()
        self.evaluator = StrategyEvaluator()
        self.pos_manager = PositionManager()

        # 🔥 初始化记账本和发信员
        self.state_mgr = StateManager()
        self.notifier = EmailNotifier()

        self.symbols = self.cfg.get("symbols", ["BTC/USDT"])
        self.timeframe = self.cfg.get("timeframe", "1h")
        self.run_mode = self.cfg.get("run_mode", "PAPER")
        self.sentiment_cache = {}

        self.stop_loss_pct = self.cfg.get("risk_management.stop_loss", 0.05)  # 默认 5%
        self.take_profit_pct = self.cfg.get("risk_management.take_profit", 0.20)  # 默认 20%

        logger.info(f"🛡️ 风控系统启动 | 止损: -{self.stop_loss_pct * 100}% | 止盈: +{self.take_profit_pct * 100}%")

    def start(self):
        logger.info(f"\n⏰ --- 开始巡航: {datetime.now().strftime('%H:%M:%S')} [{self.run_mode}] ---")
        for symbol in self.symbols:
            try:
                self._process_symbol(symbol)
            except Exception as e:
                logger.error(f"❌ 处理 {symbol} 异常: {e}")
                logger.debug(traceback.format_exc())

    def _process_symbol(self, symbol):
        logger.info(f"🔍 分析标的: {symbol}")

        # 1. 行情
        df = self.market.fetch_ohlcv(symbol, self.timeframe)
        if df is None or df.empty: return
        current_price = df.iloc[-1]['close']

        # 2. 指标
        df_ind = self.tech_analyzer.calculate_indicators(df)
        state = self.tech_analyzer.get_market_state(df_ind.iloc[-1])

        # 3. 评分逻辑 (这里必须修复！)
        rsi = state.get('momentum', {}).get('rsi', 50)

        # 🔥 [修复 1] RSI 分数反转
        # RSI 越低(30)越该买，分数应该越高(70)
        # RSI 越高(70)越该卖，分数应该越低(30)
        tech_score = 100 - rsi

        # 趋势分
        ema_s = state.get('trend', {}).get('ema_short', 0)
        ema_l = state.get('trend', {}).get('ema_long', 0)
        trend_score = 80 if ema_s > ema_l else 20

        # 🔥 [修复 2] 恢复 AI 智能 (实盘不能写死为 0)
        # 如果你想省钱先填 0 也可以，但最终形态应该是调用 self._get_smart_sentiment(symbol)
        sentiment_score = self._get_smart_sentiment(symbol)
        # sentiment_score = 0 # 调试/省钱模式用这行

        # 4. 决策 (注意第一个参数传 tech_score 而不是 rsi)
        decision = self.evaluator.evaluate(tech_score, sentiment_score, trend_score)

        logger.info(f"📊 评分: {decision['final_score']} -> {decision['action']}")
        logger.info(f"   详情: Tech(RSI:{rsi:.1f}->{tech_score:.1f}) + AI({sentiment_score}) + Trend({trend_score})")

        # 5. 进入交易处理逻辑
        self._handle_trade(symbol, decision, current_price)

    def _handle_trade(self, symbol, decision, price):
        """
        处理交易，增加了强制止盈止损逻辑
        """
        # 1. 获取策略给出的建议
        strategy_action = decision['action']
        details = decision['details']['breakdown']

        # 2. 获取持仓状态
        position = self.state_mgr.get_position(symbol)

        # ============================================
        # 🔥 核心修改：风控优先 (Risk First)
        # ============================================
        final_action = strategy_action  # 默认听策略的
        force_reason = ""

        if position:
            entry_price = position['entry_price']
            # 计算当前盈亏率 (例如: -0.06 代表亏 6%)
            current_pnl_pct = (price - entry_price) / entry_price

            # A. 检查止损 (Stop Loss)
            if current_pnl_pct <= -self.stop_loss_pct:
                logger.warning(f"🛑 {symbol} 触发强制止损! 当前亏损: {current_pnl_pct * 100:.2f}%")
                final_action = "SELL"
                force_reason = " [强制止损]"

            # B. 检查止盈 (Take Profit)
            elif current_pnl_pct >= self.take_profit_pct:
                logger.info(f"🎉 {symbol} 触发强制止盈! 当前盈利: {current_pnl_pct * 100:.2f}%")
                final_action = "SELL"
                force_reason = " [强制止盈]"

        # ============================================
        # 下面是执行逻辑 (根据 final_action 执行)
        # ============================================

        # === 情况 A: 买入 ===
        if final_action == "BUY":
            if not position:
                balance = self.market.get_balance_usdt()
                qty = self.pos_manager.calculate_buy_size(price, balance)

                if qty > 0:
                    logger.info(f"🚀 [执行买入] {symbol} @ {price}")
                    # 实盘下单...
                    self.state_mgr.update_position(symbol, price, qty)
                    self.notifier.send_alert("BUY", symbol, price, qty, details)
            else:
                logger.info("🔒 已有持仓，跳过买入")

        # === 情况 B: 卖出 (策略卖出 OR 风控强制卖出) ===
        elif final_action == "SELL":
            if position:
                entry_price = position['entry_price']
                qty = position['qty']

                pnl_pct = (price - entry_price) / entry_price * 100

                # 判断类型: 是止损、止盈、还是策略离场?
                if "止损" in force_reason:
                    trade_type = "SL"
                elif "止盈" in force_reason:
                    trade_type = "TP"
                else:
                    # 如果不是强制触发的，根据盈亏自然判断
                    trade_type = "TP" if pnl_pct > 0 else "SL"

                # 在详细信息里加上风控备注
                details += force_reason

                logger.info(f"📉 [执行卖出] {symbol} {force_reason} | 盈亏: {pnl_pct:.2f}%")
                # 实盘下单...

                self.state_mgr.clear_position(symbol)
                self.notifier.send_alert(trade_type, symbol, price, qty, details, pnl_pct)
            else:
                # 只有当策略喊卖出，且我们手里没货时，才会走到这里
                if not force_reason:
                    logger.info("🔒 空仓状态，跳过卖出")