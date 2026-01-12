import pandas as pd
import os
import random
from datetime import datetime, timedelta


def generate_realistic_regime():
    os.makedirs('data', exist_ok=True)
    file_path = 'data/ai_regime.csv'

    print(f"🛠️ 正在生成【拟真版】AI 剧本 (包含滞后、噪音和误判)...")

    # ==========================================
    # 1. 定义"绝对真实"的历史阶段 (基准真相)
    # ==========================================
    true_periods = [
        # --- 2022 (熊) ---
        ("2022-01-01", "2022-03-31", "BEAR_CRASH"),
        ("2022-04-01", "2022-05-04", "SHOCK_SIDEWAYS"),  # 暴雷前的宁静
        ("2022-05-05", "2022-06-30", "BEAR_CRASH"),  # LUNA 暴雷
        ("2022-07-01", "2022-11-05", "SHOCK_SIDEWAYS"),
        ("2022-11-06", "2022-12-31", "BEAR_CRASH"),  # FTX 暴雷

        # --- 2023 (牛/震) ---
        ("2023-01-01", "2023-02-28", "BULL_TREND"),  # 小阳春
        ("2023-03-01", "2023-09-30", "SHOCK_SIDEWAYS"),  # 漫长的猴市
        ("2023-10-01", "2023-12-31", "BULL_TREND"),  # ETF 预期

        # --- 2025-2026 (你的测试段 - 设为阴跌) ---
        ("2025-09-01", "2026-03-01", "BEAR_CRASH"),
    ]

    # ==========================================
    # 2. 模拟 AI 的"缺陷"逻辑
    # ==========================================
    def simulate_ai_perception(true_regime, day_count_in_trend):
        """
        根据真实状态，模拟 AI 的判断 (加入噪音)
        """
        rand = random.random()

        # 场景 A: 真实是牛市
        if true_regime == "BULL_TREND":
            # 1. 滞后: 牛市刚开始的前 3 天，AI 不敢信，判为震荡
            if day_count_in_trend < 3:
                return "SHOCK_SIDEWAYS"

            # 2. 噪音: 15% 的概率因为利空新闻，暂时看空或震荡 (洗盘)
            if rand < 0.15:
                return "SHOCK_SIDEWAYS"

            return "BULL_TREND"

        # 场景 B: 真实是熊市
        elif true_regime == "BEAR_CRASH":
            # 1. 滞后: 暴跌刚开始的前 2 天，AI 还在懵逼，判为震荡
            if day_count_in_trend < 2:
                return "SHOCK_SIDEWAYS"

            # 2. 噪音: 10% 的概率因为死猫跳，暂时看震荡
            if rand < 0.10:
                return "SHOCK_SIDEWAYS"

            return "BEAR_CRASH"

        # 场景 C: 真实是震荡
        elif true_regime == "SHOCK_SIDEWAYS":
            # 误判: 震荡市里最容易骗炮
            # 10% 概率看多 (诱多)，10% 概率看空 (诱空)
            if rand < 0.10:
                return "BULL_TREND"  # 假突破
            elif rand > 0.90:
                return "BEAR_CRASH"  # 假跌破

            return "SHOCK_SIDEWAYS"

    # ==========================================
    # 3. 生成数据
    # ==========================================
    all_data = []

    # 转换基准真相为查找表
    base_map = {}
    for r_start, r_end, status in true_periods:
        s = datetime.strptime(r_start, "%Y-%m-%d")
        e = datetime.strptime(r_end, "%Y-%m-%d")
        temp = s
        while temp <= e:
            base_map[temp] = status
            temp += timedelta(days=1)

    current_date = datetime(2021, 1, 1)
    end_date = datetime(2026, 12, 31)

    # 记录当前趋势维持了几天 (用于计算滞后)
    trend_counter = 0
    last_true_regime = None

    while current_date <= end_date:
        # 1. 获取上帝视角的真实状态
        true_regime = base_map.get(current_date, "SHOCK_SIDEWAYS")

        # 2. 更新计数器
        if true_regime != last_true_regime:
            trend_counter = 0
        else:
            trend_counter += 1
        last_true_regime = true_regime

        # 3. 施加 AI 滤镜 (模拟真实判断)
        ai_perceived_regime = simulate_ai_perception(true_regime, trend_counter)

        all_data.append({
            "date": current_date.strftime("%Y-%m-%d"),
            "regime": ai_perceived_regime
        })
        current_date += timedelta(days=1)

    df = pd.DataFrame(all_data)
    df.to_csv(file_path, index=False)
    print(f"✅ 拟真剧本已生成: {file_path}")
    print("💡 特征: 包含 2-3 天的信号滞后，以及 15% 的信号噪音。")


if __name__ == "__main__":
    generate_realistic_regime()