import pandas as pd
import numpy as np
from core.strategy import BaseStrategy
from modules.analysis.technical import TechnicalAnalyzer


class MomentumStrategy(BaseStrategy):
    def __init__(self):
        # 以此命名，代表这是适配 Crypto 短线高波动的 v9.0 版本
        super().__init__(name="Momentum_ShortTerm_v9.0")
        self.ta = TechnicalAnalyzer()

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        # 复用 TA 库计算全量指标
        df = self.ta.calculate_indicators(df)
        return df

    def check_signal(self, row: pd.Series) -> dict:
        """
        🔥 判定逻辑 v9.0 (Crypto 短线特化)：
        1. 趋势基准: 价格 > EMA 55 (生命线)
        2. 攻击形态: EMA 12 > EMA 26 (快线在慢线上方)
        3. 动能强度: ADX > 25 (趋势已启动)
        4. 拒绝追高: Z-Score 回调到位
        5. 拒绝接刀: RSI 处于健康反弹区
        """
        # 1. 初始化
        signal = {'action': None, 'atr': 0.0}

        # 2. 提取 ATR (用于止损计算)
        close = float(row['close'])
        atr = float(row.get('ATRr_14', close * 0.01))
        signal['atr'] = atr

        # 3. 提取指标 (直接使用 TA 里的短线指标名)
        adx = float(row.get('ADX_14', 0))
        z_score = float(row.get('z_score', 0))
        rsi = float(row.get('RSI_14', 50))

        # 🔥 均线系统 (对应 MACD 快慢线 + 生命线)
        ema_fast = float(row.get('EMA_12', 0))  # 12
        ema_slow = float(row.get('EMA_26', 0))  # 26
        ema_trend = float(row.get('EMA_55', 0))  # 55

        # ==========================================
        # 🧠 策略逻辑核心 v9.0
        # ==========================================

        # A. 趋势基准 (Trend Baseline)
        # 价格必须站稳在 55日生命线之上，否则不做多
        is_above_trend = close > ema_trend

        # B. 攻击形态 (Attack Formation)
        # 快线金叉慢线，且呈现多头排列
        is_bull_structure = ema_fast > ema_slow

        # C. 趋势强度 (Trend Strength)
        # 短线启动快，ADX > 25 即可视为进入趋势状态
        is_active_trend = adx > 25

        # D. 良性回调 (Healthy Pullback)
        # z < 0.5: 价格没有严重偏离均线（不追高）
        # z > -1.5: 价格没有发生恐慌性崩盘（不接飞刀）
        is_good_pullback = -1.5 < z_score < 0.5

        # E. 动能确认 (Momentum Check)
        # 45 < RSI < 70: 确保不是弱势阴跌，也不是严重超买
        is_rsi_healthy = 45 < rsi < 70

        # F. 信号触发 (五位一体)
        if is_above_trend and is_bull_structure and is_active_trend and is_good_pullback and is_rsi_healthy:
            signal['action'] = "BUY"

        return signal