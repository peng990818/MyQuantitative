import pandas as pd
import numpy as np
from core.strategy import BaseStrategy
from modules.analysis.technical import TechnicalAnalyzer


class SniperReversionStrategy(BaseStrategy):
    def __init__(self, sl_pct=0.04, tp_pct=0.08):
        # v6: 双轨制 (99均线防守 + 20均线进攻)
        # 经过实测，这是应对"暴跌+震荡"行情表现最好的版本
        super().__init__(name="Sniper_Adaptive_v6")
        self.ta = TechnicalAnalyzer()
        self.sl_pct = sl_pct
        self.tp_pct = tp_pct

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self.ta.calculate_indicators(df)

        # 1. 长期趋势基准 (用于判断大环境)
        df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
        df['EMA_200_Prev'] = df['EMA_200'].shift(5)
        df['Trend_Slope'] = df['EMA_200'] - df['EMA_200_Prev']

        # 🔥 2. 重型布林带 (99周期) -> 用于抓暴跌 (Mode A)
        # 特点：迟钝、宽、深 -> 熊市保命网
        win_long = 99
        base_long = df['close'].rolling(window=win_long).mean()
        std_long = df['close'].rolling(window=win_long).std()
        df['BB_Long_Lower'] = base_long - (2.0 * std_long)

        # 🔥 3. 轻型布林带 (20周期) -> 用于抓震荡 (Mode B)
        # 特点：灵敏、贴身、收缩快 -> 震荡提款机
        win_short = 20
        base_short = df['close'].rolling(window=win_short).mean()
        std_short = df['close'].rolling(window=win_short).std()

        df['BB_Short_Mid'] = base_short
        df['BB_Short_Lower'] = base_short - (2.0 * std_short)
        # 计算带宽，防止死鱼盘
        df['BB_Short_Width'] = (base_short + 2 * std_short - (base_short - 2 * std_short)) / base_short

        return df

    def check_signal(self, row: pd.Series) -> dict:
        signal = {
            'action': None,
            'sl_pct': self.sl_pct,
            'tp_pct': self.tp_pct
        }

        # 提取数据
        current_price = row['close']
        slope = row.get('Trend_Slope', 0)
        rsi = row.get('RSI_14', 50)
        adx = row.get('ADX_14', 0)

        # 布林带数据
        bb_long_lower = row.get('BB_Long_Lower')
        bb_short_lower = row.get('BB_Short_Lower')
        bb_short_mid = row.get('BB_Short_Mid')
        bb_short_width = row.get('BB_Short_Width', 0)

        if pd.isna(slope) or pd.isna(bb_long_lower): return signal

        # 🔥 熔断机制：如果均线垂直下坠 (Slope < -10)，说明是主跌浪，绝对不接
        if slope < -10: return signal

        # ==========================================
        # 🦖 模式 A: 狙击模式 (使用 99周期布林)
        # ==========================================
        # 依然维持严苛标准，抓大暴跌
        is_crash = (current_price < bb_long_lower) and (rsi < 30)

        if is_crash:
            signal['action'] = "BUY"
            signal['tp_pct'] = 0.08  # 暴跌博大反弹
            signal['sl_pct'] = 0.05
            return signal

        # ==========================================
        # 🦊 模式 B: 灵狐模式 (使用 20周期布林)
        # ==========================================
        # 1. 判定震荡: ADX < 30 (从25放宽到30，让它更容易触发)
        # 2. 判定空间: 短期布林带宽 > 3% (太窄不做，去滑点后没利润)
        is_ranging = (adx < 30) and (bb_short_width > 0.03)

        if is_ranging:
            # 入场：触碰 20周期下轨 + RSI < 45
            # 注意：这里用 bb_short_lower，它比 99 周期的高得多，容易碰到
            hit_short_lower = current_price <= bb_short_lower * 1.005
            rsi_weak = rsi < 45

            if hit_short_lower and rsi_weak:
                signal['action'] = "BUY"

                # 🔥 动态止盈：回归 20周期中轨
                dist_to_mid = (bb_short_mid - current_price) / current_price
                # 至少吃 1.5%，最多吃 4%，或者吃到中轨的 90%
                final_tp = max(0.015, min(dist_to_mid * 0.9, 0.04))

                signal['tp_pct'] = final_tp
                signal['sl_pct'] = 0.03  # 震荡市止损紧一点

                return signal

        return signal
