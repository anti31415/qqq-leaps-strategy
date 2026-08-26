from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from autotrade.brokers.alpaca import AlpacaBroker
from autotrade.config import Settings
from autotrade.data import fetch_yahoo_daily_bars
from autotrade.indicators import expanding_mean_std, rsi


SIGMA1_EXIT_RULES = (
    {"min_age_days": 0, "max_age_days": 364, "profit_target": 1.2, "label": "take_profit_120_before_12m"},
    {"min_age_days": 365, "max_age_days": 456, "profit_target": 0.6, "label": "take_profit_60_12_to_15m"},
    {"min_age_days": 457, "max_age_days": 548, "profit_target": 0.3, "label": "take_profit_30_16_to_18m"},
)

SIGMA2_EXIT_RULES = (
    {"min_age_days": 0, "max_age_days": 364, "profit_target": 1.5, "label": "take_profit_150_before_12m"},
    {"min_age_days": 365, "max_age_days": 456, "profit_target": 0.8, "label": "take_profit_80_12_to_15m"},
    {"min_age_days": 457, "max_age_days": 548, "profit_target": 0.3, "label": "take_profit_30_16_to_18m"},
)


@dataclass
class SignalSnapshot:
    as_of_date: str
    qqq_close: float
    qqq_rsi: float | None
    vix_close: float
    vix_mean: float
    vix_std: float
    sigma1_threshold: float
    sigma2_threshold: float
    sigma2_count_60: int
    sigma2_count_20: int
    regime_name: str | None
    target_quantity: int
    buy_reason: str


@dataclass
class PlannedAction:
    action: str
    symbol: str | None
    quantity: int
    side: str | None
    order_preview: dict[str, Any] | None
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategyPlan:
    signal: dict[str, Any]
    warnings: list[str]
    unmanaged_positions: list[dict[str, Any]]
    open_orders: list[dict[str, Any]]
    actions: list[PlannedAction]
    state_summary: dict[str, Any]


def _today_utc() -> date:
    return datetime.utcnow().date()


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _days_between(a: str, b: str) -> int:
    return (_parse_date(b) - _parse_date(a)).days


def _week_key(date_text: str) -> str:
    value = _parse_date(date_text)
    year, week, _ = value.isocalendar()
    return f"{year}-W{week:02d}"


def _parse_option_symbol(symbol: str) -> dict[str, Any]:
    root = symbol[:-15]
    expiry = datetime.strptime(symbol[-15:-9], "%y%m%d").date().isoformat()
    option_type = symbol[-9]
    strike = int(symbol[-8:]) / 1000
    return {"root": root, "expiration_date": expiry, "option_type": option_type, "strike_price": strike}


def _exit_rules_for_regime(regime_name: str) -> tuple[dict[str, Any], ...]:
    return SIGMA1_EXIT_RULES if regime_name == "sigma1_weekly_1lot" else SIGMA2_EXIT_RULES


def _buying_power(account: dict[str, Any]) -> float:
    candidates = [
        account.get("options_buying_power"),
        account.get("non_marginable_buying_power"),
        account.get("cash"),
        account.get("buying_power"),
    ]
    values = [float(value) for value in candidates if value not in (None, "")]
    return min(values) if values else 0.0


def _build_limit_order(symbol: str, qty: int, side: str, limit_price: float, client_order_id: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "qty": str(qty),
        "side": side,
        "type": "limit",
        "limit_price": f"{limit_price:.2f}",
        "time_in_force": "day",
        "client_order_id": client_order_id,
    }


