import ccxt
import time
import pandas as pd
import os
from utils.config_loader import ConfigLoader
from utils.proxy_manager import ProxyManager
from utils.logger import logger


class MarketDataLoader:
    def __init__(self):
        self.cfg = ConfigLoader()
        self.exchange = None
        self._init_exchange()

    def _init_exchange(self):
        """初始化交易所连接"""
        mode = self.cfg.get("run_mode", "PAPER").upper()
        proxies = ProxyManager(self.cfg).get_proxies()

        exchange_config = {
            'enableRateLimit': True,
            'timeout': 30000,
            'options': {'defaultType': 'swap'},
        }

        if proxies:
            exchange_config['proxies'] = proxies

        if mode == "REAL":
            exchange_config['apiKey'] = self.cfg.get("exchange.okx.api_key")
            exchange_config['secret'] = self.cfg.get("exchange.okx.secret")
            exchange_config['password'] = self.cfg.get("exchange.okx.password")
            logger.warning("🚨 [Market] 正在连接 OKX 【实盘】环境！")

        elif mode == "DEMO":
            exchange_config['apiKey'] = self.cfg.get("exchange.okx.demo_api_key")
            exchange_config['secret'] = self.cfg.get("exchange.okx.demo_secret")
            exchange_config['password'] = self.cfg.get("exchange.okx.demo_password")
            exchange_config['sandbox'] = True
            logger.info("🎮 [Market] 正在连接 OKX 【模拟盘】环境")

        else:
            logger.info("📝 [Market] 运行在本地回测模式 (只读公共数据)")
            self.exchange = ccxt.okx(exchange_config)
            return

        try:
            self.exchange = ccxt.okx(exchange_config)
            try:
                self.exchange.load_markets()
                logger.info(f"✅ [Market] 交易所连接成功 (模式: {mode})")
            except Exception as e:
                logger.error(f"❌ [Market] 连接验证失败: {e}")
        except Exception as e:
            logger.error(f"❌ [Market] 初始化异常: {e}")

    # =========================================================
    # 🔥🔥🔥 核心升级部分：支持日期范围下载 🔥🔥🔥
    # =========================================================

    def fetch_history_range(self, symbol, timeframe, start_str, end_str=None, save_path=None):
        """
        [新功能] 下载指定日期范围的数据
        :param start_str: "2023-01-01 00:00:00"
        :param end_str:   "2024-01-01 00:00:00" (如果不填则下载到最新)
        """
        # 1. 转换时间为毫秒时间戳
        start_ts = self.exchange.parse8601(start_str)
        if end_str:
            end_ts = self.exchange.parse8601(end_str)
        else:
            end_ts = self.exchange.milliseconds()  # 默认到现在

        logger.info(f"📡 [Loader] 下载范围: {start_str} -> {end_str if end_str else 'NOW'} | 标的: {symbol}")

        all_ohlcv = []
        since = start_ts
        limit = 100

        while True:
            try:
                # 如果 since 已经超过结束时间，停止
                if since >= end_ts:
                    break

                ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, since, limit=limit)

                if not ohlcv:
                    break

                # 过滤掉超出 end_ts 的数据 (防止多下载)
                ohlcv = [x for x in ohlcv if x[0] <= end_ts]
                if not ohlcv:
                    break

                all_ohlcv.extend(ohlcv)
                last_ts = ohlcv[-1][0]

                # 更新起点
                since = last_ts + 1

                # 进度条
                current_date = pd.to_datetime(last_ts, unit='ms')
                print(f"\r⏳ 已下载: {len(all_ohlcv)} 条 | 当前: {current_date}", end="")

                # 防封休眠
                time.sleep(self.exchange.rateLimit / 1000)

            except Exception as e:
                logger.error(f"\n❌ 下载中断: {e}")
                time.sleep(2)
                continue

        print("\n")

        if not all_ohlcv:
            logger.warning(f"⚠️ 未找到数据或时间范围无效")
            return None

        # 保存
        df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

        if save_path:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            df.to_csv(save_path, index=False)
            logger.info(f"✅ 数据已保存: {save_path}")

        return df

    def fetch_and_save_data(self, symbol, timeframe, days, save_path):
        """
        [兼容旧代码] 按天数下载 (内部调用 fetch_history_range)
        """
        # 自动计算开始时间字符串
        start_ts = self.exchange.milliseconds() - (days * 24 * 60 * 60 * 1000)
        # 转换为 ISO 8601 字符串给 range 方法用
        start_str = self.exchange.iso8601(start_ts)

        return self.fetch_history_range(symbol, timeframe, start_str, end_str=None, save_path=save_path)

    # =========================================================

    def fetch_ohlcv(self, symbol, timeframe='1h', limit=100):
        for attempt in range(3):
            try:
                ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = df[col].astype(float)
                return df
            except Exception as e:
                time.sleep(1)
        return None

    def get_current_price(self, symbol):
        try:
            return self.exchange.fetch_ticker(symbol)['last']
        except:
            return 0.0

    def get_balance_usdt(self):
        if self.cfg.get("run_mode") == "PAPER": return 10000.0
        try:
            return float(self.exchange.fetch_balance().get('USDT', {}).get('free', 0))
        except:
            return 0.0


# === 单元测试：如何使用新功能 ===
if __name__ == "__main__":
    loader = MarketDataLoader()

    # 场景 1: 下载特定年份 (例如 2023 全年)
    print("📥 正在下载 2023 全年数据...")
    loader.fetch_history_range(
        symbol="BTC/USDT",
        timeframe="1h",
        start_str="2023-01-01 00:00:00",
        end_str="2024-01-01 00:00:00",
        save_path="data/BTC_2023.csv"
    )

    # 场景 2: 保持旧用法 (最近 10 天)
    print("📥 正在下载最近 10 天数据...")
    loader.fetch_and_save_data("BTC/USDT", "15m", 10, "data/BTC_recent.csv")