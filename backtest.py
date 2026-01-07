import ccxt
import pandas as pd
import pandas_ta as ta
import matplotlib.pyplot as plt
import numpy as np
import os
import json
from datetime import datetime, timedelta
import warnings
from dotenv import load_dotenv

# 加载配置
load_dotenv(override=True)
warnings.simplefilter(action='ignore', category=FutureWarning)

# 🔥 核心：直接引入你的因子引擎，保证逻辑 100% 同步
from factor_engine import MultiFactorEngine


class RiskBacktester:
    def __init__(self, symbol='BTC/USDT', days=120):
        self.symbol = symbol
        self.days = days
        self.initial_capital = 10000

        # === ⚙️ 核心参数 (必须与 main.py 保持一致) ===
        self.TIMEFRAME_STRATEGY = '1h'  # 策略周期
        self.STOP_LOSS_PCT = 0.05  # 止损 5%
        self.TAKE_PROFIT_PCT = 0.20  # 止盈 20%
        self.COMMISSION = 0.001  # 手续费 0.1%

        self.engine = MultiFactorEngine()

        # 代理配置
        proxy_port = os.getenv("PROXY_PORT", "7890")
        self.exchange = ccxt.okx({
            'timeout': 30000,
            'proxies': {
                'http': f'http://127.0.0.1:{proxy_port}',
                'https': f'http://127.0.0.1:{proxy_port}',
            }
        })

        # 账户状态
        self.usdt = self.initial_capital
        self.btc = 0
        self.history = []  # 净值曲线
        self.trades = []  # 交易记录
        self.entry_price = 0.0  # 持仓成本

    def fetch_1m_data(self):
        """
        📥 获取 1m 原子数据
        这是所有回测的基础，包含了盘中最高价和最低价，用于精确测算止损。
        """
        safe_symbol = self.symbol.replace('/', '_')
        filename = f"data_{safe_symbol}_1m_{self.days}d.csv"
        file_path = os.path.join(os.getcwd(), filename)

        if os.path.exists(file_path):
            print(f"📂 加载本地 1m 基础数据: {filename}")
            df = pd.read_csv(file_path)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            return df

        print(f"📥 正在下载 {self.days} 天的 1m 数据 (数据量较大，请耐心等待)...")
        limit = 100
        since = self.exchange.milliseconds() - (self.days * 24 * 60 * 60 * 1000)
        all_ohlcv = []

        while since < self.exchange.milliseconds():
            try:
                ohlcv = self.exchange.fetch_ohlcv(self.symbol, '1m', since=since, limit=limit)
                if not ohlcv: break
                since = ohlcv[-1][0] + 1
                all_ohlcv += ohlcv
                print(f"   已下载 {len(all_ohlcv)} 条...", end="\r")
            except:
                break

        print(f"\n✅ 下载完成，共 {len(all_ohlcv)} 条。")
        df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

        # 保存缓存
        df.to_csv(file_path, index=False)
        return df

    def _calculate_indicators_1h(self, df_1h):
        """
        📐 计算 1H 指标
        复用之前的计算逻辑，确保 EMA, RSI 等指标是在 1H 级别上计算的。
        """

        # 辅助函数
        def get_series(res):
            if isinstance(res, pd.DataFrame): return res.iloc[:, 0]
            return res

        try:
            # 1. 基础
            df_1h['rsi'] = get_series(df_1h.ta.rsi(length=14))
            macd = df_1h.ta.macd(fast=12, slow=26, signal=9)
            if isinstance(macd, pd.DataFrame):
                df_1h['macd'] = macd.iloc[:, 0]
                df_1h['macd_signal'] = macd.iloc[:, 2]
            else:
                df_1h['macd'] = 0;
                df_1h['macd_signal'] = 0

            # 2. 动量
            kdj = df_1h.ta.stoch(k=9, d=3)
            if isinstance(kdj, pd.DataFrame):
                df_1h['kdj_k'] = kdj.iloc[:, 0];
                df_1h['kdj_d'] = kdj.iloc[:, 1]
            df_1h['cci'] = get_series(df_1h.ta.cci(length=20))
            df_1h['willr'] = get_series(df_1h.ta.willr(length=14))

            # 3. 趋势
            adx = df_1h.ta.adx(length=14)
            if isinstance(adx, pd.DataFrame):
                df_1h['adx'] = adx.iloc[:, 0];
                df_1h['dmp'] = adx.iloc[:, 1];
                df_1h['dmn'] = adx.iloc[:, 2]

            df_1h['ema_7'] = get_series(df_1h.ta.ema(length=7))
            df_1h['ema_25'] = get_series(df_1h.ta.ema(length=25))
            df_1h['ema_99'] = get_series(df_1h.ta.ema(length=99))

            # 4. 波动
            bb = df_1h.ta.bbands(length=20, std=2)
            if isinstance(bb, pd.DataFrame):
                df_1h['bb_lower'] = bb.iloc[:, 0];
                df_1h['bb_upper'] = bb.iloc[:, 2]
            df_1h['atr'] = get_series(df_1h.ta.atr(length=14))

            # 5. 资金
            df_1h['obv'] = get_series(df_1h.ta.obv())
            df_1h['mfi'] = get_series(df_1h.ta.mfi(length=14))
            df_1h['cmf'] = get_series(df_1h.ta.cmf(length=20))

            df_1h.dropna(inplace=True)
            return df_1h
        except Exception as e:
            print(f"❌ 指标计算错误: {e}")
            return pd.DataFrame()

    def _row_to_market_data(self, row):
        """将 DataFrame 行转为 Engine 需要的格式"""
        return {
            'symbol': self.symbol,
            'current_price': row['close'],
            'volume': row['volume'],
            'trend': {
                'ema_short': row['ema_7'], 'ema_long': row['ema_99'],
                'adx': row['adx'], 'di_plus': row['dmp'], 'di_minus': row['dmn']
            },
            'momentum': {
                'rsi': row['rsi'], 'cci': row['cci'], 'willr': row['willr'],
                'kdj_k': row['kdj_k'], 'kdj_d': row['kdj_d']
            },
            'volatility': {
                'atr': row['atr'], 'bb_upper': row['bb_upper'], 'bb_lower': row['bb_lower']
            },
            'volume': {
                'obv': row['obv'], 'mfi': row['mfi'], 'cmf': row['cmf']
            },
            'macd': row['macd'], 'macd_signal': row['macd_signal']
        }

    def run(self):
        # 1. 获取 1m 数据 (用于风控)
        df_1m = self.fetch_1m_data()
        if df_1m.empty: return

        # 2. 合成 1h 数据 (用于策略信号)
        print("🔄 正在合成 1H 数据并计算策略信号...")
        df_1m.set_index('timestamp', inplace=True)

        # Resample 到 1H
        agg_dict = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
        df_1h = df_1m.resample('1H').agg(agg_dict).dropna()
        df_1h.reset_index(inplace=True)

        # 计算 1H 指标
        df_1h = self._calculate_indicators_1h(df_1h)

        # 🔥 预计算所有 1H 的信号 (Actions)
        # 这样我们在 1m 循环时，直接查表即可，极大提高速度
        signal_map = {}
        mock_ai_result = {"score": 0, "reason": "Backtest"}  # 回测时不含AI分

        print("🤖 正在调用 Factor Engine 生成信号图谱...")
        for idx, row in df_1h.iterrows():
            market_data = self._row_to_market_data(row)
            tech_score, tech_sub, _ = self.engine.calculate_technical_score(market_data)
            fusion = self.engine.fuse_signals(tech_score, tech_sub, mock_ai_result)
            # Key 是 timestamp (整点时间)
            signal_map[row['timestamp']] = fusion['action']

        # 3. 开始 1m 级精细回放
        print("🚀 开始 1M 级高保真回放 (策略:1H | 风控:1M)...")
        df_1m.reset_index(inplace=True)

        for index, row in df_1m.iterrows():
            current_time = row['timestamp']
            current_price = row['close']

            # === A. 优先检查风控 (每分钟) ===
            if self.btc > 0:  # 只有持仓时才检查
                # 计算这分钟内的极端价格，看是否触发止盈止损
                low_price = row['low']
                high_price = row['high']

                # 浮动盈亏计算
                worst_pnl = (low_price - self.entry_price) / self.entry_price
                best_pnl = (high_price - self.entry_price) / self.entry_price

                # 1. 止损检查 (-5%)
                if worst_pnl <= -self.STOP_LOSS_PCT:
                    # 假设在触发价成交 (或者稍微滑一点)
                    exit_price = self.entry_price * (1 - self.STOP_LOSS_PCT)
                    self._execute_sell(current_time, exit_price, "STOP_LOSS")
                    continue  # 本分钟交易结束

                # 2. 止盈检查 (+20%)
                if best_pnl >= self.TAKE_PROFIT_PCT:
                    exit_price = self.entry_price * (1 + self.TAKE_PROFIT_PCT)
                    self._execute_sell(current_time, exit_price, "TAKE_PROFIT")
                    continue

            # === B. 检查策略信号 (仅在整点) ===
            # 我们检查当前时间是否在 signal_map 中
            # map 的 key 是 1H 的整点时间 (如 14:00:00)
            # df_1m 的 time 也是 timestamp

            # 为了对齐：通常我们是在整点收盘后，下一个整点的第0分钟开单
            # 简单做法：直接查表
            if current_time in signal_map:
                action = signal_map[current_time]

                if action in ["BUY", "STRONG_BUY"]:
                    # 只有空仓且有钱才买
                    if self.btc == 0 and self.usdt > 10:
                        self._execute_buy(current_time, current_price)

                elif action == "SELL":
                    # 只有持仓才卖
                    if self.btc > 0:
                        self._execute_sell(current_time, current_price, "STRATEGY_EXIT")

            # 记录净值
            total_val = self.usdt + (self.btc * current_price)
            self.history.append({'time': current_time, 'value': total_val, 'price': current_price})

        self._print_report()
        self._plot_curve()

    def _execute_buy(self, time, price):
        # 全仓买入
        qty = (self.usdt * 0.999) / price  # 留一点点余量防止精度问题
        cost = qty * price
        fee = cost * self.COMMISSION

        self.usdt -= cost
        self.btc += (qty - (qty * self.COMMISSION))  # 扣币式手续费
        self.entry_price = price

        self.trades.append({'time': time, 'type': 'BUY', 'price': price, 'qty': qty, 'reason': 'SIGNAL'})

    def _execute_sell(self, time, price, reason):
        # 全仓卖出
        qty = self.btc
        revenue = qty * price
        fee = revenue * self.COMMISSION

        self.btc = 0
        self.usdt += (revenue - fee)

        pnl_pct = (price - self.entry_price) / self.entry_price * 100
        self.trades.append(
            {'time': time, 'type': 'SELL', 'price': price, 'qty': qty, 'reason': f"{reason} ({pnl_pct:+.2f}%)"})
        self.entry_price = 0

    def _print_report(self):
        if not self.history: return
        end_val = self.history[-1]['value']
        profit = end_val - self.initial_capital
        roi = (profit / self.initial_capital) * 100

        # 计算最大回撤
        values = [h['value'] for h in self.history]
        peak = values[0]
        max_drawdown = 0
        for v in values:
            if v > peak: peak = v
            dd = (peak - v) / peak
            if dd > max_drawdown: max_drawdown = dd

        print("\n" + "=" * 60)
        print(f"📊 120天 回测报告 (策略:1H | 风控:1M)")
        print("=" * 60)
        print(f"💰 初始资金: {self.initial_capital:.2f} U")
        print(f"💰 最终资金: {end_val:.2f} U")
        print(f"📈 净利润  : {profit:+.2f} U")
        print(f"🚀 收益率  : {roi:+.2f}%")
        print(f"🛡️ 最大回撤: {max_drawdown * 100:.2f}%")
        print(f"📝 交易次数: {len(self.trades)}")
        print("-" * 60)
        print("交易明细:")
        for t in self.trades[-10:]:  # 只打最后10条
            print(f"  {t['time']} {t['type']} @ {t['price']:.2f} [{t['reason']}]")
        if len(self.trades) > 10: print("  ... (更多记录已省略)")
        print("=" * 60)

    def _plot_curve(self):
        if not self.history: return
        # 因为数据量太大(120天*1440分钟)，绘图时降采样一下，每小时画一个点
        df_res = pd.DataFrame(self.history)
        df_res = df_res.iloc[::60, :]

        fig, ax1 = plt.subplots(figsize=(12, 6))
        ax1.plot(df_res['time'], df_res['value'], color='blue', label='Equity')
        ax1.set_ylabel('USDT', color='blue')

        ax2 = ax1.twinx()
        ax2.plot(df_res['time'], df_res['price'], color='gray', alpha=0.3, label='BTC Price')

        # 标记买卖点
        for t in self.trades:
            if t['type'] == 'BUY':
                ax1.scatter(t['time'], t['price'], marker='^', color='green', s=80)
            else:
                # 区分止损和策略卖出
                color = 'red' if 'STOP' in t['reason'] else 'orange'
                ax1.scatter(t['time'], t['price'], marker='v', color=color, s=80)

        plt.title(f"Backtest: 1H Strategy + 1M Risk Control ({self.days} Days)")
        plt.show()


if __name__ == "__main__":
    # 直接运行
    bt = RiskBacktester(symbol='BTC/USDT', days=120)
    bt.run()