import os
import json
import re
import httpx
import google.generativeai as genai
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(override=True)


# ==========================================
# 1. 基础接口
# ==========================================
class StrategyInterface:
    def analyze(self, market_data, news_context=""):
        raise NotImplementedError


# ==========================================
# 2. 辅助工具：强制提取 JSON
# ==========================================
def extract_json(text):
    """
    强制提取 JSON，兼容 DeepSeek R1 的 <think> 标签
    """
    if not text:
        return None

    # 1. 尝试清理 <think>...</think> 标签 (DeepSeek R1 特有)
    # R1 经常把思考过程放在 <think> 标签里，我们需要去掉它，只留后面的 JSON
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

    try:
        # 2. 尝试直接解析
        return json.loads(text)
    except:
        pass

    try:
        # 3. 清理 markdown ```json ... ```
        clean_text = text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_text)
    except:
        pass

    try:
        # 4. 正则暴力搜索 {...}
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            json_str = match.group()
            return json.loads(json_str)
    except:
        pass

    print(f"❌ [JSON解析失败] AI 最终文本:\n{text[:500]}...")  # 只打印前500字
    return None


# ==========================================
# 3. Gemini 实现
# ==========================================
class GeminiProvider(StrategyInterface):
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("未找到 GEMINI_API_KEY")

        self.model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(self.model_name)
        print(f"🧠 [加载模型] Google Gemini ({self.model_name})")

    def analyze(self, market_data, news_context=""):
        prompt = self._build_prompt(market_data, news_context)
        try:
            response = self.model.generate_content(prompt)
            result = extract_json(response.text)
            return result if result else {"action": "HOLD", "reason": "Gemini Parse Error"}
        except Exception as e:
            print(f"⚠️ Gemini 思考出错: {e}")
            return {"action": "HOLD", "reason": "Gemini Error"}

    def _build_prompt(self, market_data, news_context):
        price = market_data['current_price']
        ema_long = market_data['ema']['long']
        trend = "BULLISH" if price > ema_long else "BEARISH"

        return f"""
        Act as a professional crypto quantitative analyst. 
        Combine Technical Analysis (Data) with Sentiment Analysis (News) to make a trading decision for BTC/USDT.

        === 1. Market Sentiment (News) ===
        {news_context if news_context else "No significant news."}

        === 2. Technical Context ===
        - Price: {price}
        - Trend: {trend} (Price vs EMA99)
        - ATR: {market_data['atr']}
        - OBV: {market_data['obv']}

        === 3. Indicators ===
        - RSI: {market_data['rsi']}
        - MACD: {market_data['macd']} (Signal: {market_data['macd_signal']})
        - Bollinger: Up {market_data['bollinger']['upper']} / Low {market_data['bollinger']['lower']}

        === 4. Decision Logic ===
        - BUY: Strong Uptrend + Good News + RSI < 70.
        - SELL: Downtrend + Bad News OR Indicator breakdown.
        - HOLD: Conflicting signals.

        Output JSON strictly:
        {{"action": "BUY" or "SELL" or "HOLD", "reason": "Reason < 20 words"}}
        """


# ==========================================
# 4. DeepSeek 实现 (增强版)
# ==========================================
class DeepSeekProvider(StrategyInterface):
    def __init__(self):
        api_key = os.getenv("DEEPSEEK_API_KEY")
        base_url = os.getenv("DEEPSEEK_BASE_URL")

        if not api_key:
            self.client = None
            print("⚠️ 未配置 DeepSeek Key")
        else:
            self.model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

            # 代理配置 (httpx 兼容性修复)
            proxy_port = os.getenv("PROXY_PORT")
            http_client = None

            if proxy_port:
                proxy_url = f"http://127.0.0.1:{proxy_port.strip()}"
                try:
                    http_client = httpx.Client(proxy=proxy_url)
                except TypeError:
                    http_client = httpx.Client(proxies=proxy_url)
                print(f"🌍 [DeepSeek] 使用代理通道: {proxy_url}")

            self.client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=90.0,  # 增加超时时间，R1 思考很慢
                http_client=http_client
            )
            print(f"🧠 [加载模型] DeepSeek ({self.model_name})")

    def analyze(self, market_data, news_context=""):
        if not self.client:
            return {"action": "HOLD", "reason": "DeepSeek Not Configured"}

        # Prompt
        prompt = f"""
        Analyze BTC/USDT.
        News: {news_context[:200]}...
        Price: {market_data['current_price']}
        Trend (EMA99): {market_data['ema']['long']}
        RSI: {market_data['rsi']}
        MACD: {market_data['macd']}
        ATR: {market_data['atr']}

        Output JSON strictly:
        {{"action": "BUY" or "SELL" or "HOLD", "reason": "Brief reason"}}
        """

        try:
            # 🔥 [关键修改] 增加 max_tokens 防止 R1 思考被截断
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "You are a trading bot. Output JSON only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=4000  # 从 500 增加到 4000，给 R1 留足思考空间
            )

            message = response.choices[0].message
            content = message.content

            # === 🔍 深度调试：如果内容为空，打印原始对象 ===
            if not content:
                print(f"⚠️ [DeepSeek] 返回内容为空！")
                # 尝试打印 reasoning_content (如果是 R1)
                if hasattr(message, 'reasoning_content'):
                    print(f"🤔 思考过程(Reasoning): {message.reasoning_content[:100]}...")
                return {"action": "HOLD", "reason": "DeepSeek Empty Response"}

            # 提取 JSON
            result = extract_json(content)

            if result:
                return result
            else:
                return {"action": "HOLD", "reason": "DeepSeek JSON Invalid"}

        except Exception as e:
            print(f"⚠️ DeepSeek 运行报错: {str(e)}")
            return {"action": "HOLD", "reason": "DeepSeek Error"}


# ==========================================
# 5. 策略工厂
# ==========================================
class AIStrategy:
    def __init__(self):
        provider = os.getenv("AI_PROVIDER", "GEMINI").upper()
        if provider == "DEEPSEEK":
            self.brain = DeepSeekProvider()
        else:
            self.brain = GeminiProvider()

    def analyze(self, market_data, news_context=""):
        return self.brain.analyze(market_data, news_context)