import json
import os
from utils.logger import logger

class StateManager:
    def __init__(self, filename="trade_state.json"):
        # 状态文件保存在 data/ 目录下
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.file_path = os.path.join(base_path, 'data', filename)
        self.state = self._load_state()

    def _load_state(self):
        if not os.path.exists(self.file_path):
            return {}
        try:
            with open(self.file_path, 'r') as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_state(self):
        try:
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            with open(self.file_path, 'w') as f:
                json.dump(self.state, f, indent=4)
        except Exception as e:
            logger.error(f"❌ 保存持仓状态失败: {e}")

    def update_position(self, symbol, entry_price, qty):
        """记录买入信息"""
        self.state[symbol] = {
            "holding": True,
            "entry_price": float(entry_price),
            "qty": float(qty)
        }
        self._save_state()
        logger.info(f"📝 [State] 已记录持仓: {symbol} @ {entry_price}")

    def clear_position(self, symbol):
        """卖出后清除记录"""
        if symbol in self.state:
            del self.state[symbol]
            self._save_state()
            logger.info(f"📝 [State] 已清除持仓: {symbol}")

    def get_position(self, symbol):
        """查询是否持有"""
        return self.state.get(symbol, None)