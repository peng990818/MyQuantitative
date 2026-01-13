# debug_ai.py
import time
from modules.analysis.analyzer import MarketRegimeAnalyzer
from utils.logger import logger


def test_ai():
    print("\n🚀 开始 AI 模块连通性测试...")
    print("--------------------------------------------------")

    try:
        analyzer = MarketRegimeAnalyzer()

        # 1. 构造假数据
        symbol = "BTC/USDT"
        price = 98000
        indicators = {
            'trend': 'UP',
            'rsi': 75,
            'price_loc': 'ABOVE_EMA200'
        }
        news = [
            "Bitcoin breaks $100k barrier logic test.",
            "SEC approves new crypto ETF.",
            "Federal Reserve keeps rates unchanged."
        ]

        print("📡 正在发送请求给 DeepSeek (预计耗时 5-10秒)...")
        start_time = time.time()

        # 2. 调用
        result = analyzer.analyze(symbol, price, indicators, news)

        duration = time.time() - start_time
        print("--------------------------------------------------")
        print(f"⏱️ 耗时: {duration:.2f} 秒")
        print(f"📊 返回结果: {result}")
        print("--------------------------------------------------")

        if result['confidence'] > 0:
            print("✅ 测试通过！AI 工作正常。")
        else:
            print("❌ 测试失败：AI 返回了默认降级结果 (请检查上方报错日志)。")

    except Exception as e:
        print(f"❌ 测试脚本崩溃: {e}")


if __name__ == "__main__":
    test_ai()