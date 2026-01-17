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

        # 🔥 1. 初始化智能代理管理器
        self.proxy_mgr = ProxyManager(self.cfg)

        # ==========================================
        # 2. 读取基础配置
        # ==========================================
        self.enabled = self.cfg.get("notification.email.enabled", False)
        self.smtp_server = self.cfg.get("notification.email.smtp_server", "smtp.gmail.com")
        self.smtp_port = self.cfg.get("notification.email.smtp_port", 587)

        # ==========================================
        # 3. 读取敏感信息 (优先 secrets.yaml)
        # ==========================================
        self.sender = self.cfg.get("email.sender")
        self.password = self.cfg.get("email.password")  # 应用专用密码
        self.receiver = self.cfg.get("email.receiver")

        # 兼容性兜底
        if not self.sender:
            self.sender = self.cfg.get("notification.email.sender")
        if not self.password:
            self.password = self.cfg.get("notification.email.password")
        if not self.receiver:
            self.receiver = self.cfg.get("notification.email.receiver")

        # ==========================================
        # 4. 安全检查
        # ==========================================
        if self.enabled:
            if not self.sender or not self.password or not self.receiver:
                logger.warning("⚠️ [Email] 配置缺失，邮件功能已自动禁用。")
                self.enabled = False
            else:
                logger.info(f"📧 [Email] 服务已就绪 (Sender: {self.sender})")
                # 打印一下当前的代理状态，方便调试
                if self.proxy_mgr.enabled:
                    logger.info(f"   🌍 [Network] 邮件将通过代理发送: {self.proxy_mgr.host}:{self.proxy_mgr.port}")
                else:
                    logger.info(f"   🌍 [Network] 邮件将使用服务器直连发送 (无代理)")

    def send_alert(self, title, message):
        """
        [通用接口] 发送邮件
        """
        if not self.enabled:
            return

        full_subject = f"{title} [{datetime.now().strftime('%H:%M')}]"
        # 加上当前运行模式，方便区分是实盘还是模拟
        run_mode = self.cfg.get("run_mode", "UNKNOWN")
        full_body = f"{message}\n\n------------------\n🤖 Sniper Bot v2.0 ({run_mode})"

        self._send_email_safe(full_subject, full_body)

    def _send_email_safe(self, subject, body):
        """
        使用上下文管理器安全发送
        """
        msg = MIMEText(body, 'plain', 'utf-8')
        msg['From'] = self.sender
        msg['To'] = self.receiver
        msg['Subject'] = Header(subject, 'utf-8')

        # 🔥 使用智能上下文管理器 (它会自动判断要不要挂代理)
        with self._proxy_socket_context():
            try:
                # 增加 timeout 防止网络卡死
                server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=15)
                server.starttls()
                server.login(self.sender, self.password)
                server.sendmail(self.sender, [self.receiver], msg.as_string())
                server.quit()
                logger.info(f"📧 [Email] 发送成功: {subject}")
            except Exception as e:
                logger.error(f"❌ [Email] 发送失败: {e}")

    @contextlib.contextmanager
    def _proxy_socket_context(self):
        """
        🔥 [核心修复] 智能代理上下文
        只有在 config 中 enabled=True 时才修改 socket
        """
        # 1. 如果代理未开启 (服务器模式)，直接 Yield，什么都不做 -> 直连
        if not self.proxy_mgr.enabled:
            yield
            return

        # 2. 如果代理开启 (本地开发模式)，挂载 SOCKS5
        original_socket = socket.socket
        try:
            host = self.proxy_mgr.host
            port = self.proxy_mgr.port

            if host and port:
                # logger.debug(f"🔌 挂载邮件代理: {host}:{port}")
                socks.set_default_proxy(socks.SOCKS5, host, int(port))
                socket.socket = socks.socksocket

            yield
        except Exception as e:
            logger.error(f"❌ [Proxy] 代理挂载失败: {e}")
            raise  # 抛出异常让外层捕获
        finally:
            # 3. 还原 Socket，防止污染其他模块
            socket.socket = original_socket


if __name__ == "__main__":
    # 简单的测试入口
    notifier = EmailNotifier()
    if notifier.enabled:
        notifier.send_alert("🚀 服务器部署测试", "如果收到这封邮件，说明服务器直连发送成功！")