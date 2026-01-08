import os

import pandas_ta as ta
import pandas as pd
from utils.config_loader import ConfigLoader


class TechnicalAnalyzer:
    def __init__(self):
        self.cfg = ConfigLoader()
        # 这里暂时为了兼容 v1 功能，我们先定义一个标准策略
        # 后续这里可以读取 config.yaml 里的 'indicators' 列表来动态生成
        self.strategy = ta.Strategy(
            name="QuantBot_v2_Standard",
            ta=[
                {"kind": "rsi", "length": 14},
                {"kind": "macd", "fast": 12, "slow": 26, "signal": 9},
                {"kind": "bbands", "length": 20, "std": 2},
                {"kind": "ema", "length": 7},
                {"kind": "ema", "length": 99},
                {"kind": "atr", "length": 14},
                {"kind": "adx", "length": 14},
                {"kind": "cci", "length": 20},
                {"kind": "obv"},
                {"kind": "stoch", "k": 9, "d": 3}
            ]
        )
        print("📊 [Technical] 动态指标策略已加载")

    def calculate_indicators(self, df):
        """
        输入原始 K 线 DataFrame，输出包含指标的 DataFrame
        """
        if df is None or df.empty:
            return df

        # 强制类型转换，防止报错
        df['close'] = df['close'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['volume'] = df['volume'].astype(float)

        # 🔥 一键并行计算所有指标
        df.ta.strategy(self.strategy)

        # 清洗数据 (去除因计算指标产生的 NaN)
        df.dropna(inplace=True)
        return df

    def get_market_state(self, row):
        """
        将 DataFrame 的一行转换为 v1 风格的字典，供后续评分逻辑使用
        """
        # 注意：pandas_ta 自动生成的列名通常是 "RSI_14", "EMA_7" 等
        # 这里做一个简单的映射，确保兼容性
        try:
            return {
                'current_price': row['close'],
                'trend': {
                    'ema_short': row.get('EMA_7'),
                    'ema_long': row.get('EMA_99'),
                    'adx': row.get('ADX_14'),
                },
                'momentum': {
                    'rsi': row.get('RSI_14'),
                    'cci': row.get('CCI_20_0.015'),
                },
                'volatility': {
                    'bb_upper': row.get('BBU_20_2.0'),
                    'bb_lower': row.get('BBL_20_2.0'),
                    'atr': row.get('ATRr_14'),
                },
                'volume': {
                    'obv': row.get('OBV'),
                },
                'macd': row.get('MACD_12_26_9'),
                'macd_signal': row.get('MACDs_12_26_9')
            }
        except Exception as e:
            print(f"❌ 数据映射错误: {e}")
            print(f"可用列名: {row.index.tolist()}")
            return {}

if __name__ == "__main__":
    import sys
    import pandas as pd
    import numpy as np

    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

    print("📊 正在测试 TechnicalAnalyzer...")

    # 1. 造假数据 (100根K线)
    print("⏳ 生成模拟 K 线数据...")
    df = pd.DataFrame({
        'close': np.random.uniform(90000, 95000, 100),
        'high': np.random.uniform(95000, 96000, 100),
        'low': np.random.uniform(89000, 90000, 100),
        'volume': np.random.uniform(100, 1000, 100)
    })

    # 2. 计算
    try:
        analyzer = TechnicalAnalyzer()
        df_res = analyzer.calculate_indicators(df)

        print("✅ 计算完成！")
        print(f"   输入行数: 100 -> 输出行数: {len(df_res)} (因指标计算会消耗头部数据)")
        print(
            f"   包含指标列: {[col for col in df_res.columns if col not in ['close', 'high', 'low', 'volume']][:5]}...")

        # 3. 测试状态提取
        last_row = df_res.iloc[-1]
        state = analyzer.get_market_state(last_row)
        print(f"✅ 状态提取测试: RSI={state['momentum'].get('rsi'):.2f}")

    except Exception as e:
        print(f"❌ 测试失败: {e}")