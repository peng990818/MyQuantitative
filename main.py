import sys
import time
import schedule
import warnings
import os

# 🔥 [新增] 必须放在最前面：强力屏蔽 Google 和 Pandas 的废话
os.environ["GRPC_VERBOSITY"] = "ERROR"  # 屏蔽 Google gRPC 底层日志
os.environ["GLOG_minloglevel"] = "2"  # 屏蔽 Google Log

warnings.simplefilter(action='ignore', category=FutureWarning)
warnings.simplefilter(action='ignore', category=UserWarning)
warnings.filterwarnings("ignore", module="google")  # 针对性屏蔽 google

from utils.logger import logger
from core.engine import TradingEngine


def main():
    logger.info("==========================================")
    logger.info("🤖 QuantBot v2.0 - 启动 (固定仓位版)")
    logger.info("==========================================")

    try:
        # 1. 实例化引擎
        bot = TradingEngine()

        # 2. 立即运行一次 (开机自检)
        bot.start()

        # 3. 设置定时任务
        # 测试期间建议每分钟一次
        schedule.every(1).minutes.do(bot.start)

        logger.info("✅ 系统就绪，正在后台运行...")

        while True:
            schedule.run_pending()
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("\n🛑 用户手动停止")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"❌ 主进程崩溃: {e}", exc_info=True)


if __name__ == "__main__":
    main()