def latest_signal_snapshot(broker: AlpacaBroker, settings: Settings) -> SignalSnapshot:
    today = _today_utc().isoformat()
    qqq_bars = broker.get_daily_bars(settings.signal_symbol, start=(_today_utc() - timedelta(days=450)).isoformat(), end=today)
    if len(qqq_bars) < settings.rsi_period + 5:
        raise RuntimeError(f"Not enough Alpaca daily bars returned for {settings.signal_symbol}")

    vix_rows = fetch_yahoo_daily_bars(settings.vix_symbol, settings.data_start, today)
    vix_by_date = {row["date"]: row["close"] for row in vix_rows}

    merged: list[dict[str, Any]] = []
    closes: list[float] = []
    qqq_dates: list[str] = []
    for bar in qqq_bars:
        bar_date = bar["t"][:10]
        if bar_date not in vix_by_date:
            continue
        closes.append(float(bar["c"]))
        qqq_dates.append(bar_date)
    if len(closes) < settings.rsi_period + 5:
        raise RuntimeError("Not enough overlapping QQQ/VIX daily bars to compute the signal")

    aligned_vix_values = [vix_by_date[bar_date] for bar_date in qqq_dates]
    vix_stats = expanding_mean_std(aligned_vix_values)

    for index, bar_date in enumerate(qqq_dates):
        merged.append(
            {
                "date": bar_date,
                "close": closes[index],
                "vix": aligned_vix_values[index],
                "vix_mean": vix_stats[index][0],
                "vix_std": vix_stats[index][1],
            }
        )

    qqq_close_series = [row["close"] for row in merged]
    latest_rsi = rsi(qqq_close_series, settings.rsi_period)
    if latest_rsi is None:
        raise RuntimeError("RSI could not be computed from the merged daily series")

    eligible_indices = []
    for index, row in enumerate(merged):
        partial_rsi = rsi(qqq_close_series[:index + 1], settings.rsi_period)
        sigma2_threshold = row["vix_mean"] + row["vix_std"] * 2
        if partial_rsi is not None and partial_rsi < settings.rsi_buy_below and row["vix"] >= sigma2_threshold:
            eligible_indices.append(index)

    latest = merged[-1]
    sigma1_threshold = latest["vix_mean"] + latest["vix_std"]
    sigma2_threshold = latest["vix_mean"] + latest["vix_std"] * 2
    latest_index = len(merged) - 1
    sigma2_count_60 = sum(1 for index in eligible_indices if index >= latest_index - 59)
    sigma2_count_20 = sum(1 for index in eligible_indices if index >= latest_index - 19)

    regime_name: str | None = None
    quantity = 0
    buy_reason = "signal_conditions_not_met"
    if latest_rsi < settings.rsi_buy_below:
        if latest["vix"] >= sigma2_threshold:
            if sigma2_count_60 == 1:
                regime_name = "sigma2_first_60d_1lot"
                quantity = 1
                buy_reason = "first_sigma2_signal_in_last_60_trading_days"
            elif sigma2_count_20 >= 2:
                regime_name = "sigma2_repeat_20d_2lot"
                quantity = 2
                buy_reason = "second_or_later_sigma2_signal_in_last_20_trading_days"
            else:
                buy_reason = "sigma2_day_but_between_rolling_rules"
        elif latest["vix"] >= sigma1_threshold:
            regime_name = "sigma1_weekly_1lot"
            quantity = 1
            buy_reason = "sigma1_band_signal"
        else:
            buy_reason = "rsi_triggered_but_vix_filter_not_met"
    else:
        buy_reason = "rsi_not_below_threshold"

    return SignalSnapshot(
        as_of_date=latest["date"],
        qqq_close=latest["close"],
        qqq_rsi=latest_rsi,
        vix_close=latest["vix"],
        vix_mean=latest["vix_mean"],
        vix_std=latest["vix_std"],
        sigma1_threshold=sigma1_threshold,
        sigma2_threshold=sigma2_threshold,
        sigma2_count_60=sigma2_count_60,
        sigma2_count_20=sigma2_count_20,
        regime_name=regime_name,
        target_quantity=quantity,
        buy_reason=buy_reason,
    )


