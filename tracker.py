from decimal import Decimal, InvalidOperation


class AssetManager:
    def __init__(self, name="BTC/USDT", accounting_method='AVCO'):
        self.name = name
        self.holdings_qty = Decimal('0')
        self.avg_cost = Decimal('0')
        self.realized_pnl = Decimal('0')

    def get_total_qty(self):
        return self.holdings_qty

    # --- [新增] 安全转换工具：专门处理 None 和奇怪数据 ---
    def _to_decimal(self, value, default='0'):
        """如果数据是 None 或非法，自动转为 0，防止报错"""
        if value is None:
            return Decimal(default)
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            # 如果转不了数字（比如传了 'abc'），就返回 0
            return Decimal(default)

    def sync_holdings(self, real_qty_float, current_price_float=None):
        # 使用安全转换
        real_qty = self._to_decimal(real_qty_float)

        # 只有差异超过 0.00000001 时才打印
        if abs(real_qty - self.holdings_qty) > Decimal('0.00000001'):
            print(f"🔄 [同步] 持仓校准: 本地 {self.holdings_qty:.8f} -> 交易所 {real_qty:.8f}")

            # 初始化成本
            if self.avg_cost == 0 and real_qty > 0 and current_price_float:
                self.avg_cost = self._to_decimal(current_price_float)
                print(f"⚙️ [初始化] 成本基准设为当前价: {self.avg_cost}")

            self.holdings_qty = real_qty

    def buy(self, price, qty, fee=0):
        try:
            # --- [核心修复] 使用安全转换，遇到 None 自动变 0 ---
            p = self._to_decimal(price)
            q = self._to_decimal(qty)
            f = self._to_decimal(fee)
            # -----------------------------------------------

            total_cost = (self.holdings_qty * self.avg_cost) + (q * p)
            self.holdings_qty += q

            if self.holdings_qty > 0:
                self.avg_cost = total_cost / self.holdings_qty

            print(f"📒 [买入] {q} @ {p} | 手续费: {f} | 新均价: {self.avg_cost:.2f}")
        except Exception as e:
            print(f"❌ 记账(Buy)内部错误: {e}")

    def sell(self, price, qty, fee=0):
        try:
            # --- [核心修复] 使用安全转换 ---
            p = self._to_decimal(price)
            q = self._to_decimal(qty)
            f = self._to_decimal(fee)
            # ---------------------------

            if q > self.holdings_qty:
                # 容错：如果不小心卖超了，只按持仓量算
                # print(f"⚠️ [修正] 卖出量 {q} > 持仓 {self.holdings_qty}，仅计算持仓部分")
                pass

            gross_profit = (p - self.avg_cost) * q
            net_profit = gross_profit - f

            self.realized_pnl += net_profit
            self.holdings_qty -= q

            print(f"💰 [卖出] {q} @ {p} | 手续费: {f} | 净赚: {net_profit:.2f}")
        except Exception as e:
            print(f"❌ 记账(Sell)内部错误: {e}")

    def report(self, current_market_price):
        try:
            curr_p = self._to_decimal(current_market_price)
            floating_pnl = (curr_p - self.avg_cost) * self.holdings_qty

            print("-" * 35)
            print(f"📊 策略持仓: {self.holdings_qty:.8f} {self.name.split('/')[0]}")
            print(f"⚖️ 持仓成本: {self.avg_cost:.2f}")
            print(f"📈 浮动盈亏: {floating_pnl:+.2f} (未实现)")
            print(f"💰 已落袋净利: {self.realized_pnl:+.6f} (含手续费)")
            print("-" * 35)
        except Exception as e:
            print(f"❌ 报表错: {e}")