import pandas as pd
import os
from utils.logger import logger


class MarketRegimeOracle:
    def __init__(self, data_path="data/ai_regime.csv"):
        self.regime_map = {}
        self.default_regime = "SHOCK_SIDEWAYS"  # 默认震荡

        if os.path.exists(data_path):
            self._load_data(data_path)
        else:
            logger.warning(f"⚠️ 未找到 AI 剧本文件: {data_path}，将使用技术指标自动判定。")

    def _load_data(self, path):
        try:
            df = pd.read_csv(path)
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')

            # 将 DataFrame 转换为以日期为 Key 的字典，方便快速查询
            # 注意：这里我们用 'ffill' (前向填充) 的逻辑
            # 即：如果 1月1日是 BULL，1月2日没记录，那1月2日也是 BULL
            self.df_regime = df.set_index('date')
            logger.info(f"🔮 [Oracle] AI 市场剧本已加载: {len(df)} 条记录")
        except Exception as e:
            logger.error(f"❌ 加载 AI 剧本失败: {e}")

    def get_regime(self, current_time: pd.Timestamp) -> str:
        """
        根据当前回测时间，返回 AI 判断的市场状态
        """
        if not self.regime_map and not hasattr(self, 'df_regime'):
            return None  # 返回 None 表示没有外部 AI 数据，让策略自己算

        # 查找当前时间之前最近的一条记录 (asof)
        # 比如当前是 2023-01-05，最近的记录是 2023-01-01 BULL，那就返回 BULL
        try:
            # 获取 current_time 索引之前最后有效的值
            idx = self.df_regime.index.asof(current_time)
            if pd.isna(idx):
                return self.default_regime

            regime = self.df_regime.loc[idx]['regime']
            return regime
        except Exception:
            return self.default_regime