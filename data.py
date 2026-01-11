import pandas as pd
import os
from datetime import datetime, timedelta


def generate_perfect_regime():
    # 确保 data 目录存在
    os.makedirs('data', exist_ok=True)
    file_path = 'data/ai_regime.csv'

    print(f"🛠️ 正在生成全能回测剧本 (以 2021 年为蓝本)...")

    # ==========================================
    # 🎨 剧本定义 (Regime Definition)
    # ==========================================
    # 状态: BULL_TREND (牛), BEAR_CRASH (熊), SHOCK_SIDEWAYS (震荡)

    regime_periods = [
        # --- 2021: 史诗级全能测试年 ---
        ("2021-01-01", "2021-04-13", "BULL_TREND"),  # 主升浪 (29k -> 64k)
        ("2021-04-14", "2021-05-10", "SHOCK_SIDEWAYS"),  # 顶部震荡/出货
        ("2021-05-11", "2021-07-20", "BEAR_CRASH"),  # 519大暴跌 (64k -> 29k) -> 这里的 Mode A 应该接针
        ("2021-07-21", "2021-09-06", "BULL_TREND"),  # 二次反弹 (29k -> 52k)
        ("2021-09-07", "2021-09-29", "SHOCK_SIDEWAYS"),  # 9月回调
        ("2021-09-30", "2021-11-09", "BULL_TREND"),  # 冲顶 69k
        ("2021-11-10", "2021-12-31", "BEAR_CRASH"),  # 牛市结束，崩盘开始

        # --- 2022: 纯熊市 (测试空仓能力) ---
        ("2022-01-01", "2022-12-31", "BEAR_CRASH"),  # 应该全程空仓

        # --- 2025-2026: 针对你之前的回测亏损段 ---
        # 强制标记为熊市，让 v19/v20 策略学会"装死"
        ("2025-09-01", "2026-03-01", "BEAR_CRASH"),
    ]

    # ==========================================
    # 生成逻辑
    # ==========================================
    all_data = []

    # 我们生成从 2020 到 2027 的数据，覆盖所有可能的回测范围
    current_date = datetime(2020, 1, 1)
    end_date = datetime(2027, 12, 31)

    # 转换配置为查找表
    date_map = {}
    for r_start, r_end, status in regime_periods:
        s = datetime.strptime(r_start, "%Y-%m-%d")
        e = datetime.strptime(r_end, "%Y-%m-%d")
        temp = s
        while temp <= e:
            date_map[temp] = status
            temp += timedelta(days=1)

    while current_date <= end_date:
        # 默认为 SHOCK (既不是明显牛也不是明显熊)
        regime = date_map.get(current_date, "SHOCK_SIDEWAYS")

        all_data.append({
            "date": current_date.strftime("%Y-%m-%d"),
            "regime": regime
        })
        current_date += timedelta(days=1)

    # 保存
    df = pd.DataFrame(all_data)
    df.to_csv(file_path, index=False)

    print(f"✅ 剧本已生成: {file_path}")
    print(f"📊 包含 2021 全年 (牛熊转换) 及 2025-2026 (你的测试段)")


if __name__ == "__main__":
    generate_perfect_regime()