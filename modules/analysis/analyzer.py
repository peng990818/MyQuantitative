import json
import re
import sys
import os
from datetime import datetime
from utils.logger import logger

# === 路径黑魔法 ===
# 让我们在直接运行此文件时，也能找到项目根目录
if __name__ == "__main__":
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 尝试导入工厂类 (根据你的截图目录结构调整)
try:
    from modules.llm.factory import LLMFactory
except ImportError:
    # 兼容性导入：如果上面的路径不对，尝试从 ai 目录导入
    try:
        from modules.ai.factory import LLMFactory
    except ImportError:
        print("❌ 无法找到 LLMFactory，请检查 modules/llm/factory.py 是否存在")
        sys.exit(1)


class MarketRegimeAnalyzer:
    def __init__(self):
        # 初始化 LLM (DeepSeek / Gemini)
        self.llm = LLMFactory.create_llm()

    def analyze(self, symbol, current_price, indicators, news_list):
        """
        核心方法：传入数据，返回市场状态
        :param current_price: float
        :param indicators: dict {'ema_trend': 'UP', 'rsi': 60...}
        :param news_list: list [str] 最近 24h 新闻标题
        """

        # 1. 如果没有新闻，直接降级为震荡 (防止幻觉)
        if not news_list:
            logger.warning("⚠️ 无新闻输入，AI 默认判定为震荡")
            return self._default_result("无新闻数据")

        # 2. 构建 Prompt
        system_prompt, user_prompt = self._build_prompts(symbol, current_price, indicators, news_list)

        # 3. 调用 AI
        try:
            # logger.info("🧠 AI 正在思考市场状态...")
            raw_response = self.llm.generate(system_prompt, user_prompt)

            # 4. 解析结果 (清洗 Markdown 标记)
            result = self._parse_json(raw_response)

            # 5. 安全校验
            valid_regimes = ['BULL_TREND', 'BEAR_CRASH', 'SHOCK_SIDEWAYS']
            if result.get('regime') not in valid_regimes:
                logger.warning(f"⚠️ AI 返回了非法状态: {result.get('regime')}，强制转为 SHOCK")
                result['regime'] = 'SHOCK_SIDEWAYS'

            return result

        except Exception as e:
            logger.error(f"❌ AI 分析失败: {e}")
            return self._default_result(f"AI 调用错误: {str(e)}")

    def _build_prompts(self, symbol, price, indicators, news):
        """
        构造 Prompt，加入标的身份信息
        """

        # 1. 简单的资产画像注入 (Prompt Engineering)
        # 根据标的名称，给 AI 一些背景提示，激活它的先验知识
        asset_context = ""
        if "BTC" in symbol:
            asset_context = "(属性: 数字黄金, 避险/风险双重属性, 市场风向标)"
        elif "ETH" in symbol:
            asset_context = "(属性: 智能合约平台, 强关联 DeFi/NFT 生态, 波动率略高于 BTC)"
        elif "SOL" in symbol:
            asset_context = "(属性: 高性能公链, 高波动, 强关联 Meme 生态)"

        news_str = "\n".join([f"- {n}" for n in news])

        system_prompt = f"""
        你是一个严谨的加密货币量化交易决策系统。
        你当前正在分析的标的是：【{symbol}】 {asset_context}。

        请遵循以下逻辑：
        1. 【相关性过滤】：在阅读新闻时，重点关注与 {symbol} 直接相关，或宏观（美联储/监管）相关的新闻。忽略无关币种的新闻。
        2. 【性格匹配】：{symbol} 的波动率特性应纳入考量。
        3. 【震荡常态】：除非有针对 {symbol} 的明确驱动力，否则默认震荡。

        必须返回纯 JSON 格式。
        """

        user_prompt = f"""
        【当前市场数据 ({symbol})】
        - 价格: {price}
        - 技术形态: {indicators}

        【最近 24h 新闻流】
        {news_str}

        请基于 {symbol} 的特性进行分析并输出 JSON。
        """
        return system_prompt, user_prompt

    def _parse_json(self, raw_text):
        """清洗 AI 返回的 Markdown json 格式"""
        if not raw_text:
            return self._default_result("空响应")

        # 暴力清洗：有时候 AI 会返回 ```json ... ```，有时候会返回 ``` ... ```
        text = raw_text.strip()
        # 移除 ```json
        text = re.sub(r"^```json", "", text, flags=re.MULTILINE)
        # 移除 ```
        text = re.sub(r"^```", "", text, flags=re.MULTILINE)
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.error(f"❌ JSON 解析失败，原始文本: {raw_text}")
            return self._default_result("JSON 解析失败")

    def _default_result(self, reason):
        return {
            "regime": "SHOCK_SIDEWAYS",
            "confidence": 0,
            "reasoning": f"默认降级: {reason}"
        }


# ==========================================
# 🔥 单元测试入口 (直接运行此文件即可测试)
# ==========================================
if __name__ == "__main__":
    print("\n🧪 正在启动 MarketRegimeAnalyzer 单元测试...\n")

    # 实例化 (会自动读取 config.yaml)
    try:
        analyzer = MarketRegimeAnalyzer()
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        sys.exit(1)

    # --- 测试用例 1: 复杂震荡市 ---
    print("--------------------------------------------------")
    print("CASE 1: 复杂震荡 (多空消息打架)")
    res1 = analyzer.analyze(
        current_price=95000,
        indicators={'trend': 'flat', 'rsi': 50},
        news_list=[
            "美联储会议纪要显示降息可能推迟到年底",  # 利空
            "MicroStrategy 再次买入 1000 枚比特币",  # 利好
            "某交易所发生小规模被盗事件",  # 小利空
            "以太坊网络活跃度上升"  # 中性
        ]
    )
    print(f"🤖 AI 判定: {res1}")

    # --- 测试用例 2: 疯牛启动 ---
    print("\n--------------------------------------------------")
    print("CASE 2: 疯牛启动 (重大利好)")
    res2 = analyzer.analyze(
        current_price=98000,
        indicators={'trend': 'bullish', 'ema_slope': 'high', 'rsi': 65},
        news_list=[
            "突发：SEC 正式批准所有比特币现货 ETF 申请",
            "贝莱德 CEO：比特币是数字黄金",
            "Google 宣布将比特币整合进支付系统"
        ]
    )
    print(f"🤖 AI 判定: {res2}")

    # --- 测试用例 3: 垃圾时间 ---
    print("\n--------------------------------------------------")
    print("CASE 3: 垃圾时间 (无有效信息)")
    res3 = analyzer.analyze(
        current_price=94000,
        indicators={'trend': 'bearish', 'rsi': 40},
        news_list=[
            "某 KOL 预测比特币年底十万",
            "昨天行情的简单回顾",
            "社区讨论激增",
        ]
    )
    print(f"🤖 AI 判定: {res3}")
    print("--------------------------------------------------\n")