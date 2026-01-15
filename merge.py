import pandas as pd
import glob
import os


def merge_csv_files(input_folder, output_file):
    print(f"🔍 正在扫描文件夹: {input_folder} ...")

    # 1. 获取所有 CSV 文件路径
    all_files = glob.glob(os.path.join(input_folder, "*.csv"))

    if not all_files:
        print("❌ 未找到 CSV 文件，请检查路径！")
        return

    print(f"📦 找到 {len(all_files)} 个文件，开始合并...")

    df_list = []

    for filename in all_files:
        try:
            # 读取文件 (假设没有表头，或者表头不标准，我们统一处理)
            # 如果你的源文件第一行就是 title (open_time, open...), header=0
            # 如果源文件第一行就是数据, header=None
            # 这里默认按照 Binance 导出格式 (通常带 header)
            df = pd.read_csv(filename)

            # === 适配 Binance / 通用格式 ===
            # 如果列名包含 'open_time' 或 'timestamp'，统一改名为 'timestamp'
            # 这里的逻辑是标准化列名
            rename_map = {
                'open_time': 'timestamp',
                'Date': 'timestamp',
                'Time': 'timestamp',
                'Open': 'open',
                'High': 'high',
                'Low': 'low',
                'Close': 'close',
                'Volume': 'volume'
            }
            df.rename(columns=rename_map, inplace=True)

            # 确保包含必要的列
            required_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']

            # 简单的列名清洗 (转小写)
            df.columns = [c.lower() for c in df.columns]

            # 检查列是否存在
            if not all(col in df.columns for col in required_cols):
                # 尝试处理无表头的情况 (Binance 数据有时候没有表头)
                # 假设顺序是: timestamp, open, high, low, close, volume ...
                if df.shape[1] >= 6:
                    print(f"⚠️ 文件 {os.path.basename(filename)} 似乎没有标准表头，尝试按位置映射...")
                    df = df.iloc[:, :6]
                    df.columns = required_cols
                else:
                    print(f"⚠️ 跳过文件 {os.path.basename(filename)}: 列格式不匹配")
                    continue

            # 只保留我们需要的列
            df = df[required_cols]
            df_list.append(df)

        except Exception as e:
            print(f"⚠️ 读取 {os.path.basename(filename)} 失败: {e}")

    # 2. 合并所有数据
    if not df_list:
        print("❌ 没有有效数据被合并。")
        return

    full_df = pd.concat(df_list, ignore_index=True)

    # 3. 数据清洗
    print("🧹 正在清洗数据 (排序、去重、转换)...")

    # 转换时间戳 (如果是毫秒级时间戳，除以1000转秒，或者直接转 datetime)
    # 假设是 Binance 的毫秒时间戳
    if pd.api.types.is_numeric_dtype(full_df['timestamp']):
        # 判断是秒还是毫秒 (13位是毫秒)
        if full_df['timestamp'].iloc[0] > 1000000000000:
            full_df['timestamp'] = pd.to_datetime(full_df['timestamp'], unit='ms')
        else:
            full_df['timestamp'] = pd.to_datetime(full_df['timestamp'], unit='s')
    else:
        # 字符串格式
        full_df['timestamp'] = pd.to_datetime(full_df['timestamp'])

    # 按时间排序
    full_df.sort_values('timestamp', inplace=True)

    # 去除重复的时间点 (保留最后一条)
    full_df.drop_duplicates(subset=['timestamp'], keep='last', inplace=True)

    # 重置索引
    full_df.reset_index(drop=True, inplace=True)

    # 4. 导出
    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    full_df.to_csv(output_file, index=False)

    print(f"✅ 合并完成！")
    print(f"📅 时间范围: {full_df['timestamp'].min()} -> {full_df['timestamp'].max()}")
    print(f"📊 总条数: {len(full_df)}")
    print(f"💾 已保存至: {output_file}")


if __name__ == "__main__":
    # ================= 配置区 =================
    # 1. 把你下载的 CSV 文件都丢到这个文件夹里 (例如 downloads/btc_1h)
    INPUT_FOLDER = 'downloads/btc_data'

    # 2. 输出文件的位置
    OUTPUT_FILE = 'data/backtest_BTC_USDT_2021-01-01_2024-01-01.csv'
    # =========================================

    merge_csv_files(INPUT_FOLDER, OUTPUT_FILE)