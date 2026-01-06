import os
import ccxt
import pandas as pd
import pandas_ta as ta
import urllib3
from dotenv import load_dotenv
import traceback

load_dotenv()

# 禁用 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class OKXBaseEngine:
    """
    OKX 基础引擎：负责网络配置和公共行情数据获取
    """

    def __init__(self, api_key='', secret='', password='', is_demo=True):
        # 从环境变量获取代理端口，默认为 7897
        proxy_port = os.getenv('PROXY_PORT', '7897')
        proxy_url = f'socks5h://127.0.0.1:{proxy_port}'

        os.environ.pop('http_proxy', None)
        os.environ.pop('https_proxy', None)

        self.is_demo = is_demo

        # ccxt 配置
        self.exchange_config = {
            'apiKey': api_key,
            'secret': secret,
            'password': password,
            'enableRateLimit': True,
            'proxies': {
                'http': proxy_url,
                'https': proxy_url,
            },
            'timeout': 60000,
            'verify': False,
            'options': {
                'adjustForTimeDifference': True,
                'defaultType': 'spot',
            }
        }

        self.exchange = ccxt.okx(self.exchange_config)

        # 如果是模拟盘，必须开启 sandbox 模式
        if self.is_demo:
            self.exchange.set_sandbox_mode(True)
            print("💡 已启动 [模拟盘] 模式")
        else:
            print("⚠️ 已启动 [实盘] 模式 (请谨慎操作)")

    def fetch_market_data(self, symbol='BTC/USDT', timeframe='1m', limit=100):
        """
        获取行情数据（公共逻辑，模拟盘和实盘通用）
        """
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            if not ohlcv or len(ohlcv) < 30:
                print("⚠️ 抓取到的 K 线数据量不足")
                return None

            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

            # 指标计算
            df['RSI'] = ta.rsi(df['close'], length=14)
            macd_df = ta.macd(df['close'])
            macd_col = [c for c in macd_df.columns if c.startswith('MACD_') and 'h' not in c and 's' not in c][0]
            df = pd.concat([df, macd_df], axis=1)

            bbands_df = ta.bbands(df['close'], length=20, std=2)
            bbl_col = [c for c in bbands_df.columns if c.startswith('BBL_')][0]
            bbu_col = [c for c in bbands_df.columns if c.startswith('BBU_')][0]
            df = pd.concat([df, bbands_df], axis=1)

            df['EMA_20'] = ta.ema(df['close'], length=20)

            latest_row = df.iloc[-1]
            if pd.isna(latest_row['RSI']): return None

            # 深度和成交
            orderbook = self.exchange.fetch_order_book(symbol, limit=5)
            best_bid = orderbook['bids'][0][0] if orderbook['bids'] else None
            best_ask = orderbook['asks'][0][0] if orderbook['asks'] else None

            recent_trades = self.exchange.fetch_trades(symbol, limit=20)
            avg_trade_size = pd.DataFrame(recent_trades)['amount'].mean()

            return {
                "symbol": symbol,
                "current_price": float(latest_row['close']),
                "time": latest_row['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                "indicators": {
                    "RSI": round(float(latest_row['RSI']), 2),
                    "MACD": round(float(latest_row[macd_col]), 4),
                    "EMA_20": round(float(latest_row['EMA_20']), 2),
                    "BB_Upper": round(float(latest_row[bbu_col]), 2),
                    "BB_Lower": round(float(latest_row[bbl_col]), 2),
                },
                "market_context": {
                    "spread": round(float(best_ask - best_bid), 4) if best_bid and best_ask else 0,
                    "avg_trade_size": round(float(avg_trade_size), 4),
                    "volume_1m": round(float(latest_row['volume']), 4)
                }
            }
        except Exception as e:
            print(f"行情获取失败: {e}")
            return None

    def get_balance(self):
        """通用余额查询"""
        try:
            return self.exchange.fetch_balance()
        except Exception as e:
            print(f"获取余额失败: {e}")
            return None

    # --- [新增] 查询账户余额的方法 ---
    def get_account_balance(self):
        try:
            # fetch_balance 会返回所有币种的余额
            balance = self.exchange.fetch_balance()

            # 提取我们关心的 USDT 和 BTC
            usdt_free = balance.get('USDT', {}).get('free', 0)
            btc_free = balance.get('BTC', {}).get('free', 0)
            total_equity = balance.get('total', {}).get('USDT', 0)  # 估算总资产(USDT计价)

            return {
                "USDT": usdt_free,
                "BTC": btc_free,
                "Total_Equity": total_equity
            }
        except Exception as e:
            print(f"❌ 获取余额失败: {e}")
            return {"USDT": 0, "BTC": 0, "Total_Equity": 0}



# --- 子类 1：模拟盘 ---
class OKXDemoTrader(OKXBaseEngine):
    def __init__(self):
        # 显式从环境变量读取模拟盘密钥
        api_key = os.getenv('OKX_DEMO_API_KEY', '')
        secret = os.getenv('OKX_DEMO_SECRET', '')
        password = os.getenv('OKX_DEMO_PASSWORD', '')
        super().__init__(api_key, secret, password, is_demo=True)


# --- 子类 2：实盘 ---
class OKXRealTrader(OKXBaseEngine):
    def __init__(self):
        # 显式从环境变量读取实盘密钥
        api_key = os.getenv('OKX_API_KEY', '')
        secret = os.getenv('OKX_SECRET', '')
        password = os.getenv('OKX_PASSWORD', '')
        super().__init__(api_key, secret, password, is_demo=False)


# --- 运行测试 ---
if __name__ == "__main__":
    # 如果你想测试模拟盘
    print("--- 正在测试模拟盘 ---")
    trader = OKXDemoTrader()

    # 1. 测试抓取行情（行情数据一般实盘模拟盘通用的，但这里走的是模拟盘链路）
    data = trader.fetch_market_data('BTC/USDT')
    if data:
        print(f"最新价格: {data['current_price']}")

    # 2. 测试获取余额（如果你配置了模拟盘 API Key，这里能看到虚拟的 USDT）
    balance = trader.get_balance()
    if balance:
        print(f"可用 USDT: {balance['free'].get('USDT', 0)}")

    # 如果你想切换到实盘（目前没配置 Key 会报错或返回空，很安全）
    # trader_real = OKXRealTrader()