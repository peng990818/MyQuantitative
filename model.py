import os
import json
import google.generativeai as genai
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(override=True)


# ==========================================
# 1. 基础接口 (Interface)
# ==========================================
class StrategyInterface:
    """标准策略接口，所有模型必须实现此方法"""

    def analyze(self, market_data):
        raise NotImplementedError


# ==========================================
# 2. 具体模型实现 (Implementations)
# ==========================================
class GeminiStrategy(StrategyInterface):
    """Google Gemini 模型具体实现"""

    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("❌ [配置错误] 未找到 GEMINI_API_KEY")

        # 动态读取版本
        self.model_name = os.getenv("GEMINI_MODEL") or os.getenv("STRATEGY_MODEL") or "gemini-2.5-flash"

        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(self.model_name)
        print(f"🧠 [底层加载] Google Gemini (版本: {self.model_name})")

    def analyze(self, market_data):
        prompt = self._build_prompt(market_data)
        try:
            response = self.model.generate_content(prompt)
            return self._parse_response(response.text)
        except Exception as e:
            print(f"⚠️ Gemini 思考出错: {e}")
            return {"action": "HOLD", "reason": "Gemini Error"}

    def _build_prompt(self, market_data):
        return f"""
        Analyze BTC/USDT data.
        Price: {market_data['current_price']}
        RSI: {market_data['rsi']}
        MACD: {market_data['macd']}
        Bollinger: {market_data['bollinger']['upper']} / {market_data['bollinger']['lower']}

        Output JSON strictly:
        {{"action": "BUY" or "SELL" or "HOLD", "reason": "Reason < 15 words"}}
        """

    def _parse_response(self, text):
        try:
            clean_text = text.replace('```json', '').replace('```', '').strip()
            return json.loads(clean_text)
        except:
            return {"action": "HOLD", "reason": "Parse Error"}


class DeepSeekStrategy(StrategyInterface):
    """DeepSeek 模型 (支持 V3 和 R1 深度思考)"""

    def __init__(self):
        api_key = os.getenv("DEEPSEEK_API_KEY")
        base_url = os.getenv("DEEPSEEK_BASE_URL")

        if not api_key or not base_url:
            raise ValueError("❌ [配置错误] DeepSeek 配置缺失")

        self.model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

        # [修改 1] 设置更长的超时时间 (60秒)，给 R1 思考的时间
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=60.0
        )
        print(f"🧠 [底层加载] DeepSeek (版本: {self.model_name})")

    def analyze(self, market_data):
        prompt = f"""
        Analyze BTC/USDT technical indicators.
        Current Price: {market_data['current_price']}
        RSI (14): {market_data['rsi']}
        MACD: {market_data['macd']}
        Bollinger Bands: Upper {market_data['bollinger']['upper']}, Lower {market_data['bollinger']['lower']}

        Logic:
        1. RSI > 70 is overbought (Sell risk), RSI < 30 is oversold (Buy opp).
        2. Price breaking Upper Band suggests pullback.

        Output JSON strictly (no markdown):
        {{"action": "BUY" or "SELL" or "HOLD", "reason": "Brief reason"}}
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "You are a professional crypto trader. Output JSON only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                # [修改 2] R1 需要更大的 token 空间来存放思考过程和结果
                max_tokens=2000
            )

            message = response.choices[0].message

            # === 尝试捕获深度思考 ===
            # 注意：官方 SDK 有时把 reasoning 放在 extra_fields 里
            reasoning = getattr(message, 'reasoning_content', None)
            # 如果上面拿不到，尝试从 dict 里拿 (防备 SDK 版本差异)
            if not reasoning and hasattr(message, 'model_dump'):
                reasoning = message.model_dump().get('reasoning_content')

            if reasoning:
                print("\n" + "=" * 20 + " 🤔 深度思考中 " + "=" * 20)
                print(f"\033[90m{reasoning.strip()}\033[0m")
                print("=" * 55 + "\n")

            content = message.content
            # 清洗一下返回内容，防止 R1 啰嗦
            clean_text = content.replace('```json', '').replace('```', '').strip()

            # 这里的 log 可以帮你看到它到底回复了什么（有时候它回了非 JSON 格式的话）
            # print(f"🔍 R1 原始回复: {clean_text}")

            return json.loads(clean_text)

        except Exception as e:
            # [修改 3] 打印最关键的错误详情！
            print(f"⚠️ DeepSeek 详细报错: {str(e)}")
            return {"action": "HOLD", "reason": f"DeepSeek Error: {str(e)[:20]}..."}


# ==========================================
# 3. 策略工厂与通用入口 (Factory & Entry)
# ==========================================
def ModelFactory():
    """根据 .env 配置，生产出对应的模型实例"""
    provider = os.getenv("AI_PROVIDER", "GEMINI").upper()

    if provider == "DEEPSEEK":
        return DeepSeekStrategy()
    elif provider == "GEMINI":
        return GeminiStrategy()
    else:
        print(f"⚠️ 未知提供商 {provider}, 默认回退至 Gemini")
        return GeminiStrategy()


class AIStrategy:
    """
    【通用 AI 策略入口】
    Main 程序只和这个类交互，不用关心底层是 Gemini 还是 DeepSeek。
    """

    def __init__(self):
        # 初始化时，通过工厂决定实例化哪一个大脑
        self.brain = ModelFactory()

    def analyze(self, market_data):
        # 委托给具体的大脑去分析
        return self.brain.analyze(market_data)