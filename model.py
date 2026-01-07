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
# 🤖 DeepSeek 实现类
# ==========================================
class DeepSeekProvider(AIProvider):
    def __init__(self):
        api_key = os.getenv("DEEPSEEK_API_KEY")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

        # 代理配置
        proxy_port = os.getenv("PROXY_PORT")
        http_client = None
        if proxy_port:
            proxy_url = f"http://127.0.0.1:{proxy_port.strip()}"
            try:
                http_client = httpx.Client(proxy=proxy_url)
            except:
                http_client = httpx.Client(proxies=proxy_url)

        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
            timeout=60.0
        )
        print(f"🧠 [AI底层] DeepSeek 适配器已加载 (Model: {self.model_name})")

    def generate_text(self, system_prompt, user_prompt):
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


# ==========================================
# 🌟 Gemini 实现类
# ==========================================
class GeminiProvider(AIProvider):
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("❌ 缺少 GEMINI_API_KEY")

        # Gemini 的代理通常通过环境变量 HTTPS_PROXY 设置，SDK 会自动读取
        proxy_port = os.getenv("PROXY_PORT")
        if proxy_port:
            os.environ["HTTP_PROXY"] = f"http://127.0.0.1:{proxy_port}"
            os.environ["HTTPS_PROXY"] = f"http://127.0.0.1:{proxy_port}"

        genai.configure(api_key=api_key)
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.model = genai.GenerativeModel(self.model_name)
        print(f"🧠 [AI底层] Gemini 适配器已加载 (Model: {self.model_name})")

    def generate_text(self, system_prompt, user_prompt):
        # Gemini API 通常把 system prompt 拼在前面或者使用新的 config，这里简化处理
        full_prompt = f"{system_prompt}\n\nUser Task:\n{user_prompt}"
        response = self.model.generate_content(full_prompt)
        return response.text


# ==========================================
# 🧠 舆情分析师 (业务层)
# ==========================================
class SentimentAnalyst:
    """
    通用舆情分析师
    只负责业务逻辑（Prompt工程、JSON解析），不负责底层 API 调用。
    """

    def __init__(self):
        # 工厂模式：根据配置选择具体实现
        self.provider_type = os.getenv("AI_PROVIDER", "GEMINI").upper()

        try:
            if self.provider_type == "DEEPSEEK":
                self.llm = DeepSeekProvider()
            elif self.provider_type == "GEMINI":
                self.llm = GeminiProvider()
            else:
                # 默认回退
                print(f"⚠️ 未知 Provider: {self.provider_type}，回退到 Gemini")
                self.llm = GeminiProvider()
        except Exception as e:
            print(f"❌ AI 初始化失败: {e}")
            self.llm = None

    def analyze_sentiment(self, symbol, news_text):
        """
        输入：标的名称 (如 'BTC'), 新闻文本
        输出：情感分数 (-10 到 +10)
        """
        if not self.llm:
            return {"score": 0, "reason": "AI Not Initialized"}

        if not news_text or "No news" in news_text:
            return {"score": 0, "reason": "No significant news"}

        # 1. 构造 Prompt
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

        # 2. 调用 AI (多态调用)
        try:
            content = self.llm.generate_text(system_prompt, user_prompt)

            # 3. 解析结果
            result = extract_json(content)
            if result:
                result['score'] = float(result.get('score', 0))
                return result
            return {"score": 0, "reason": "JSON Parse Error"}

        except Exception as e:
            print(f"⚠️ 舆情分析运行时错误: {e}")
            return {"score": 0, "reason": "AI Runtime Error"}