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

        self.last_regime = "SHOCK_SIDEWAYS"

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

        # ============================================================
        # 🔥 [新增] 稳压器 (Stabilizer): 兼容插入，不破坏原有结构
        # ============================================================
        # 逻辑：如果上一根K线是牛市，AI 突然喊震荡，但价格还守在 EMA55 之上 -> 强行续命
        curr_price = row['close']
        ma_trend = row.get('EMA_55', 0)  # 确保 technical.py 算了这个指标

        if self.last_regime == 'BULL_TREND' and ai_regime == 'SHOCK_SIDEWAYS':
            if curr_price > ma_trend:
                # 触发防假摔机制：无视 AI 的短期震荡信号，保持牛市判断
                ai_regime = 'BULL_TREND'

        # 记录本次修正后的状态，供下一次使用
        self.last_regime = ai_regime
        # ============================================================

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

        # ==========================================
        # 策略逻辑 (引用 self.params)
        # ==========================================

        # ==========================================
        # 策略逻辑 (引用 self.params)
        # ==========================================

    def _strategy_bull_trend(self, row):
        """
        牛市主策略：趋势回调买入 (EMA支撑)
        """
        close = row['close']
        ema_55 = row['EMA_55']
        rsi = row['RSI_14']
        signal = {'action': None}

        # 🔥 从 self.params 读取配置
        buffer = self.params['ema_entry_buffer']
        rsi_max = self.params['bull_rsi_entry']
        sl_pct = self.params['sl_bull']

        # 逻辑：价格回调到 EMA55 附近，且 RSI 没有过热
        hit_support = close <= ema_55 * buffer
        rsi_valid = 40 < rsi < rsi_max

        if hit_support and rsi_valid:
            signal['action'] = "BUY"
            signal['sl_pct'] = sl_pct
            signal['use_trailing'] = True
            signal['trailing_start'] = sl_pct * 0.8
            signal['trailing_drop'] = sl_pct * 0.4
            signal['tp_pct'] = 0.50

            # ============================================================
            # 🔥 [修复版] 极寒模式 (Winter Mode)
            # 弃用 Slope，改用 "现价 vs EMA200"
            # ============================================================
            ema_200 = row.get('EMA_200', 0)  # 确保 technical.py 算了 EMA_200

            # 如果 EMA200 存在，且当前价格在年线之下 -> 认定为深熊
            if ema_200 > 0 and row['close'] < ema_200:
                # 熊市由于流动性差，假突破极多
                # 强制降级为 0.25 (1/4仓位)
                signal['regime'] = "BEAR_CRASH"
            else:
                # 站上年线，才是真正的牛市
                signal['regime'] = "BULL_TREND"

        return signal

    def _strategy_bull_correction(self, row):
        """
        牛市副策略：深跌捡漏 (布林带下轨)
        """
        close = row['close']
        bb_short_lower = row['BB_Short_Lower']
        rsi = row['RSI_14']
        signal = {'action': None}

        # 逻辑：牛市里偶尔急跌插针到布林带下轨
        hit_lower = close <= bb_short_lower * 1.005
        rsi_oversold = rsi < 45

        if hit_lower and rsi_oversold:
            signal['action'] = "BUY"
            sl_base = self.params['sl_bull']
            signal['sl_pct'] = sl_base * 0.9
            signal['use_trailing'] = True
            signal['trailing_start'] = sl_base * 0.6
            signal['trailing_drop'] = sl_base * 0.3
            signal['tp_pct'] = 0.20

            # ============================================================
            # 🔥 [修复版] 极寒模式
            # ============================================================
            ema_200 = row.get('EMA_200', 0)

            if ema_200 > 0 and row['close'] < ema_200:
                # 熊市深蹲 -> 轻仓博弈
                signal['regime'] = "BEAR_CRASH"
            else:
                # 牛市黄金坑 -> 满仓干
                signal['regime'] = "BULL_TREND"

        return signal

    def _strategy_bear_reversal(self, row):
        """
        熊市策略：只接恐慌深针 (反转博弈)
        """
        close = row['close']
        bb_long_lower = row['BB_Long_Lower']
        rsi = row['RSI_14']
        ema_5 = row['EMA_5']
        signal = {'action': None}

        # 🔥 从 self.params 读取
        rsi_limit = self.params['bear_rsi_entry']
        sl_pct = self.params['sl_bear']

        # 逻辑：跌破长期布林下轨 + RSI极度恐慌 + 短期有企稳迹象(站上EMA5)
        is_deep = close < bb_long_lower
        is_panic = rsi < rsi_limit
        is_stabilized = close > ema_5

        if is_deep and is_panic and is_stabilized:
            signal['action'] = "BUY"
            signal['sl_pct'] = sl_pct
            signal['use_trailing'] = False
            signal['tp_pct'] = 0.10  # 熊市抢反弹，吃一口就跑

            # 🔥 [关键] 标记这是熊市策略 -> 对应 1/4 仓位 (0.25)
            signal['regime'] = "BEAR_CRASH"

        return signal

    def _strategy_sideways(self, row):
        """
        震荡策略：布林带内高抛低吸
        """
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

        # 过滤：ADX 太高说明有趋势，不做震荡；布林太窄说明没肉吃，不做
        if adx > 25: return signal
        if bb_width < min_width: return signal

        hit_lower = close <= bb_short_lower * 1.005
        rsi_weak = rsi < rsi_entry

        if hit_lower and rsi_weak:
            signal['action'] = "BUY"
            signal['sl_pct'] = sl_pct
            signal['use_trailing'] = False  # 震荡市用固定止盈更稳

            # 动态止盈：目标是回归中轨 (Middle Band)
            dist_to_mid = (bb_short_mid - close) / close
            signal['tp_pct'] = max(0.015, min(dist_to_mid * 0.9, 0.05))

            # 🔥 [关键] 标记这是震荡策略 -> 对应半仓 (0.5)
            signal['regime'] = "SHOCK_SIDEWAYS"

        return signal
