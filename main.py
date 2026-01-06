import os
import time
import schedule
from datetime import datetime
from dotenv import load_dotenv

# 加载配置
load_dotenv(override=True)

# ==========================================
# 0. 网络连接修复 (针对家庭宽带/Mac M系列)
# ==========================================
import socket
import urllib3

orig_getaddrinfo = socket.getaddrinfo


def forced_ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    # 强制使用 IPv4 (AF_INET)，解决部分梯子在 IPv6 下连不上 OKX 的问题
    return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)


socket.getaddrinfo = forced_ipv4_getaddrinfo
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
# ==========================================

from trading_engine import OKXDemoTrader, OKXRealTrader
from model import AIStrategy
from tracker import AssetManager

# === 全局配置 ===
RUN_MODE = "DEMO"  # 模拟盘: DEMO | 实盘: REAL
SYMBOL = "BTC/USDT"
TRADE_QTY = 0.0001  # 每次交易数量


class QuantBotCommander:
    def __init__(self, mode="DEMO", symbol="BTC/USDT", qty=0.0001):
        self.mode = mode.upper()
        self.symbol = symbol
        self.qty = qty

        print("-" * 50)
        print(f"🚀 量化机器人启动初始化...")

        # 1. 初始化交易接口
        if self.mode == "REAL":
            print(f"⚠️ [实盘模式] 资金实盘交易中，请注意风险！")
            self.trader = OKXRealTrader()
        else:
            print(f"🛠️ [模拟模式] 使用模拟资金测试")
            self.trader = OKXDemoTrader()

        # 2. 初始化 AI 策略
        # [修改] 显式实例化通用 AI 策略类
        # 这个类内部会自己去查 .env 决定用 Gemini 还是 DeepSeek
        print(f"🧠 [AI 系统] 正在加载智能策略模块...")
        self.strategy = AIStrategy()

        # 3. 初始化账本
        self.tracker = AssetManager(name=symbol)
        print("-" * 50)

    def execute_logic(self):
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 扫描市场中...")

        try:
            # ============================================
            # A. 【交易前】资产快照 (Snap A)
            # ============================================
            balance_before = self.trader.get_account_balance()
            usdt_before = balance_before.get('USDT', 0)
            btc_before = balance_before.get('BTC', 0)

            # ============================================
            # B. 获取行情 & 同步账本
            # ============================================
            market_data = self.trader.fetch_market_data(self.symbol)
            if not market_data:
                print("❌ 无法获取行情，跳过本次循环")
                return

            current_price = market_data['current_price']

            # 强行同步账本持仓 (防止本地记录与交易所不符)
            self.tracker.sync_holdings(btc_before, current_price)

            # 🔥🔥🔥 [新增] 打印技术指标看板 🔥🔥🔥
            print(f"📊 [行情看板] {self.symbol}")
            print(f"   💰 现价     : {market_data['current_price']}")
            print(f"   📉 RSI(14)  : {market_data['rsi']}")
            print(f"   📊 MACD     : {market_data['macd']}")
            print(f"   🌭 布林上轨 : {market_data['bollinger']['upper']}")
            print(f"   🌭 布林下轨 : {market_data['bollinger']['lower']}")
            print("-" * 30)

            # ============================================
            # C. AI 决策 (Gemini 或 DeepSeek)
            # ============================================
            decision = self.strategy.analyze(market_data)
            action = decision.get("action", "HOLD")
            reason = decision.get("reason", "N/A")

            print(f"🤖 AI信号: {action} | 原因: {reason}")
            print(f"💵 当前资金: {usdt_before:.2f} U | 持仓: {btc_before:.8f} BTC")

            # ============================================
            # D. 执行交易
            # ============================================
            trade_executed = False  # 标记本次是否真的开了单

            if action == "BUY":
                cost_estimate = current_price * self.qty
                if usdt_before < cost_estimate:
                    print(f"⚠️ 余额不足 ({usdt_before:.2f} < {cost_estimate:.2f})，无法买入")
                else:
                    print(f"🟢 执行买入: {self.qty} BTC ...")
                    order = self.trader.exchange.create_market_order(self.symbol, 'buy', self.qty)
                    if order:
                        trade_executed = True
                        # 记账 (为了 Tracker 报表)
                        fee = order.get('fee', {}).get('cost', 0) if order.get('fee') else 0
                        exec_price = order.get('average') or current_price
                        self.tracker.buy(exec_price, order['amount'], fee)

            elif action == "SELL":
                if btc_before > 0:
                    # 如果余额很少(小于交易量)，就清仓；否则卖固定量
                    sell_amt = self.qty if btc_before > self.qty else float(btc_before)
                    print(f"🔴 执行卖出: {sell_amt:.8f} BTC ...")

                    order = self.trader.exchange.create_market_order(self.symbol, 'sell', sell_amt)
                    if order:
                        trade_executed = True
                        # 记账
                        fee = order.get('fee', {}).get('cost', 0) if order.get('fee') else 0
                        exec_price = order.get('average') or current_price
                        self.tracker.sell(exec_price, order['amount'], fee)
                else:
                    print("⚠️ 无持仓，无法卖出")

            # ============================================
            # E. 【交易后】资金流结算 (Snap B - Snap A)
            # ============================================
            if trade_executed:
                print("⏳ 等待交易所结算 (1秒)...")
                time.sleep(1)  # 给交易所一点时间刷新余额

                balance_after = self.trader.get_account_balance()
                usdt_after = balance_after.get('USDT', 0)
                btc_after = balance_after.get('BTC', 0)

                # 计算变动
                usdt_change = usdt_after - usdt_before
                btc_change = btc_after - btc_before

                print("=" * 45)
                if usdt_change > 0:
                    print(f"💰 [资金回笼] 卖出成功！")
                    print(f"   USDT 变动: +{usdt_change:.4f} U")
                    print(f"   BTC  变动: {btc_change:.8f}")
                else:
                    print(f"💸 [资金支出] 买入成功！")
                    print(f"   USDT 变动: {usdt_change:.4f} U")
                    print(f"   BTC  变动: +{btc_change:.8f}")
                print(f"🧾 最新余额: {usdt_after:.2f} U")
                print("=" * 45)

            # ============================================
            # F. 生成持仓报表 (即使 HOLD 也显示，心里有底)
            # ============================================
            self.tracker.report(current_price)

        except Exception as e:
            import traceback
            # 打印详细错误，方便你排查 DeepSeek 此时是否连得上
            print(f"❌ 运行异常: {e}")
            # traceback.print_exc()

    def start(self):
        # 启动时先跑一次
        self.execute_logic()

        # 每 1 分钟执行一次
        schedule.every(1).minutes.do(self.execute_logic)

        print(f"✅ 计划任务已启动，按 Ctrl+C 停止")
        while True:
            schedule.run_pending()
            time.sleep(1)


if __name__ == "__main__":
    bot = QuantBotCommander(mode=RUN_MODE, symbol=SYMBOL, qty=TRADE_QTY)
    bot.start()