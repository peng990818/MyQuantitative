import ccxt
import pandas as pd
import pandas_ta as ta
import os
import time
import json
import warnings
from datetime import datetime
from dotenv import load_dotenv

# [新增] 屏蔽 Pandas 的 FutureWarning
warnings.simplefilter(action='ignore', category=FutureWarning)

load_dotenv(override=True)


# ... (保留原本的 OKXTraderBase 类不动) ...
class OKXTraderBase:
    def __init__(self, is_demo=True):
        self.is_demo = is_demo
        self.exchange = None
        self._init_exchange()

    def _init_exchange(self):
        # 注意：这里我们依然需要连接交易所来获取行情
        if self.is_demo:
            api_key = os.getenv("OKX_DEMO_API_KEY")
            secret = os.getenv("OKX_DEMO_SECRET")
            password = os.getenv("OKX_DEMO_PASSWORD")
        else:
            api_key = os.getenv("OKX_REAL_API_KEY")
            secret = os.getenv("OKX_REAL_SECRET")
            password = os.getenv("OKX_REAL_PASSWORD")

        # 🔥 [修改] 默认值设为空字符串，实现智能代理
        proxy_port = os.getenv("PROXY_PORT", "")

        exchange_config = {
            'apiKey': api_key,
            'secret': secret,
            'password': password,
            'enableRateLimit': True,

            # 🔥 [优化] 增大超时时间到 30秒，防止网络抖动报错
            'timeout': 30000,

            'options': {'defaultType': 'swap'},
        }

        # 🔥 [新增] 智能判断：只有当配置了端口时，才加上代理
        if proxy_port:
            exchange_config['proxies'] = {
                'http': f'http://127.0.0.1:{proxy_port}',
                'https': f'http://127.0.0.1:{proxy_port}',
            }
            print(f"🌍 [OKX] 使用代理连接: 127.0.0.1:{proxy_port}")
        else:
            print("🚀 [OKX] 检测到无代理配置，使用直连模式 (Direct Connection)")

        self.exchange = ccxt.okx(exchange_config)

        # PaperTrader 不需要 sandbox，因为它只读行情，不交易
        if self.is_demo and not isinstance(self, OKXPaperTrader):
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

    def fetch_market_data(self, symbol, timeframe='1h', limit=100):
        # 🔥 [新增] 失败重试机制
        max_retries = 3
        df = None

        for attempt in range(max_retries):
            try:
                ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                # 如果成功获取，跳出重试循环
                break
            except Exception as e:
                print(f"⚠️ [第 {attempt + 1} 次] 获取行情失败: {e}")
                if attempt < max_retries - 1:
                    time.sleep(3)  # 等待 3 秒后重试
                else:
                    print("❌ 重试多次无效，放弃本次扫描。")
                    return None

        try:
            # 强制转换 float
            numeric_cols = ['open', 'high', 'low', 'close', 'volume']
            for col in numeric_cols:
                df[col] = df[col].astype(float)
            df['timestamp'] = df['timestamp'].astype(int)

            # === 因子计算 (保持不变) ===
            df['rsi'] = df.ta.rsi(length=14)
            macd = df.ta.macd(fast=12, slow=26, signal=9)
            df['macd'] = macd.iloc[:, 0]
            df['macd_signal'] = macd.iloc[:, 1]

            kdj = df.ta.stoch(k=9, d=3)
            df['kdj_k'] = kdj.iloc[:, 0]
            df['kdj_d'] = kdj.iloc[:, 1]
            df['cci'] = df.ta.cci(length=20)
            df['willr'] = df.ta.willr(length=14)

            adx = df.ta.adx(length=14)
            df['adx'] = adx.iloc[:, 0]
            df['dmp'] = adx.iloc[:, 1]
            df['dmn'] = adx.iloc[:, 2]

            df['ema_7'] = df.ta.ema(length=7)
            df['ema_25'] = df.ta.ema(length=25)
            df['ema_99'] = df.ta.ema(length=99)

            bb = df.ta.bbands(length=20, std=2)
            df['bb_upper'] = bb.iloc[:, 0]
            df['bb_lower'] = bb.iloc[:, 2]
            df['bb_width'] = bb.iloc[:, 4]
            df['atr'] = df.ta.atr(length=14)

            df['obv'] = df.ta.obv()
            df['mfi'] = df.ta.mfi(length=14)
            df['cmf'] = df.ta.cmf(length=20)

            latest = df.iloc[-1]

            return {
                'symbol': symbol,
                'current_price': float(latest['close']),
                'volume': float(latest['volume']),
                'trend': {
                    'ema_short': float(latest['ema_7']),
                    'ema_long': float(latest['ema_99']),
                    'adx': float(latest['adx']),
                    'di_plus': float(latest['dmp']),
                    'di_minus': float(latest['dmn'])
                },
                'momentum': {
                    'rsi': float(latest['rsi']),
                    'cci': float(latest['cci']),
                    'willr': float(latest['willr']),
                    'kdj_k': float(latest['kdj_k']),
                    'kdj_d': float(latest['kdj_d'])
                },
                'volatility': {
                    'atr': float(latest['atr']),
                    'bb_width': float(latest['bb_width']),
                    'bb_upper': float(latest['bb_upper']),
                    'bb_lower': float(latest['bb_lower'])
                },
                'volume': {
                    'obv': float(latest['obv']),
                    'mfi': float(latest['mfi']),
                    'cmf': float(latest['cmf'])
                },
                'macd': float(latest['macd']),
                'macd_signal': float(latest['macd_signal'])
            }
        except Exception as e:
            print(f"❌ 数据处理异常: {e}")
            return None


