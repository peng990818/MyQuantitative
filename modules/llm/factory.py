import os
import httpx
import warnings

# 🔥 [新增] 在导入 google 库之前屏蔽它的特定警告
warnings.filterwarnings("ignore", message=".*google.generativeai.*")
warnings.filterwarnings("ignore", message=".*Python version.*")

from abc import ABC, abstractmethod
from openai import OpenAI
import google.generativeai as genai
from utils.config_loader import ConfigLoader
from utils.proxy_manager import ProxyManager


# === 1. 定义基类 (接口) ===
class BaseLLM(ABC):
    @abstractmethod
    def generate(self, system_prompt, user_prompt):
        pass


# === 2. DeepSeek 实现 ===
class DeepSeekLLM(BaseLLM):
    def __init__(self, config):
        # 1. 获取兼容的 http_client
        http_client = ProxyManager(config).get_httpx_client()

        # 2. 传入 OpenAI
        self.client = OpenAI(
            api_key=config.get("ai_keys.deepseek"),
            base_url="https://api.deepseek.com",
            http_client=http_client,
            timeout=60.0
        )
        self.model = config.get("ai.model_name", "deepseek-chat")

    def generate(self, system_prompt, user_prompt):
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"❌ DeepSeek Error: {e}")
            return None


# === 3. Gemini 实现 ===
class GeminiLLM(BaseLLM):
    def __init__(self, config):
        api_key = config.get("ai_keys.gemini")
        if not api_key: raise ValueError("Gemini API Key missing")

        # 设置系统代理 (Gemini SDK 特性)
        ProxyManager(config).set_system_proxy()

        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(config.get("ai.model_name", "gemini-2.0-flash"))

    def generate(self, system_prompt, user_prompt):
        try:
            full_prompt = f"{system_prompt}\n\nTask:\n{user_prompt}"
            response = self.model.generate_content(full_prompt)
            return response.text
        except Exception as e:
            print(f"❌ Gemini Error: {e}")
            return None


# === 4. 工厂类 (对外唯一入口) ===
class LLMFactory:
    @staticmethod
    def create_llm():
        cfg = ConfigLoader()
        provider = cfg.get("ai.provider", "deepseek").lower()

        print(f"🧠 [AI Factory] 初始化模型: {provider}")

        if provider == "deepseek":
            return DeepSeekLLM(cfg)
        elif provider == "gemini":
            return GeminiLLM(cfg)
        else:
            # 默认回退
            return DeepSeekLLM(cfg)


if __name__ == "__main__":
    import sys

    # 路径魔法
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

    print("🧠 正在测试 LLMFactory...")
    try:
        llm = LLMFactory.create_llm()
        print(f"✅ 模型实例已创建: {type(llm).__name__}")

        # print("⏳ 正在发送测试请求...")
        # response = llm.generate("System", "Hi")
        # print(f"✅ AI 回复: {response}")

    except Exception as e:
        print(f"❌ 测试失败: {e}")