def _select_long_leaps_candidate(broker: AlpacaBroker, settings: Settings, as_of_date: str) -> dict[str, Any]:
    expiry_start = (_parse_date(as_of_date) + timedelta(days=settings.contract_target_days - settings.contract_day_tolerance)).isoformat()
    expiry_end = (_parse_date(as_of_date) + timedelta(days=settings.contract_target_days + settings.contract_day_tolerance)).isoformat()
    contracts = broker.get_option_contracts(settings.signal_symbol, expiry_start, expiry_end, option_type="call")
    if not contracts:
        raise RuntimeError("No LEAPS call contracts found inside the target expiration window")
    snapshots = broker.get_option_snapshots([contract["symbol"] for contract in contracts], settings.option_feed)
    candidates: list[dict[str, Any]] = []
    for contract in contracts:
        symbol = contract["symbol"]
        snapshot = snapshots.get(symbol)
        if not snapshot:
            continue
        mid_price = broker.option_mid_price(snapshot)
        delta = broker.option_delta(snapshot)
        if mid_price is None or delta is None or delta <= 0:
            continue
        expiration_date = contract["expiration_date"]
        dte = _days_between(as_of_date, expiration_date)
        candidates.append(
            {
                "symbol": symbol,
                "expiration_date": expiration_date,
                "strike_price": float(contract["strike_price"]),
                "delta": float(delta),
                "mid_price": float(mid_price),
                "dte": dte,
            }
        )
    if not candidates:
        raise RuntimeError("No LEAPS call candidate had both a tradable mid price and delta")
    candidates.sort(key=lambda item: (abs(item["delta"] - settings.target_delta), abs(item["dte"] - settings.contract_target_days), item["strike_price"]))
    return candidates[0]


def _select_short_call_candidate(
    broker: AlpacaBroker,
    settings: Settings,
    as_of_date: str,
    underlying_price: float,
) -> dict[str, Any]:
    expiry_start = (_parse_date(as_of_date) + timedelta(days=settings.short_call_dte - 5)).isoformat()
    expiry_end = (_parse_date(as_of_date) + timedelta(days=settings.short_call_dte + 5)).isoformat()
    contracts = broker.get_option_contracts(settings.signal_symbol, expiry_start, expiry_end, option_type="call")
    if not contracts:
        raise RuntimeError("No short call contracts found inside the target expiration window")
    snapshots = broker.get_option_snapshots([contract["symbol"] for contract in contracts], settings.option_feed)
    target_strike = underlying_price * (1 + settings.short_call_otm_pct)
    candidates: list[dict[str, Any]] = []
    for contract in contracts:
        strike = float(contract["strike_price"])
        if strike < target_strike:
            continue
        symbol = contract["symbol"]
        snapshot = snapshots.get(symbol)
        if not snapshot:
            continue
        mid_price = broker.option_mid_price(snapshot)
        if mid_price is None:
            continue
        expiration_date = contract["expiration_date"]
        dte = _days_between(as_of_date, expiration_date)
        candidates.append(
            {
                "symbol": symbol,
                "expiration_date": expiration_date,
                "strike_price": strike,
                "mid_price": float(mid_price),
                "dte": dte,
            }
        )
    if not candidates:
        raise RuntimeError("No short call candidate had both a strike above target and a tradable mid price")
    candidates.sort(key=lambda item: (abs(item["dte"] - settings.short_call_dte), abs(item["strike_price"] - target_strike), item["strike_price"]))
    return candidates[0]


def _sync_pending_orders(state: dict[str, Any], positions_by_symbol: dict[str, dict[str, Any]]) -> None:
    remaining_pending: list[dict[str, Any]] = []
    managed_leaps = state["managed_leaps"]

    for pending in state["pending_orders"]:
        symbol = pending["symbol"]
        if pending["kind"] == "open_leaps" and symbol in positions_by_symbol:
            position = positions_by_symbol[symbol]
            managed_leaps[symbol] = {
                "symbol": symbol,
                "regime_name": pending["regime_name"],
                "entry_date": pending["entry_date"],
                "entry_price": abs(float(position.get("avg_entry_price", pending["limit_price"]))),
                "quantity": abs(int(float(position.get("qty", pending["quantity"])))),
                "expiration_date": pending["expiration_date"],
                "strike_price": pending["strike_price"],
                "entry_cost": abs(float(position.get("avg_entry_price", pending["limit_price"]))) * 100 * abs(int(float(position.get("qty", pending["quantity"])))),
                "realized_short_call_cash": 0.0,
                "active_short_call": None,
            }
            state["entry_history"].append(
                {
                    "date": pending["entry_date"],
                    "regime_name": pending["regime_name"],
                    "quantity": pending["quantity"],
                    "symbol": symbol,
                }
            )
            continue

        if pending["kind"] == "open_short_call" and symbol in positions_by_symbol:
            parent_symbol = pending["parent_leaps_symbol"]
            leaps = managed_leaps.get(parent_symbol)
            if leaps:
                leaps["active_short_call"] = {
                    "symbol": symbol,
                    "entry_date": pending["entry_date"],
                    "quantity": pending["quantity"],
                    "entry_price": pending["limit_price"],
                    "expiration_date": pending["expiration_date"],
                    "strike_price": pending["strike_price"],
                }
                leaps["realized_short_call_cash"] += pending["limit_price"] * 100 * pending["quantity"]
            continue

        if pending["kind"] == "close_short_call" and symbol not in positions_by_symbol:
            parent_symbol = pending["parent_leaps_symbol"]
            leaps = managed_leaps.get(parent_symbol)
            if leaps and leaps.get("active_short_call"):
                leaps["realized_short_call_cash"] -= pending["limit_price"] * 100 * pending["quantity"]
                leaps["active_short_call"] = None
            continue

        if pending["kind"] == "close_leaps" and symbol not in positions_by_symbol:
            managed_leaps.pop(symbol, None)
            continue

        remaining_pending.append(pending)

    state["pending_orders"] = remaining_pending


