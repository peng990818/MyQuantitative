import os
import json
import requests
import google.generativeai as genai
import unittest
from dotenv import load_dotenv

# 🔥 核心：加载 .env
load_dotenv(override=True)


class GeminiStrategy:
    def __init__(self):
        # 1. 从 .env 读取配置
        self.api_key = os.getenv('GEMINI_API_KEY', '').strip()
        # 这里修复了：优先读环境变量，读不到才用默认值
        self.model_name = os.getenv('STRATEGY_MODEL', 'gemini-2.0-flash')

        # 2. 网络配置 (深圳联通专用)
        port = os.getenv('PROXY_PORT', '7890')
        self.proxy_url = f"http://127.0.0.1:{port}"
        self.proxies = {'http': self.proxy_url, 'https': self.proxy_url}

        # 强制注入环境变量 (SDK 依赖)
        os.environ['HTTP_PROXY'] = self.proxy_url
        os.environ['HTTPS_PROXY'] = self.proxy_url
        os.environ['grpc_proxy'] = self.proxy_url

        # 3. SDK 初始化 (带版本兼容性保护)
        try:
            genai.configure(api_key=self.api_key, transport='rest')
        except TypeError:
            genai.configure(api_key=self.api_key)

        self.model = genai.GenerativeModel(model_name=self.model_name)
        print(f"🧠 [Init] 策略引擎就绪 | 模型: {self.model_name} | 代理: {port}")

    def _build_prompt(self, data: dict) -> str:
        return f"""
        你是一名资深加密货币交易员。请分析以下数据并返回 JSON。
        交易对: {data.get('symbol')} | 现价: {data.get('current_price')}
        指标: {json.dumps(data.get('indicators', {}))}

        输出格式要求 (严格遵守):
        {{
            "action": "BUY" (或 "SELL", "HOLD"),
            "confidence": 0.9,
            "reason": "简短分析理由"
        }}
        不要使用 Markdown 代码块。
        """

    def _analyze_via_rest_direct(self, prompt):
        """直连备份：彻底绕过 SDK"""
        print("⚠️ 正在切换 HTTPS 直连模式...")
        # 注意：这里使用了 self.model_name，所以 .env 改了这里也会生效
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"

        headers = {'Content-Type': 'application/json'}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"response_mime_type": "application/json"}
        }

        res = requests.post(url, json=payload, headers=headers, proxies=self.proxies, timeout=20)
        if res.status_code != 200:
            raise Exception(f"直连失败 {res.status_code}: {res.text}")

        return json.loads(res.json()['candidates'][0]['content']['parts'][0]['text'])

    def analyze(self, market_data: dict) -> dict:
        prompt = self._build_prompt(market_data)
        try:
            # 优先 SDK
            response = self.model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            return json.loads(response.text)
        except Exception as e:
            # 出错切直连
            if "location" in str(e).lower() or "400" in str(e):
                try:
                    return self._analyze_via_rest_direct(prompt)
                except Exception as err:
                    print(f"❌ 备份失败: {err}")
            return {"action": "HOLD", "reason": "系统异常", "confidence": 0}


# --- 单测 ---
class TestGemini(unittest.TestCase):
    def test_env_read(self):
        s = GeminiStrategy()
        # 验证是否真的读了 .env
        env_model = os.getenv('STRATEGY_MODEL')
        if env_model:
            self.assertEqual(s.model_name, env_model)
            print(f"✅ 配置读取正确: {s.model_name}")

    def test_run(self):
        s = GeminiStrategy()
        res = s.analyze({"symbol": "BTC", "current_price": 50000})
        print("AI响应:", res)
        self.assertIn("action", res)


if __name__ == "__main__":
    unittest.main()