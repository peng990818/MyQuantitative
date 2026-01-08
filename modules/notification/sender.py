import smtplib
import socket
import socks
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime
from utils.config_loader import ConfigLoader
from utils.proxy_manager import ProxyManager
from utils.logger import logger


class EmailNotifier:
    def __init__(self):
        self.cfg = ConfigLoader()
        self.proxy_mgr = ProxyManager(self.cfg)

        self.enabled = self.cfg.get("notification.email.enabled", False)
        self.smtp_server = self.cfg.get("notification.email.smtp_server", "smtp.gmail.com")
        self.smtp_port = self.cfg.get("notification.email.smtp_port", 587)

        self.sender = self.cfg.get("email.sender")
        self.password = self.cfg.get("email.password")
        self.receiver = self.cfg.get("email.receiver")

    def send_alert(self, type_, symbol, price, qty, details, pnl_pct=0.0):
        """
        发送交易提醒
        :param type_: "BUY" | "TP"(止盈) | "SL"(止损)
        """
        if not self.enabled:
            return

        # 1. 设置图标和标题
        icon_map = {
            "BUY": "🚀 [买入]",
            "TP": "💰 [止盈]",
            "SL": "🛑 [止损]"
        }
        icon = icon_map.get(type_, "📢")
        subject = f"{icon} {symbol} 触发提醒"

        # 2. 盈亏描述
        pnl_info = ""
        if type_ in ["TP", "SL"]:
            emoji = "🎉" if pnl_pct > 0 else "😭"
            pnl_info = f"📈 本次盈亏: {pnl_pct:+.2f}% {emoji}"

        # 3. 邮件正文
        body = f"""
        QuantBot v2.0 交易报告
        ================================
        动作: {type_}
        时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        标的: {symbol}
        价格: {price:.2f} USDT
        数量: {qty}
        --------------------------------
        {pnl_info}

        🧠 策略分析:
        {details}
        ================================
        """

        self._send_email_via_proxy(subject, body)

    def _send_email_via_proxy(self, subject, body):
        """通过代理发送 Gmail"""
        # 保存原始 socket 环境
        original_socket = socket.socket

        try:
            # === 1. 强行挂载 SOCKS5 代理 ===
            # Gmail 在国内必须翻墙才能连上 SMTP
            proxy_url = self.proxy_mgr.get_proxy_url()
            if proxy_url:
                # 假设 proxy_url 是 http://127.0.0.1:7890
                # 我们需要解析出 IP 和 端口
                p_host = self.proxy_mgr.host
                p_port = int(self.proxy_mgr.port)

                # 关键黑魔法：把 Python 的 socket 替换成 socks
                socks.set_default_proxy(socks.SOCKS5, p_host, p_port)
                socket.socket = socks.socksocket
                # logger.debug(f"🔌 [Email] 已挂载代理: {p_host}:{p_port}")

            # === 2. 发送邮件 ===
            msg = MIMEText(body, 'plain', 'utf-8')
            msg['From'] = self.sender
            msg['To'] = self.receiver
            msg['Subject'] = Header(subject, 'utf-8')

            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()  # Gmail 必须启用 TLS
            server.login(self.sender, self.password)
            server.sendmail(self.sender, [self.receiver], msg.as_string())
            server.quit()

            logger.info(f"📧 [Email] 发送成功: {subject}")

        except Exception as e:
            logger.error(f"❌ [Email] 发送失败: {e}")
            logger.warning("💡 提示: 请检查是否开启了 Gmail 应用专用密码，以及代理是否通畅。")

        finally:
            # === 3. 还原 socket，防止影响其他模块 ===
            socket.socket = original_socket


if __name__ == "__main__":
    # 简单的测试代码
    import sys, os

    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    print("📧 正在测试 Gmail 发送...")
    notifier = EmailNotifier()
    notifier.send_alert("BUY", "BTC/USDT", 95000, 0.01, "测试邮件功能")