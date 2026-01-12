import smtplib
import socket
import socks
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime
import contextlib
from utils.config_loader import ConfigLoader
from utils.proxy_manager import ProxyManager
from utils.logger import logger


class EmailNotifier:
    def __init__(self):
        self.cfg = ConfigLoader()
        self.proxy_mgr = ProxyManager(self.cfg)

        # ==========================================
        # 1. 读取基础配置 (通常在 config.yaml)
        # ==========================================
        # 这些是非敏感信息，通常放在 config.yaml 的 notification.email 下
        self.enabled = self.cfg.get("notification.email.enabled", False)
        self.smtp_server = self.cfg.get("notification.email.smtp_server", "smtp.gmail.com")
        self.smtp_port = self.cfg.get("notification.email.smtp_port", 587)

        # ==========================================
        # 2. 读取敏感信息 (你的 secrets.yaml)
        # ==========================================
        # 🔥 修正点：根据你的描述，这些在 secrets.yaml 的根节点 email 下
        self.sender = self.cfg.get("email.sender")
        self.password = self.cfg.get("email.password")  # 应用专用密码
        self.receiver = self.cfg.get("email.receiver")

        # 兼容性尝试：如果根节点没读到，试着去 notification.email 下读（防止有人放混了）
        if not self.sender:
            self.sender = self.cfg.get("notification.email.sender")
        if not self.password:
            self.password = self.cfg.get("notification.email.password")
        if not self.receiver:
            self.receiver = self.cfg.get("notification.email.receiver")

        # ==========================================
        # 3. 安全检查 (防止 NoneType 崩溃)
        # ==========================================
        if self.enabled:
            # 只要有一个关键信息缺失，就强制禁用，防止程序崩溃
            if not self.sender or not self.password or not self.receiver:
                logger.warning("⚠️ [Email] 账号/密码/接收人配置缺失！邮件功能已自动禁用。")
                logger.warning(f"   (读取到的 Sender: {self.sender})")  # 方便调试
                self.enabled = False
            else:
                logger.info(f"📧 [Email] 服务已就绪 (Sender: {self.sender})")

    def send_alert(self, title, message):
        """
        [通用接口] 适配 Engine 的调用
        :param title: 邮件标题
        :param message: 邮件正文
        """
        if not self.enabled:
            return

        full_subject = f"{title} [{datetime.now().strftime('%H:%M')}]"
        full_body = f"{message}\n\n------------------\n🤖 Sniper Bot v2.0"

        self._send_email_safe(full_subject, full_body)

    def _send_email_safe(self, subject, body):
        """
        使用上下文管理器安全地挂载代理发送
        """
        msg = MIMEText(body, 'plain', 'utf-8')
        msg['From'] = self.sender
        msg['To'] = self.receiver
        msg['Subject'] = Header(subject, 'utf-8')

        # 获取代理信息
        proxy_host = self.proxy_mgr.host
        proxy_port = self.proxy_mgr.port

        # 临时挂载代理，发送完立即还原
        with self._proxy_socket_context(proxy_host, proxy_port):
            try:
                server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=10)
                server.starttls()
                server.login(self.sender, self.password)  # 如果这里还是 None，上面的检查会拦截，不会走到这
                server.sendmail(self.sender, [self.receiver], msg.as_string())
                server.quit()
                logger.info(f"📧 [Email] 发送成功: {subject}")
            except Exception as e:
                logger.error(f"❌ [Email] 发送失败: {e}")

    @contextlib.contextmanager
    def _proxy_socket_context(self, host, port):
        original_socket = socket.socket
        try:
            if host and port:
                socks.set_default_proxy(socks.SOCKS5, host, int(port))
                socket.socket = socks.socksocket
            yield
        finally:
            socket.socket = original_socket


# === 单元测试 ===
if __name__ == "__main__":
    import sys, os

    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

    print("📧 正在测试邮件发送 (读取 secrets.yaml)...")
    notifier = EmailNotifier()

    if notifier.enabled:
        notifier.send_alert(
            title="🚀 配置读取测试",
            message="如果你收到这封信，说明 secrets.yaml 读取路径修复成功！"
        )
    else:
        print("❌ 邮件功能未启用，请检查日志里的警告信息。")