def _cleanup_missing_short_calls(state: dict[str, Any], positions_by_symbol: dict[str, dict[str, Any]], as_of_date: str) -> None:
    for leaps in state["managed_leaps"].values():
        short_call = leaps.get("active_short_call")
        if not short_call:
            continue
        if short_call["symbol"] in positions_by_symbol:
            continue
        if as_of_date >= short_call["expiration_date"]:
            leaps["active_short_call"] = None


def _current_long_mid_price(broker: AlpacaBroker, symbol: str, feed: str) -> float | None:
    snapshots = broker.get_option_snapshots([symbol], feed)
    snapshot = snapshots.get(symbol, {})
    return broker.option_mid_price(snapshot)


def _current_short_liability(broker: AlpacaBroker, short_call_symbol: str, feed: str) -> float:
    snapshots = broker.get_option_snapshots([short_call_symbol], feed)
    snapshot = snapshots.get(short_call_symbol, {})
    mid_price = broker.option_mid_price(snapshot)
    return 0.0 if mid_price is None else mid_price * 100


def _managed_state_summary(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "managed_leaps_count": len(state["managed_leaps"]),
        "pending_orders_count": len(state["pending_orders"]),
        "entry_history_count": len(state["entry_history"]),
    }


def plan_next_action(broker: AlpacaBroker, settings: Settings, state: dict[str, Any]) -> StrategyPlan:
    signal = latest_signal_snapshot(broker, settings)
    account = broker.get_account()
    positions = broker.get_positions()
    open_orders = [order for order in broker.get_orders(status="open") if str(order.get("client_order_id", "")).startswith("qqq-leaps-")]
    positions_by_symbol = {position["symbol"]: position for position in positions}

    _sync_pending_orders(state, positions_by_symbol)
    _cleanup_missing_short_calls(state, positions_by_symbol, signal.as_of_date)

    warnings: list[str] = []
    if open_orders:
        warnings.append("Existing open strategy orders detected; new orders are not planned until they clear.")

    unmanaged_positions = []
    for position in positions:
        if position.get("asset_class") != "us_option":
            continue
        symbol = position["symbol"]
        if symbol in state["managed_leaps"]:
            continue
        active_short_symbols = {
            leaps["active_short_call"]["symbol"]
            for leaps in state["managed_leaps"].values()
            if leaps.get("active_short_call")
        }
        if symbol in active_short_symbols:
            continue
        if symbol.startswith(settings.signal_symbol):
            unmanaged_positions.append(position)

    if unmanaged_positions:
        warnings.append("Unmanaged QQQ option positions found in Alpaca account; planner will not make assumptions about them.")

    actions: list[PlannedAction] = []
    if not open_orders and not unmanaged_positions:
        for symbol, leaps in list(state["managed_leaps"].items()):
            if symbol not in positions_by_symbol:
                continue
            long_mid = _current_long_mid_price(broker, symbol, settings.option_feed)
            if long_mid is None:
                warnings.append(f"Could not price managed LEAPS position {symbol}; skipping exit evaluation.")
                continue
            quantity = int(abs(float(positions_by_symbol[symbol].get("qty", leaps["quantity"]))))
            net_value = long_mid * 100 * quantity + float(leaps.get("realized_short_call_cash", 0.0))
            short_call = leaps.get("active_short_call")
            if short_call:
                net_value -= _current_short_liability(broker, short_call["symbol"], settings.option_feed) * int(short_call["quantity"])
            entry_cost = float(leaps["entry_cost"])
            pnl_pct = (net_value - entry_cost) / entry_cost if entry_cost else 0.0
            age_days = _days_between(leaps["entry_date"], signal.as_of_date)
            days_to_expiry = _days_between(signal.as_of_date, leaps["expiration_date"])
            exit_reason = None
            for rule in _exit_rules_for_regime(leaps["regime_name"]):
                if rule["min_age_days"] <= age_days <= rule["max_age_days"] and pnl_pct >= rule["profit_target"]:
                    exit_reason = rule["label"]
                    break
            if exit_reason is None and days_to_expiry <= settings.force_exit_days_to_expiry:
                exit_reason = "force_exit_180d_to_expiry"

            if exit_reason:
                if short_call:
                    short_mid = _current_long_mid_price(broker, short_call["symbol"], settings.option_feed)
                    if short_mid is not None:
                        actions.append(
                            PlannedAction(
                                action="buy_to_close_short_call",
                                symbol=short_call["symbol"],
                                quantity=int(short_call["quantity"]),
                                side="buy",
                                order_preview=_build_limit_order(
                                    symbol=short_call["symbol"],
                                    qty=int(short_call["quantity"]),
                                    side="buy",
                                    limit_price=short_mid,
                                    client_order_id=f"qqq-leaps-close-short-{signal.as_of_date.replace('-', '')}-{short_call['symbol'][-8:]}",
                                ),
                                reason=exit_reason,
                                metadata={"parent_leaps_symbol": symbol, "expiration_date": short_call["expiration_date"], "strike_price": short_call["strike_price"]},
                            )
                        )
                actions.append(
                    PlannedAction(
                        action="sell_to_close_leaps",
                        symbol=symbol,
                        quantity=quantity,
                        side="sell",
                        order_preview=_build_limit_order(
                            symbol=symbol,
                            qty=quantity,
                            side="sell",
                            limit_price=long_mid,
                            client_order_id=f"qqq-leaps-close-long-{signal.as_of_date.replace('-', '')}-{symbol[-8:]}",
                        ),
                        reason=exit_reason,
                        metadata={"regime_name": leaps["regime_name"], "expiration_date": leaps["expiration_date"], "strike_price": leaps["strike_price"]},
                    )
                )

        if not actions:
            underlying_price = signal.qqq_close
            for symbol, leaps in state["managed_leaps"].items():
                if symbol not in positions_by_symbol:
                    continue
                if leaps.get("active_short_call"):
                    continue
                if _days_between(signal.as_of_date, leaps["expiration_date"]) <= settings.force_exit_days_to_expiry:
                    continue
                short_candidate = _select_short_call_candidate(broker, settings, signal.as_of_date, underlying_price)
                qty = int(abs(float(positions_by_symbol[symbol].get("qty", leaps["quantity"]))))
                actions.append(
                    PlannedAction(
                        action="sell_short_call_overlay",
                        symbol=short_candidate["symbol"],
                        quantity=qty,
                        side="sell",
                        order_preview=_build_limit_order(
                            symbol=short_candidate["symbol"],
                            qty=qty,
                            side="sell",
                            limit_price=short_candidate["mid_price"],
                            client_order_id=f"qqq-leaps-open-short-{signal.as_of_date.replace('-', '')}-{short_candidate['symbol'][-8:]}",
                        ),
                        reason="managed_leaps_open_without_short_call_overlay",
                        metadata={
                            "parent_leaps_symbol": symbol,
                            "expiration_date": short_candidate["expiration_date"],
                            "strike_price": short_candidate["strike_price"],
                            "mid_price": short_candidate["mid_price"],
                        },
                    )
                )

        if not actions and signal.regime_name:
            buying_power = _buying_power(account)
            already_bought_sigma1_this_week = False
            if signal.regime_name == "sigma1_weekly_1lot":
                latest_week = _week_key(signal.as_of_date)
                already_bought_sigma1_this_week = any(
                    item["regime_name"] == "sigma1_weekly_1lot" and _week_key(item["date"]) == latest_week
                    for item in state["entry_history"]
                )
            if already_bought_sigma1_this_week:
                warnings.append("Sigma1 buy signal is active, but this strategy already recorded a sigma1 entry this week.")
            else:
                long_candidate = _select_long_leaps_candidate(broker, settings, signal.as_of_date)
                contract_cost = long_candidate["mid_price"] * 100
                quantity = signal.target_quantity
                if quantity > 1 and buying_power < contract_cost * quantity and buying_power >= contract_cost:
                    quantity = 1
                if buying_power < contract_cost:
                    warnings.append("Signal is active, but current buying power does not cover even one LEAPS contract.")
                else:
                    actions.append(
                        PlannedAction(
                            action="buy_leaps",
                            symbol=long_candidate["symbol"],
                            quantity=quantity,
                            side="buy",
                            order_preview=_build_limit_order(
                                symbol=long_candidate["symbol"],
                                qty=quantity,
                                side="buy",
                                limit_price=long_candidate["mid_price"],
                                client_order_id=f"qqq-leaps-open-long-{signal.as_of_date.replace('-', '')}-{long_candidate['symbol'][-8:]}",
                            ),
                            reason=signal.buy_reason,
                            metadata={
                                "regime_name": signal.regime_name,
                                "expiration_date": long_candidate["expiration_date"],
                                "strike_price": long_candidate["strike_price"],
                                "delta": long_candidate["delta"],
                                "mid_price": long_candidate["mid_price"],
                            },
                        )
                    )

    return StrategyPlan(
        signal=signal.__dict__,
        warnings=warnings,
        unmanaged_positions=unmanaged_positions,
        open_orders=open_orders,
        actions=actions,
        state_summary=_managed_state_summary(state),
    )


