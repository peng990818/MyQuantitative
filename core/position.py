from utils.config_loader import ConfigLoader
from utils.logger import logger


class PositionManager:
    def __init__(self):
        self.cfg = ConfigLoader()
        # 读取资金管理配置
        self.mode = self.cfg.get("money_management.mode", "fixed")  # compound 或 fixed
        self.risk_pct = self.cfg.get("money_management.risk_per_trade", 0.1)
        self.fixed_qty = self.cfg.get("money_management.fixed_qty", 0.01)

        logger.info(f"💰 [Position] 资金管理模式: {self.mode.upper()}")
        if self.mode == 'compound':
            logger.info(f"   - 复利比例: 每次投入总资金的 {self.risk_pct * 100}%")
        else:
            logger.info(f"   - 单利固定: 每次 {self.fixed_qty} 个")

    def calculate_buy_size(self, current_price, account_balance):
        """
        计算买入数量
        :param current_price: 当前币价
        :param account_balance: 账户可用余额 (USDT)
        :return: (float) 建议购买数量
        """
        if current_price <= 0:
            return 0.0

        qty = 0.0

        if self.mode == "compound":
            # === 复利模式 (v2.0) ===
            invest_amount = account_balance * self.risk_pct
            qty = invest_amount / current_price

            # 余额不足时的保护
            if invest_amount > account_balance:
                qty = account_balance / current_price

        else:
            # === 单利模式 (v1.0) ===
            qty = self.fixed_qty

        # 精度控制 (保留4位小数)
        qty = round(qty, 4)

        # 最小下单量保护
        if qty < 0.0001:
            # 只是警告，不阻断，让上层决定是否下单
            pass

        return qty