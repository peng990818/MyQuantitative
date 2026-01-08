import pandas as pd
import matplotlib.pyplot as plt
import os
import sys
import warnings
from datetime import timedelta
import numpy as np
import re

# === 基础设置与警告屏蔽 ===
warnings.simplefilter(action='ignore', category=FutureWarning)
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.config_loader import ConfigLoader
from utils.logger import logger
from modules.market.loader import MarketDataLoader
from modules.analysis.technical import TechnicalAnalyzer
from modules.strategy.evaluator import StrategyEvaluator
from core.position import PositionManager


def parse_timeframe(tf: str):
    """
    支持：1h, 4h, 15m, 30m, 5m 等
    返回：(pandas_freq_str, timedelta)
    """
    m = re.fullmatch(r"(\d+)([mh])", tf.strip().lower())
    if not m:
        raise ValueError(f"Unsupported timeframe format: {tf}")
    n = int(m.group(1))
    unit = m.group(2)

    if unit == "h":
        return f"{n}H", timedelta(hours=n)
    else:
        return f"{n}min", timedelta(minutes=n)


class BacktestEngine:
    def __init__(self, symbol="BTC/USDT", days=120):
        self.cfg = ConfigLoader()
        self.cfg._config['run_mode'] = 'BACKTEST'

        # 🔥 回测专用权重
        self.cfg._config['scoring'] = {
            'weights': {'technical': 0.7, 'sentiment': 0.0, 'trend': 0.3},
            'thresholds': {'buy': 80, 'sell': 40}
        }

        self.symbol = symbol
        self.days = days
        self.timeframe_str = self.cfg.get("timeframe", "1h")

        self.tf_freq, self.tf_delta = parse_timeframe(self.timeframe_str)

        self.market = MarketDataLoader()
        self.tech_analyzer = TechnicalAnalyzer()
        self.evaluator = StrategyEvaluator()
        self.pos_manager = PositionManager()

        # 账户初始状态
        self.initial_balance = 10000.0
        self.usdt = self.initial_balance
        self.btc = 0.0
        self.entry_price = 0.0
        self.trades = []
        self.equity_curve = []
        self.last_price = None

        # 风险管理变量
        self.dynamic_sl_price = 0.0
        self.max_seen_price = 0.0
        self.commission = 0.001

        # 成交模型（可调）
        self.slippage_bps = 5  # 5 bps = 0.05%

        # 权益曲线记录频率（分钟）
        self.equity_sample_minutes = 1

        logger.info(f"🚀 Backtest v8.1 启动 | 标的: {symbol} | TF: {self.timeframe_str}")

    def fetch_and_prepare(self):
        safe_symbol = self.symbol.replace('/', '_')
        cache_file = f"data/backtest_{safe_symbol}_{self.days}d.csv"
        if not os.path.exists(cache_file):
            raise Exception(f"找不到缓存文件 {cache_file}")

        df_1m = pd.read_csv(cache_file)
        df_1m['timestamp'] = pd.to_datetime(df_1m['timestamp'])
        df_1m.sort_values('timestamp', inplace=True)

        # ---- resample 生成 TF K线（明确 label/closed，避免歧义）----
        df_1m.set_index('timestamp', inplace=True)
        df_tf = df_1m.resample(self.tf_freq, label="left", closed="left").agg({
            'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
        }).dropna()

        # 指标计算
        df_tf = self.tech_analyzer.calculate_indicators(df_tf)
        df_tf.dropna(inplace=True)

        # reset index
        df_1m.reset_index(inplace=True)
        df_tf.reset_index(inplace=True)

        # --- 强校验：避免指标列名不匹配导致 silent fallback ---
        required_cols = ["EMA_50", "EMA_200", "ATRr_14"]
        missing = [c for c in required_cols if c not in df_tf.columns]
        if missing:
            raise ValueError(
                f"Indicators missing in df_tf: {missing}. "
                f"Please align calculate_indicators() output column names."
            )

        return df_1m, df_tf

    def run(self):
        df_1m, df_tf = self.fetch_and_prepare()

        # 预计算信号：key 用 TF candle 的 timestamp（label=left）
        signal_map = self._pre_calculate_signals(df_tf)

        # TF 指标快速查询：timestamp -> row(dict-like)
        tf_lookup = {row['timestamp']: row for _, row in df_tf.iterrows()}

        print(f"📉 开始步进回放 (v8.1 修复lookahead + 更真实成交)...")
        last_candle_time = None

        for _, row in df_1m.iterrows():
            curr_time = row['timestamp']
            curr_price = float(row['close'])
            self.last_price = curr_price

            # 当前所在 TF candle（左端点对齐）
            current_candle = curr_time.floor(self.tf_freq)
            prev_candle = current_candle - self.tf_delta  # ✅ 上一根已收盘 candle

            # --- A. 风险管理（只用 prev_candle 指标，杜绝偷看未来） ---
            if self.btc > 0:
                if self._handle_risk_management(curr_time, row, tf_lookup, prev_candle):
                    # 平仓后跳过信号逻辑
                    self._sample_equity(curr_time, curr_price)
                    continue

            # --- B. 信号执行（同样只执行上一根已收盘 candle 的信号） ---
            if current_candle != last_candle_time:
                sig = signal_map.get(prev_candle)
                if sig and sig['action'] == "BUY" and self.btc == 0:
                    self._execute_buy(curr_time, curr_price, sig['atr'])
                last_candle_time = current_candle

            # --- C. 记录权益曲线 ---
            self._sample_equity(curr_time, curr_price)

        self._show_report()

    def _sample_equity(self, curr_time, curr_price):
        if self.equity_sample_minutes <= 0:
            return
        if curr_time.minute % self.equity_sample_minutes == 0 and curr_time.second == 0:
            equity = self.usdt + (self.btc * curr_price)
            self.equity_curve.append({'time': curr_time, 'equity': equity})

    def _pre_calculate_signals(self, df_tf):
        signals = {}
        for _, row in df_tf.iterrows():
            state = self.tech_analyzer.get_market_state(row)
            adx = state['trend']['adx']
            z_score = state['momentum']['z_score']
            ema50 = state['trend']['ema_mid']
            ema200 = state['trend']['ema_long']

            tech_score = 40
            # v8.x：强趋势 + 均线多头 + 适度回调
            if adx > 32 and row['close'] > ema50 > ema200:
                if -1.2 < z_score < 0.2:
                    tech_score = 95

            decision = self.evaluator.evaluate(tech_score, 0, 80)
            if decision['final_score'] >= 80:
                signals[row['timestamp']] = {
                    'action': "BUY",
                    'atr': float(state['volatility']['atr'])
                }
        return signals

    def _handle_risk_management(self, time, row_1m, tf_lookup, prev_candle_time):
        """
        v8.1：Trailing Stop + Trend Exit
        ✅ 指标只取 prev_candle（上一根已收盘TF K线），避免lookahead。
        """
        curr_price = float(row_1m['close'])
        pnl_pct = (curr_price - self.entry_price) / self.entry_price if self.entry_price > 0 else 0.0

        # 更新持仓期间最高价（用 1m high）
        self.max_seen_price = max(self.max_seen_price, float(row_1m['high']))

        # 取上一根已收盘 TF 指标
        tf_row = tf_lookup.get(prev_candle_time, None)
        if tf_row is None:
            # TF 不足时做保守 fallback
            current_atr = self.entry_price * 0.02
            curr_ema50 = None
        else:
            current_atr = float(tf_row['ATRr_14'])
            curr_ema50 = float(tf_row['EMA_50'])

        # 1) 吊灯止损：max_seen_price - 3 * ATR
        trailing_stop = self.max_seen_price - (3.0 * current_atr)
        self.dynamic_sl_price = max(self.dynamic_sl_price, trailing_stop)

        # A) 止损触发：用更保守的成交模型（避免“完美止损价成交”）
        if float(row_1m['low']) <= self.dynamic_sl_price:
            fill_price = self._stop_fill_price(row_1m, self.dynamic_sl_price)
            self._execute_sell(time, fill_price, "🛑 TRAILING_STOP")
            return True

        # B) 趋势离场：盈利 >3% 且跌破 EMA50（EMA50 来自上一根已收盘 TF）
        if curr_ema50 is not None and curr_price < curr_ema50 and pnl_pct > 0.03:
            fill_price = self._market_fill_price(curr_price)
            self._execute_sell(time, fill_price, "📉 TREND_EXIT")
            return True

        return False

    def _stop_fill_price(self, row_1m, stop_price):
        """
        止损成交模型（保守）：
        - 如果本分钟开盘价就已经在止损价下方，按 open 成交（gap）
        - 否则按 stop_price 成交
        - 再叠加滑点
        """
        o = float(row_1m['open'])
        fill = o if o < stop_price else stop_price
        # 滑点（卖出时往不利方向：更低）
        fill *= (1 - self.slippage_bps / 10000.0)
        return fill

    def _market_fill_price(self, price):
        """
        市价成交模型（卖出）：叠加滑点（更低）
        """
        return float(price) * (1 - self.slippage_bps / 10000.0)

    def _execute_buy(self, time, price, atr):
        qty = self.pos_manager.calculate_buy_size(price, self.usdt)
        if qty <= 0:
            return

        cost = qty * price
        fee = cost * self.commission

        if cost + fee > self.usdt:
            # 防止超买（极端情况下 PositionManager 返回过大）
            return

        self.usdt -= (cost + fee)
        self.btc = qty
        self.entry_price = float(price)

        self.max_seen_price = float(price)
        self.dynamic_sl_price = float(price) - (2.5 * float(atr))

        self.trades.append({'time': time, 'type': 'BUY', 'price': float(price), 'qty': float(qty)})

    def _execute_sell(self, time, price, reason):
        revenue = self.btc * float(price)
        fee = revenue * self.commission

        cost_basis = self.btc * self.entry_price
        pnl = (revenue - fee) - cost_basis
        pnl_pct = (pnl / cost_basis * 100) if cost_basis > 0 else 0.0

        self.usdt += (revenue - fee)
        self.trades.append({
            'time': time, 'type': 'SELL', 'price': float(price),
            'pnl': float(pnl), 'pnl_pct': float(pnl_pct), 'reason': reason
        })

        # reset position
        self.btc = 0.0
        self.entry_price = 0.0
        self.max_seen_price = 0.0
        self.dynamic_sl_price = 0.0

    def _show_report(self):
        print("\n" + "=" * 40)
        print("📊 QuantBot v8.1 回测报告（修复lookahead）")
        print("=" * 40)

        last_price = self.last_price if self.last_price is not None else 0.0
        final_equity = self.usdt + (self.btc * last_price)
        total_ret = (final_equity - self.initial_balance) / self.initial_balance * 100

        df_curve = pd.DataFrame(self.equity_curve)
        if df_curve.empty:
            print("⚠️ equity_curve 为空（可能采样频率设置导致），跳过回撤计算。")
            mdd = 0.0
        else:
            df_curve['peak'] = df_curve['equity'].cummax()
            mdd = ((df_curve['peak'] - df_curve['equity']) / df_curve['peak']).max() * 100

        sells = [t for t in self.trades if t.get('type') == 'SELL']
        wins = [t for t in sells if t.get('pnl', 0) > 0]
        win_rate = len(wins) / len(sells) if sells else 0

        print(f"💰 最终净值: {final_equity:.2f} (收益率: {total_ret:+.2f}%)")
        print(f"📉 最大回撤: {mdd:.2f}%")
        print(f"📈 交易次数: {len(sells)} | 胜率: {win_rate * 100:.1f}%")

        if sells:
            avg_win = sum([t['pnl_pct'] for t in wins]) / len(wins) if wins else 0.0
            losses = [t for t in sells if t.get('pnl', 0) <= 0]
            avg_loss = sum([t['pnl_pct'] for t in losses]) / len(losses) if losses else 0.0

            if avg_loss != 0:
                print(f"⚖️ 盈亏比: {abs(avg_win / avg_loss):.2f} (平均赢: {avg_win:.2f}% / 平均输: {avg_loss:.2f}%)")
            else:
                print(f"⚖️ 平均赢: {avg_win:.2f}% / 平均输: {avg_loss:.2f}%")

        # plot
        if not df_curve.empty:
            plt.figure(figsize=(12, 6))
            plt.plot(df_curve['time'], df_curve['equity'], label='Equity')
            plt.legend()
            plt.show()


if __name__ == "__main__":
    BacktestEngine(days=120).run()