def apply_submitted_orders(state: dict[str, Any], submitted_actions: list[tuple[PlannedAction, dict[str, Any]]], signal_date: str) -> None:
    for action, response in submitted_actions:
        payload = action.order_preview or {}
        if action.action == "buy_leaps":
            state["pending_orders"].append(
                {
                    "kind": "open_leaps",
                    "client_order_id": response.get("client_order_id", payload.get("client_order_id")),
                    "symbol": action.symbol,
                    "quantity": action.quantity,
                    "limit_price": float(payload["limit_price"]),
                    "entry_date": signal_date,
                    "regime_name": action.metadata["regime_name"],
                    "expiration_date": action.metadata["expiration_date"],
                    "strike_price": action.metadata["strike_price"],
                }
            )
        elif action.action == "sell_short_call_overlay":
            state["pending_orders"].append(
                {
                    "kind": "open_short_call",
                    "client_order_id": response.get("client_order_id", payload.get("client_order_id")),
                    "symbol": action.symbol,
                    "quantity": action.quantity,
                    "limit_price": float(payload["limit_price"]),
                    "entry_date": signal_date,
                    "parent_leaps_symbol": action.metadata["parent_leaps_symbol"],
                    "expiration_date": action.metadata["expiration_date"],
                    "strike_price": action.metadata["strike_price"],
                }
            )
        elif action.action == "buy_to_close_short_call":
            state["pending_orders"].append(
                {
                    "kind": "close_short_call",
                    "client_order_id": response.get("client_order_id", payload.get("client_order_id")),
                    "symbol": action.symbol,
                    "quantity": action.quantity,
                    "limit_price": float(payload["limit_price"]),
                    "entry_date": signal_date,
                    "parent_leaps_symbol": action.metadata["parent_leaps_symbol"],
                }
            )
        elif action.action == "sell_to_close_leaps":
            state["pending_orders"].append(
                {
                    "kind": "close_leaps",
                    "client_order_id": response.get("client_order_id", payload.get("client_order_id")),
                    "symbol": action.symbol,
                    "quantity": action.quantity,
                    "limit_price": float(payload["limit_price"]),
                    "entry_date": signal_date,
                }
            )

