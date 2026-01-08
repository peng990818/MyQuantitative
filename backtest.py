import pandas as pd
import matplotlib.pyplot as plt
import os
import sys
import warnings
from datetime import timedelta

# === 屏蔽警告 & 路径魔法 ===
warnings.simplefilter(action='ignore', category=FutureWarning)
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# === 引入 v2.0 核心模块 ===
from utils.config_loader import ConfigLoader
from utils.logger import logger
from modules.market.loader import MarketDataLoader
from modules.analysis.technical import TechnicalAnalyzer
from modules.strategy.evaluator import StrategyEvaluator
from core.position import PositionManager


class BacktestEngine:
    def __init__(self, symbol="BTC/USDT", days=None):
        # 1. 初始化配置
        self.cfg = ConfigLoader()
        self.cfg._config['run_mode'] = 'BACKTEST'

        # 天数优先级: 参数 > Config > 默认
        config_days = self.cfg.get("backtest.days", 60)
        self.days = days if days is not None else config_days

        # 周期配置
        self.timeframe_str = self.cfg.get("timeframe", "1h")

        print(f"⏳ 初始化回测引擎 | 标的: {symbol}")
        print(f"🎯 策略周期: {self.timeframe_str}")
        print(f"📅 回测跨度: {self.days} 天")

        # Pandas 周期转换
        self.resample_rule = self._map_timeframe_to_pandas(self.timeframe_str)
        self.time_delta = self._get_time_delta(self.timeframe_str)

        # 加载回测策略配置
        bt_scoring = self.cfg.get("scoring_backtest")
        if bt_scoring:
            print("🔧 [配置] 应用 scoring_backtest 回测专用权重...")
            self.cfg._config['scoring'] = bt_scoring
            t = bt_scoring.get('thresholds', {})
            print(f"   -> 阈值: Buy={t.get('buy')} | Sell={t.get('sell')}")
        else:
            print("⚠️ [警告] 未找到 scoring_backtest，使用默认实盘配置")

        self.symbol = symbol
        self.market = MarketDataLoader()
        self.tech_analyzer = TechnicalAnalyzer()
        self.evaluator = StrategyEvaluator()
        self.pos_manager = PositionManager()

        # 账户状态
        self.initial_balance = 10000.0
        self.usdt = self.initial_balance
        self.btc = 0.0
        self.entry_price = 0.0
        self.trades = []
        self.equity_curve = []  # 记录资金曲线

        # 风控参数
        self.stop_loss_pct = self.cfg.get("risk_management.stop_loss", 0.05)
        self.take_profit_pct = self.cfg.get("risk_management.take_profit", 0.20)
        self.commission = 0.001

        print(f"🛡️ 风控参数: SL={self.stop_loss_pct * 100}% | TP={self.take_profit_pct * 100}%")

    def _map_timeframe_to_pandas(self, tf_str):
        if tf_str.endswith('m'): return tf_str.replace('m', 'min')
        if tf_str.endswith('h'): return tf_str
        if tf_str.endswith('d'): return tf_str.upper()
        return tf_str

    def _get_time_delta(self, tf_str):
        num = int(''.join(filter(str.isdigit, tf_str)))
        if 'm' in tf_str: return timedelta(minutes=num)
        if 'h' in tf_str: return timedelta(hours=num)
        if 'd' in tf_str: return timedelta(days=num)
        return timedelta(hours=1)

    def fetch_data(self):
        safe_symbol = self.symbol.replace('/', '_')
        cache_file = f"data/backtest_{safe_symbol}_{self.days}d.csv"
        os.makedirs("data", exist_ok=True)

        if os.path.exists(cache_file):
            print(f"📂 加载本地缓存: {cache_file}")
            df_1m = pd.read_csv(cache_file)
            df_1m['timestamp'] = pd.to_datetime(df_1m['timestamp'])
        else:
            print(f"📥 正在下载 {self.days} 天的 1m 数据...")
            all_ohlcv = []
            since = self.market.exchange.milliseconds() - (self.days * 24 * 60 * 60 * 1000)
            limit = 100

            while True:
                try:
                    t_str = pd.to_datetime(since, unit='ms')
                    print(f"   ...下载进度: {t_str}", end="\r")
                    ohlcv = self.market.exchange.fetch_ohlcv(self.symbol, "1m", since=since, limit=limit)
                    if not ohlcv: break
                    all_ohlcv += ohlcv
                    since = ohlcv[-1][0] + 60000
                    if since > self.market.exchange.milliseconds(): break
                    if len(ohlcv) < limit: break
                except Exception as e:
                    print(f"\n⚠️ 下载中断: {e}")
                    break

            print(f"\n✅ 下载完成: {len(all_ohlcv)} 条")
            if not all_ohlcv: raise Exception("No Data")
            df_1m = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_1m['timestamp'] = pd.to_datetime(df_1m['timestamp'], unit='ms')
            df_1m.to_csv(cache_file, index=False)

        print(f"🔄 重采样为: {self.timeframe_str}...")
        df_1m.set_index('timestamp', inplace=True)
        df_tf = df_1m.resample(self.resample_rule).agg({
            'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
        }).dropna()

        df_tf = self.tech_analyzer.calculate_indicators(df_tf)
        df_tf.dropna(inplace=True)

        df_1m.reset_index(inplace=True)
        df_tf.reset_index(inplace=True)
        return df_1m, df_tf

    def pre_calculate_signals(self, df_tf):
        print(f"🧠 计算 {self.timeframe_str} 信号...")
        signals = {}
        high_scores = 0

        for idx, row in df_tf.iterrows():
            state = self.tech_analyzer.get_market_state(row)
            rsi = state.get('momentum', {}).get('rsi')
            ema_s = state.get('trend', {}).get('ema_short')
            ema_l = state.get('trend', {}).get('ema_long')

            if rsi is None or ema_s is None or ema_l is None: continue

            # RSI 反转逻辑
            tech_score = 100 - rsi
            trend_score = 80 if ema_s > ema_l else 20
            sentiment_score = 0

            decision = self.evaluator.evaluate(tech_score, sentiment_score, trend_score)
            signals[row['timestamp']] = decision['action']

            if decision['final_score'] >= self.cfg.get("scoring.thresholds.buy", 70):
                high_scores += 1

        print(f"🧐 [预统计] 潜在买入信号: {high_scores} 次")
        return signals

    def run(self):
        df_1m, df_tf = self.fetch_data()
        signal_map = self.pre_calculate_signals(df_tf)

        print(f"🚀 开始回放 {len(df_1m)} 分钟数据...")
        last_processed_candle = None

        for idx, row in df_1m.iterrows():
            curr_time = row['timestamp']
            curr_price = row['close']

            # A. 风控
            if self.btc > 0:
                if self._check_risk_management(curr_time, row['low'], row['high']): continue

                # B. 策略 (周期对齐)
            current_candle_time = curr_time.floor(self.resample_rule)
            prev_candle_time = current_candle_time - self.time_delta
            time_diff_minutes = (curr_time - current_candle_time).seconds / 60

            if time_diff_minutes < 5 and current_candle_time != last_processed_candle:
                action = signal_map.get(prev_candle_time, "HOLD")
                if action == "BUY" and self.btc == 0:
                    self._buy(curr_time, curr_price, "SIGNAL")
                    last_processed_candle = current_candle_time
                elif action == "SELL" and self.btc > 0:
                    self._sell(curr_time, curr_price, "SIGNAL")
                    last_processed_candle = current_candle_time

            # 资金记录 (每小时)
            if curr_time.minute == 0:
                equity = self.usdt + (self.btc * curr_price)
                self.equity_curve.append({'time': curr_time, 'equity': equity})

        self._generate_report()

    def _check_risk_management(self, time, low, high):
        pnl_low = (low - self.entry_price) / self.entry_price
        if pnl_low <= -self.stop_loss_pct:
            exec_price = self.entry_price * (1 - self.stop_loss_pct)
            if low < exec_price: exec_price = (exec_price + low) / 2
            self._sell(time, exec_price, f"🛑 STOP_LOSS ({pnl_low * 100:.1f}%)")
            return True

        pnl_high = (high - self.entry_price) / self.entry_price
        if pnl_high >= self.take_profit_pct:
            exec_price = self.entry_price * (1 + self.take_profit_pct)
            self._sell(time, exec_price, f"💰 TAKE_PROFIT ({pnl_high * 100:.1f}%)")
            return True
        return False

    def _buy(self, time, price, reason):
        qty = self.pos_manager.calculate_buy_size(price, self.usdt)
        if qty > 0:
            cost = qty * price
            fee = cost * self.commission
            if cost + fee > self.usdt:
                qty = qty * 0.99
                cost = qty * price
                fee = cost * self.commission
            self.usdt -= (cost + fee)
            self.btc += qty
            self.entry_price = price
            self.trades.append({'time': time, 'type': 'BUY', 'price': price, 'qty': qty, 'reason': reason})

    def _sell(self, time, price, reason):
        revenue = self.btc * price
        fee = revenue * self.commission
        profit = (revenue - fee) - (self.btc * self.entry_price)
        profit_pct = profit / (self.btc * self.entry_price) * 100
        self.usdt += (revenue - fee)
        self.trades.append(
            {'time': time, 'type': 'SELL', 'price': price, 'qty': self.btc, 'reason': reason, 'pnl': profit,
             'pnl_pct': profit_pct})
        self.btc = 0
        self.entry_price = 0

    def _generate_report(self):
        print("\n" + "=" * 40)
        print("📊 回测报告 (Backtest Report)")
        print("=" * 40)

        final_equity = self.usdt
        if self.btc > 0 and self.equity_curve: final_equity = self.equity_curve[-1]['equity']

        ret = (final_equity - self.initial_balance) / self.initial_balance * 100

        # 🔥🔥🔥 计算最大回撤 (Max Drawdown) 🔥🔥🔥
        max_drawdown = 0.0
        if self.equity_curve:
            df_curve = pd.DataFrame(self.equity_curve)
            # 1. 计算历史最高点 (Running Peak)
            df_curve['peak'] = df_curve['equity'].cummax()
            # 2. 计算当前回撤幅度
            df_curve['drawdown'] = (df_curve['peak'] - df_curve['equity']) / df_curve['peak']
            # 3. 取最大值
            max_drawdown = df_curve['drawdown'].max()

        print(f"策略配置: 周期={self.timeframe_str} | 天数={self.days}天")
        print(f"资金变动: {self.initial_balance:.2f} -> {final_equity:.2f} U")
        print(f"最终收益: {ret:+.2f}%")
        print(f"📉 最大回撤: {max_drawdown * 100:.2f}%")  # 🔥 打印回撤
        print(f"交易次数: {len([t for t in self.trades if t['type'] == 'SELL'])} 次")
        print(f"风控配置: SL={self.stop_loss_pct * 100}% | TP={self.take_profit_pct * 100}%")

        if self.equity_curve:
            df = pd.DataFrame(self.equity_curve)
            plt.figure(figsize=(10, 6))
            plt.plot(df['time'], df['equity'], label='Equity')

            for t in self.trades:
                if t['type'] == 'BUY':
                    plt.scatter(t['time'], t['price'], marker='^', c='g', s=60)
                elif 'STOP' in t['reason']:
                    plt.scatter(t['time'], t['price'], marker='x', c='k', s=60)
                elif 'TAKE' in t['reason']:
                    plt.scatter(t['time'], t['price'], marker='*', c='gold', s=80)
                else:
                    plt.scatter(t['time'], t['price'], marker='v', c='r', s=60)

            # 🔥 标题中也显示回撤
            plt.title(f"Backtest: {ret:.2f}% | MaxDD: {max_drawdown * 100:.2f}%")
            plt.legend()
            plt.show()


if __name__ == "__main__":
    bt = BacktestEngine(symbol="BTC/USDT", days=60)
    bt.run()