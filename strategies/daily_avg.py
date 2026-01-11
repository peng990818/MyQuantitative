import pandas as pd
from core.strategy import BaseStrategy


class DailyAvgStrategy(BaseStrategy):
    def __init__(self, sl_pct=0.03, tp_pct=0.15):
        # 策略改名为 "Hourly_MA_Regression" 更贴切
        super().__init__(name="Hourly_MA_Regression")
        self.sl_pct = sl_pct
        self.tp_pct = tp_pct

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算回归基准线
        """
        df = df.copy()

        # 🔥 使用 MA99 作为 1H 级别的回归中枢 (生命线)
        # 如果你一定要用日均线，在 1H 图上就是 MA24 (24小时)
        # 这里推荐 MA99，因为它在 Crypto 里支撑压力更明显
        df['MA_Line'] = df['close'].rolling(window=99).mean()

        return df

    def check_signal(self, row: pd.Series) -> dict:
        signal = {
            'action': None,
            'sl_pct': self.sl_pct,
            'tp_pct': self.tp_pct
        }

        current_price = row['close']
        ma_line = row.get('MA_Line')

        # 如果均线还没算出来 (前99根K线)，跳过
        if pd.isna(ma_line):
            return signal

        # 🔥 核心逻辑：
        # 价格低于均线 -> 视为超卖/便宜 -> 买入
        # 增加 0.5% 的缓冲区，防止在均线刚好卡住的时候反复开仓磨损
        if current_price < ma_line * 0.995:
            signal['action'] = "BUY"

        return signal