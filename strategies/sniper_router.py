import pandas as pd
import numpy as np
from core.strategy import BaseStrategy
from modules.analysis.technical import TechnicalAnalyzer


class SniperRouterStrategy(BaseStrategy):
    def __init__(self):
        # 严格遵循 BaseStrategy 接口
        super().__init__(name="Sniper_Router_v20_AI")
        self.ta = TechnicalAnalyzer()

    # ==================================================================
    # 步骤 1: 统一计算所有需要的指标 (数据仓库)
    # ==================================================================
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self.ta.calculate_indicators(df)

        # --- A. 趋势指纹 (用于识别体制) ---
        df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
        df['EMA_55'] = df['close'].ewm(span=55, adjust=False).mean()
        df['EMA_5'] = df['close'].ewm(span=5, adjust=False).mean()  # 短期生命线

        # 计算斜率 (判断趋势强弱)
        df['Slope_200'] = df['EMA_200'] - df['EMA_200'].shift(5)

        # --- B. 熊市防御网 (99周期布林) ---
        win_long = 99
        base_long = df['close'].rolling(window=win_long).mean()
        std_long = df['close'].rolling(window=win_long).std()
        df['BB_Long_Lower'] = base_long - (2.0 * std_long)

        # --- C. 震荡/牛市回调网 (20周期布林) ---
        win_short = 20
        base_short = df['close'].rolling(window=win_short).mean()
        std_short = df['close'].rolling(window=win_short).std()
        df['BB_Short_Mid'] = base_short
        df['BB_Short_Lower'] = base_short - (2.0 * std_short)
        # 带宽 (用于过滤死鱼盘)
        df['BB_Short_Width'] = (base_short + 2 * std_short - (base_short - 2 * std_short)) / base_short

        return df

    # ==================================================================
    # 步骤 2: 核心路由逻辑 (司令部)
    # ==================================================================
    def check_signal(self, row: pd.Series) -> dict:
        """
        AI 决策层: 判断当前属于什么体制，然后下发给具体的逻辑模块执行
        """
        # 0. 基础数据准备
        slope = row.get('Slope_200', 0)
        if pd.isna(slope): return {'action': None}

        # 1. 宏观熔断 (全局风控)
        # 哪怕 AI 说可以买，如果正在自由落体，也必须强制空仓
        if slope < -10:
            return {'action': None}

        # 2. 体制识别 (Regime Identification)
        # 这里模拟 AI 的判断。如果你接入了 GPT，这里就是 self.ask_gpt(row)
        regime = self._determine_regime(row)

        # 3. 策略分发
        signal = {'action': None}

        if regime == "BULL_TREND":
            # 牛市：主攻趋势，辅攻震荡(回调)
            signal = self._strategy_bull_trend(row)
            if not signal['action']:
                signal = self._strategy_bull_correction(row)  # 牛市里的震荡策略

        elif regime == "BEAR_CRASH":
            # 熊市：严防死守，只接飞刀
            signal = self._strategy_bear_reversal(row)

        elif regime == "SHOCK_SIDEWAYS":
            # 震荡市：高抛低吸，但参数要严格
            signal = self._strategy_sideways(row)

        return signal

    # ==================================================================
    # 辅助方法: 体制识别器 (模拟 AI 大脑)
    # ==================================================================
    def _determine_regime(self, row):
        ema_55 = row.get('EMA_55')
        ema_200 = row.get('EMA_200')
        slope = row.get('Slope_200')
        adx = row.get('ADX_14', 0)

        # 金叉 + 斜率向上 = 牛市
        if (ema_55 > ema_200) and (slope > 0):
            return "BULL_TREND"

        # 死叉 + 斜率向下 = 熊市
        if (ema_55 < ema_200) and (slope < 0):
            return "BEAR_CRASH"

        # 其他情况视为震荡/过渡期
        return "SHOCK_SIDEWAYS"

    # ==================================================================
    # 策略 A: 牛市趋势策略 (Aggressive)
    # ==================================================================
    def _strategy_bull_trend(self, row):
        """
        逻辑：追涨。
        严格指标：回踩 EMA 55 + RSI 健康
        """
        close = row['close']
        ema_55 = row['EMA_55']
        rsi = row['RSI_14']

        signal = {'action': None}

        # 严格判断:
        # 1. 回踩幅度不能太深 (EMA 55 附近 1.5%)
        hit_support = close <= ema_55 * 1.015
        # 2. RSI 不能过热也不能过冷 (牛市里 RSI 40-60 是支撑区)
        rsi_valid = 40 < rsi < 65

        if hit_support and rsi_valid:
            signal['action'] = "BUY"
            signal['sl_pct'] = 0.05
            # 牛市特权：开启移动止盈
            signal['use_trailing'] = True
            signal['trailing_start'] = 0.04
            signal['trailing_drop'] = 0.025
            signal['tp_pct'] = 0.50  # 虚设上限

        return signal

    # ==================================================================
    # 策略 B: 牛市回调/震荡策略 (Moderate)
    # ==================================================================
    def _strategy_bull_correction(self, row):
        """
        逻辑：牛市里的深回调（送钱机会）。
        严格指标：触碰 20 布林下轨
        """
        close = row['close']
        bb_short_lower = row['BB_Short_Lower']
        rsi = row['RSI_14']

        signal = {'action': None}

        # 牛市里跌破 20 布林下轨，通常是假摔
        hit_lower = close <= bb_short_lower * 1.005
        rsi_oversold = rsi < 45  # 牛市里 45 就算超卖了

        if hit_lower and rsi_oversold:
            signal['action'] = "BUY"
            signal['sl_pct'] = 0.04
            # 同样开启移动止盈，防止回调变成主升浪
            signal['use_trailing'] = True
            signal['trailing_start'] = 0.03
            signal['trailing_drop'] = 0.02
            signal['tp_pct'] = 0.20

        return signal

    # ==================================================================
    # 策略 C: 熊市反转策略 (Defensive)
    # ==================================================================
    def _strategy_bear_reversal(self, row):
        """
        逻辑：绝对防御。只接历史大底。
        严格指标：跌破 99 布林 + RSI < 25 + EMA 5 确认
        """
        close = row['close']
        bb_long_lower = row['BB_Long_Lower']
        rsi = row['RSI_14']
        ema_5 = row['EMA_5']

        signal = {'action': None}

        # 1. 深度必须够 (99下轨)
        is_deep = close < bb_long_lower
        # 2. 情绪必须恐慌 (RSI < 25) - 比牛市严格得多
        is_panic = rsi < 25
        # 3. 🔥 必须有止跌迹象 (站上 EMA 5) - 物理锁，防止接飞刀
        is_stabilized = close > ema_5

        if is_deep and is_panic and is_stabilized:
            signal['action'] = "BUY"
            signal['sl_pct'] = 0.06
            # 熊市不做移动止盈，快进快出
            signal['use_trailing'] = False
            signal['tp_pct'] = 0.10

        return signal

    # ==================================================================
    # 策略 D: 纯震荡市策略 (Sniper)
    # ==================================================================
    def _strategy_sideways(self, row):
        """
        逻辑：垃圾时间刷单。
        严格指标：ADX 低 + 带宽够
        """
        close = row['close']
        bb_short_lower = row['BB_Short_Lower']
        bb_short_mid = row['BB_Short_Mid']
        bb_width = row['BB_Short_Width']
        adx = row['ADX_14']
        rsi = row['RSI_14']

        signal = {'action': None}

        # 1. 必须是真震荡 (ADX < 25)
        if adx > 25: return signal
        # 2. 必须有肉吃 (带宽 > 3%)
        if bb_width < 0.03: return signal

        # 3. 严格的高抛低吸
        hit_lower = close <= bb_short_lower * 1.005
        rsi_weak = rsi < 40  # 震荡市要求 RSI 更低才安全

        if hit_lower and rsi_weak:
            signal['action'] = "BUY"
            signal['sl_pct'] = 0.03  # 窄止损
            signal['use_trailing'] = False

            # 动态止盈：回归中轨
            dist_to_mid = (bb_short_mid - close) / close
            signal['tp_pct'] = max(0.015, min(dist_to_mid * 0.9, 0.04))

        return signal