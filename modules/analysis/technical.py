import pandas as pd
import numpy as np
from utils.config_loader import ConfigLoader
from utils.logger import logger

class TechnicalAnalyzer:
    def __init__(self):
        self.cfg = ConfigLoader()
        logger.info("📊 [Technical] 计算引擎 v5.2 (多周期直出版) 已加载")

    def calculate_indicators(self, df):
        """
        计算核心指标：显式计算 EMA 12/26/55/50/200，不做任何变量映射
        """
        if df is None or df.empty:
            return df

        # 使用 copy 避免 SettingWithCopyWarning
        df = df.copy()
        for col in ['close', 'high', 'low', 'volume']:
            df[col] = df[col].astype(float)

        close = df['close']
        high = df['high']
        low = df['low']

        # ==========================================
        # 🚀 1. 趋势强度 (ADX_14)
        # ==========================================
        alpha = 1 / 14
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.ewm(alpha=alpha, adjust=False).mean()

        up = high - high.shift()
        down = low.shift() - low

        plus_dm = np.where((up > down) & (up > 0), up, 0)
        minus_dm = np.where((down > up) & (down > 0), down, 0)

        plus_di = 100 * (pd.Series(plus_dm, index=df.index).ewm(alpha=alpha, adjust=False).mean() / atr)
        minus_di = 100 * (pd.Series(minus_dm, index=df.index).ewm(alpha=alpha, adjust=False).mean() / atr)

        dx = 100 * (abs(plus_di - minus_di) / (plus_di + minus_di + 0.00001))
        df['ADX_14'] = dx.ewm(alpha=alpha, adjust=False).mean()

        # ==========================================
        # 🚀 2. 统计位置 (Z-Score)
        # ==========================================
        sma20 = close.rolling(window=20).mean()
        std20 = close.rolling(window=20).std().replace(0, 0.00001)
        df['z_score'] = (close - sma20) / std20

        # ==========================================
        # 🚀 3. 趋势方向 (EMA 全家桶)
        # ==========================================
        # --- 短线灵敏组 ---
        df['EMA_12'] = close.ewm(span=12, adjust=False).mean() # 快线
        df['EMA_26'] = close.ewm(span=26, adjust=False).mean() # 慢线
        df['EMA_55'] = close.ewm(span=55, adjust=False).mean() # 短线生命线

        # --- 传统稳健组 (保留以备不时之需) ---
        df['EMA_50'] = close.ewm(span=50, adjust=False).mean()
        df['EMA_200'] = close.ewm(span=200, adjust=False).mean()

        # ==========================================
        # 🚀 4. 波动率与动能
        # ==========================================
        df['ATRr_14'] = atr

        # 斜率 (短线改为3周期)
        df['slope_pct'] = close.pct_change(3) * 100

        # RSI (14)
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1 / 14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1 / 14, adjust=False).mean()
        rs = gain / loss
        df['RSI_14'] = 100 - (100 / (1 + rs))

        return df

    def get_market_state(self, row):
        """
        返回所有计算好的指标，供外部调用
        """
        try:
            return {
                'current_price': row['close'],
                'trend': {
                    'ema_12': row.get('EMA_12'),
                    'ema_26': row.get('EMA_26'),
                    'ema_55': row.get('EMA_55'),
                    'ema_50': row.get('EMA_50'),
                    'ema_200': row.get('EMA_200'),
                    'adx': row.get('ADX_14'),
                    'slope': row.get('slope_pct'),
                },
                'momentum': {
                    'z_score': row.get('z_score'),
                    'rsi': row.get('RSI_14'),
                },
                'volatility': {
                    'atr': row.get('ATRr_14'),
                }
            }
        except Exception as e:
            logger.warning(f"❌ [Technical] 数据映射异常: {e}")
            return {}