import os
import json
import re
import httpx
import google.generativeai as genai
from openai import OpenAI
from abc import ABC, abstractmethod
from dotenv import load_dotenv

load_dotenv(override=True)


# ==========================================
# 🛠️ 辅助工具
# ==========================================
def extract_json(text):
    """提取文本中的 JSON 部分"""
    if not text: return None
    # 移除 <think> 标签 (DeepSeek R1 特有)
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    try:
        return json.loads(text)
    except:
        pass
    try:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match: return json.loads(match.group())
    except:
        pass
    return None


# ==========================================
# 🔌 AI 提供商接口 (基类)
# ==========================================
class AIProvider(ABC):
    """所有 AI 模型必须遵守的标准接口"""

    @abstractmethod
    def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        pass


# ==========================================
# 🤖 DeepSeek 实现类 (OpenAI SDK 兼容)
# ==========================================
class DeepSeekProvider(AIProvider):
    def __init__(self):
        api_key = os.getenv("DEEPSEEK_API_KEY")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

        # 🔥 [修改] 智能代理配置 (增强兼容性)
        proxy_port = os.getenv("PROXY_PORT", "")
        http_client = None

        if proxy_port:
            proxy_url = f"http://127.0.0.1:{proxy_port.strip()}"
            print(f"🌍 [DeepSeek] 正在配置代理: {proxy_url}")

            # 🔥 兼容性修复：尝试不同的参数名
            try:
                # 方案 A: 新版 httpx 使用 'proxy' (单数)
                http_client = httpx.Client(proxy=proxy_url)
            except TypeError:
                # 方案 B: 旧版或特定版本使用 'proxies' (复数)
                try:
                    http_client = httpx.Client(proxies=proxy_url)
                except Exception as e:
                    print(f"❌ [DeepSeek] 代理配置失败，尝试字典格式: {e}")
                    # 方案 C: 最稳妥的字典格式
                    http_client = httpx.Client(proxies={
                        "http://": proxy_url,
                        "https://": proxy_url
                    })
        else:
            print("🚀 [DeepSeek] 使用直连模式")

        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
            timeout=60.0
        )
        print(f"🧠 [AI底层] DeepSeek 适配器已加载 (Model: {self.model_name})")

    def generate_text(self, system_prompt, user_prompt):
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                max_tokens=4000
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"❌ DeepSeek 调用失败: {e}")
            raise e


# ==========================================
# 🌟 Gemini 实现类
# ==========================================
class GeminiProvider(AIProvider):
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("❌ 缺少 GEMINI_API_KEY")

        # Gemini SDK 自动读取 HTTP_PROXY/HTTPS_PROXY 环境变量
        proxy_port = os.getenv("PROXY_PORT", "")

        if proxy_port:
            proxy_url = f"http://127.0.0.1:{proxy_port.strip()}"
            os.environ["HTTP_PROXY"] = proxy_url
            os.environ["HTTPS_PROXY"] = proxy_url
            print(f"🌍 [Gemini] 设置系统代理环境变量: {proxy_url}")
        else:
            print("🚀 [Gemini] 使用直连模式")

        genai.configure(api_key=api_key)
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self.model = genai.GenerativeModel(self.model_name)
        print(f"🧠 [AI底层] Gemini 适配器已加载 (Model: {self.model_name})")

    def generate_text(self, system_prompt, user_prompt):
        try:
            full_prompt = f"{system_prompt}\n\nUser Task:\n{user_prompt}"
            response = self.model.generate_content(full_prompt)
            return response.text
        except Exception as e:
            print(f"❌ Gemini 调用失败: {e}")
            raise e


# ==========================================
# 🧠 舆情分析师 (业务层)
# ==========================================
class SentimentAnalyst:
    """
    通用舆情分析师
    """

    def __init__(self):
        self.provider_type = os.getenv("AI_PROVIDER", "GEMINI").upper()

        try:
            if self.provider_type == "DEEPSEEK":
                self.llm = DeepSeekProvider()
            elif self.provider_type == "GEMINI":
                self.llm = GeminiProvider()
            else:
                print(f"⚠️ 未知 Provider: {self.provider_type}，回退到 Gemini")
                self.llm = GeminiProvider()
        except Exception as e:
            print(f"❌ AI 初始化失败: {e}")
            self.llm = None

    def analyze_sentiment(self, symbol, news_text):
        if not self.llm:
            return {"score": 0, "reason": "AI Not Initialized"}

        if not news_text or "No news" in news_text:
            return {"score": 0, "reason": "No significant news"}

        system_prompt = "You are a financial sentiment scorer. Output JSON only."
        user_prompt = f"""
        Analyze the sentiment for asset: {symbol}.

        [News Context]
        {news_text[:1500]} 

        [Task]
        Rate the sentiment from -10 (Extremely Negative/Crash imminent) to +10 (Extremely Positive/Skyrocket).
        0 is Neutral.

        Output JSON strictly:
        {{"score": float, "reason": "Brief explanation"}}
        """

        try:
            content = self.llm.generate_text(system_prompt, user_prompt)
            result = extract_json(content)
            if result:
                result['score'] = float(result.get('score', 0))
                return result
            return {"score": 0, "reason": "JSON Parse Error"}

        except Exception as e:
            print(f"⚠️ 舆情分析运行时错误: {e}")
            return {"score": 0, "reason": "AI Runtime Error"}