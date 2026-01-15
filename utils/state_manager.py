import json
import os
from utils.logger import logger


class StateManager:
    def __init__(self, file_path="data/state.json"):
        self.file_path = file_path
        # 确保目录存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        self.data = self._load_state()

    def _load_state(self):
        """加载状态，如果没有文件则初始化默认值"""
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"❌ 读取状态文件失败: {e}")

        # 默认初始状态
        return {
            "balance": 10000.0,  # 💰 默认虚拟本金 10000 U
            "positions": {}  # 持仓字典
        }

    def _save_state(self):
        """保存状态到磁盘"""
        try:
            with open(self.file_path, 'w') as f:
                json.dump(self.data, f, indent=4)
        except Exception as e:
            logger.error(f"❌ 保存状态失败: {e}")

    # ==========================
    # 💰 余额管理 (影子模式专用)
    # ==========================
    def get_balance(self):
        return self.data.get("balance", 10000.0)

    def update_balance(self, new_balance):
        self.data["balance"] = new_balance
        self._save_state()

    # ==========================
    # 📦 持仓管理
    # ==========================
    def get_position(self, symbol):
        return self.data["positions"].get(symbol)

    def update_position(self, symbol, entry_price, qty, **kwargs):
        """开仓：记录持仓信息"""
        self.data["positions"][symbol] = {
            "symbol": symbol,
            "entry_price": entry_price,
            "qty": qty,
            "sl_pct": kwargs.get('sl_pct', 0.05),
            "timestamp": kwargs.get('timestamp')
        }
        self._save_state()

    def clear_position(self, symbol):
        """平仓：删除持仓信息"""
        if symbol in self.data["positions"]:
            del self.data["positions"][symbol]
            self._save_state()

        # 加在 StateManager 类里

    def set_cooldown(self, symbol, timestamp):
        """设置冷却结束时间戳 (float)"""
        if 'cooldowns' not in self.state:
            self.state['cooldowns'] = {}
        self.state['cooldowns'][symbol] = timestamp
        self._save_state()

    def get_cooldown(self, symbol):
        """获取冷却结束时间戳，如果不存在或已过期返回 0"""
        cooldowns = self.state.get('cooldowns', {})
        return cooldowns.get(symbol, 0)

    def update_position_high(self, symbol, new_high):
        """更新持仓的最高价格 (用于移动止盈)"""
        if symbol in self.state.get('positions', {}):
            self.state['positions'][symbol]['highest_price'] = new_high
            self._save_state()
