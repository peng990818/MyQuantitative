import time
import schedule
import sys
import os
import json
from datetime import datetime
from dotenv import load_dotenv

# 引入你的模块
from trading_engine import OKXDemoTrader, OKXRealTrader, OKXPaperTrader
from factor_engine import MultiFactorEngine
from news_loader import NewsFetcher
from model import SentimentAnalyst

# 加载环境变量
load_dotenv(override=True)

# ==========================================
# ⚙️ 策略与风控配置
# ==========================================
RUN_MODE = "PAPER"  # 模式: PAPER(模拟实盘) / REAL(实盘) / DEMO(测试网)
SYMBOL = "BTC/USDT"
TIMEFRAME = "1h"  # ⏳ 策略周期：1小时
TRADE_QTY = 0.01  # 每次买入数量 (BTC)

# 🛑 风控参数
ENABLE_RISK_CONTROL = True
STOP_LOSS_PCT = 0.05  # 止损：亏损 5% 立刻卖出
TAKE_PROFIT_PCT = 0.20  # 止盈：盈利 20% 立刻卖出 (抓住暴涨)


# ==========================================
# 📦 持仓状态管理器 (用于记录成本价)
# ==========================================
class PositionManager:
    def __init__(self, filename="bot_state.json"):
        self.filename = filename
        self.state = self._load_state()

    def _load_state(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {"has_position": False, "avg_price": 0.0, "timestamp": None}

    def save_state(self, has_position, price):
        self.state = {
            "has_position": has_position,
            "avg_price": price,
            "timestamp": str(datetime.now())
        }
        with open(self.filename, 'w') as f:
            json.dump(self.state, f, indent=4)

    def get_avg_price(self):
        return self.state.get("avg_price", 0.0)

    def is_holding(self):
        return self.state.get("has_position", False)


# ==========================================
# 🤖 量化指挥官
# ==========================================
class QuantBotCommander:
    def __init__(self):
        # 1. 初始化交易执行器
        if RUN_MODE == "REAL":
            print(f"⚠️ [实盘警告] 正在使用真实资金交易 {SYMBOL}...")
            self.trader = OKXRealTrader()
        elif RUN_MODE == "PAPER":
            print(f"📝 [模拟实盘] 使用实时行情 + 虚拟资金...")
            self.trader = OKXPaperTrader(initial_usdt=10000.0)
        else:
            self.trader = OKXDemoTrader()

        # 2. 初始化大脑
        self.engine = MultiFactorEngine()
        self.news_loader = NewsFetcher()
        self.analyst = SentimentAnalyst()
        self.pos_manager = PositionManager()

        # 3. 状态缓存
        self.last_sentiment = {"score": 0, "reason": "Init"}
        self.qty = TRADE_QTY

    def execute_logic(self):
        try:
            current_time = datetime.now()

            # --- A. 获取 1H 数据 (用于计算信号) ---
            # 即使每分钟运行，这里也只拿 1h 的 K线
            market_data = self.trader.fetch_market_data(SYMBOL, timeframe=TIMEFRAME)
            if not market_data: return

            current_price = market_data['current_price']

            # --- B. 🛑 优先执行风控检查 (每分钟都跑) ---
            # 只有持仓时才检查风控
            if self.pos_manager.is_holding():
                entry_price = self.pos_manager.get_avg_price()
                if entry_price > 0:
                    pnl_pct = (current_price - entry_price) / entry_price

                    # 1. 检查止损 (Stop Loss)
                    if pnl_pct <= -STOP_LOSS_PCT:
                        print(f"🩸 [触发止损] 当前浮亏 {pnl_pct * 100:.2f}% (阈值 -{STOP_LOSS_PCT * 100}%)")
                        self._force_sell(current_price, "STOP_LOSS")
                        return  # 卖完直接结束本次循环

                    # 2. 检查止盈 (Take Profit)
                    if pnl_pct >= TAKE_PROFIT_PCT:
                        print(f"💰 [触发止盈] 当前浮盈 {pnl_pct * 100:.2f}% (阈值 +{TAKE_PROFIT_PCT * 100}%)")
                        self._force_sell(current_price, "TAKE_PROFIT")
                        return

            # --- C. 策略信号计算 (静默模式) ---
            # 逻辑：整点附近(0-5分)打印详细看板，其他时间静默扫描
            is_new_hour = current_time.minute < 5
            silent_mode = not is_new_hour

            if is_new_hour:
                print(f"\n⏰ [{current_time.strftime('%H:%M')}] 整点巡航 ({TIMEFRAME})...")
                # 只有整点才调用 AI (省钱)
                news = self.news_loader.get_latest_news(SYMBOL)
                self.last_sentiment = self.analyst.analyze_sentiment(SYMBOL, news)
            else:
                if not silent_mode: print(".", end="", flush=True)

            # 计算技术分
            tech_score, tech_sub, _ = self.engine.calculate_technical_score(market_data)
            # 融合 AI 分数
            fusion = self.engine.fuse_signals(tech_score, tech_sub, self.last_sentiment)

            final_score = fusion['final_score']
            action = fusion['action']

            # --- D. 只有当有动作 或 整点时 才打印看板 ---
            has_action = action in ["BUY", "STRONG_BUY", "SELL"]

            if is_new_hour or has_action:
                if not is_new_hour: print(f"\n⚡ [{current_time.strftime('%H:%M')}] 信号突变！")
                self._print_dashboard(final_score, action, tech_sub, self.last_sentiment, current_price)

            # --- E. 交易执行 ---
            if action == "HOLD": return

            if action in ["BUY", "STRONG_BUY"]:
                self._try_buy(current_price)

            elif action == "SELL":
                self._try_sell(current_price, "STRATEGY_EXIT")

        except Exception as e:
            print(f"❌ 异常: {e}")
            import traceback
            traceback.print_exc()

    # === 交易动作封装 ===

    def _try_buy(self, price):
        # 1. 检查余额
        bal = self.trader.get_account_balance()
        cost = price * self.qty

        # 2. 只有没持仓 且 钱够 才买
        if not self.pos_manager.is_holding() and bal['USDT'] >= cost:
            print(f"🚀 [买入信号] 执行买入 {self.qty} BTC...")

            order = None
            if RUN_MODE == "PAPER":
                order = self.trader.mock_create_order(SYMBOL, 'buy', self.qty, price)
            elif RUN_MODE == "REAL":
                order = self.trader.exchange.create_market_order(SYMBOL, 'buy', self.qty)

            if order:
                # 记录持仓状态和成本价
                avg_price = order.get('average', price)  # 尝试获取真实成交均价
                self.pos_manager.save_state(True, avg_price)
                print(f"✅ 买入成功，成本价记录为: {avg_price:.2f}")

    def _try_sell(self, price, reason):
        # 只有持仓才卖
        if self.pos_manager.is_holding():
            print(f"📉 [卖出信号: {reason}] 执行卖出...")

            # 简单处理：全仓卖出 (或卖出固定 qty)
            # 这里为了简单，假设我们要卖出之前买入的 qty
            # 严谨做法是查询账户 BTC 余额
            bal = self.trader.get_account_balance()
            sell_qty = bal['BTC']  # 清仓模式

            if sell_qty < 0.0001:
                print("⚠️ BTC 余额不足，无法卖出")
                return

            if RUN_MODE == "PAPER":
                self.trader.mock_create_order(SYMBOL, 'sell', sell_qty, price)
            elif RUN_MODE == "REAL":
                self.trader.exchange.create_market_order(SYMBOL, 'sell', sell_qty)

            # 清除持仓状态
            self.pos_manager.save_state(False, 0.0)
            print(f"✅ 卖出成功，持仓已清空")

    def _force_sell(self, price, reason):
        """强制平仓（用于止损止盈）"""
        print(f"🚨 [风控触发] {reason} !!!")
        self._try_sell(price, reason)

    def _print_dashboard(self, score, action, tech, ai, price):
        entry_info = ""
        if self.pos_manager.is_holding():
            cost = self.pos_manager.get_avg_price()
            pnl = (price - cost) / cost * 100
            entry_info = f"| 成本: {cost:.0f} | 浮盈: {pnl:+.2f}%"

        print("-" * 60)
        print(f"📊 {SYMBOL} [1h] | 现价: {price:.2f} {entry_info}")
        print(f"🎯 综合得分: {score:.1f}  ==>  {action}")
        print(f"🌊 趋势: {tech['Trend']:.0f} | 🚀 动量: {tech['Momentum']:.0f} | 💸 资金: {tech['Volume']:.0f}")
        print(f"🤖 AI分析: {ai.get('score', 0)} ({ai.get('reason', 'N/A')[:40]}...)")
        print("-" * 60)

    def start(self):
        print(f"🤖 量化机器人启动 | 模式: {RUN_MODE} | 周期: {TIMEFRAME}")
        if ENABLE_RISK_CONTROL:
            print(f"🛡️ 风控系统已开启: 止损 -{STOP_LOSS_PCT * 100}% | 止盈 +{TAKE_PROFIT_PCT * 100}%")

        # 第一次运行
        self.execute_logic()

        # ⚠️ 必须保持 1分钟 扫描！
        # 这样才能保证止损止盈在盘中触发，而不是等收盘
        schedule.every(1).minutes.do(self.execute_logic)

        print("✅ 监控回路已建立，等待信号...")
        try:
            while True:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 机器人已停止")
            sys.exit(0)


if __name__ == "__main__":
    bot = QuantBotCommander()
    bot.start()