import os
import time
import schedule
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv

# 加载配置
load_dotenv(override=True)

# ==========================================
# 0. 网络连接修复
# ==========================================
import socket
import urllib3

orig_getaddrinfo = socket.getaddrinfo


def forced_ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)


socket.getaddrinfo = forced_ipv4_getaddrinfo
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 引入模块
# ==========================================
from trading_engine import OKXDemoTrader, OKXRealTrader
from model import AIStrategy
from tracker import AssetManager
from news_loader import NewsFetcher

# === 全局配置 ===
RUN_MODE = "DEMO"
SYMBOL = "BTC/USDT"
TRADE_QTY = 0.0001


class QuantBotCommander:
    def __init__(self, mode="DEMO", symbol="BTC/USDT", qty=0.0001):
        self.mode = mode.upper()
        self.symbol = symbol
        self.qty = qty
        self.start_time = datetime.now()  # 记录启动时间

        print("=" * 60)
        print(f"🚀 量化机器人 [V3极速版 | 1分钟轮询] 正在初始化...")
        print("=" * 60)

        # 1. 初始化交易接口
        if self.mode == "REAL":
            print(f"⚠️ [实盘模式] 资金实盘操作中，请注意风险！")
            self.trader = OKXRealTrader()
        else:
            print(f"🛠️ [模拟模式] 使用测试资金")
            self.trader = OKXDemoTrader()

        # 2. 初始化 AI
        print(f"🧠 [AI 大脑] 加载策略模型...")
        self.strategy = AIStrategy()

        # 3. 初始化新闻
        print(f"📰 [情报网] 连接 CryptoPanic V2...")
        self.news_fetcher = NewsFetcher()
        if not self.news_fetcher.test_connection():
            print("⚠️ 代理连接失败，新闻模块将降级或失效")

        # 4. 初始化账本
        self.tracker = AssetManager(name=symbol)

        # 5. 🔥 [新增] 锁定初始资金快照 🔥
        print("-" * 30)
        self.initial_assets = self._get_total_asset_valuation(print_log=True, label="初始资金")
        print("-" * 30)
        print("✅ 系统就绪，等待定投任务...")

    def _get_total_asset_valuation(self, print_log=False, label="当前资产"):
        """
        计算账户总估值 = USDT余额 + (BTC持仓 * 当前市价)
        """
        try:
            # 1. 获取余额
            balance = self.trader.get_account_balance()
            usdt_bal = balance.get('USDT', 0)
            btc_bal = balance.get('BTC', 0)

            # 2. 获取最新价格用于折算
            ticker = self.trader.exchange.fetch_ticker(self.symbol)
            current_price = ticker['last']

            # 3. 计算总值
            total_value_usdt = usdt_bal + (btc_bal * current_price)

            if print_log:
                print(f"💰 [{label}]")
                print(f"   💵 USDT余额: {usdt_bal:.2f} U")
                print(f"   🪙 BTC 持仓: {btc_bal:.8f} (≈ {btc_bal * current_price:.2f} U)")
                print(f"   💎 总净值  : {total_value_usdt:.2f} U (按市价 {current_price:.2f})")

            return total_value_usdt

        except Exception as e:
            print(f"⚠️ 资产估值计算失败: {e}")
            return 0

    def print_final_report(self):
        """
        🔥 [新增] 停止程序时打印的战报
        """
        print("\n" + "=" * 60)
        print(f"🛑 程序停止 | 生成最终盈亏报告")
        print("=" * 60)

        end_assets = self._get_total_asset_valuation(print_log=True, label="最终资产")

        # 计算盈亏
        pnl = end_assets - self.initial_assets
        roi = (pnl / self.initial_assets) * 100 if self.initial_assets > 0 else 0

        # 计算运行时长
        duration = datetime.now() - self.start_time
        # 简单的格式化时长
        hours, remainder = divmod(duration.total_seconds(), 3600)
        minutes, seconds = divmod(remainder, 60)
        duration_str = f"{int(hours)}小时 {int(minutes)}分 {int(seconds)}秒"

        print("-" * 30)
        print(f"⏱️ 运行时长: {duration_str}")

        # 根据盈亏显示不同颜色/图标
        if pnl >= 0:
            print(f"📈 累计盈利: +{pnl:.2f} U")
            print(f"🚀 投资回报率 (ROI): +{roi:.4f}%")
        else:
            print(f"📉 累计亏损: {pnl:.2f} U")
            print(f"🥀 投资回报率 (ROI): {roi:.4f}%")
        print("=" * 60 + "\n")

    def execute_logic(self):
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🔍 市场扫描 (1min)...")

        try:
            # 1. 资产快照
            balance_before = self.trader.get_account_balance()
            usdt_before = balance_before.get('USDT', 0)
            btc_before = balance_before.get('BTC', 0)

            # 2. 获取行情
            market_data = self.trader.fetch_market_data(self.symbol)
            if not market_data:
                print("❌ 无法获取行情")
                return

            price_t0 = market_data['current_price']
            self.tracker.sync_holdings(btc_before, price_t0)

            # 趋势判断
            ema_long = market_data['ema']['long']
            trend_icon = "🐂 多头" if price_t0 > ema_long else "🐻 空头"

            # 技术看板
            print(f"📊 {self.symbol} | {trend_icon} | 现价: {price_t0:.2f}")
            print(f"   🌊 OBV:{market_data['obv']:.0f} | ATR:{market_data['atr']:.2f} | RSI:{market_data['rsi']:.1f}")

            # 3. 获取新闻
            news_text = self.news_fetcher.get_latest_news(self.symbol)
            if news_text and "No news" not in news_text:
                print(f"🗞️ [新闻摘要] {news_text[:100]}...")

            # 4. AI 决策 (含耗时监控)
            print("⏳ AI思考中...", end="", flush=True)
            t_start = time.time()
            decision = self.strategy.analyze(market_data, news_context=news_text)
            ai_duration = time.time() - t_start
            print(f" Done ({ai_duration:.2f}s)")

            action = decision.get("action", "HOLD")
            reason = decision.get("reason", "N/A")
            print(f"🤖 指令: {action} | 💡 原因: {reason}")

            # 5. 执行交易
            if action == "BUY":
                cost_estimate = price_t0 * self.qty
                if usdt_before >= cost_estimate:
                    print(f"🟢 买入 {self.qty} BTC...")
                    self.trader.exchange.create_market_order(self.symbol, 'buy', self.qty)
                    # 简单模拟成交后续处理
                    time.sleep(1)
                    # 重新获取一次余额以确认扣款
                    self._get_total_asset_valuation(print_log=False)
                else:
                    print(f"⚠️ 余额不足")

            elif action == "SELL":
                if btc_before > 0.000001:
                    sell_amt = btc_before if btc_before < self.qty else self.qty
                    print(f"🔴 卖出 {sell_amt:.6f} BTC...")
                    self.trader.exchange.create_market_order(self.symbol, 'sell', sell_amt)
                    time.sleep(1)
                else:
                    print("⚠️ 无持仓")

        except Exception as e:
            print(f"❌ 运行异常: {e}")

    def start(self):
        # 先执行一次
        self.execute_logic()

        # 🔥 [修改] 改为 1 分钟轮询 🔥
        schedule.every(1).minutes.do(self.execute_logic)

        print(f"✅ 任务已启动，按 Ctrl+C 停止并查看战报...")

        # 🔥 [新增] 捕获 Ctrl+C 以打印战报 🔥
        try:
            while True:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            self.print_final_report()
            sys.exit(0)


if __name__ == "__main__":
    bot = QuantBotCommander(mode=RUN_MODE, symbol=SYMBOL, qty=TRADE_QTY)
    bot.start()