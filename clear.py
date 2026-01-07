import time
from dotenv import load_dotenv
from trading_engine import OKXDemoTrader

# 加载配置
load_dotenv(override=True)


def clear_all_btc():
    print("🧹 [系统] 正在初始化清理程序...")
    try:
        # 初始化交易器
        trader = OKXDemoTrader()

        # 1. 查余额
        balance = trader.get_account_balance()
        btc_qty = balance.get('BTC', 0)

        print(f"🔍 当前持仓: {btc_qty} BTC")

        if btc_qty <= 0:
            print("✅ 账户已经是空仓 (0 BTC)，无需清理。")
            return

        # 2. 只有当数量大于最小交易精度时才卖出 (比如 > 0.00001)
        if btc_qty > 0.00001:
            print(f"📉 正在执行市价清仓: 卖出 {btc_qty} BTC...")

            # 执行全仓卖出
            order = trader.exchange.create_market_order("BTC/USDT", 'sell', btc_qty)

            print("=" * 30)
            print(f"✅ 清仓成功！")
            print(f"💰 获得 USDT 估值: {order.get('cost', '未知')}")
            print(f"🆔 订单 ID: {order['id']}")
            print("=" * 30)

            # 再查一次确认
            time.sleep(1)
            new_bal = trader.get_account_balance()
            print(f"🧾 清理后余额: {new_bal.get('BTC', 0)} BTC")

        else:
            print("⚠️ 余额由粉尘组成 (太小无法交易)，可视作 0 处理。")

    except Exception as e:
        print(f"❌ 清理失败: {e}")


if __name__ == "__main__":
    # 二次确认防止手滑
    confirm = input("⚠️ 你确定要卖出模拟盘所有 BTC 吗？(y/n): ")
    if confirm.lower() == 'y':
        clear_all_btc()
    else:
        print("已取消操作。")