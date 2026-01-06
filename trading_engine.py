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

    def fetch_market_data(self, symbol="BTC/USDT", timeframe='15m', limit=100):
        try:
            # 1. 抓取 K 线
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

            # 必须保证有足够的数据来计算 RSI(14) 和 布林带(20)
            if not ohlcv or len(ohlcv) < 25:
                print(f"⚠️ K线数据不足 (只有 {len(ohlcv) if ohlcv else 0} 条)，等待下一轮...")
                return None

            # 2. 转为 DataFrame
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

            # ==========================================
            # 3. 计算指标 (强制重命名，杜绝 Key Error)
            # ==========================================

            # [RSI]
            # 计算后直接赋值给 'rsi' 列，不依赖自动列名
            rsi_series = df.ta.rsi(length=14)
            df['rsi'] = rsi_series

            # [MACD]
            # macd 方法返回 DataFrame，包含 3 列。我们只取 MACDh (柱状图)
            macd_df = df.ta.macd(fast=12, slow=26, signal=9)
            # MACDh 通常是中间那列，或者名字里带 'h' 的
            # 安全做法：找列名中包含 'MACDh' 的列
            macd_hist_col = [c for c in macd_df.columns if 'MACDh' in c][0]
            df['macd_hist'] = macd_df[macd_hist_col]

            # [Bollinger Bands]
            bb_df = df.ta.bbands(length=20, std=2)
            # BBU=Upper, BBL=Lower
            upper_col = [c for c in bb_df.columns if 'BBU' in c][0]
            lower_col = [c for c in bb_df.columns if 'BBL' in c][0]
            df['bb_upper'] = bb_df[upper_col]
            df['bb_lower'] = bb_df[lower_col]

            # 4. 获取最新一行 (且处理 NaN)
            last_row = df.iloc[-1].fillna(0)

            data = {
                "current_price": float(last_row['close']),
                "rsi": round(float(last_row['rsi']), 2),
                "macd": round(float(last_row['macd_hist']), 2),
                "bollinger": {
                    "upper": round(float(last_row['bb_upper']), 2),
                    "lower": round(float(last_row['bb_lower']), 2)
                }
            }

            # 再次检查：如果 RSI 还是 0 (说明计算失败)，给个中间值防止 AI 误判
            if data['rsi'] == 0:
                data['rsi'] = 50.0

            return data

        except Exception as e:
            print(f"❌ 获取行情失败: {e}")
            # 打印列名帮助调试 (如果不幸再次出错)
            # print(f"DEBUG Cols: {df.columns.tolist()}")
            return None


class OKXDemoTrader(OKXTraderBase):
    def __init__(self):
        super().__init__(is_demo=True)


class OKXRealTrader(OKXTraderBase):
    def __init__(self):
        super().__init__(is_demo=False)