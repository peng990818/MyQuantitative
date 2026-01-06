import os
import time
import schedule
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(override=True)

# --- 深圳联通修复 ---
import socket
import urllib3

orig_getaddrinfo = socket.getaddrinfo


def forced_ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)


socket.getaddrinfo = forced_ipv4_getaddrinfo
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
# ------------------

from trading_engine import OKXDemoTrader, OKXRealTrader
from model import GeminiStrategy
from tracker import AssetManager

# === 配置 ===
RUN_MODE = "DEMO"
SYMBOL = "BTC/USDT"
TRADE_QTY = 0.0001


class QuantBotCommander:
    def __init__(self, mode="DEMO", symbol="BTC/USDT", qty=0.0001):
        self.mode = mode.upper()
        self.symbol = symbol
        self.qty = qty

        if self.mode == "REAL":
            print(f"⚠️ [实盘启动] 请注意风险！")
            self.trader = OKXRealTrader()
        else:
            print(f"🛠️ [模拟启动] 测试模式")
            self.trader = OKXDemoTrader()

        self.strategy = GeminiStrategy()
        # tracker 仅用于同步状态，不负责记账了，账单由 main.py 直接算
        self.tracker = AssetManager(name=symbol)

    def execute_logic(self):
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 扫描中...")

        try:
            # 1. 【操作前】全资产快照 (Snap A)
            balance_before = self.trader.get_account_balance()
            usdt_before = balance_before.get('USDT', 0)
            btc_before = balance_before.get('BTC', 0)

            print(f"💵 [当前资金] USDT: {usdt_before:.2f} | BTC: {btc_before:.8f}")

            # 2. 查行情
            market_data = self.trader.fetch_market_data(self.symbol)
            if not market_data: return
            current_price = market_data['current_price']

            # 3. 同步持仓
            self.tracker.sync_holdings(btc_before, current_price)

            # 4. AI 决策
            decision = self.strategy.analyze(market_data)
            action = decision.get("action", "HOLD")
            print(f"🤖 AI信号: {action} | 原因: {decision.get('reason', 'N/A')}")

            # 5. 执行交易
            trade_executed = False

            if action == "BUY":
                if usdt_before < (current_price * self.qty):
                    print(f"⚠️ USDT 不足，无法买入")
                else:
                    order = self.trader.exchange.create_market_order(self.symbol, 'buy', self.qty)
                    if order: trade_executed = True

            elif action == "SELL":
                if btc_before > 0:
                    sell_amt = self.qty if btc_before > self.qty else float(btc_before)
                    order = self.trader.exchange.create_market_order(self.symbol, 'sell', sell_amt)
                    if order: trade_executed = True
                else:
                    print("⚠️ 无BTC持仓，无法卖出。")

            # 6. 【操作后】结算账单 (Snap B - Snap A)
            if trade_executed:
                time.sleep(1)  # 等交易所结算

                balance_after = self.trader.get_account_balance()
                usdt_after = balance_after.get('USDT', 0)
                btc_after = balance_after.get('BTC', 0)

                # 计算变动
                usdt_change = usdt_after - usdt_before
                btc_change = btc_after - btc_before

                print("=" * 45)
                if usdt_change > 0:
                    print(f"💰 [卖出成功] 资金回笼")
                    print(f"   USDT: +{usdt_change:.4f} U")
                    print(f"   BTC : {btc_change:.8f} BTC")  # 通常是负数
                else:
                    print(f"💸 [买入成功] 资产增加")
                    print(f"   USDT: {usdt_change:.4f} U")  # 通常是负数
                    print(f"   BTC : +{btc_change:.8f} BTC")

                print("-" * 45)
                print(f"🧾 [最新余额] USDT: {usdt_after:.2f} | BTC: {btc_after:.8f}")
                print("=" * 45)

        except Exception as e:
            print(f"❌ 运行异常: {e}")

    def start(self):
        self.execute_logic()
        schedule.every(1).minutes.do(self.execute_logic)
        while True:
            schedule.run_pending()
            time.sleep(1)


if __name__ == "__main__":
    bot = QuantBotCommander(mode=RUN_MODE, symbol=SYMBOL, qty=TRADE_QTY)
    bot.start()