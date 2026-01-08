import logging
import os
import sys
from logging.handlers import RotatingFileHandler

class LogManager:
    _instance = None
    _logger = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LogManager, cls).__new__(cls)
            cls._instance._setup_logger()
        return cls._instance

    def _setup_logger(self):
        # 1. 创建 logs 文件夹
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log_dir = os.path.join(base_path, 'logs')
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        # 2. 初始化 Logger
        self._logger = logging.getLogger("QuantBot_v2")
        self._logger.setLevel(logging.INFO)  # 默认级别：INFO
        self._logger.propagate = False  # 防止重复打印

        # 3. 格式设置
        # 格式：[时间] [级别] [模块] 消息
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-7s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # 4. Handler 1: 控制台输出 (带颜色)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        self._logger.addHandler(console_handler)

        # 5. Handler 2: 文件输出 (滚动日志，最大 5MB，保留 3 个备份)
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, 'bot.log'),
            maxBytes=5*1024*1024,
            backupCount=3,
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        self._logger.addHandler(file_handler)

    def get_logger(self):
        return self._logger

# 便捷入口，供其他模块直接调用
logger = LogManager().get_logger()

# ... (上面的代码保持不变)

if __name__ == "__main__":
    print("📝 正在测试 LogManager...")

    # 获取 logger
    log = LogManager().get_logger()

    log.debug("这条是 DEBUG (默认不显示)")
    log.info("这条是 INFO (应该显示)")
    log.warning("这条是 WARNING (应该显示)")
    log.error("这条是 ERROR (应该显示)")

    # 告诉用户日志文件在哪
    base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_file = os.path.join(base_path, 'logs', 'bot.log')
    print(f"\n✅ 请检查文件是否生成: {log_file}")