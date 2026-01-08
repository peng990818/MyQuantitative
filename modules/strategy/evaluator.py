from utils.config_loader import ConfigLoader
from utils.logger import logger


class StrategyEvaluator:
    def __init__(self):
        self.cfg = ConfigLoader()

        # 1. 读取权重配置 (默认 4:4:2)
        # Technical: 技术指标得分
        # Sentiment: AI舆情得分
        # Trend: 趋势强度得分
        self.weights = self.cfg.get("scoring.weights", {
            "technical": 0.4,
            "sentiment": 0.4,
            "trend": 0.2
        })

        # 2. 读取阈值配置 (0-100分制)
        # 🔥 [修正] 这里的默认值也要改成 75.0 和 30.0，保持一致性
        self.thresholds = self.cfg.get("scoring.thresholds", {
            "buy": 75.0,
            "sell": 30.0
        })

        logger.info(
            f"⚖️ [Strategy] 策略引擎已加载 (百分制) | 权重: Tech={self.weights.get('technical')} Sentiment={self.weights.get('sentiment')}")

    def evaluate(self, tech_score, sentiment_score, trend_score):
        """
        全系统统一使用 0-100 分制
        :param tech_score: 0-100
        :param sentiment_score: -10 到 +10
        :param trend_score: 0-100
        """

        # === Step 1: 归一化 (全部映射到 0-100) ===

        # A. 技术分 (0-100)
        norm_tech = float(tech_score)

        # B. 舆情分 (-10 ~ +10  ==>  0 ~ 100)
        # 公式: (分数 + 10) * 5
        # 示例: -10 -> 0, 0 -> 50, +10 -> 100
        norm_sentiment = (float(sentiment_score) + 10) * 5
        # 钳位限制，防止 AI 给出夸张分数导致溢出
        norm_sentiment = max(0, min(100, norm_sentiment))

        # C. 趋势分 (0-100)
        norm_trend = float(trend_score)

        # === Step 2: 加权计算 (保持 0-100) ===
        w_tech = self.weights.get('technical', 0.4)
        w_sent = self.weights.get('sentiment', 0.4)
        w_trend = self.weights.get('trend', 0.2)

        final_score = (
                norm_tech * w_tech +
                norm_sentiment * w_sent +
                norm_trend * w_trend
        )

        # 🔥 [确认] 保留一位小数，例如 78.5
        final_score = round(final_score, 1)

        # === Step 3: 生成信号 (对比 0-100 的阈值) ===
        action = "HOLD"
        reason_code = "WAIT"

        # 这里的 thresholds['buy'] 已经是 75.0 了
        if final_score >= self.thresholds['buy']:
            action = "BUY"
            reason_code = "SIGNAL_BUY"
        elif final_score <= self.thresholds['sell']:
            action = "SELL"
            reason_code = "SIGNAL_SELL"

        return {
            "action": action,
            "final_score": final_score,  # range: 0-100
            "reason": reason_code,
            "details": {
                "raw_tech": tech_score,
                "raw_sentiment": sentiment_score,
                "raw_trend": trend_score,
                # 方便调试查看具体贡献
                "breakdown": f"Tech({norm_tech:.0f}*{w_tech}) + Sent({norm_sentiment:.0f}*{w_sent}) + Trend({norm_trend:.0f}*{w_trend})"
            }
        }


# === 单元测试 (Unit Test) ===
if __name__ == "__main__":
    import sys, os

    # 路径魔法
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

    print("🧪 正在测试策略评估 (0-100分制)...")
    evaluator = StrategyEvaluator()

    # 场景 A: 也就是你刚才疑惑的场景
    # 技术 50 (平庸), 舆情 +10 (极好), 趋势 50 (平庸)
    # 预期计算: (50*0.4) + (100*0.4) + (50*0.2) = 20 + 40 + 10 = 70 分
    # 70 < 75 (Buy线)，所以结果应为 HOLD
    print("\n--- 测试场景 A: 消息面爆炸，技术面平庸 ---")
    res = evaluator.evaluate(tech_score=50, sentiment_score=10, trend_score=50)
    print(f"输入: Tech=50, Sent=+10, Trend=50")
    print(f"输出: {res['action']} | 得分: {res['final_score']} (预期 70.0)")
    print(f"解释: {res['details']['breakdown']}")

    # 场景 B: 全面利好
    print("\n--- 测试场景 B: 全面爆发 ---")
    res = evaluator.evaluate(tech_score=85, sentiment_score=8, trend_score=90)
    print(f"输入: Tech=85, Sent=+8(即90分), Trend=90")
    print(f"输出: {res['action']} | 得分: {res['final_score']} (预期 > 75.0)")