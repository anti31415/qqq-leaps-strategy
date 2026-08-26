from AlgorithmImports import *


class QqqTqqqWheelCloudBacktest(QCAlgorithm):
    """Cloud version of the locally deployed QQQ-signal / TQQQ-wheel strategy."""

    def initialize(self):
        self.set_start_date(2021, 8, 13)
        self.set_end_date(2026, 8, 12)
        self.set_cash(20_000)
        self.set_benchmark("QQQ")
        self.set_warm_up(220, Resolution.DAILY)

        self.qqq = self.add_equity(
            "QQQ", Resolution.DAILY, data_normalization_mode=DataNormalizationMode.ADJUSTED
        ).symbol
        self.tqqq = self.add_equity(
            "TQQQ", Resolution.MINUTE, data_normalization_mode=DataNormalizationMode.RAW
        ).symbol
        option = self.add_option(self.tqqq, Resolution.MINUTE)
        option.set_filter(
            lambda universe: universe.include_weeklys().strikes(-80, 30).expiration(20, 40)
        )
        self.option_symbol = option.symbol

        self.sma200 = self.sma(self.qqq, 200, Resolution.DAILY)
        self.rsi14 = self.rsi(
            self.qqq, 14, MovingAverageType.WILDERS, Resolution.DAILY
        )
        self.previous_qqq_close = None
        self.latest_chain = None
        self.trade_log = []

        self.schedule.on(
            self.date_rules.every_day(self.tqqq),
            self.time_rules.after_market_open(self.tqqq, 10),
            self.evaluate_strategy,
        )

    def on_data(self, slice):
        chain = slice.option_chains.get(self.option_symbol)
        if chain is not None:
            self.latest_chain = list(chain)

        qqq_bar = slice.bars.get(self.qqq)
        if qqq_bar is not None:
            self.previous_qqq_close = float(qqq_bar.close)

    def evaluate_strategy(self):
        if self.is_warming_up or not self.sma200.is_ready or not self.rsi14.is_ready:
            return
        if self.transactions.get_open_orders():
            return

        option_holdings = [
            security
            for security in self.securities.values()
            if security.type == SecurityType.OPTION and security.invested
        ]
        if option_holdings:
            return

        share_quantity = int(self.portfolio[self.tqqq].quantity)
        if share_quantity >= 100:
            self.sell_covered_call(share_quantity)
            return
        if share_quantity != 0:
            return

        history = self.history[TradeBar](self.qqq, 2, Resolution.DAILY)
        bars = list(history)
        if len(bars) < 2:
            return
        previous_close = float(bars[-2].close)
        latest_close = float(bars[-1].close)
        signal = (
            latest_close < previous_close
            and latest_close > float(self.sma200.current.value)
            and float(self.rsi14.current.value) < 35
        )
        if signal:
            self.sell_cash_secured_put()

    def available_contracts(self, right):
        if not self.latest_chain:
            return []
        now_date = self.time.date()
        return [
            contract
            for contract in self.latest_chain
            if contract.right == right and 23 <= (contract.expiry.date() - now_date).days <= 37
        ]

    def sell_cash_secured_put(self):
        underlying = float(self.securities[self.tqqq].price)
        target_strike = underlying * 0.90
        candidates = self.available_contracts(OptionRight.PUT)
        if not candidates:
            return
        candidates.sort(
            key=lambda contract: (
                abs((contract.expiry.date() - self.time.date()).days - 30),
                abs(float(contract.strike) - target_strike),
                contract.expiry,
            )
        )
        contract = candidates[0]
        collateral = float(contract.strike) * 100
        if self.portfolio.cash < collateral:
            self.debug(f"SKIP_CSP_INSUFFICIENT_CASH,{self.time.date()},{collateral:.2f}")
            return
        ticket = self.market_order(contract.symbol, -1, tag="QQQ down-day + above SMA200 + RSI14<35")
        self.trade_log.append((self.time, "SELL_CSP", str(contract.symbol), ticket.order_id))

    def sell_covered_call(self, share_quantity):
        underlying = float(self.securities[self.tqqq].price)
        average_entry = float(self.portfolio[self.tqqq].average_price)
        target_strike = max(underlying, average_entry)
        candidates = [
            contract
            for contract in self.available_contracts(OptionRight.CALL)
            if float(contract.strike) >= target_strike
        ]
        if not candidates:
            return
        candidates.sort(
            key=lambda contract: (
                abs((contract.expiry.date() - self.time.date()).days - 30),
                abs(float(contract.strike) - target_strike),
                contract.expiry,
            )
        )
        contract = candidates[0]
        quantity = share_quantity // 100
        ticket = self.market_order(contract.symbol, -quantity, tag="Covered call on assigned TQQQ")
        self.trade_log.append((self.time, "SELL_CC", str(contract.symbol), ticket.order_id))

    def on_order_event(self, order_event):
        if order_event.status == OrderStatus.FILLED:
            self.log(
                f"FILL,{order_event.utc_time},{order_event.symbol},{order_event.direction},"
                f"{order_event.fill_quantity},{order_event.fill_price}"
            )

    def on_end_of_algorithm(self):
        self.set_runtime_statistic("Strategy", "QQQ signal / TQQQ wheel")
        self.set_runtime_statistic("Actions", str(len(self.trade_log)))
