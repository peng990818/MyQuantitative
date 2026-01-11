import pandas as pd
import matplotlib.pyplot as plt
import mplfinance as mpf
import os
import sys
import warnings
from datetime import timedelta
import numpy as np
import re

# === 基础设置 ===
warnings.simplefilter(action='ignore', category=FutureWarning)
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.config_loader import ConfigLoader
from utils.logger import logger
from modules.market.loader import MarketDataLoader
from core.position import PositionManager

# 🔥 引入 AI 预言机
from core.market_oracle import MarketRegimeOracle

# 引入 v20 策略 (策略路由版)
from strategies.sniper_router import SniperRouterStrategy


def parse_timeframe(tf: str):
    m = re.fullmatch(r"(\d+)([mh])", tf.strip().lower())
    if not m: raise ValueError(f"Timeframe Error: {tf}")
    n, unit = int(m.group(1)), m.group(2)
    return (f"{n}H", timedelta(hours=n)) if unit == "h" else (f"{n}min", timedelta(minutes=n))


class BacktestEngine:
    def __init__(self, symbol="BTC/USDT", days=120, start_date=None, end_date=None):
        self.cfg = ConfigLoader()
        self.cfg._config['run_mode'] = 'BACKTEST'
        self.symbol = symbol
        self.days = days
        self.start_date = start_date
        self.end_date = end_date

        self.timeframe_str = "1h"
        self.tf_freq, self.tf_delta = parse_timeframe(self.timeframe_str)

        self.market = MarketDataLoader()
        self.pos_manager = PositionManager()

        # 🔥 初始化 AI 预言机
        # 你需要自己创建一个 csv 放在 data/ai_regime.csv，或者它会默认用技术指标
        self.oracle = MarketRegimeOracle(data_path="data/ai_regime.csv")

        # 加载 v20 策略
        self.strategy = SniperRouterStrategy()
        logger.info(f"🧠 已加载策略: {self.strategy.name}")

        # 账户
        self.initial_balance = 10000.0
        self.usdt = self.initial_balance
        self.btc = 0.0
        self.entry_price = 0.0
        self.trades = []
        self.equity_curve = []

        # 风控变量
        self.target_tp_price = 0.0
        self.target_sl_price = 0.0

        # 移动止盈状态
        self.trailing_enabled = False
        self.trailing_active = False
        self.trailing_activation_price = 0.0
        self.trailing_callback_pct = 0.0
        self.highest_price_since_entry = 0.0

        self.commission = 0.001
        self.slippage_bps = 5
        self.equity_sample_minutes = 60
        self.df_tf = None

        # 记录 AI 历史状态用于绘图
        self.ai_regime_history = []

    def fetch_and_prepare(self):
        # ... (保持不变) ...
        safe_symbol = self.symbol.replace('/', '_')
        if self.start_date:
            s_tag = self.start_date.split(' ')[0]
            e_tag = self.end_date.split(' ')[0] if self.end_date else "NOW"
            cache_file = f"data/backtest_{safe_symbol}_{s_tag}_{e_tag}.csv"
            if not os.path.exists(cache_file):
                logger.info(f"📥 正在下载指定范围数据: {self.start_date} -> {self.end_date}")
                self.market.fetch_history_range(self.symbol, "1m", self.start_date, self.end_date, cache_file)
        else:
            cache_file = f"data/backtest_{safe_symbol}_{self.days}d.csv"
            if not os.path.exists(cache_file):
                logger.info(f"📥 正在下载最近 {self.days} 天数据...")
                self.market.fetch_and_save_data(self.symbol, "1m", self.days, cache_file)

        if not os.path.exists(cache_file):
            logger.error("❌ 数据文件未找到")
            sys.exit(1)

        df_1m = pd.read_csv(cache_file)
        df_1m['timestamp'] = pd.to_datetime(df_1m['timestamp'])
        df_1m.sort_values('timestamp', inplace=True)
        df_1m.set_index('timestamp', inplace=True)

        df_tf = df_1m.resample(self.tf_freq, label="left", closed="left").agg({
            'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
        }).dropna()

        df_tf = self.strategy.calculate_indicators(df_tf)
        df_tf.dropna(inplace=True)
        self.df_tf = df_tf.copy()

        df_1m.reset_index(inplace=True)
        df_tf.reset_index(inplace=True)
        return df_1m, df_tf

    def run(self):
        df_1m, df_tf = self.fetch_and_prepare()

        print(f"📉 预计算策略信号...")
        signal_map = {}

        # 遍历 1H K线生成信号
        for index, row in df_tf.iterrows():
            curr_time = row['timestamp']

            # 🔥🔥🔥 关键修改：获取 AI 观点并注入策略 🔥🔥🔥
            # 1. 问预言机
            ai_regime = self.oracle.get_regime(curr_time)

            # 2. 注入到 row 数据中 (临时添加一列)
            # 策略里的 check_signal 会读取这一列
            row_with_ai = row.copy()
            if ai_regime:
                row_with_ai['AI_REGIME'] = ai_regime
                self.ai_regime_history.append({'time': curr_time, 'regime': ai_regime})

            # 3. 策略根据 AI 观点 + 技术指标 生成信号
            sig = self.strategy.check_signal(row_with_ai)

            if sig['action'] == "BUY":
                signal_map[curr_time] = sig

        last_candle_time = None

        print(f"▶️ 开始回放...")
        for _, row in df_1m.iterrows():
            curr_time = row['timestamp']
            curr_price = float(row['close'])
            current_candle_start = curr_time.floor(self.tf_freq)
            prev_candle_finished = current_candle_start - self.tf_delta

            if self.btc > 0:
                if self._handle_risk_dynamic(curr_time, row):
                    self._sample_equity(curr_time, curr_price)
                    continue

            if current_candle_start != last_candle_time:
                sig = signal_map.get(prev_candle_finished)
                if sig and sig['action'] == "BUY" and self.btc == 0:
                    self._execute_buy(curr_time, curr_price, sig)
                last_candle_time = current_candle_start

            self._sample_equity(curr_time, curr_price)

        if self.btc > 0:
            self._execute_sell(df_1m.iloc[-1]['timestamp'], df_1m.iloc[-1]['close'], "END")

        self._show_report()

    # ... (风控 _handle_risk_dynamic, _execute_buy, _execute_sell, _sample_equity 保持不变) ...
    def _handle_risk_dynamic(self, time, row_1m):
        high = float(row_1m['high'])
        low = float(row_1m['low'])

        # 1. 硬止损
        if low <= self.target_sl_price:
            fill = min(float(row_1m['open']), self.target_sl_price) * (1 - self.slippage_bps / 10000)
            self._execute_sell(time, fill, "🛑 STOP_LOSS")
            return True

        # 2. 移动止盈
        if self.trailing_enabled:
            if high > self.highest_price_since_entry:
                self.highest_price_since_entry = high

            if not self.trailing_active:
                if high >= self.trailing_activation_price:
                    self.trailing_active = True

            if self.trailing_active:
                dynamic_sl = self.highest_price_since_entry * (1 - self.trailing_callback_pct)
                if low <= dynamic_sl:
                    self._execute_sell(time, dynamic_sl, "🏄 TRAILING_PROFIT")
                    return True

        # 3. 固定止盈
        if high >= self.target_tp_price:
            self._execute_sell(time, self.target_tp_price, "🚀 FIXED_TP")
            return True

        return False

    def _execute_buy(self, t, p, sig):
        qty = self.pos_manager.calculate_buy_size(p, self.usdt)
        if qty <= 0: return

        p_real = p * (1 + self.slippage_bps / 10000)
        cost = qty * p_real * (1 + self.commission)
        if cost > self.usdt: return

        self.usdt -= cost
        self.btc = qty
        self.entry_price = p_real

        sl_pct = sig.get('sl_pct', 0.05)
        self.target_sl_price = p_real * (1 - sl_pct)

        tp_pct = sig.get('tp_pct', 0.08)
        self.target_tp_price = p_real * (1 + tp_pct)

        self.trailing_enabled = sig.get('use_trailing', False)
        if self.trailing_enabled:
            t_start = sig.get('trailing_start', 0.03)
            self.trailing_activation_price = p_real * (1 + t_start)
            self.trailing_callback_pct = sig.get('trailing_drop', 0.02)
            self.trailing_active = False
            self.highest_price_since_entry = p_real

        self.trades.append({'time': t, 'type': 'BUY', 'price': p_real, 'qty': qty,
                            'mode': 'TRAILING' if self.trailing_enabled else 'FIXED'})

    def _execute_sell(self, t, p, reason):
        rev = self.btc * p * (1 - self.commission)
        pnl = rev - (self.btc * self.entry_price)
        pnl_pct = pnl / (self.btc * self.entry_price) * 100
        self.usdt += rev
        self.trades.append({'time': t, 'type': 'SELL', 'price': p, 'pnl': pnl, 'pnl_pct': pnl_pct, 'reason': reason})
        self.btc = 0
        self.entry_price = 0

    def _sample_equity(self, t, p):
        if t.minute % self.equity_sample_minutes == 0:
            self.equity_curve.append({'time': t, 'equity': self.usdt + self.btc * p})

    def _show_report(self):
        if not self.trades:
            print("⚠️ 无交易记录")
            return

        df_trades = pd.DataFrame(self.trades)
        df_equity = pd.DataFrame(self.equity_curve).set_index('time')

        final_equity = df_equity.iloc[-1]['equity']
        total_return = (final_equity - self.initial_balance) / self.initial_balance * 100

        sells = df_trades[df_trades['type'] == 'SELL']
        total_trades = len(sells)
        wins = sells[sells['pnl'] > 0]
        win_rate = len(wins) / total_trades * 100 if total_trades > 0 else 0

        print("\n" + "=" * 50)
        print(f"📊 策略: {self.strategy.name}")
        print("-" * 50)
        print(f"💰 最终净值: {final_equity:.2f} USDT")
        print(f"📈 收益率  : {total_return:+.2f}%")
        print(f"🔄 交易次数: {total_trades}")
        print(f"🎯 胜率    : {win_rate:.1f}%")
        print("=" * 50 + "\n")

        print("🔍 最近 5 笔交易详情:")
        print(df_trades[['time', 'type', 'pnl_pct', 'reason']].tail(10))
        print("=" * 50 + "\n")

        self._plot_charts(df_trades, df_equity)

    def _plot_charts(self, df_trades, df_equity):
        logger.info("🎨 正在生成图表...")
        plot_data = self.df_tf.copy()
        ts_index = plot_data.index
        buys = pd.Series(np.nan, index=ts_index)
        sells = pd.Series(np.nan, index=ts_index)
        for _, t in df_trades.iterrows():
            idx = t['time'].floor(self.tf_freq)
            if idx in ts_index:
                if t['type'] == 'BUY':
                    buys.loc[idx] = t['price'] * 0.98
                elif t['type'] == 'SELL':
                    sells.loc[idx] = t['price'] * 1.02

        apds = [
            mpf.make_addplot(buys, type='scatter', markersize=80, marker='^', color='g'),
            mpf.make_addplot(sells, type='scatter', markersize=80, marker='v', color='r')
        ]

        # 绘制均线和布林带
        if 'EMA_55' in plot_data.columns:
            apds.append(mpf.make_addplot(plot_data['EMA_55'], color='orange', width=1.5))
        if 'BB_Long_Lower' in plot_data.columns:
            apds.append(mpf.make_addplot(plot_data['BB_Long_Lower'], color='darkblue', width=1.5))
        if 'BB_Short_Lower' in plot_data.columns:
            apds.append(mpf.make_addplot(plot_data['BB_Short_Lower'], color='skyblue', width=1))

        # 🔥 可视化 AI 状态 (在副图显示不同颜色的色块或线条)
        # 这里用简单的办法：在价格图下方画一条状态线
        if self.ai_regime_history:
            df_regime = pd.DataFrame(self.ai_regime_history).set_index('time')
            # 重新索引对齐 K 线
            df_regime = df_regime.reindex(ts_index, method='ffill')

            # 将文本转为数字以便绘图: BULL=1, SHOCK=0, BEAR=-1
            regime_val = df_regime['regime'].map({
                'BULL_TREND': 1,
                'SHOCK_SIDEWAYS': 0,
                'BEAR_CRASH': -1
            }).fillna(0)

            # 在副图 2 画出 AI 状态
            apds.append(
                mpf.make_addplot(regime_val, panel=2, color='purple', title='AI Regime', ylabel='Bull(1)/Bear(-1)'))

        equity_aligned = df_equity['equity'].reindex(ts_index, method='ffill')
        apds.append(mpf.make_addplot(equity_aligned, panel=1, color='cyan', title='Equity'))

        s = mpf.make_mpf_style(marketcolors=mpf.make_marketcolors(up='green', down='red', inherit=True), gridstyle=':')
        mpf.plot(plot_data, type='candle', style=s, addplot=apds, volume=True, panel_ratios=(6, 2, 2),
                 title=f"Backtest: {self.strategy.name}", datetime_format='%Y-%m-%d', tight_layout=True)


if __name__ == "__main__":
    print("🔥 正在进行 2021 史诗级全能测试...")

    # 策略路由 v20 会读取上面生成的 csv
    # 1月-4月: 它会用 BullStrategy 狂赚
    # 5月-7月: 它会用 BearStrategy 空仓避险，并尝试接针
    # 11月后:  它会再次切入 BearStrategy 锁住利润

    engine = BacktestEngine(
        symbol="BTC/USDT",
        start_date="2021-01-01 00:00:00",
        end_date="2022-01-01 00:00:00"
    )
    engine.run()