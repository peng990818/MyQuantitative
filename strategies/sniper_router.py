import pandas as pd
import numpy as np
from core.strategy import BaseStrategy
from modules.analysis.technical import TechnicalAnalyzer


class SniperRouterStrategy(BaseStrategy):
    def __init__(self):
        # v21: 技术否决版 (Trust but Verify)
        # AI 定性，技术定量。如果技术面不支持 AI 的判断，拒绝执行。
        super().__init__(name="Sniper_Router_v21_Veto")
        self.ta = TechnicalAnalyzer()

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self.ta.calculate_indicators(df)

        # 1. 趋势指纹
        df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
        df['EMA_55'] = df['close'].ewm(span=55, adjust=False).mean()
        df['EMA_5'] = df['close'].ewm(span=5, adjust=False).mean()

        # 2. 斜率 (判断趋势力度)
        df['Slope_200'] = df['EMA_200'] - df['EMA_200'].shift(5)

        # 3. 熊市布林 (99)
        win_long = 99
        base_long = df['close'].rolling(window=win_long).mean()
        std_long = df['close'].rolling(window=win_long).std()
        df['BB_Long_Lower'] = base_long - (2.0 * std_long)

        # 4. 震荡布林 (20)
        win_short = 20
        base_short = df['close'].rolling(window=win_short).mean()
        std_short = df['close'].rolling(window=win_short).std()
        df['BB_Short_Mid'] = base_short
        df['BB_Short_Lower'] = base_short - (2.0 * std_short)
        df['BB_Short_Width'] = (base_short + 2 * std_short - (base_short - 2 * std_short)) / base_short

        return df

    def check_signal(self, row: pd.Series) -> dict:
        # 0. 基础数据准备
        slope = row.get('Slope_200', 0)
        if pd.isna(slope): return {'action': None}

        # 1. 宏观熔断 (最高级风控)
        if slope < -10: return {'action': None}

        # 2. 获取 AI 观点 (优先读取 CSV 注入的字段)
        ai_regime = row.get('AI_REGIME')
        if not ai_regime:
            ai_regime = self._determine_regime_fallback(row)

        # 3. 🔥 技术否决层 (The Veto Layer) 🔥
        # 即使 AI 说是牛市，如果技术面已经崩了，也不许做多
        actual_regime = self._technical_veto(row, ai_regime)

        # 4. 策略分发
        signal = {'action': None}

        if actual_regime == "BULL_TREND":
            signal = self._strategy_bull_trend(row)
            if not signal['action']:
                signal = self._strategy_bull_correction(row)

        elif actual_regime == "BEAR_CRASH":
            signal = self._strategy_bear_reversal(row)

        elif actual_regime == "SHOCK_SIDEWAYS":
            signal = self._strategy_sideways(row)

        return signal

    # ==================================================================
    # 🔥 核心新功能: 技术否决器
    # ==================================================================
    def _technical_veto(self, row, ai_regime):
        """
        AI 说的话，必须经过技术面的验证。
        如果严重背离，强制降级为 'WAIT' (空仓)。
        """
        close = row['close']
        ema_200 = row['EMA_200']
        slope = row['Slope_200']

        # 场景 A: AI 说是牛市，但价格跌破 EMA 200 (技术性熊市)
        if ai_regime == "BULL_TREND":
            if close < ema_200:
                # 拒绝执行牛市策略，转为观望 (或者降级为震荡)
                return "WAIT"
            return "BULL_TREND"

        # 场景 B: AI 说是熊市，但价格还在 EMA 200 之上 (多头不死)
        if ai_regime == "BEAR_CRASH":
            if close > ema_200:
                # 此时接飞刀太危险(可能是上涨中继)，不如观望
                return "WAIT"
            return "BEAR_CRASH"

        # 场景 C: AI 说是震荡，但正在暴跌 (Slope < -5)
        if ai_regime == "SHOCK_SIDEWAYS":
            if slope < -5:
                return "WAIT"  # 正在跌，别接飞刀
            return "SHOCK_SIDEWAYS"

        return "WAIT"

    # ==================================================================
    # 辅助: 没有 CSV 时的回退逻辑
    # ==================================================================
    def _determine_regime_fallback(self, row):
        ema_55 = row.get('EMA_55')
        ema_200 = row.get('EMA_200')
        slope = row.get('Slope_200')
        if (ema_55 > ema_200) and (slope > 0): return "BULL_TREND"
        if (ema_55 < ema_200) and (slope < 0): return "BEAR_CRASH"
        return "SHOCK_SIDEWAYS"

    # ==================================================================
    # 策略 A: 牛市策略 (放宽止损，加强确认)
    # ==================================================================
    def _strategy_bull_trend(self, row):
        close = row['close']
        ema_55 = row['EMA_55']
        rsi = row['RSI_14']

        signal = {'action': None}

        # 逻辑：回踩 EMA 55
        hit_support = close <= ema_55 * 1.015
        # 修正：牛市里 RSI 可以高一点，太低反而说明趋势坏了
        rsi_valid = 40 < rsi < 70

        if hit_support and rsi_valid:
            signal['action'] = "BUY"
            signal['sl_pct'] = 0.07  # 🔥 放大止损到 7%
            signal['use_trailing'] = True
            signal['trailing_start'] = 0.05
            signal['trailing_drop'] = 0.03
            signal['tp_pct'] = 0.50

        return signal

    def _strategy_bull_correction(self, row):
        close = row['close']
        bb_short_lower = row['BB_Short_Lower']
        rsi = row['RSI_14']

        signal = {'action': None}

        hit_lower = close <= bb_short_lower * 1.005
        rsi_oversold = rsi < 45

        if hit_lower and rsi_oversold:
            signal['action'] = "BUY"
            signal['sl_pct'] = 0.06  # 🔥 放大止损
            signal['use_trailing'] = True
            signal['trailing_start'] = 0.04
            signal['trailing_drop'] = 0.025
            signal['tp_pct'] = 0.20

        return signal

    # ==================================================================
    # 策略 B: 熊市策略 (极其保守)
    # ==================================================================
    def _strategy_bear_reversal(self, row):
        close = row['close']
        bb_long_lower = row['BB_Long_Lower']
        rsi = row['RSI_14']
        ema_5 = row['EMA_5']

        signal = {'action': None}

        # 必须是极值中的极值
        is_deep = close < bb_long_lower
        is_panic = rsi < 20  # 修正：熊市不恐慌不买
        is_stabilized = close > ema_5  # 必须站稳 5日线

        if is_deep and is_panic and is_stabilized:
            signal['action'] = "BUY"
            signal['sl_pct'] = 0.05
            signal['use_trailing'] = False
            signal['tp_pct'] = 0.10

        return signal

    # ==================================================================
    # 策略 C: 震荡策略 (只做宽幅震荡)
    # ==================================================================
    def _strategy_sideways(self, row):
        close = row['close']
        bb_short_lower = row['BB_Short_Lower']
        bb_short_mid = row['BB_Short_Mid']
        bb_width = row['BB_Short_Width']
        adx = row['ADX_14']
        rsi = row['RSI_14']

        signal = {'action': None}

        if adx > 25: return signal
        if bb_width < 0.04: return signal  # 🔥 修正：太窄不做 (去掉手续费没钱赚)

        hit_lower = close <= bb_short_lower * 1.005
        rsi_weak = rsi < 40

        if hit_lower and rsi_weak:
            signal['action'] = "BUY"
            signal['sl_pct'] = 0.04  # 🔥 放大止损
            signal['use_trailing'] = False

            dist_to_mid = (bb_short_mid - close) / close
            signal['tp_pct'] = max(0.015, min(dist_to_mid * 0.9, 0.05))

        return signal