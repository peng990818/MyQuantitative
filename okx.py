from dotenv import load_dotenv
import os
import ccxt
import pandas as pd
import pandas_ta as ta
import urllib3

load_dotenv()

# 禁用 SSL 警告（针对部分代理环境）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class OKXDataEngine:
    def __init__(self, api_key='', secret='', password='', proxy_port='7897'):
        # 建议换成 socks5h 协议，它让代理服务器解析域名，躲避干扰最有效
        proxy_url = f'socks5h://127.0.0.1:{proxy_port}'

        # 显式清理，防止环境变量冲突
        os.environ.pop('http_proxy', None)
        os.environ.pop('https_proxy', None)

        self.exchange = ccxt.okx({
            'apiKey': api_key,
            'secret': secret,
            'password': password,
            'enableRateLimit': True,
            'proxies': {
                'http': proxy_url,
                'https': proxy_url,
            },
            'timeout': 60000,  # 增加到 60 秒，代理链路长，给它宽限时间
            'verify': False,
            'options': {
                'adjustForTimeDifference': True,  # 自动校准 Intel Mac 与服务器的时间差
                'defaultType': 'spot',  # 只加载现货市场，大幅减少初始化数据量
            }
        })

    def fetch_market_data(self, symbol='BTC/USDT', timeframe='1m', limit=100):
        """
        获取核心技术信息：K线、指标、深度、成交
        """
        try:
            # 1. 获取 OHLCV (K线数据)
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            if not ohlcv or len(ohlcv) < 30:
                print("⚠️ 抓取到的 K 线数据量不足，无法计算指标")
                return None

            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

            # 2. 计算技术指标
            # RSI
            df['RSI'] = ta.rsi(df['close'], length=14)

            # MACD (动态获取列名)
            macd_df = ta.macd(df['close'])
            # 寻找主线 MACD_12_26_9 这种格式的列
            macd_col = [c for c in macd_df.columns if c.startswith('MACD_') and 'h' not in c and 's' not in c][0]
            df = pd.concat([df, macd_df], axis=1)

            # 布林带 (动态获取列名)
            bbands_df = ta.bbands(df['close'], length=20, std=2)
            bbl_col = [c for c in bbands_df.columns if c.startswith('BBL_')][0]
            bbu_col = [c for c in bbands_df.columns if c.startswith('BBU_')][0]
            df = pd.concat([df, bbands_df], axis=1)

            # EMA
            df['EMA_20'] = ta.ema(df['close'], length=20)

            # 3. 检查最后一行数据是否有效 (防止 NaN)
            latest_row = df.iloc[-1]
            if pd.isna(latest_row['RSI']) or pd.isna(latest_row[bbu_col]):
                print("⚠️ 技术指标计算中，请稍候再试（冷启动阶段）")
                return None

            # 4. 获取市场深度
            orderbook = self.exchange.fetch_order_book(symbol, limit=5)
            best_bid = orderbook['bids'][0][0] if orderbook['bids'] else None
            best_ask = orderbook['asks'][0][0] if orderbook['asks'] else None
            bid_ask_spread = best_ask - best_bid if best_bid and best_ask else 0

            # 5. 获取最近成交
            recent_trades = self.exchange.fetch_trades(symbol, limit=20)
            avg_trade_size = pd.DataFrame(recent_trades)['amount'].mean()

            # 封装结果
            latest_data = {
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
                    "spread": round(float(bid_ask_spread), 4),
                    "avg_trade_size": round(float(avg_trade_size), 4),
                    "volume_1m": round(float(latest_row['volume']), 4)
                }
            }
            return latest_data

        except Exception as e:
            print(f"数据获取失败: {e}")
            import traceback
            traceback.print_exc()  # 打印完整堆栈，方便调试
            return None


if __name__ == "__main__":
    engine = OKXDataEngine()
    print("🚀 启动 OKX 数据引擎单测...")

    target_symbol = 'BTC/USDT'
    data = engine.fetch_market_data(symbol=target_symbol)

    if data:
        print(f"\n✅ 成功获取 {target_symbol} 实时技术信息:")
        print("-" * 30)
        print(f"当前价格: {data['current_price']}")
        print(f"获取时间: {data['time']}")
        print("\n[技术指标]")
        for k, v in data['indicators'].items():
            print(f"  {k}: {v}")
        print("\n[市场上下文]")
        for k, v in data['market_context'].items():
            print(f"  {k}: {v}")
        print("-" * 30)
    else:
        print("\n❌ 运行结束，未获取到有效数据。")