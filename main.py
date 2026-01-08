import time
import schedule
import sys
import os
import json
import csv
import numpy as np
from datetime import datetime, timedelta
from dotenv import load_dotenv

# === 引入自定义模块 ===
from trading_engine import OKXDemoTrader, OKXRealTrader, OKXPaperTrader
from factor_engine import MultiFactorEngine
from news_loader import NewsFetcher
from model import SentimentAnalyst
from notifier import EmailNotifier

# === 加载配置 ===
load_dotenv(override=True)

# ==========================================
# ⚙️ 全局配置 (Configuration)
# ==========================================
RUN_MODE = "PAPER"  # PAPER(模拟实盘) | REAL(真金白银)
SYMBOL = "BTC/USDT"
TIMEFRAME = "1h"  # 策略周期
TRADE_QTY = 0.01  # 单次交易数量

# 🛑 风控参数
ENABLE_RISK_CONTROL = True
STOP_LOSS_PCT = 0.05  # 止损 -5%
TAKE_PROFIT_PCT = 0.20  # 止盈 +20%


# ==========================================
# 📦 持仓状态管理器 (Position Manager)
# ==========================================
class PositionManager:
    def __init__(self, filename="bot_state.json"):
        self.filename = filename
        self.state = self._load_state()

    def _load_state(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {"has_position": False, "avg_price": 0.0, "timestamp": None}

    def save_state(self, has_position, price):
        self.state = {
            "has_position": has_position,
            "avg_price": price,
            "timestamp": str(datetime.now())
        }
        with open(self.filename, 'w') as f:
            json.dump(self.state, f, indent=4)

    def get_avg_price(self):
        return self.state.get("avg_price", 0.0)

    def is_holding(self):
        return self.state.get("has_position", False)


# ==========================================
# 🤖 量化指挥官 (Commander)
# ==========================================
class QuantBotCommander:
    def __init__(self):
        proxy = os.getenv("PROXY_PORT", "")
        mode_str = f"🌍 代理模式 ({proxy})" if proxy else "🚀 直连模式"
        print(f"\n{'=' * 40}")
        print(f"🤖 量化机器人启动 | {mode_str}")
        print(f"📈 交易标的: {SYMBOL} | 周期: {TIMEFRAME}")
        print(f"🤖 初始化量化核心 [模式: {RUN_MODE}]...")

        print(f"{'=' * 40}\n")

        # 1. 初始化交易执行器
        if RUN_MODE == "REAL":
            print(f"⚠️ [实盘警告] 正在使用真实资金交易 {SYMBOL}...")
            self.trader = OKXRealTrader()
        elif RUN_MODE == "PAPER":
            print(f"📝 [模拟实盘] 使用实时行情 + 虚拟资金...")
            self.trader = OKXPaperTrader(initial_usdt=10000.0)
        else:
            self.trader = OKXDemoTrader()

        # 2. 初始化各功能模块
        self.engine = MultiFactorEngine()
        self.news_loader = NewsFetcher()
        self.analyst = SentimentAnalyst()
        self.pos_manager = PositionManager()
        self.notifier = EmailNotifier()

        # 3. 运行时状态
        self.last_sentiment = {"score": 0, "reason": "Init"}
        self.qty = TRADE_QTY
        self.start_time = datetime.now()

        # 4. 统计与日志
        self.session_trades = []  # 内存中的交易记录
        self.equity_curve = []  # 净值曲线
        self._init_csv_logger()  # 初始化 CSV 黑匣子

        # 5. 计算初始权益
        try:
            ticker = self.trader.exchange.fetch_ticker(SYMBOL)
            price = ticker['last']
        except:
            price = 0
        self.initial_equity = self._calculate_total_equity(price)
        print(f"💰 初始权益: {self.initial_equity:.2f} U")

    # --- 📝 CSV 黑匣子功能 ---
    def _init_csv_logger(self):
        """初始化交易日志文件 (黑匣子)"""
        self.csv_file = "trade_history.csv"
        if not os.path.exists(self.csv_file):
            with open(self.csv_file, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Time", "Type", "Symbol", "Expected_Price", "Fill_Price",
                    "Slippage(%)", "Latency(ms)", "Score", "Trend", "Momentum", "Reason", "PnL(%)"
                ])

    def _log_trade_to_csv(self, data):
        """写入一行交易记录"""
        with open(self.csv_file, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                data['time'], data['type'], SYMBOL,
                f"{data['exp_price']:.2f}", f"{data['fill_price']:.2f}",
                f"{data['slippage']:.4f}", f"{data['latency']:.0f}",
                f"{data.get('score', 0):.1f}", f"{data.get('trend', 0):.0f}", f"{data.get('momentum', 0):.0f}",
                data['reason'], f"{data.get('pnl', 0):.2f}"
            ])

    def _calculate_total_equity(self, current_price):
        """计算账户总权益 (USDT + 持仓市值)"""
        if not current_price:
            try:
                market = self.trader.exchange.fetch_ticker(SYMBOL)
                current_price = market['last']
            except:
                return 0

        bal = self.trader.get_account_balance()
        return bal.get('USDT', 0) + (bal.get('BTC', 0) * current_price)

    # --- 🧠 核心逻辑循环 (每分钟执行) ---
    def execute_logic(self):
        try:
            current_time = datetime.now()

            # 1. 获取 1H 行情
            market_data = self.trader.fetch_market_data(SYMBOL, timeframe=TIMEFRAME)
            if not market_data: return
            current_price = market_data['current_price']

            # 2. 记录净值 (用于回撤计算)
            current_equity = self._calculate_total_equity(current_price)
            self.equity_curve.append(current_equity)

            # 3. 计算技术指标
            tech_score, tech_sub, _ = self.engine.calculate_technical_score(market_data)

            # AI 逻辑: 仅在整点 (0-5分) 调用 AI，其他时间复用缓存
            is_new_hour = current_time.minute < 5
            silent_mode = not is_new_hour

            if is_new_hour:
                print(f"\n⏰ [{current_time.strftime('%H:%M')}] 整点巡航 ({TIMEFRAME})...")
                news = self.news_loader.get_latest_news(SYMBOL)
                self.last_sentiment = self.analyst.analyze_sentiment(SYMBOL, news)

            # 4. 融合信号
            fusion = self.engine.fuse_signals(tech_score, tech_sub, self.last_sentiment)
            final_score = fusion['final_score']
            action = fusion['action']

            # 5. 构造当前市场状态快照 (用于记录日志)
            market_state = {
                "score": final_score,
                "trend": tech_sub.get('Trend', 0),
                "momentum": tech_sub.get('Momentum', 0)
            }

            # 6. 🛡️ 风控与状态监控
            if self.pos_manager.is_holding():
                entry_price = self.pos_manager.get_avg_price()
                pnl_pct = (current_price - entry_price) / entry_price

                # 静默日志
                if silent_mode:
                    dist_sl = pnl_pct - (-STOP_LOSS_PCT)
                    status = "🟢 盈利" if pnl_pct > 0 else "🔴 亏损"
                    print(
                        f"\r[{current_time.strftime('%H:%M')}] 🛡️ 持仓 | 现价:{current_price:.2f} | 净值:{current_equity:.0f} | {status}:{pnl_pct * 100:+.2f}% | 距止损:{dist_sl * 100:.2f}%",
                        end="   ", flush=True)

                # 止损/止盈检查
                if pnl_pct <= -STOP_LOSS_PCT:
                    print(f"\n🩸 [触发止损] -{pnl_pct * 100:.2f}%")
                    self._force_sell(current_price, "STOP_LOSS", market_state)
                    return

                if pnl_pct >= TAKE_PROFIT_PCT:
                    print(f"\n💰 [触发止盈] +{pnl_pct * 100:.2f}%")
                    self._force_sell(current_price, "TAKE_PROFIT", market_state)
                    return
            else:
                # 空仓日志
                if silent_mode:
                    gap = 60 - final_score
                    print(
                        f"\r[{current_time.strftime('%H:%M')}] 🔭 搜寻 | 现价:{current_price:.2f} | 净值:{current_equity:.0f} | 分数:{final_score:.1f} (差{gap:.1f}分买入)",
                        end="   ", flush=True)

            # 7. 打印详细看板 (仅在整点或有动作时)
            has_action = action in ["BUY", "STRONG_BUY", "SELL"]
            if is_new_hour or has_action:
                if silent_mode: print("")  # 换行
                if not is_new_hour: print(f"\n⚡ [{current_time.strftime('%H:%M')}] 信号突变！")
                self._print_dashboard(final_score, action, tech_sub, self.last_sentiment, current_price)

            # 8. 执行交易策略
            if action == "HOLD": return

            if action in ["BUY", "STRONG_BUY"]:
                self._try_buy(current_price, market_state)

            elif action == "SELL":
                self._try_sell(current_price, "STRATEGY_EXIT", market_state)

        except Exception as e:
            print(f"\n❌ 运行异常: {e}")
            # import traceback
            # traceback.print_exc()

    # --- ⚔️ 交易执行函数 (含黑匣子记录) ---

    def _try_buy(self, expected_price, market_state):
        bal = self.trader.get_account_balance()
        cost = expected_price * self.qty

        # 检查是否已有持仓 & 余额是否足够
        if not self.pos_manager.is_holding() and bal['USDT'] >= cost:
            print(f"🚀 [买入信号] 正在执行买入 {self.qty} BTC...")

            # 计时开始
            t_start = time.time()

            # 下单
            order = None
            if RUN_MODE == "PAPER":
                order = self.trader.mock_create_order(SYMBOL, 'buy', self.qty, expected_price)
            elif RUN_MODE == "REAL":
                order = self.trader.exchange.create_market_order(SYMBOL, 'buy', self.qty)

            # 计算延迟
            latency_ms = (time.time() - t_start) * 1000

            if order:
                fill_price = order.get('average', expected_price)
                if not fill_price: fill_price = expected_price

                # 计算滑点
                slippage_pct = (fill_price - expected_price) / expected_price * 100

                # 保存状态
                self.pos_manager.save_state(True, fill_price)

                print(f"✅ 成交 | 价:{fill_price:.2f} | 延:{latency_ms:.0f}ms | 滑:{slippage_pct:.4f}%")

                # 发送邮件
                self.notifier.send_buy_alert(SYMBOL, fill_price, self.qty, "策略信号")

                # 记录日志
                log_data = {
                    "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "type": "BUY",
                    "exp_price": expected_price,
                    "fill_price": fill_price,
                    "slippage": slippage_pct,
                    "latency": latency_ms,
                    "score": market_state.get('score', 0),
                    "trend": market_state.get('trend', 0),
                    "momentum": market_state.get('momentum', 0),
                    "reason": "SIGNAL",
                    "pnl": 0
                }
                self._log_trade_to_csv(log_data)
                self.session_trades.append(log_data)

    def _try_sell(self, expected_price, reason, market_state):
        if self.pos_manager.is_holding():
            print(f"📉 [卖出信号: {reason}] 正在执行卖出...")

            bal = self.trader.get_account_balance()
            sell_qty = bal['BTC']
            if sell_qty < 0.0001: return  # 余额不足忽略

            # 计时
            t_start = time.time()

            # 下单
            order = None
            if RUN_MODE == "PAPER":
                order = self.trader.mock_create_order(SYMBOL, 'sell', sell_qty, expected_price)
            elif RUN_MODE == "REAL":
                order = self.trader.exchange.create_market_order(SYMBOL, 'sell', sell_qty)

            # 延迟
            latency_ms = (time.time() - t_start) * 1000

            # 确定成交价
            fill_price = expected_price
            if order and order.get('average'): fill_price = order.get('average')

            # 滑点
            slippage_pct = (expected_price - fill_price) / expected_price * 100

            # 结算 PnL
            entry_price = self.pos_manager.get_avg_price()
            pnl_pct = (fill_price - entry_price) / entry_price * 100

            # 清除持仓
            self.pos_manager.save_state(False, 0.0)

            print(
                f"✅ 成交 | 价:{fill_price:.2f} | 延:{latency_ms:.0f}ms | 滑:{slippage_pct:.4f}% | 盈亏:{pnl_pct:+.2f}%")

            # 发送邮件
            new_bal = self.trader.get_account_balance()
            self.notifier.send_sell_alert(SYMBOL, fill_price, sell_qty, reason, entry_price, new_bal.get('USDT', 0))

            # 记录日志
            log_data = {
                "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "type": "SELL",
                "exp_price": expected_price,
                "fill_price": fill_price,
                "slippage": slippage_pct,
                "latency": latency_ms,
                "score": market_state.get('score', 0),
                "trend": market_state.get('trend', 0),
                "momentum": market_state.get('momentum', 0),
                "reason": reason,
                "pnl": pnl_pct
            }
            self._log_trade_to_csv(log_data)
            self.session_trades.append(log_data)

    def _force_sell(self, price, reason, market_state):
        """强制平仓包装器"""
        print(f"🚨 [风控触发] {reason} !!!")
        self._try_sell(price, reason, market_state)

    def _print_dashboard(self, score, action, tech, ai, price):
        entry_info = ""
        if self.pos_manager.is_holding():
            cost = self.pos_manager.get_avg_price()
            pnl = (price - cost) / cost * 100
            entry_info = f"| 成本: {cost:.0f} | 浮盈: {pnl:+.2f}%"

        print("-" * 75)
        print(f"📊 {SYMBOL} [1h] | 现价: {price:.2f} {entry_info}")
        print(f"🎯 综合得分: {score:.1f}  ==>  {action}")
        print(
            f"🌊 趋势: {tech.get('Trend', 0):.0f} | 🚀 动量: {tech.get('Momentum', 0):.0f} | 💸 资金: {tech.get('Volume', 0):.0f} | ⚡ 波动: {tech.get('Volatility', 0):.0f}")
        print(f"🤖 AI分析: {ai.get('score', 0)} ({ai.get('reason', 'N/A')[:40]}...)")
        print("-" * 75)

    # --- 📈 会话报告生成 ---
    def generate_session_report(self):
        end_time = datetime.now()
        duration = end_time - self.start_time

        # 1. 基础盈亏
        final_equity = self.equity_curve[-1] if self.equity_curve else self.initial_equity
        profit = final_equity - self.initial_equity
        roi = (profit / self.initial_equity) * 100 if self.initial_equity > 0 else 0

        # 2. 最大回撤
        max_drawdown = 0
        if self.equity_curve:
            peaks = np.maximum.accumulate(self.equity_curve)
            drawdowns = (peaks - self.equity_curve) / peaks
            max_drawdown = drawdowns.max() * 100

        # 3. 交易统计
        closed_trades = [t for t in self.session_trades if t['type'] == 'SELL']
        total_closed = len(closed_trades)

        win_rate = 0
        pl_ratio = 0
        if total_closed > 0:
            winning = [t for t in closed_trades if t['pnl'] > 0]
            losing = [t for t in closed_trades if t['pnl'] <= 0]
            win_rate = (len(winning) / total_closed) * 100

            avg_win = np.mean([t['pnl'] for t in winning]) if winning else 0
            avg_loss = np.abs(np.mean([t['pnl'] for t in losing])) if losing else 1
            pl_ratio = avg_win / avg_loss if avg_loss > 0 else 0

        # 4. 年化推算
        days_run = duration.total_seconds() / (24 * 3600)
        annual_ret = (roi / days_run * 365) if days_run > 0.04 else 0

        print("\n" + "=" * 60)
        print(f"📝 机器人投资分析报告 (Session Analysis)")
        print("=" * 60)
        print(f"⏱️ 运行时长 : {str(duration).split('.')[0]}")
        print(f"💰 权益变动 : {self.initial_equity:.2f} ➔ {final_equity:.2f} U")
        print(f"📈 净利润   : {profit:+.2f} U")
        print("-" * 60)
        print(f"🚀 ROI (本场) : {roi:+.2f}%")
        print(f"📅 年化推算   : {annual_ret:+.2f}%" if annual_ret else "📅 年化推算   : -- (时间太短)")
        print(f"🛡️ 最大回撤   : {max_drawdown:.2f}%")
        print("-" * 60)
        print(f"🎲 交易笔数   : {total_closed} 笔")
        print(f"🏆 胜率       : {win_rate:.1f}%")
        print(f"⚖️ 盈亏比     : {pl_ratio:.2f}")
        print("=" * 60)

        if self.session_trades:
            print("流水摘要:")
            for t in self.session_trades:
                if t['type'] == 'BUY':
                    print(f"  [{t['time'][5:16]}] 🟢 买入 @ {float(t['fill_price']):.0f}")
                else:
                    emoji = "💰" if t['pnl'] > 0 else "🩸"
                    print(
                        f"  [{t['time'][5:16]}] {emoji} 卖出 @ {float(t['fill_price']):.0f} | {t['pnl']:+.2f}% ({t['reason']})")
        print("\n")

    def start(self):
        print(f"🤖 量化机器人启动 | 模式: {RUN_MODE} | 周期: {TIMEFRAME}")
        if ENABLE_RISK_CONTROL:
            print(f"🛡️ 风控系统已开启: 止损 -{STOP_LOSS_PCT * 100}% | 止盈 +{TAKE_PROFIT_PCT * 100}%")

        self.execute_logic()
        schedule.every(1).minutes.do(self.execute_logic)

        print("✅ 监控回路已建立 (按 Ctrl+C 停止并生成报告)...")
        try:
            while True:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n\n🛑 正在停止并计算指标...")
            self.generate_session_report()
            sys.exit(0)


if __name__ == "__main__":
    bot = QuantBotCommander()
    bot.start()