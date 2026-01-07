from main import QuantBotCommander
import sys

# 初始化机器人 (默认 PAPER 模式)
bot = QuantBotCommander()

print("🔴 正在检查持仓...")

# 强制读取持仓状态
if bot.pos_manager.is_holding():
    cost = bot.pos_manager.get_avg_price()
    print(f"⚠️ 当前持仓成本: {cost}")
    print("💥 正在执行【强制清仓】程序...")

    # 获取当前市价 (为了模拟真实场景)
    market = bot.trader.fetch_market_data("BTC/USDT", timeframe="1h")
    current_price = market['current_price']

    # 🔥 触发强制卖出 (理由写: 手动紧急清仓)
    # 这会直接调用 _try_sell -> 发送邮件
    bot._force_sell(current_price, "MANUAL_PANIC_SELL")

    print("✅ 清仓指令已发送，请检查邮箱！")
else:
    print("💨 当前空仓，无需操作。")
    # 为了测试邮件，我们可以强制发一个假的
    print("📧 发送测试邮件...")
    bot.notifier.send_sell_alert("BTC/USDT", 90000, 0.01, "测试_止损", 95000, 10000)
    print("✅ 测试邮件已发送")