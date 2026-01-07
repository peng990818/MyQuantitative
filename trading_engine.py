import ccxt
import pandas as pd
import pandas_ta as ta
import os
import time
from dotenv import load_dotenv

load_dotenv(override=True)


class OKXTraderBase:
    def __init__(self, is_demo=True):
        self.is_demo = is_demo
        self.exchange = None
        self._init_exchange()

    def _init_exchange(self):
        if self.is_demo:
            api_key = os.getenv("OKX_DEMO_API_KEY")
            secret = os.getenv("OKX_DEMO_SECRET")
            password = os.getenv("OKX_DEMO_PASSWORD")
        else:
            api_key = os.getenv("OKX_REAL_API_KEY")
            secret = os.getenv("OKX_REAL_SECRET")
            password = os.getenv("OKX_REAL_PASSWORD")

        proxy_port = os.getenv("PROXY_PORT", "7890")

        exchange_config = {
            'apiKey': api_key,
            'secret': secret,
            'password': password,
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'},
            'proxies': {
                'http': f'http://127.0.0.1:{proxy_port}',
                'https': f'http://127.0.0.1:{proxy_port}',
            }
        }

        self.exchange = ccxt.okx(exchange_config)
        if self.is_demo:
            self.exchange.set_sandbox_mode(True)

    def get_account_balance(self):
        try:
            balance = self.exchange.fetch_balance()
            usdt = balance.get('USDT', {}).get('free', 0)
            btc = balance.get('BTC', {}).get('free', 0)
            return {'USDT': float(usdt), 'BTC': float(btc)}
        except Exception as e:
            print(f"❌ 获取余额失败: {e}")
            return {'USDT': 0, 'BTC': 0}

    def fetch_market_data(self, symbol, timeframe='15m', limit=100):
        try:
            # 1. 获取 K 线数据
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

            # 2. 计算技术指标 (使用 pandas_ta)
            # --- 基础震荡 ---
            df['rsi'] = df.ta.rsi(length=14)

            # MACD
            macd = df.ta.macd(fast=12, slow=26, signal=9)
            df['macd'] = macd.iloc[:, 0]  # MACD 线
            df['macd_signal'] = macd.iloc[:, 1]  # 信号线 (用于金叉死叉)

            # 布林带
            bb = df.ta.bbands(length=20, std=2)
            df['bb_upper'] = bb.iloc[:, 0]
            df['bb_lower'] = bb.iloc[:, 2]

            # --- 🔥 [新增] 趋势与能量指标 🔥 ---
            # EMA 趋势线
            df['ema_7'] = df.ta.ema(length=7)  # 短线
            df['ema_99'] = df.ta.ema(length=99)  # 牛熊分界线

            # ATR 波动率 (判断市场活跃度)
            df['atr'] = df.ta.atr(length=14)

            # OBV 能量潮 (判断资金流入流出)
            df['obv'] = df.ta.obv()

            # 3. 获取最新数据
            latest = df.iloc[-1]

            # 4. 组装数据包
            return {
                'symbol': symbol,
                'current_price': float(latest['close']),
                'volume': float(latest['volume']),
                # 基础
                'rsi': float(latest['rsi']),
                'macd': float(latest['macd']),
                'macd_signal': float(latest['macd_signal']),
                'bollinger': {
                    'upper': float(latest['bb_upper']),
                    'lower': float(latest['bb_lower'])
                },
                # 进阶
                'ema': {
                    'short': float(latest['ema_7']),
                    'long': float(latest['ema_99'])
                },
                'atr': float(latest['atr']),
                'obv': float(latest['obv'])
            }
        except Exception as e:
            print(f"❌ 获取行情失败: {e}")
            return None

class OKXDemoTrader(OKXTraderBase):
    def __init__(self):
        super().__init__(is_demo=True)


class OKXRealTrader(OKXTraderBase):
    def __init__(self):
        super().__init__(is_demo=False)