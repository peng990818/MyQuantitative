import os
import socket
import requests
import google.generativeai as genai
import ccxt
import urllib3
from dotenv import load_dotenv

# ==========================================
# 1. 联通底层修复：强制 IPv4 (防止 IPv6 泄露真实坐标导致 400 错误)
# ==========================================
orig_getaddrinfo = socket.getaddrinfo


def forced_ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)


socket.getaddrinfo = forced_ipv4_getaddrinfo

# 基础配置
load_dotenv()
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class UnicomDemoDiagnostic:
    def __init__(self):
        # 端口建议：公司 7897，家里 M4 Max 建议 7890
        self.proxy_port = os.getenv('PROXY_PORT', '7897')
        self.proxy_url = f"http://127.0.0.1:{self.proxy_port}"

        # 2. 注入环境变量：覆盖 gRPC 协议，防止 Gemini 插件直连
        for var in ['HTTP_PROXY', 'HTTPS_PROXY', 'grpc_proxy', 'all_proxy']:
            os.environ[var] = self.proxy_url

        print(f"🚀 [2026 联通环境专用] 诊断引擎启动 | 代理端口: {self.proxy_port}")
        print("-" * 60)

    def test_proxy_exit(self):
        """测试基础代理出口"""
        print("🔎 [Step 1] 测试代理出口状态...")
        try:
            res = requests.get('https://api.ip.sb/ip', timeout=15)
            print(f"✅ 代理正常 | 出口 IP: {res.text.strip()}")
            return True
        except Exception as e:
            print(f"❌ 代理连接失败: {e}\n👉 请检查代理软件是否开启。")
            return False

    def test_okx_demo(self):
        """测试 OKX 模拟盘连通性"""
        print("\n🔎 [Step 2] 测试 OKX 模拟盘 (Sandbox)...")
        try:
            # 3. 严格清洗 Key，防止 latin-1 编码导致身份验证失败
            api_key = os.getenv('OKX_DEMO_API_KEY', '').strip()
            secret = os.getenv('OKX_DEMO_SECRET', '').strip()
            password = os.getenv('OKX_DEMO_PASSWORD', '').strip()

            if not api_key:
                print("⚠️ 跳过：未在 .env 中发现 OKX_DEMO_API_KEY")
                return

            exchange = ccxt.okx({
                'apiKey': api_key,
                'secret': secret,
                'password': password,
                'enableRateLimit': True,
                'proxies': {'http': self.proxy_url, 'https': self.proxy_url},
                'verify': False,
                'timeout': 30000
            })

            # 必须调用此方法进入模拟环境，否则会报 50101 错误
            exchange.set_sandbox_mode(True)

            balance = exchange.fetch_balance()
            usdt_total = balance.get('total', {}).get('USDT', 0)
            print(f"✅ OKX 模拟盘连接成功！")
            print(f"💰 虚拟 USDT 总额: {usdt_total}")

        except Exception as e:
            if "50101" in str(e):
                print("❌ OKX 报错: APIKey 与环境不匹配 (Code 50101)")
                print("   👉 提示：请确认 Key 是在 OKX『模拟交易』页面下申请的。")
            else:
                print(f"❌ OKX 测试失败: {e}")

    def test_gemini(self):
        """测试 Gemini 连通性与模型列表"""
        print("\n🔎 [Step 3] 测试 Gemini AI 决策大脑...")
        try:
            api_key = os.getenv('GEMINI_API_KEY', '').strip()
            if not api_key:
                print("⚠️ 跳过：未在 .env 中发现 GEMINI_API_KEY")
                return

            genai.configure(api_key=api_key)

            # 获取 2026 年最新可用模型，避免 404
            print("📡 正在检索可用模型...")
            models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]

            if not models:
                print("❌ 未找到支持生成内容的模型。")
                return

            for m in models: print(f"   - {m}")

            # 自动选择 2.0/2.5 系列进行测试
            target = next((m for m in models if "flash" in m), models[0])
            print(f"📡 尝试与 [{target}] 握手测试...")

            model = genai.GenerativeModel(target)
            response = model.generate_content("Ping")
            print(f"✅ Gemini 响应成功: {response.text.strip()}")

        except Exception as e:
            if "location is not supported" in str(e).lower():
                print("❌ Gemini 报错: 地理位置受限 (400)。")
                print("   👉 提示：请在代理中切换到美国或日本节点，避开香港。")
            else:
                print(f"❌ Gemini 测试失败: {e}")


if __name__ == "__main__":
    diag = UnicomDemoDiagnostic()
    # 修正了之前报错的方法名调用
    if diag.test_proxy_exit():
        diag.test_okx_demo()
        diag.test_gemini()
    print("\n" + "=" * 60)
    print("📢 诊断结束。全部通过后即可开始自动化量化！")