import pandas as pd
import numpy as np
from utils.config_loader import ConfigLoader
from utils.logger import logger

class TechnicalAnalyzer:
    def __init__(self):
        self.cfg = ConfigLoader()
        logger.info("📊 [Technical] 机构级计算引擎 v5.0 (兼容性修复版) 已加载")

    def calculate_indicators(self, df):
        """
        计算核心指标，不执行内部 dropna，由引擎决定如何清洗
        """
        if df is None or df.empty:
            return df

        # 使用 copy 避免对原数据造成非预期修改
        df = df.copy()
        for col in ['close', 'high', 'low', 'volume']:
            df[col] = df[col].astype(float)

        close = df['close']
        high = df['high']
        low = df['low']

        # ==========================================
        # 🚀 1. 趋势强度 (ADX)
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

        # 这里使用 values 转换，确保索引对齐不出错
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
        # 🚀 3. 趋势方向 (EMA)
        # ==========================================
        df['EMA_50'] = close.ewm(span=50, adjust=False).mean()
        df['EMA_200'] = close.ewm(span=200, adjust=False).mean()

        # ==========================================
        # 🚀 4. 波动率风控 (ATR)
        # ==========================================
        df['ATRr_14'] = atr

        # 兼容性字段
        df['slope_pct'] = close.pct_change(5) * 100
        df['RSI_14'] = 50

        # 🔥 【关键改动】不再在此处调用 dropna()
        # 保持 DataFrame 长度与输入一致，由调用者清洗
        return df

    def get_market_state(self, row):
        try:
            return {
                'current_price': row['close'],
                'trend': {
                    'ema_long': row.get('EMA_200'),
                    'ema_mid': row.get('EMA_50'),
                    'adx': row.get('ADX_14'),
                    'slope': row.get('slope_pct'),
                },
                'momentum': {
                    'z_score': row.get('z_score'),
                },
                'volatility': {
                    'atr': row.get('ATRr_14'),
                }
            }
        except Exception as e:
            logger.warning(f"❌ [Technical] 数据映射异常: {e}")
            return {}