import pandas as pd
import os
import random
from datetime import datetime, timedelta


def generate_realistic_regime():
    # 🔥 [新增] 固定随机种子，保证每次生成的"噪音"位置都一样
    # 方便你调试策略参数 (控制变量法)
    random.seed(44)

    os.makedirs('data', exist_ok=True)
    file_path = 'data/ai_regime.csv'

    print(f"🛠️ 正在生成【拟真版】AI 剧本 (包含 2021-2023 完整周期)...")

    # ==========================================
    # 1. 定义"绝对真实"的历史阶段 (基准真相)
    # ==========================================
    true_periods = [
        # === 2021: 疯牛与双顶 (最考验人性的一年) ===
        ("2021-01-01", "2021-04-13", "BULL_TREND"),  # 疯牛: 2w -> 6.4w
        ("2021-04-14", "2021-05-18", "SHOCK_SIDEWAYS"),  # 顶部派发: 假摔预警
        ("2021-05-19", "2021-07-20", "BEAR_CRASH"),  # 519惨案: 腰斩到 3w
        ("2021-07-21", "2021-11-09", "BULL_TREND"),  # 死灰复燃: 冲刺 6.9w
        ("2021-11-10", "2021-12-31", "BEAR_CRASH"),  # 真正的熊市开始

        # === 2022: 深熊 (单边下跌) ===
        ("2022-01-01", "2022-03-31", "BEAR_CRASH"),  # 阴跌
        ("2022-04-01", "2022-05-04", "SHOCK_SIDEWAYS"),  # 暴雷前的死寂
        ("2022-05-05", "2022-06-30", "BEAR_CRASH"),  # LUNA 归零
        ("2022-07-01", "2022-11-05", "SHOCK_SIDEWAYS"),  # 底部磨底
        ("2022-11-06", "2022-12-31", "BEAR_CRASH"),  # FTX 暴雷

        # === 2023: 修复与骗炮 (震荡上行) ===
        ("2023-01-01", "2023-02-28", "BULL_TREND"),  # 小阳春
        ("2023-03-01", "2023-09-30", "SHOCK_SIDEWAYS"),  # 漫长的猴市 (最磨人)
        ("2023-10-01", "2023-12-31", "BULL_TREND"),  # ETF 预期行情
    ]

    # ==========================================
    # 2. 模拟 AI 的"缺陷"逻辑 (保持不变，很完美)
    # ==========================================
    def simulate_ai_perception(true_regime, day_count_in_trend):
        rand = random.random()

        # 场景 A: 真实是牛市
        if true_regime == "BULL_TREND":
            # 滞后: 趋势前 3 天看不出来
            if day_count_in_trend < 3: return "SHOCK_SIDEWAYS"
            # 噪音: 15% 概率因为利空看震荡 (容易卖飞)
            if rand < 0.15: return "SHOCK_SIDEWAYS"
            return "BULL_TREND"

        # 场景 B: 真实是熊市
        elif true_regime == "BEAR_CRASH":
            # 滞后: 暴跌前 2 天反应不过来
            if day_count_in_trend < 2: return "SHOCK_SIDEWAYS"
            # 噪音: 10% 概率看震荡 (容易抄底在半山腰)
            if rand < 0.10: return "SHOCK_SIDEWAYS"
            return "BEAR_CRASH"

        # 场景 C: 真实是震荡
        elif true_regime == "SHOCK_SIDEWAYS":
            # 诱多: 10% 概率看涨 (假突破)
            if rand < 0.10:
                return "BULL_TREND"
            # 诱空: 10% 概率看跌 (假跌破)
            elif rand > 0.90:
                return "BEAR_CRASH"
            return "SHOCK_SIDEWAYS"

    # ==========================================
    # 3. 生成数据核心循环
    # ==========================================
    all_data = []

    # 转换查找表
    base_map = {}
    for r_start, r_end, status in true_periods:
        s = datetime.strptime(r_start, "%Y-%m-%d")
        e = datetime.strptime(r_end, "%Y-%m-%d")
        temp = s
        while temp <= e:
            base_map[temp] = status
            temp += timedelta(days=1)

    # 设定生成时间范围 (覆盖 2021-2024)
    current_date = datetime(2021, 1, 1)
    end_date = datetime(2024, 1, 1)

    trend_counter = 0
    last_true_regime = None

    while current_date <= end_date:
        # 获取上帝视角 (默认为震荡)
        true_regime = base_map.get(current_date, "SHOCK_SIDEWAYS")

        if true_regime != last_true_regime:
            trend_counter = 0
        else:
            trend_counter += 1
        last_true_regime = true_regime

        # 生成 AI 视角
        ai_perceived_regime = simulate_ai_perception(true_regime, trend_counter)

        all_data.append({
            "date": current_date.strftime("%Y-%m-%d"),
            "regime": ai_perceived_regime
        })
        current_date += timedelta(days=1)

    df = pd.DataFrame(all_data)
    df.to_csv(file_path, index=False)
    print(f"✅ 拟真剧本已更新: {file_path}")
    print(f"📊 数据范围: {all_data[0]['date']} -> {all_data[-1]['date']}")
    print("💡 已加入随机种子(Seed=44)，结果可复现。")


if __name__ == "__main__":
    generate_realistic_regime()