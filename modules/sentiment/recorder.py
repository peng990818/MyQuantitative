import csv
import os
from datetime import datetime
from utils.logger import logger


class TradeRecorder:
    def __init__(self, filepath="data/trade_history.csv"):
        self.filepath = filepath
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        """如果文件不存在，创建并写入表头"""
        if not os.path.exists(self.filepath):
            try:
                os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
                with open(self.filepath, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    # 写入表头
                    writer.writerow([
                        "Time",  # 时间
                        "Mode",  # 模式 (REAL/PAPER)
                        "Symbol",  # 标的
                        "Action",  # 动作 (BUY/SELL)
                        "Price",  # 价格
                        "Qty",  # 数量
                        "Amount",  # 总金额 (U)
                        "Fee",  # 手续费 (预估)
                        "PnL",  # 盈亏 (仅平仓时有)
                        "PnL_Pct",  # 盈亏率
                        "Balance",  # 交易后余额
                        "Reason",  # 原因 (AI观点/止损理由)
                        "AI_Regime"  # 当时的市场状态
                    ])
            except Exception as e:
                logger.error(f"❌ 初始化交易记录表失败: {e}")

    def log_trade(self, mode, symbol, action, price, qty, balance, reason,
                  ai_regime="N/A", pnl=0.0, pnl_pct=0.0, fee=0.0):
        """
        写入一条交易记录
        """
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            amount = price * qty

            with open(self.filepath, 'a', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow([
                    timestamp,
                    mode,
                    symbol,
                    action,
                    f"{price:.4f}",
                    f"{qty:.6f}",
                    f"{amount:.2f}",
                    f"{fee:.4f}",
                    f"{pnl:.4f}" if action == "SELL" else "",
                    f"{pnl_pct * 100:.2f}%" if action == "SELL" else "",
                    f"{balance:.2f}",
                    reason,
                    ai_regime
                ])

            logger.info(f"📝 交易已归档至 CSV: {action} {symbol}")

        except Exception as e:
            logger.error(f"❌ 写入交易记录失败: {e}")