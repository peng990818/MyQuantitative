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
    def __init__(self, symbol="BTC/USDT", days=30):
        print(f"⏳ 初始化回测引擎 | 标的: {symbol} | 周期: {days}天")

        # 1. 初始化配置加载器
        self.cfg = ConfigLoader()

        # 🔥 [关键] 注入 BACKTEST 模式 (屏蔽邮件/通知)
        self.cfg._config['run_mode'] = 'BACKTEST'

        # 2. 🔥 [关键] 加载回测专用策略配置
        # 不再硬编码，而是从 config.yaml 读取 scoring_backtest 并覆盖默认 scoring
        bt_scoring = self.cfg.get("scoring_backtest")

        if bt_scoring:
            print("🔧 [配置] 检测到 scoring_backtest，正在应用回测专用权重...")
            self.cfg._config['scoring'] = bt_scoring
            # 打印确认
            w = bt_scoring.get('weights', {})
            t = bt_scoring.get('thresholds', {})
            print(f"   -> 权重: Tech={w.get('technical')} | Trend={w.get('trend')} | AI={w.get('sentiment')}")
            print(f"   -> 阈值: Buy={t.get('buy')} | Sell={t.get('sell')}")
        else:
            print("⚠️ [警告] 未找到 scoring_backtest 配置，将使用默认实盘配置 (可能导致无交易)")

        self.symbol = symbol
        self.days = days

        # 3. 初始化核心模块
        self.market = MarketDataLoader()
        self.tech_analyzer = TechnicalAnalyzer()
        self.evaluator = StrategyEvaluator()
        self.pos_manager = PositionManager()

        # 4. 账户模拟状态
        self.initial_balance = 10000.0
        self.usdt = self.initial_balance
        self.btc = 0.0
        self.entry_price = 0.0

        # 5. 交易记录
        self.trades = []
        self.equity_curve = []

        # 6. 读取风控参数
        self.stop_loss_pct = self.cfg.get("risk_management.stop_loss", 0.05)
        self.take_profit_pct = self.cfg.get("risk_management.take_profit", 0.20)
        self.commission = 0.001

        print(f"🛡️ 风控参数: SL={self.stop_loss_pct * 100}% | TP={self.take_profit_pct * 100}%")

    def fetch_data(self):
        """
        获取 1m 高频数据 (循环分页下载) 并合成 1h 数据
        """
        # 1. 缓存文件路径
        safe_symbol = self.symbol.replace('/', '_')
        cache_file = f"data/backtest_{safe_symbol}_{self.days}d.csv"
        os.makedirs("data", exist_ok=True)

        if os.path.exists(cache_file):
            print(f"📂 加载本地缓存: {cache_file}")
            df_1m = pd.read_csv(cache_file)
            df_1m['timestamp'] = pd.to_datetime(df_1m['timestamp'])
        else:
            print(f"📥 正在下载 {self.days} 天的 1m 数据 (分页下载中)...")

            # === 循环分页下载逻辑 ===
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

                    # 更新时间：最后一条数据的下一分钟
                    since = ohlcv[-1][0] + 60000

                    # 停止条件：已经追上当前时间
                    if since > self.market.exchange.milliseconds(): break
                    if len(ohlcv) < limit: break  # 数据不足 limit 说明取完了

                except Exception as e:
                    print(f"\n⚠️ 下载中断: {e}")
                    break

            print(f"\n✅ 下载完成，共 {len(all_ohlcv)} 条")

            if not all_ohlcv:
                raise Exception("❌ 未下载到数据，请检查网络/代理")

            df_1m = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_1m['timestamp'] = pd.to_datetime(df_1m['timestamp'], unit='ms')
            df_1m.to_csv(cache_file, index=False)

        # 2. 合成 1H 数据
        print("🔄 合成 1H 数据...")
        df_1m.set_index('timestamp', inplace=True)
        df_1h = df_1m.resample('1h').agg({
            'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
        }).dropna()

        # 3. 计算指标
        df_1h = self.tech_analyzer.calculate_indicators(df_1h)

        # 🔥 [关键] 删除预热期 (Warm-up Period)
        # 刚开始的 ~100 行数据，EMA 是空的，必须删掉，否则后面会报错
        df_1h.dropna(inplace=True)

        # 恢复索引
        df_1m.reset_index(inplace=True)
        df_1h.reset_index(inplace=True)

        # 检查数据量
        print(f"🧐 数据校验: 1M={len(df_1m)}条 | 1H={len(df_1h)}条 (有效策略时长)")

        return df_1m, df_1h

    def pre_calculate_signals(self, df_1h):
        print("🧠 计算策略信号 (RSI逻辑已修正)...")
        signals = {}
        high_scores = 0

        for idx, row in df_1h.iterrows():
            state = self.tech_analyzer.get_market_state(row)

            rsi = state.get('momentum', {}).get('rsi')
            ema_s = state.get('trend', {}).get('ema_short')
            ema_l = state.get('trend', {}).get('ema_long')

            # 🔥 防御性检查：只要有空值就跳过
            if rsi is None or ema_s is None or ema_l is None:
                continue

                # 🔥 [关键修正] RSI 分数反转
            # RSI=30(超卖) -> 100-30=70分 (高分买入)
            tech_score = 100 - rsi

            # 趋势分
            trend_score = 80 if ema_s > ema_l else 20

            # 回测无 AI
            sentiment_score = 0

            # 评估
            decision = self.evaluator.evaluate(tech_score, sentiment_score, trend_score)
            signals[row['timestamp']] = decision['action']

            if decision['final_score'] >= self.cfg.get("scoring.thresholds.buy", 75):
                high_scores += 1

        print(f"🧐 [统计] 触发买入信号次数: {high_scores}")
        return signals

    def run(self):
        df_1m, df_1h = self.fetch_data()
        signal_map = self.pre_calculate_signals(df_1h)

        print(f"🚀 开始回放 {len(df_1m)} 分钟数据...")
        last_processed_hour = None

        for idx, row in df_1m.iterrows():
            curr_time = row['timestamp']
            curr_price = row['close']

            # === A. 风控检查 (每分钟) ===
            if self.btc > 0:
                triggered = self._check_risk_management(curr_time, row['low'], row['high'])
                if triggered: continue

                # === B. 策略信号检查 (整点) ===
            current_hour = curr_time.floor('1h')
            prev_hour = current_hour - timedelta(hours=1)

            # 在整点后 5 分钟内，执行上个小时的信号
            if curr_time.minute < 5 and current_hour != last_processed_hour:

                # 查表
                action = signal_map.get(prev_hour, "HOLD")

                if action == "BUY":
                    if self.btc == 0:
                        self._buy(curr_time, curr_price, "SIGNAL")
                        last_processed_hour = current_hour
                elif action == "SELL":
                    if self.btc > 0:
                        self._sell(curr_time, curr_price, "SIGNAL")
                        last_processed_hour = current_hour

            # 记录资金曲线
            if curr_time.minute == 0:
                equity = self.usdt + (self.btc * curr_price)
                self.equity_curve.append({'time': curr_time, 'equity': equity})

        self._generate_report()

    def _check_risk_management(self, time, low, high):
        """盘中风控检查"""
        # 1. 止损
        pnl_low = (low - self.entry_price) / self.entry_price
        if pnl_low <= -self.stop_loss_pct:
            exec_price = self.entry_price * (1 - self.stop_loss_pct)
            if low < exec_price: exec_price = (exec_price + low) / 2  # 模拟滑点
            self._sell(time, exec_price, f"🛑 STOP_LOSS ({pnl_low * 100:.1f}%)")
            return True

        # 2. 止盈
        pnl_high = (high - self.entry_price) / self.entry_price
        if pnl_high >= self.take_profit_pct:
            exec_price = self.entry_price * (1 + self.take_profit_pct)
            self._sell(time, exec_price, f"💰 TAKE_PROFIT ({pnl_high * 100:.1f}%)")
            return True
        return False

    def _buy(self, time, price, reason):
        # 使用 PositionManager 计算数量
        qty = self.pos_manager.calculate_buy_size(price, self.usdt)

        if qty > 0:
            cost = qty * price
            fee = cost * self.commission

            # 资金修正：如果不够手续费，稍微减仓
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
        print(f"资金: {self.initial_balance:.2f} -> {final_equity:.2f} U")
        print(f"收益: {ret:+.2f}%")
        print(f"交易: {len([t for t in self.trades if t['type'] == 'SELL'])} 次")
        print(f"风控: SL={self.stop_loss_pct * 100}% | TP={self.take_profit_pct * 100}%")

        if self.equity_curve:
            df = pd.DataFrame(self.equity_curve)
            plt.figure(figsize=(10, 6))
            plt.plot(df['time'], df['equity'], label='Equity')

            for t in self.trades:
                if t['type'] == 'BUY':
                    plt.scatter(t['time'], t['price'], marker='^', c='g', s=60)
                elif 'STOP' in t['reason']:
                    plt.scatter(t['time'], t['price'], marker='x', c='k', s=60, label='Stop Loss')
                elif 'TAKE' in t['reason']:
                    plt.scatter(t['time'], t['price'], marker='*', c='gold', s=80, label='Take Profit')
                else:
                    plt.scatter(t['time'], t['price'], marker='v', c='r', s=60)

            plt.title(f"Backtest: {ret:.2f}% Return")
            plt.legend()
            plt.show()


if __name__ == "__main__":
    # 🔥 记得去 data/ 目录删掉旧的 csv 文件，让它重新下载新的 60 天数据！
    bt = BacktestEngine(symbol="BTC/USDT", days=60)
    bt.run()