class OKXDemoTrader(OKXTraderBase):
    def __init__(self):
        super().__init__(is_demo=True)


class OKXRealTrader(OKXTraderBase):
    def __init__(self):
        super().__init__(is_demo=False)


# ==========================================
# 📝 [新增] 纸面交易员 (Paper Trader)
# ==========================================
class OKXPaperTrader(OKXTraderBase):
    def __init__(self, initial_usdt=10000.0):
        # 继承 Base，但不连接 sandbox，而是连接 Real 获取真实数据
        # 我们这里传 is_demo=True 仅仅为了初始化，后面我们会覆盖 create_order
        super().__init__(is_demo=True)

        # 🔥 [修改] 读取端口，默认为空
        proxy_port = os.getenv("PROXY_PORT", "")

        # 基础配置
        paper_config = {
            'enableRateLimit': True,
            # 🔥 [优化] 同样加上超时设置
            'timeout': 30000,
        }

        # 🔥 [新增] 只有有端口时才加代理
        if proxy_port:
            paper_config['proxies'] = {
                'http': f'http://127.0.0.1:{proxy_port}',
                'https': f'http://127.0.0.1:{proxy_port}',
            }
            print(f"📝 [模拟实盘] 使用代理连接实盘行情")
        else:
            print(f"📝 [模拟实盘] 直连模式连接实盘行情")

        self.exchange = ccxt.okx(paper_config)

        self.balance_file = "paper_balance.json"
        self.commission_rate = 0.001  # 0.1% 手续费

        # 加载或初始化虚拟余额
        self.virtual_balance = self._load_balance(initial_usdt)

    def _load_balance(self, initial_usdt):
        if os.path.exists(self.balance_file):
            try:
                with open(self.balance_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {'USDT': initial_usdt, 'BTC': 0.0}

    def _save_balance(self):
        with open(self.balance_file, 'w') as f:
            json.dump(self.virtual_balance, f, indent=4)

    # 🔥 覆盖：返回虚拟余额
    def get_account_balance(self):
        return self.virtual_balance

    # 🔥 覆盖：模拟下单
    def mock_create_order(self, symbol, side, qty, price):
        # 模拟滑点 (买入稍微贵一点，卖出稍微便宜一点)
        slippage = 0.0002  # 0.02% 随机滑点
        import random
        # 简单的随机正负滑点模拟
        real_slippage = random.uniform(-slippage, slippage)
        real_price = price * (1 + real_slippage)

        cost = qty * real_price
        fee = cost * self.commission_rate

        if side == 'buy':
            if self.virtual_balance['USDT'] >= cost:
                self.virtual_balance['USDT'] -= cost
                self.virtual_balance['BTC'] += (qty - (qty * self.commission_rate))
                print(f"📝 [模拟成交] 买入 {qty} BTC @ {real_price:.2f} (手续费: {fee:.2f} U)")
                self._save_balance()
                return {'average': real_price, 'price': real_price, 'status': 'closed'}
            else:
                print("❌ [模拟失败] USDT 余额不足")
                return None

        elif side == 'sell':
            if self.virtual_balance['BTC'] >= qty:
                revenue = qty * real_price
                fee = revenue * self.commission_rate
                self.virtual_balance['BTC'] -= qty
                self.virtual_balance['USDT'] += (revenue - fee)
                print(f"📝 [模拟成交] 卖出 {qty} BTC @ {real_price:.2f} (手续费: {fee:.2f} U)")
                self._save_balance()
                return {'average': real_price, 'price': real_price, 'status': 'closed'}
            else:
                print("❌ [模拟失败] BTC 余额不足")
                return None