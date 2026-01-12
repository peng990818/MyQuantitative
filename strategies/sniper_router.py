import pandas as pd
import numpy as np
from core.strategy import BaseStrategy
from modules.analysis.technical import TechnicalAnalyzer
from utils.config_loader import ConfigLoader  # 引入配置加载器


class SniperRouterStrategy(BaseStrategy):
    def __init__(self, symbol="BTC/USDT"):
        # v23: 配置驱动版 (Config Driven)
        base_coin = symbol.split('/')[0]
        super().__init__(name=f"Sniper_v23_{base_coin}")

        self.ta = TechnicalAnalyzer()
        self.symbol = symbol

        # 🔥 从 YAML 加载参数
        self.params = self._load_params_from_config(base_coin)

    def _load_params_from_config(self, base_coin):
        """
        读取 config.yaml 并根据币种自动选择参数模板
        """
        cfg = ConfigLoader().get('strategy_params')

        if not cfg:
            raise ValueError("❌ 错误: config.yaml 中缺少 'strategy_params' 部分！")

        # 1. 判定是否为高波动币种
        # 将配置里的列表转为大写集合，防止大小写错误
        volatile_list = [x.upper() for x in cfg.get('volatile_symbols', [])]

        if base_coin.upper() in volatile_list:
            print(f"🔧 [Strategy] 检测到高波动币种 {base_coin} -> 加载 Volatile 模板")
            return cfg['volatile']
        else:
            print(f"🔧 [Strategy] 检测到标准币种 {base_coin} -> 加载 Default 模板")
            return cfg['default']

    # ==========================================
    # 下面的代码几乎不用动，因为都是引用 self.params
    # ==========================================

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        # ... (保持 v22 代码不变) ...
        df = self.ta.calculate_indicators(df)
        df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
        df['EMA_55'] = df['close'].ewm(span=55, adjust=False).mean()
        df['EMA_5'] = df['close'].ewm(span=5, adjust=False).mean()
        df['Slope_200'] = df['EMA_200'] - df['EMA_200'].shift(5)

        win_long = 99
        df['BB_Long_Lower'] = df['close'].rolling(win_long).mean() - 2.0 * df['close'].rolling(win_long).std()

        win_short = 20
        base_short = df['close'].rolling(win_short).mean()
        std_short = df['close'].rolling(win_short).std()
        df['BB_Short_Mid'] = base_short
        df['BB_Short_Lower'] = base_short - 2.0 * std_short
        df['BB_Short_Width'] = (base_short + 2 * std_short - (base_short - 2 * std_short)) / base_short
        return df

    def check_signal(self, row: pd.Series) -> dict:
        # ... (逻辑保持 v22 不变) ...
        slope = row.get('Slope_200', 0)
        if pd.isna(slope) or slope < -10: return {'action': None}

        ai_regime = row.get('AI_REGIME')
        if not ai_regime: ai_regime = self._determine_regime_fallback(row)

        actual_regime = self._technical_veto(row, ai_regime)
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

    # ... (技术否决 _technical_veto 和 fallback 保持不变) ...
    def _technical_veto(self, row, ai_regime):
        close = row['close']
        ema_200 = row['EMA_200']
        slope = row['Slope_200']
        if ai_regime == "BULL_TREND" and close < ema_200: return "WAIT"
        if ai_regime == "BEAR_CRASH" and close > ema_200: return "WAIT"
        if ai_regime == "SHOCK_SIDEWAYS" and slope < -5: return "WAIT"
        return ai_regime

    def _determine_regime_fallback(self, row):
        ema_55 = row.get('EMA_55')
        ema_200 = row.get('EMA_200')
        slope = row.get('Slope_200')
        if (ema_55 > ema_200) and (slope > 0): return "BULL_TREND"
        if (ema_55 < ema_200) and (slope < 0): return "BEAR_CRASH"
        return "SHOCK_SIDEWAYS"

    # ==========================================
    # 策略逻辑 (引用 self.params)
    # ==========================================
    def _strategy_bull_trend(self, row):
        close = row['close']
        ema_55 = row['EMA_55']
        rsi = row['RSI_14']
        signal = {'action': None}

        # 🔥 从 self.params 读取配置
        buffer = self.params['ema_entry_buffer']
        rsi_max = self.params['bull_rsi_entry']
        sl_pct = self.params['sl_bull']

        hit_support = close <= ema_55 * buffer
        rsi_valid = 40 < rsi < rsi_max

        if hit_support and rsi_valid:
            signal['action'] = "BUY"
            signal['sl_pct'] = sl_pct
            signal['use_trailing'] = True
            signal['trailing_start'] = sl_pct * 0.8
            signal['trailing_drop'] = sl_pct * 0.4
            signal['tp_pct'] = 0.50
        return signal

    def _strategy_bear_reversal(self, row):
        close = row['close']
        bb_long_lower = row['BB_Long_Lower']
        rsi = row['RSI_14']
        ema_5 = row['EMA_5']
        signal = {'action': None}

        # 🔥 从 self.params 读取
        rsi_limit = self.params['bear_rsi_entry']
        sl_pct = self.params['sl_bear']

        is_deep = close < bb_long_lower
        is_panic = rsi < rsi_limit
        is_stabilized = close > ema_5

        if is_deep and is_panic and is_stabilized:
            signal['action'] = "BUY"
            signal['sl_pct'] = sl_pct
            signal['use_trailing'] = False
            signal['tp_pct'] = 0.10
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
            # 牛市回调的止损通常比追涨止损稍微紧一点
            sl_base = self.params['sl_bull']
            signal['sl_pct'] = sl_base * 0.9
            signal['use_trailing'] = True
            signal['trailing_start'] = sl_base * 0.6
            signal['trailing_drop'] = sl_base * 0.3
            signal['tp_pct'] = 0.20
        return signal

    def _strategy_sideways(self, row):
        close = row['close']
        bb_short_lower = row['BB_Short_Lower']
        bb_short_mid = row['BB_Short_Mid']
        bb_width = row['BB_Short_Width']
        adx = row['ADX_14']
        rsi = row['RSI_14']
        signal = {'action': None}

        # 🔥 从 self.params 读取
        min_width = self.params['shock_min_width']
        rsi_entry = self.params['shock_rsi_entry']
        sl_pct = self.params['sl_shock']

        if adx > 25: return signal
        if bb_width < min_width: return signal

        hit_lower = close <= bb_short_lower * 1.005
        rsi_weak = rsi < rsi_entry

        if hit_lower and rsi_weak:
            signal['action'] = "BUY"
            signal['sl_pct'] = sl_pct
            signal['use_trailing'] = False

            dist_to_mid = (bb_short_mid - close) / close
            signal['tp_pct'] = max(0.015, min(dist_to_mid * 0.9, 0.05))
        return signal