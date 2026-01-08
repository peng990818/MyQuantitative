import ccxt
import time
import pandas as pd
from utils.config_loader import ConfigLoader
from utils.proxy_manager import ProxyManager
from utils.logger import logger


class MarketDataLoader:
    def __init__(self):
        self.cfg = ConfigLoader()
        self.exchange = None
        self._init_exchange()

    def _init_exchange(self):
        """初始化交易所连接 (支持 REAL / DEMO / PAPER)"""
        mode = self.cfg.get("run_mode", "PAPER").upper()
        proxies = ProxyManager(self.cfg).get_proxies()

        # 基础配置
        exchange_config = {
            'enableRateLimit': True,
            'timeout': 30000,
            'options': {'defaultType': 'swap'},  # 默认合约
        }

        # 注入代理
        if proxies:
            exchange_config['proxies'] = proxies

        # === 模式分流 ===
        if mode == "REAL":
            # 1. 实盘模式
            exchange_config['apiKey'] = self.cfg.get("exchange.okx.api_key")
            exchange_config['secret'] = self.cfg.get("exchange.okx.secret")
            exchange_config['password'] = self.cfg.get("exchange.okx.password")
            logger.warning("🚨 [Market] 正在连接 OKX 【实盘】环境！")

        elif mode == "DEMO":
            # 2. 模拟盘模式 (OKX Testnet)
            exchange_config['apiKey'] = self.cfg.get("exchange.okx.demo_api_key")
            exchange_config['secret'] = self.cfg.get("exchange.okx.demo_secret")
            exchange_config['password'] = self.cfg.get("exchange.okx.demo_password")

            # 🔥 关键设置：开启沙箱模式
            exchange_config['sandbox'] = True
            logger.info("🎮 [Market] 正在连接 OKX 【模拟盘】环境")

        else:
            # 3. 游客/纸面模式
            logger.info("📝 [Market] 运行在本地回测模式 (只读公共数据)")
            self.exchange = ccxt.okx(exchange_config)
            return

        # 初始化 CCXT 对象
        try:
            self.exchange = ccxt.okx(exchange_config)

            # 检查连接 (获取一次余额验证 Key 是否正确)
            # 注意：模拟盘余额获取可能会因为网络波动失败，不强制抛出异常
            try:
                self.exchange.load_markets()
                logger.info(f"✅ [Market] 交易所连接成功 (模式: {mode})")
            except Exception as e:
                logger.error(f"❌ [Market] 连接验证失败，请检查 Key 或网络: {e}")

        except Exception as e:
            logger.error(f"❌ [Market] 初始化异常: {e}")

    def fetch_ohlcv(self, symbol, timeframe='1h', limit=100):
        """获取K线"""
        for attempt in range(3):
            try:
                ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = df[col].astype(float)
                return df
            except Exception as e:
                logger.warning(f"⚠️ [Market] K线获取失败 ({attempt + 1}/3): {e}")
                time.sleep(2)
        return None

    def get_current_price(self, symbol):
        """获取价格"""
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return ticker['last']
        except Exception as e:
            logger.error(f"❌ 获取价格失败: {e}")
            return 0.0

    def get_balance_usdt(self):
        """获取余额"""
        # 如果是 PAPER 模式，返回本地假钱
        if self.cfg.get("run_mode") == "PAPER":
            return 10000.0

        # REAL 或 DEMO 模式，去交易所查
        try:
            bal = self.exchange.fetch_balance()
            # 注意：合约账户通常是 USDT，如果是统一账户可能是 'free'
            return float(bal.get('USDT', {}).get('free', 0))
        except Exception as e:
            logger.error(f"❌ 获取余额失败: {e}")
            return 0.0


# === 单元测试 ===
if __name__ == "__main__":
    import sys, os

    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

    loader = MarketDataLoader()

    print("-" * 30)
    print("⏳ 测试 1: 获取行情...")
    price = loader.get_current_price("BTC/USDT")
    print(f"✅ 当前价格: {price}")

    print("-" * 30)
    print("⏳ 测试 2: 获取账户余额 (请确保 secrets.yaml 配置正确)...")
    bal = loader.get_balance_usdt()
    print(f"✅ 当前可用余额: {bal} USDT")