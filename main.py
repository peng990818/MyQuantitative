import sys
import time
import os
import signal
import warnings
import traceback
from datetime import datetime

# ==========================================
# 🔥 0. 环境配置: 强力屏蔽噪音日志
# ==========================================
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"
warnings.simplefilter(action='ignore', category=FutureWarning)
warnings.simplefilter(action='ignore', category=UserWarning)
# 针对 Google Generative AI 的底层日志屏蔽
try:
    import logging

    logging.getLogger("tornado.access").setLevel(logging.ERROR)
    logging.getLogger("httpx").setLevel(logging.WARNING)
except:
    pass

# ==========================================
# 📦 1. 项目模块导入
# ==========================================
from utils.logger import logger
from utils.config_loader import ConfigLoader
from core.engine import TradingEngine

# 全局运行标志
running = True


def signal_handler(sig, frame):
    """
    捕获系统信号 (Ctrl+C / Kill)，实现优雅退出
    """
    global running
    print("\n")
    logger.warning("🛑 接到停止指令 (SIGINT)，正在安全关闭系统...")
    running = False
    # 这里可以添加保存状态的逻辑，但 StateManager 每次操作都实时保存了，所以直接退出即可
    sys.exit(0)


def main():
    # 注册信号监听
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 读取简单配置用于显示 Banner
    cfg = ConfigLoader()
    mode = cfg.get("run_mode", "PAPER").upper()
    symbol_count = len(cfg.get("symbols", []))

    logger.info("==========================================")
    logger.info("🤖 Sniper QuantBot (AI 实盘守护版) - 启动")
    logger.info("==========================================")
    logger.info(f"⏰ 启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"🛡️ 运行模式: 【{mode}】 (安全守护中)")
    logger.info(f"🎯 监控数量: {symbol_count} 个标的")
    logger.info("------------------------------------------")

    # 崩溃熔断计数器
    crash_count = 0
    last_crash_time = 0

    while running:
        try:
            # === 核心启动 ===
            # Engine 内部是 while True 循环，正常情况下代码会阻塞在这里
            bot = TradingEngine()
            bot.start()

        except KeyboardInterrupt:
            logger.info("👋 用户手动停止")
            sys.exit(0)

        except Exception as e:
            # === 崩溃恢复逻辑 ===
            current_time = time.time()
            logger.critical(f"❌ 核心引擎崩溃: {e}")
            logger.debug(traceback.format_exc())  # 打印详细报错堆栈

            # 熔断机制: 如果 60秒内连续崩溃 3次，说明有严重 Bug 或环境问题，彻底停止
            if current_time - last_crash_time < 60:
                crash_count += 1
            else:
                crash_count = 1  # 重置计数

            last_crash_time = current_time

            if crash_count >= 3:
                logger.critical("🔥 [系统熔断] 短时间内频繁崩溃 (3次)，程序已终止以保护账户安全。")
                # 尝试发送报警邮件
                try:
                    from modules.notification.sender import EmailNotifier
                    EmailNotifier().send_alert("🚨 系统熔断报警", f"错误详情: {str(e)}\n请立即检查服务器！")
                except:
                    pass
                sys.exit(1)

            logger.warning(f"🔄 系统将在 5 秒后尝试第 {crash_count} 次自动重启...")
            time.sleep(5)
            logger.info("▶️ 正在重启引擎...")

    logger.info("👋 系统已安全退出。")


if __name__ == "__main__":
    main()