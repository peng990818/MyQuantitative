class MultiFactorEngine:
    def __init__(self):
        # 权重配置
        self.W_TECH = 0.7
        self.W_NEWS = 0.3

        self.W_TREND = 0.4
        self.W_MOMENTUM = 0.3
        self.W_VOLUME = 0.2
        self.W_VOLATILITY = 0.1

    def calculate_technical_score(self, data):
        score_trend = self._score_trend(data)
        score_momentum = self._score_momentum(data)
        score_volume = self._score_volume(data)
        score_volatility = self._score_volatility(data)

        total_tech_score = (
                (score_trend * self.W_TREND) +
                (score_momentum * self.W_MOMENTUM) +
                (score_volume * self.W_VOLUME) +
                (score_volatility * self.W_VOLATILITY)
        )

        sub_scores = {
            "Trend": score_trend,
            "Momentum": score_momentum,
            "Volume": score_volume,
            "Volatility": score_volatility
        }

        reasons = []
        if score_trend > 40:
            reasons.append(f"Trend Strong (+{score_trend:.0f})")
        elif score_trend < -40:
            reasons.append(f"Trend Weak ({score_trend:.0f})")

        if score_volume > 40: reasons.append(f"Money Inflow (+{score_volume:.0f})")
        if score_volatility > 50: reasons.append("Volatility Breakout")

        return total_tech_score, sub_scores, reasons

    def _score_trend(self, data):
        """趋势分校准：满分 100"""
        s = 0
        price = data['current_price']
        t = data['trend']

        # 1. 价格站上 EMA99 (长期趋势) -> 40分 (原30)
        if price > t['ema_long']:
            s += 40
        else:
            s -= 40

        # 2. 短期均线金叉 (短期趋势) -> 20分 (原10)
        if t['ema_short'] > t['ema_long']:
            s += 20
        else:
            s -= 20

        # 3. ADX 趋势强度 -> 40分 (原20)
        # 只有趋势强的时候，上面两个信号才有效，否则打折
        if t['adx'] > 25:
            if t['di_plus'] > t['di_minus']:
                s += 40
            else:
                s -= 40
        else:
            s = s * 0.5  # 震荡市分数减半

        return max(-100, min(100, s))

    def _score_momentum(self, data):
        """动量分校准：满分 100"""
        s = 0
        m = data['momentum']

        # 1. RSI -> 30分
        if m['rsi'] < 30:
            s += 30
        elif m['rsi'] > 70:
            s -= 30

        # 2. CCI -> 30分 (原20)
        if m['cci'] > 100:
            s += 30
        elif m['cci'] < -100:
            s -= 30

        # 3. KDJ -> 20分 (原10)
        if m['kdj_k'] > m['kdj_d']:
            s += 20
        else:
            s -= 20

        # 4. WillR -> 20分
        if m['willr'] < -80:
            s += 20
        elif m['willr'] > -20:
            s -= 20

        return max(-100, min(100, s))

    def _score_volume(self, data):
        """资金分校准：满分 100"""
        s = 0
        v = data['volume']

        # 1. MFI -> 60分 (原40) - MFI非常重要
        if v['mfi'] < 20:
            s += 60
        elif v['mfi'] > 80:
            s -= 60

        # 2. CMF -> 40分 (原30)
        if v['cmf'] > 0.1:
            s += 40
        elif v['cmf'] < -0.1:
            s -= 40

        return max(-100, min(100, s))

    def _score_volatility(self, data):
        """波动分校准：满分 100"""
        s = 0
        price = data['current_price']
        bb = data['volatility']

        # 突破直接给 100 分 (原50)
        # 因为波动率突破通常是二元状态：要么突破了，要么没突破
        if price > bb['bb_upper']:
            s += 100
        elif price < bb['bb_lower']:
            s -= 100

        return s

    def fuse_signals(self, tech_score, tech_sub_scores, sentiment_result):
        news_raw_score = sentiment_result.get('score', 0)
        news_score_normalized = news_raw_score * 10

        final_score = (tech_score * self.W_TECH) + (news_score_normalized * self.W_NEWS)

        action = "HOLD"

        # === 🔥 [参数微调：稳健模式] 🔥 ===
        # 核心思路：提高门槛，减少开单频率，提升胜率。

        # 1. 强力买入：门槛从 50 提至 60
        # 只有 趋势(+40) + 资金(+60) 同时爆发才可能达到这个分
        if final_score >= 60:
            action = "STRONG_BUY"

        # 2. 普通买入：门槛从 30 提至 40
        # 过滤掉那些“看起来还行但其实很勉强”的机会
        elif 40 <= final_score < 60:
            # 必须要求舆情不是负面，防止在利空消息下接飞刀
            if news_raw_score >= 0:
                action = "BUY"

        # 3. 卖出/止损：门槛从 -30 降至 -40
        # 给行情多一点呼吸空间，不要稍微一回调就吓跑了
        elif final_score <= -40:
            action = "SELL"

        return {
            "final_score": final_score,
            "action": action,
            "details": {
                "tech_score": tech_score,
                "tech_breakdown": tech_sub_scores,
                "news_score": news_score_normalized,
                "ai_reason": sentiment_result.get('reason', 'N/A')
            }
        }