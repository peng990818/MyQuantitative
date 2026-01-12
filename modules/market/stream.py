import ccxt
import pandas as pd
import time
import sys
import os
from utils.logger import logger
from utils.config_loader import ConfigLoader
from utils.proxy_manager import ProxyManager


class MarketStream:
    def __init__(self, symbol="BTC/USDT", timeframe="1h"):
        """
        OKX 实盘行情流连接器
        """
        self.symbol = symbol
        self.timeframe = timeframe
        self.cfg = ConfigLoader()

        # 1. 获取代理 (OKX 必须)
        proxies = ProxyManager(self.cfg).get_proxies()

        # 2. 配置 Exchange
        exchange_config = {
            'enableRateLimit': True,  # 必须开启，防止被 OKX 封 IP
            'timeout': 30000,
            'options': {
                'defaultType': 'swap',  # 🔥 关键: 默认为永续合约 (Swap)
            }
        }

        if proxies:
            exchange_config['proxies'] = proxies
            # logger.info(f"🔗 [Stream] OKX 使用代理: {proxies}")

        self.exchange = ccxt.okx(exchange_config)

    def get_latest_candles(self, limit=300):
        """
        获取最新的 K 线数据 (适配 OKX 格式)
        """
        try:
            # OKX 的永续合约 symbol 通常不需要改，ccxt 会自动处理 defaultType
            # 如果 symbol 是 "BTC/USDT"，且 defaultType='swap'，它会自动找永续
            ohlcv = self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit=limit)

            if not ohlcv:
                logger.warning(f"⚠️ {self.symbol} 未获取到 K 线 (OKX 返回空)")
                return None

            # 转为 DataFrame
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

            # 确保排序
            df = df.sort_values('timestamp')

            # 数据类型转换
            df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(
                float)

            return df

        except Exception as e:
            logger.error(f"❌ [OKX] 获取行情失败: {e}")
            # 如果是网络错误，尝试重连逻辑可以写在这里
            return None

    def get_current_price(self):
        """
        获取最新成交价
        """
        try:
            ticker = self.exchange.fetch_ticker(self.symbol)
            return ticker['last']
        except Exception as e:
            logger.error(f"❌ [OKX] 获取价格失败: {e}")
            return None


# ==========================================
# 🔥 连接测试
# ==========================================
if __name__ == "__main__":
    # 路径黑魔法
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

    print(f"📡 正在连接 OKX (Type=Swap)...")

    # 注意: OKX 的永续合约代码通常也是 BTC/USDT，配合 defaultType='swap'
    stream = MarketStream(symbol="BTC/USDT", timeframe="1h")

    print("\n1. 请求 K 线...")
    df = stream.get_latest_candles(limit=5)

    if df is not None:
        print(f"✅ 获取成功! 最新时间: {df.iloc[-1]['timestamp']}")
        print(f"✅ 最新收盘价: {df.iloc[-1]['close']}")
        print(df.tail())
    else:
        print("❌ 获取失败，请检查代理设置")