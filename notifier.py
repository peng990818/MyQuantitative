import smtplib
import os
import socket  # 👈 新增
import socks  # 👈 新增 (需要 pip install PySocks)
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(override=True)


class EmailNotifier:
    def __init__(self):
        self.enabled = os.getenv("EMAIL_ENABLED", "False").lower() == "true"
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.sender = os.getenv("EMAIL_SENDER")
        self.password = os.getenv("EMAIL_PASSWORD")
        self.receiver = os.getenv("EMAIL_RECEIVER")

        # 读取代理端口
        self.proxy_port = os.getenv("PROXY_PORT")

    def _send(self, subject, body):
        if not self.enabled: return

        # === 🔥 核心黑魔法：临时挂载代理 ===
        # 保存原始的 socket 连接方式，发完邮件后要还原
        original_socket = socket.socket

        try:
            # 如果配置了代理端口，就强行打补丁
            if self.proxy_port:
                print(f"🔌 [邮件]正在通过代理 (127.0.0.1:{self.proxy_port}) 连接 SMTP...")
                # 设置 SOCKS5 代理 (兼容大多数梯子)
                socks.set_default_proxy(socks.SOCKS5, "127.0.0.1", int(self.proxy_port))
                socket.socket = socks.socksocket

            msg = MIMEText(body, 'plain', 'utf-8')
            msg['From'] = self.sender
            msg['To'] = self.receiver
            msg['Subject'] = Header(subject, 'utf-8')

            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.sender, self.password)
            server.sendmail(self.sender, [self.receiver], msg.as_string())
            server.quit()
            print(f"📧 [通知] 邮件已发送: {subject}")

        except Exception as e:
            print(f"❌ [通知] 邮件发送失败: {e}")
            # 如果是 Gmail 连接超时，通常是因为代理没生效
            if "Time out" in str(e) or "10060" in str(e):
                print("   👉 提示: 请检查 PROXY_PORT 是否正确，且梯子已开启 SOCKS5 模式")

        finally:
            # === 🔥 还原现场 ===
            # 无论发送成功还是失败，必须把 socket 还原回去
            # 否则可能会影响 CCXT 或 DeepSeek 的连接
            if self.proxy_port:
                socket.socket = original_socket

    def send_buy_alert(self, symbol, price, qty, reason):
        subject = f"🚀 [买入] {symbol} @ {price:.2f}"
        body = f"""
        [自动交易机器人报告]
        --------------------------------
        类型: 买入 (BUY)
        标的: {symbol}
        时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        --------------------------------
        成交价格: {price:.2f}
        成交数量: {qty}
        触发原因: {reason}
        --------------------------------
        """
        self._send(subject, body.strip())

    def send_sell_alert(self, symbol, price, qty, reason, entry_price, balance):
        pnl_amt = (price - entry_price) * qty
        pnl_pct = (price - entry_price) / entry_price * 100

        # 标题根据盈亏变色
        if "STOP_LOSS" in reason:
            subject = f"🚨 [止损离场] {symbol} ({pnl_pct:+.2f}%)"
        elif "TAKE_PROFIT" in reason:
            subject = f"💰 [止盈落袋] {symbol} ({pnl_pct:+.2f}%)"
        else:
            emoji = "📉" if pnl_amt < 0 else "📈"
            subject = f"{emoji} [卖出] {symbol} ({pnl_pct:+.2f}%)"

        body = f"""
        [自动交易机器人报告]
        --------------------------------
        类型: 卖出 (SELL)
        标的: {symbol}
        时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        --------------------------------
        卖出价格: {price:.2f}
        买入成本: {entry_price:.2f}
        --------------------------------
        📊 本单盈亏: {pnl_amt:+.2f} U
        📈 收益率  : {pnl_pct:+.2f}%
        --------------------------------
        ⚡ 触发原因: {reason}
        💰 当前余额: {balance:.2f} U
        --------------------------------
        """
        self._send(subject, body.strip())


# 测试代码
if __name__ == "__main__":
    notifier = EmailNotifier()
    if notifier.enabled:
        print("📨 正在测试 Gmail 代理发送...")
        notifier.send_buy_alert("BTC/USDT", 95000, 0.01, "代理连接测试")
    else:
        print("请先在 .env 中设置 EMAIL_ENABLED=True")