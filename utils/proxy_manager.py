import os
import httpx  # 👈 确保安装了 httpx


class ProxyManager:
    def __init__(self, config):
        # 支持从 config 对象读取，也支持从 dict 读取 (兼容性处理)
        if isinstance(config, dict):
            self.enabled = config.get('proxy', {}).get('enabled', False)
            self.host = config.get('proxy', {}).get('host', '127.0.0.1')
            self.port = config.get('proxy', {}).get('port', 7890)
        else:
            self.enabled = config.get('proxy.enabled')
            self.host = config.get('proxy.host')
            self.port = config.get('proxy.port')

        self.proxy_url = f"http://{self.host}:{self.port}" if self.enabled and self.port else None

    def get_proxies(self):
        """
        返回 requests/ccxt 需要的 proxies 字典
        """
        if self.proxy_url:
            return {
                "http": self.proxy_url,
                "https": self.proxy_url
            }
        return None

    def get_proxy_url(self):
        """
        返回单个字符串 (供需要字符串的库使用)
        """
        return self.proxy_url

    def set_system_proxy(self):
        """
        设置系统环境变量 (Gemini 等 SDK 需要)
        """
        if self.proxy_url:
            os.environ["HTTP_PROXY"] = self.proxy_url
            os.environ["HTTPS_PROXY"] = self.proxy_url
            print(f"🌍 [System] 系统代理环境变量已设置: {self.proxy_url}")
        else:
            # 即使没开启，也要尝试清理环境变量，防止残留
            os.environ.pop("HTTP_PROXY", None)
            os.environ.pop("HTTPS_PROXY", None)

    def get_httpx_client(self):
        """
        🔥 [核心修复] 返回配置好代理的 httpx.Client
        """
        if not self.proxy_url:
            return None

        print(f"🌍 [Httpx] 正在配置代理 client: {self.proxy_url}")

        # 方案 A: 标准字典格式 (兼容性最好)
        try:
            return httpx.Client(proxies={
                "http://": self.proxy_url,
                "https://": self.proxy_url
            })
        except Exception:
            pass

        # 方案 B: 新版 httpx 可能要求 'proxy' 参数
        try:
            return httpx.Client(proxy=self.proxy_url)
        except Exception:
            pass

        # 方案 C: 旧版 httpx 使用 'proxies' 字符串
        try:
            return httpx.Client(proxies=self.proxy_url)
        except Exception as e:
            print(f"❌ [ProxyManager] 创建 httpx 客户端失败: {e}")
            return None