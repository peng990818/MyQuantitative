import traceback
import time
from datetime import datetime, timedelta
from utils.config_loader import ConfigLoader
from utils.logger import logger

# === 引入核心模块 ===
from modules.market.loader import MarketDataLoader
from modules.analysis.technical import TechnicalAnalyzer
from modules.sentiment.news import NewsFetcher
from modules.llm.factory import LLMFactory
from modules.strategy.evaluator import StrategyEvaluator
from core.position import PositionManager
from utils.state_manager import StateManager
from modules.notification.sender import EmailNotifier


class TradingEngine:
    def __init__(self):
        logger.info("⚙️ 正在启动核心交易引擎 (v2.0 详细日志版)...")
        self.cfg = ConfigLoader()

        # 1. 初始化各子模块
        self.market = MarketDataLoader()
        self.tech_analyzer = TechnicalAnalyzer()

        # 尝试初始化 AI 模块
        try:
            self.news_fetcher = NewsFetcher()
            self.llm = LLMFactory.create_llm()
            self.ai_enabled = True
            logger.info("🧠 AI 智能分析模块: [已启用]")
        except Exception as e:
            logger.warning(f"⚠️ AI 模块初始化受限: {e}")
            self.ai_enabled = False

        self.evaluator = StrategyEvaluator()
        self.pos_manager = PositionManager()
        self.state_mgr = StateManager()
        self.notifier = EmailNotifier()

        # 加载参数
        self.symbols = self.cfg.get("symbols", ["BTC/USDT"])
        self.timeframe = self.cfg.get("timeframe", "15m")
        self.run_mode = self.cfg.get("run_mode", "PAPER")

        self.stop_loss_pct = self.cfg.get("risk_management.stop_loss", 0.04)
        self.take_profit_pct = self.cfg.get("risk_management.take_profit", 0.03)

        # 情感分析缓存
        self.sentiment_cache = {}
        self.sentiment_ttl_hours = 4

    def start(self):
        logger.info(f"\n⏰ --- 引擎巡航开始: {datetime.now().strftime('%H:%M:%S')} [{self.run_mode}] ---")

        # 🔥 [新增日志] 每一轮循环开始，先看一眼总资产
        try:
            balance = self.market.get_balance_usdt()
            logger.info(f"💰 当前账户可用余额: {balance:.2f} USDT")
        except Exception:
            logger.info("💰 账户余额获取失败 (可能是回测或模拟模式)")

        for symbol in self.symbols:
            try:
                self._process_symbol(symbol)
            except Exception as e:
                logger.error(f"❌ 处理 {symbol} 异常: {e}")
                logger.debug(traceback.format_exc())

    def _process_symbol(self, symbol):
        logger.info(f"🔍 正在分析标的: {symbol} ({self.timeframe})")

        # 1. 获取行情
        df = self.market.fetch_ohlcv(symbol, self.timeframe, limit=250)
        if df is None or df.empty: return
        current_price = df.iloc[-1]['close']

        # 2. 计算指标
        df_ind = self.tech_analyzer.calculate_indicators(df)
        state = self.tech_analyzer.get_market_state(df_ind.iloc[-1])

        # ==========================================
        # 🔥 v4.0 双轨策略 (趋势 + 回归)
        # ==========================================

        # 获取因子
        z_score = state.get('momentum', {}).get('z_score', 0)
        slope_pct = state.get('trend', {}).get('slope', 0)
        atr = state.get('volatility', {}).get('atr', 0)

        # 辅助因子
        rsi = state.get('momentum', {}).get('rsi', 50)
        # 我们假设 calculate_indicators 里算过 EMA，如果没有，这里临时取一下状态
        # (为了稳妥，这里用 Z-Score 和 Slope 就能判断趋势)

        tech_score = 50  # 默认中性

        # --- 第一步：判断市场体制 (Regime Detection) ---
        # 如果 20日均线斜率是正的，且价格在均线上方，定义为“强势多头”
        is_strong_trend = (slope_pct > 0.1) and (z_score > 0)

        logger.info(f"   🌊 市场状态: {'强势多头 (顺势模式)' if is_strong_trend else '震荡/空头 (抄底模式)'}")

        # --- 第二步：根据体制分发逻辑 ---

        if is_strong_trend:
            # === 模式 A: 顺势交易 (Trend Following) ===
            # 逻辑：只要趋势向上，且没有极度超买 (Z > 2.5)，就应该持有或买入
            # 不需要等跌破均线，只要 Z-Score 回调到 0.5 附近就可以上车

            if z_score < 1.0:
                # 价格在 1 倍标准差以内，且趋势向上 -> 买点
                tech_score = 80
                logger.info(f"   🚀 [顺势] 趋势向上且价格合理 (Z={z_score:.2f} < 1.0)")
            elif z_score > 2.5:
                # 涨太疯了，要注意风险
                tech_score = 40
                logger.info(f"   ⚠️ [顺势] 短期涨幅过大 (Z={z_score:.2f})")
            else:
                # 中间地带，持有
                tech_score = 60

        else:
            # === 模式 B: 均值回归 (Mean Reversion) ===
            # 逻辑：趋势不明朗或向下，必须等深跌 (抄底)

            if z_score < -1.5:
                # 跌破 1.5 倍标准差 -> 抄底机会
                tech_score = 90
                logger.info(f"   💎 [抄底] 统计学超卖 (Z={z_score:.2f})")

                # 熔断保护 (防止瀑布)
                if slope_pct < -4.0:  # 5小时跌 4% 才熔断
                    tech_score = 45
                    logger.info(f"   ✋ [风控] 跌速过快 (Slope={slope_pct:.1f}%)，暂停接刀")

            elif z_score > 1.5:
                # 震荡市触顶 -> 卖出
                tech_score = 20
                logger.info(f"   📉 [高抛] 触及震荡上沿 (Z={z_score:.2f})")

        # C. 情感面
        sentiment_score = self._get_smart_sentiment(symbol)

        # 4. 综合评估
        decision = self.evaluator.evaluate(tech_score, sentiment_score, 50)  # Trend分已融入Tech，给50即可

        logger.info(
            f"   📊 最终因子: Z({z_score:.2f}) | Slope({slope_pct:.1f}%) | Mode({'Trend' if is_strong_trend else 'Reversion'})")
        logger.info(f"   👉 决策结果: {decision['action']} (得分: {decision['final_score']:.1f})")

        # 5. 交易逻辑
        self._handle_trade(symbol, decision, current_price, atr)

    def _handle_trade(self, symbol, decision, price, atr):
        """
        🔥 升级: 引入 ATR 动态止损
        """
        strategy_action = decision['action']
        details = decision['details'].get('breakdown', '')
        position = self.state_mgr.get_position(symbol)
        final_action = strategy_action
        force_reason = ""

        if position:
            entry_price = float(position['entry_price'])
            qty = float(position['qty'])
            pnl_pct = (price - entry_price) / entry_price

            # 🔥 动态计算止损位
            # 如果 ATR 是 500U，那么止损就是开仓价 - 1000U (2倍ATR)
            # 这种止损方式比固定 3% 科学得多
            dynamic_sl_price = entry_price - (2.0 * atr)
            dynamic_sl_pct = (dynamic_sl_price - entry_price) / entry_price

            # 为了安全，我们还是保留一个硬底线 (比如最大亏损不超过 5%)
            stop_loss_threshold = max(dynamic_sl_pct, -0.05)

            # 止盈可以设为回归均值，或者简单的风险收益比 1:1.5
            take_profit_threshold = abs(stop_loss_threshold) * 1.5

            if pnl_pct <= stop_loss_threshold:
                final_action = "SELL";
                force_reason = f" [ATR止损 {stop_loss_threshold * 100:.1f}%]"
            elif pnl_pct >= take_profit_threshold:
                final_action = "SELL";
                force_reason = f" [ATR止盈 {take_profit_threshold * 100:.1f}%]"

            # 打印持仓状态
            logger.info(f"   🔒 持仓中: 浮盈 {pnl_pct * 100:.2f}% | 动态ATR止损线: {stop_loss_threshold * 100:.2f}%")

        if final_action == "BUY" and not position:
            balance = self.market.get_balance_usdt()
            qty = self.pos_manager.calculate_buy_size(price, balance)
            if qty > 0:
                logger.info(f"   🚀 买入 {symbol} @ {price}")
                self.state_mgr.update_position(symbol, price, qty)
                self.notifier.send_alert("BUY", symbol, price, qty, details)
        elif final_action == "SELL" and position:
            pnl_realized = (price - float(position['entry_price'])) / float(position['entry_price']) * 100
            logger.info(f"   📉 卖出 {symbol} {force_reason} | PnL: {pnl_realized:.2f}%")
            self.state_mgr.clear_position(symbol)
            self.notifier.send_alert("SELL", symbol, price, position['qty'], details + force_reason, pnl_realized)

    def _get_smart_sentiment(self, symbol):
        """
        适配 NewsFetcher.get_latest_news()
        """
        if not self.ai_enabled: return 50.0

        now = datetime.now()
        cache = self.sentiment_cache.get(symbol)

        # 缓存检查
        if cache and (now - cache['updated_at'] < timedelta(hours=self.sentiment_ttl_hours)):
            # 🔥 [新增日志] 明确告知用户用的是缓存
            logger.info(
                f"   🧠 AI 情感使用缓存: {cache['score']} 分 (上次更新: {cache['updated_at'].strftime('%H:%M')})")
            return cache['score']

        try:
            coin = symbol.split('/')[0] if '/' in symbol else symbol

            logger.info(f"   📡 正在抓取 {coin} 的新闻数据...")
            news_text = self.news_fetcher.get_latest_news(coin, limit=5)

            if not news_text or "No news" in news_text:
                logger.warning("   ⚠️ 未获取到新闻，AI 模块跳过 (默认 50 分)")
                return 50.0

            # 🔥 [新增日志] 把抓到的新闻打印出来，让你知道 AI 看到了什么
            logger.info(f"   📰 投喂给 AI 的新闻摘要:\n{news_text.strip()}")
            logger.info("   🤖 正在请求 LLM 进行推理...")

            # 调用 LLM
            score = self.llm.analyze_sentiment([news_text])

            self.sentiment_cache[symbol] = {'score': score, 'updated_at': now}
            logger.info(f"   ✅ AI 分析完成: 给予 {score} 分")
            return score

        except Exception as e:
            logger.error(f"❌ AI 分析异常: {e}")
            return cache['score'] if cache else 50.0



if __name__ == "__main__":
    engine = TradingEngine()
    engine.start()