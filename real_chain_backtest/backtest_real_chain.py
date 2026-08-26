from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.dataset as ds


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUTPUT = ROOT / "outputs"
START = pd.Timestamp("2020-12-16")
END = pd.Timestamp("2025-12-15")
INITIAL_CAPITAL = 20_000.0
MULTIPLIER = 100

SCENARIOS = {
    "mid": 0.0,
    "spread_25pct_half": 0.25,
    "spread_50pct_half": 0.50,
    "ask_buy_bid_sell": 1.0,
}


@dataclass
class LongPosition:
    contract_id: str
    entry_date: pd.Timestamp
    expiration: pd.Timestamp
    strike: float
    quantity: int
    regime: str
    entry_fill: float
    entry_cost: float
    entry_delta: float
    entry_dte: int
    entry_rsi: float
    entry_vix: float
    entry_vix_mean: float
    entry_vix_std: float
    realized_short_cash: float = 0.0
    short_call: "ShortPosition | None" = None
    short_events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ShortPosition:
    contract_id: str
    entry_date: pd.Timestamp
    expiration: pd.Timestamp
    strike: float
    quantity: int
    entry_fill: float


def wilder_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = pd.Series(np.nan, index=series.index, dtype=float)
    avg_loss = pd.Series(np.nan, index=series.index, dtype=float)
    if len(series) <= period:
        return avg_gain
    avg_gain.iloc[period] = gains.iloc[1 : period + 1].mean()
    avg_loss.iloc[period] = losses.iloc[1 : period + 1].mean()
    for index in range(period + 1, len(series)):
        avg_gain.iloc[index] = (avg_gain.iloc[index - 1] * (period - 1) + gains.iloc[index]) / period
        avg_loss.iloc[index] = (avg_loss.iloc[index - 1] * (period - 1) + losses.iloc[index]) / period
    relative_strength = avg_gain / avg_loss
    result = 100 - 100 / (1 + relative_strength)
    result[(avg_loss == 0) & (avg_gain > 0)] = 100
    return result


def load_market_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    qqq = pd.read_parquet(DATA / "QQQ_underlying.parquet")
    qqq["date"] = pd.to_datetime(qqq["date"])
    qqq = qqq.sort_values("date").drop_duplicates("date")
    qqq["rsi"] = wilder_rsi(qqq["adjusted_close"], 14)

    vix = pd.read_csv(DATA / "VIX_History.csv")
    vix["date"] = pd.to_datetime(vix["DATE"], format="%m/%d/%Y")
    vix = vix.rename(columns={"CLOSE": "vix"}).sort_values("date")
    vix["vix_mean"] = vix["vix"].shift(1).expanding(min_periods=1000).mean()
    vix["vix_std"] = vix["vix"].shift(1).expanding(min_periods=1000).std(ddof=1)

    market = qqq[["date", "close", "adjusted_close", "rsi"]].merge(
        vix[["date", "vix", "vix_mean", "vix_std"]], on="date", how="inner"
    )
    market = market[(market["date"] >= START) & (market["date"] <= END)].copy()
    market = market.sort_values("date").reset_index(drop=True)

    dataset = ds.dataset(DATA / "QQQ_options.parquet", format="parquet")
    option_filter = (
        (ds.field("type") == "call")
        & (ds.field("date") >= START.to_pydatetime())
        & (ds.field("date") <= END.to_pydatetime())
    )
    options = dataset.to_table(
        columns=[
            "contract_id",
            "date",
            "expiration",
            "strike",
            "bid",
            "ask",
            "mark",
            "delta",
            "implied_volatility",
            "volume",
            "open_interest",
        ],
        filter=option_filter,
    ).to_pandas()
    options["dte"] = (options["expiration"] - options["date"]).dt.days
    options["mid"] = (options["bid"] + options["ask"]) / 2
    options["spread_pct"] = (options["ask"] - options["bid"]) / options["mid"].where(options["mid"] > 0)
    options = options.sort_values(["date", "contract_id"]).reset_index(drop=True)
    return market, options


def valid_quote(row: pd.Series) -> bool:
    return bool(row["bid"] > 0 and row["ask"] > 0 and row["ask"] >= row["bid"])


def buy_fill(row: pd.Series, half_spread_fraction: float) -> float:
    return float(row["mid"] + half_spread_fraction * (row["ask"] - row["bid"]) / 2)


def sell_fill(row: pd.Series, half_spread_fraction: float) -> float:
    return float(row["mid"] - half_spread_fraction * (row["ask"] - row["bid"]) / 2)


def quote_for(chain: pd.DataFrame, contract_id: str) -> pd.Series | None:
    rows = chain[chain["contract_id"] == contract_id]
    return None if rows.empty else rows.iloc[0]


def select_long(chain: pd.DataFrame, target_dte: int, tolerance: int) -> pd.Series | None:
    candidates = chain[
        (chain["dte"] >= target_dte - tolerance)
        & (chain["dte"] <= target_dte + tolerance)
        & (chain["delta"] >= 0.65)
        & (chain["delta"] <= 0.75)
        & (chain["bid"] > 0)
        & (chain["ask"] > 0)
        & (chain["ask"] >= chain["bid"])
        & (chain["spread_pct"] <= 0.10)
    ].copy()
    if candidates.empty:
        return None
    candidates["delta_error"] = (candidates["delta"] - 0.70).abs()
    candidates["dte_error"] = (candidates["dte"] - target_dte).abs()
    return candidates.sort_values(["delta_error", "dte_error", "strike", "contract_id"]).iloc[0]


def select_short(chain: pd.DataFrame, underlying: float) -> pd.Series | None:
    target_strike = underlying * 1.10
    candidates = chain[
        (chain["dte"] >= 25)
        & (chain["dte"] <= 35)
        & (chain["strike"] >= target_strike)
        & (chain["bid"] > 0)
        & (chain["ask"] > 0)
        & (chain["ask"] >= chain["bid"])
    ].copy()
    if candidates.empty:
        return None
    candidates["dte_error"] = (candidates["dte"] - 30).abs()
    candidates["strike_error"] = (candidates["strike"] - target_strike).abs()
    return candidates.sort_values(["dte_error", "strike_error", "strike", "contract_id"]).iloc[0]


def market_level(row: pd.Series) -> int:
    if not math.isfinite(row["rsi"]) or row["rsi"] >= 35:
        return 0
    if row["vix"] >= row["vix_mean"] + 2 * row["vix_std"]:
        return 2
    if row["vix"] >= row["vix_mean"] + row["vix_std"]:
        return 1
    return 0


def value_position(position: LongPosition, chain: pd.DataFrame) -> tuple[float | None, float]:
    long_quote = quote_for(chain, position.contract_id)
    if long_quote is None or not valid_quote(long_quote):
        return None, 0.0
    long_value = float(long_quote["mid"]) * MULTIPLIER * position.quantity
    short_liability = 0.0
    if position.short_call is not None:
        short_quote = quote_for(chain, position.short_call.contract_id)
        if short_quote is not None and valid_quote(short_quote):
            short_liability = float(short_quote["mid"]) * MULTIPLIER * position.short_call.quantity
    return long_value + position.realized_short_cash - short_liability, short_liability


def performance(equity: pd.DataFrame) -> dict[str, float]:
    if equity.empty:
        return {}
    values = equity["equity"].astype(float)
    daily = values.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    years = (equity["date"].iloc[-1] - equity["date"].iloc[0]).days / 365.25
    peak = values.cummax()
    drawdown = values / peak - 1
    cagr = (values.iloc[-1] / INITIAL_CAPITAL) ** (1 / years) - 1 if years > 0 else np.nan
    vol = daily.std(ddof=1) * math.sqrt(252) if len(daily) > 1 else np.nan
    sharpe = (daily.mean() * 252 - 0.03) / vol if vol and vol > 0 else np.nan
    return {
        "start_equity": INITIAL_CAPITAL,
        "ending_equity": float(values.iloc[-1]),
        "total_return": float(values.iloc[-1] / INITIAL_CAPITAL - 1),
        "cagr": float(cagr),
        "annualized_volatility": float(vol),
        "sharpe_3pct": float(sharpe),
        "max_drawdown": float(drawdown.min()),
    }


def run_strategy(
    market: pd.DataFrame,
    options: pd.DataFrame,
    strategy: str,
    scenario: str,
    half_spread_fraction: float,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    option_dates = options["date"].to_numpy()
    unique_dates, starts, counts = np.unique(option_dates, return_index=True, return_counts=True)
    date_slices = {
        pd.Timestamp(date): (int(start), int(start + count))
        for date, start, count in zip(unique_dates, starts, counts)
    }
    positions: list[LongPosition] = []
    trades: list[dict[str, Any]] = []
    short_events: list[dict[str, Any]] = []
    curve: list[dict[str, Any]] = []
    cash = INITIAL_CAPITAL
    skipped_no_chain = 0
    skipped_cash = 0
    skipped_missing_exit_quote = 0
    last_sigma1_week: tuple[int, int] | None = None
    sigma2_indexes: list[int] = []

    for index, row in market.iterrows():
        date = row["date"]
        if date not in date_slices:
            continue
        slice_start, slice_end = date_slices[date]
        chain = options.iloc[slice_start:slice_end]

        # Settle expired short calls at intrinsic value before evaluating the LEAPS.
        if strategy == "deployed":
            for position in positions:
                short = position.short_call
                if short is not None and date >= short.expiration:
                    settlement = max(0.0, float(row["close"]) - short.strike) * MULTIPLIER * short.quantity
                    position.realized_short_cash -= settlement
                    cash -= settlement
                    event = {
                        "strategy": strategy,
                        "scenario": scenario,
                        "date": date,
                        "event": "short_expiry_settlement",
                        "contract_id": short.contract_id,
                        "cash_flow": -settlement,
                    }
                    position.short_events.append(event)
                    short_events.append(event)
                    position.short_call = None

        for position in list(reversed(positions)):
            quote = quote_for(chain, position.contract_id)
            if quote is None or not valid_quote(quote):
                continue
            net_value, _ = value_position(position, chain)
            if net_value is None:
                continue
            pnl_pct = (net_value - position.entry_cost) / position.entry_cost
            age_days = (date - position.entry_date).days
            dte = (position.expiration - date).days
            sigma2 = position.regime.startswith("sigma2")
            reason = None
            if strategy == "dte_v1":
                if 457 <= dte <= 548 and pnl_pct >= 0.30:
                    reason = "take_profit_30_dte_457_548"
                elif 365 <= dte <= 456 and pnl_pct >= (0.80 if sigma2 else 0.60):
                    reason = "take_profit_mid_dte"
                elif 181 <= dte <= 364 and pnl_pct >= (1.50 if sigma2 else 1.20):
                    reason = "take_profit_low_dte"
            else:
                if 0 <= age_days <= 364 and pnl_pct >= (1.50 if sigma2 else 1.20):
                    reason = "take_profit_before_12m"
                elif 365 <= age_days <= 456 and pnl_pct >= (0.80 if sigma2 else 0.60):
                    reason = "take_profit_12_to_15m"
                elif 457 <= age_days <= 548 and pnl_pct >= 0.30:
                    reason = "take_profit_16_to_18m"
            if reason is None and dte <= 180:
                reason = "force_exit_180_dte"
            if reason is None:
                continue

            short_close_cost = 0.0
            if position.short_call is not None:
                short_quote = quote_for(chain, position.short_call.contract_id)
                if short_quote is None or not valid_quote(short_quote):
                    skipped_missing_exit_quote += 1
                    continue
                short_close_fill = buy_fill(short_quote, half_spread_fraction)
                short_close_cost = short_close_fill * MULTIPLIER * position.short_call.quantity
                position.realized_short_cash -= short_close_cost
                cash -= short_close_cost
                event = {
                    "strategy": strategy,
                    "scenario": scenario,
                    "date": date,
                    "event": "buy_to_close_short",
                    "contract_id": position.short_call.contract_id,
                    "fill": short_close_fill,
                    "cash_flow": -short_close_cost,
                }
                position.short_events.append(event)
                short_events.append(event)
                position.short_call = None

            exit_fill = sell_fill(quote, half_spread_fraction)
            exit_proceeds = exit_fill * MULTIPLIER * position.quantity
            cash += exit_proceeds
            total_exit_value = exit_proceeds + position.realized_short_cash
            trades.append(
                {
                    "strategy": strategy,
                    "scenario": scenario,
                    "entry_date": position.entry_date,
                    "exit_date": date,
                    "contract_id": position.contract_id,
                    "expiration": position.expiration,
                    "strike": position.strike,
                    "quantity": position.quantity,
                    "regime": position.regime,
                    "entry_delta": position.entry_delta,
                    "entry_dte": position.entry_dte,
                    "entry_fill": position.entry_fill,
                    "entry_cost": position.entry_cost,
                    "exit_fill": exit_fill,
                    "exit_proceeds": exit_proceeds,
                    "short_net_cash": position.realized_short_cash,
                    "total_exit_value": total_exit_value,
                    "pnl": total_exit_value - position.entry_cost,
                    "pnl_pct": total_exit_value / position.entry_cost - 1,
                    "reason": reason,
                    "age_days": age_days,
                }
            )
            positions.remove(position)

        level = market_level(row)
        regime = None
        quantity = 0
        if strategy == "dte_v1":
            previous_level = market_level(market.iloc[index - 1]) if index > 0 else 0
            if level > 0 and level != previous_level:
                regime = "sigma2_edge_1lot" if level == 2 else "sigma1_edge_1lot"
                quantity = 1
        else:
            sigma2_today = level == 2
            count60 = sum(1 for prior in sigma2_indexes if prior >= index - 59) + (1 if sigma2_today else 0)
            count20 = sum(1 for prior in sigma2_indexes if prior >= index - 19) + (1 if sigma2_today else 0)
            if level == 2 and count60 == 1:
                regime, quantity = "sigma2_first_60d_1lot", 1
            elif level == 2 and count20 >= 2:
                regime, quantity = "sigma2_repeat_20d_2lot", 2
            elif level == 1:
                week = date.isocalendar()
                week_key = (int(week.year), int(week.week))
                if week_key != last_sigma1_week:
                    regime, quantity = "sigma1_weekly_1lot", 1
            if sigma2_today:
                sigma2_indexes.append(index)

        if regime is not None:
            candidate = select_long(chain, 680 if strategy == "dte_v1" else 730, 50 if strategy == "dte_v1" else 120)
            if candidate is None:
                skipped_no_chain += 1
            else:
                fill = buy_fill(candidate, half_spread_fraction)
                per_contract = fill * MULTIPLIER
                actual_quantity = quantity
                if strategy == "deployed" and quantity == 2 and cash < 2 * per_contract and cash >= per_contract:
                    actual_quantity = 1
                cost = per_contract * actual_quantity
                if actual_quantity > 0 and cash >= cost:
                    cash -= cost
                    positions.append(
                        LongPosition(
                            contract_id=str(candidate["contract_id"]),
                            entry_date=date,
                            expiration=candidate["expiration"],
                            strike=float(candidate["strike"]),
                            quantity=actual_quantity,
                            regime=regime,
                            entry_fill=fill,
                            entry_cost=cost,
                            entry_delta=float(candidate["delta"]),
                            entry_dte=int(candidate["dte"]),
                            entry_rsi=float(row["rsi"]),
                            entry_vix=float(row["vix"]),
                            entry_vix_mean=float(row["vix_mean"]),
                            entry_vix_std=float(row["vix_std"]),
                        )
                    )
                    if regime == "sigma1_weekly_1lot":
                        week = date.isocalendar()
                        last_sigma1_week = (int(week.year), int(week.week))
                else:
                    skipped_cash += 1

        if strategy == "deployed":
            for position in positions:
                if position.short_call is not None or (position.expiration - date).days <= 180:
                    continue
                candidate = select_short(chain, float(row["close"]))
                if candidate is None:
                    continue
                fill = sell_fill(candidate, half_spread_fraction)
                premium = fill * MULTIPLIER * position.quantity
                position.realized_short_cash += premium
                cash += premium
                position.short_call = ShortPosition(
                    contract_id=str(candidate["contract_id"]),
                    entry_date=date,
                    expiration=candidate["expiration"],
                    strike=float(candidate["strike"]),
                    quantity=position.quantity,
                    entry_fill=fill,
                )
                event = {
                    "strategy": strategy,
                    "scenario": scenario,
                    "date": date,
                    "event": "sell_short_call",
                    "contract_id": str(candidate["contract_id"]),
                    "fill": fill,
                    "cash_flow": premium,
                }
                position.short_events.append(event)
                short_events.append(event)

        open_mid_value = 0.0
        short_liability = 0.0
        missing_marks = 0
        for position in positions:
            long_quote = quote_for(chain, position.contract_id)
            if long_quote is None or not valid_quote(long_quote):
                missing_marks += 1
                continue
            long_mid_value = float(long_quote["mid"]) * MULTIPLIER * position.quantity
            liability = 0.0
            if position.short_call is not None:
                short_quote = quote_for(chain, position.short_call.contract_id)
                if short_quote is not None and valid_quote(short_quote):
                    liability = float(short_quote["mid"]) * MULTIPLIER * position.short_call.quantity
            open_mid_value += long_mid_value - liability
            short_liability += liability
        curve.append(
            {
                "strategy": strategy,
                "scenario": scenario,
                "date": date,
                "equity": cash + open_mid_value,
                "cash": cash,
                "open_net_mid_value": open_mid_value,
                "short_mid_liability": short_liability,
                "open_long_positions": len(positions),
                "missing_position_marks": missing_marks,
                "qqq_close": float(row["close"]),
                "rsi": float(row["rsi"]),
                "vix": float(row["vix"]),
            }
        )

    equity = pd.DataFrame(curve)
    trades_df = pd.DataFrame(trades)
    shorts_df = pd.DataFrame(short_events)
    metrics = performance(equity)
    metrics.update(
        {
            "strategy": strategy,
            "scenario": scenario,
            "window_start": START.date().isoformat(),
            "window_end": END.date().isoformat(),
            "initial_capital": INITIAL_CAPITAL,
            "closed_trade_count": len(trades_df),
            "open_position_count": len(positions),
            "contracts_entered": int(trades_df["quantity"].sum()) + sum(p.quantity for p in positions) if not trades_df.empty else sum(p.quantity for p in positions),
            "realized_pnl_closed_longs_and_overlay": float(trades_df["pnl"].sum()) if not trades_df.empty else 0.0,
            "ending_cash": cash,
            "ending_open_net_mid_value": float(equity.iloc[-1]["open_net_mid_value"]) if not equity.empty else 0.0,
            "skipped_signal_no_qualifying_chain": skipped_no_chain,
            "skipped_signal_insufficient_cash": skipped_cash,
            "skipped_exit_missing_quote": skipped_missing_exit_quote,
            "short_event_count": len(shorts_df),
        }
    )
    open_rows = pd.DataFrame(
        [
            {
                "strategy": strategy,
                "scenario": scenario,
                "contract_id": position.contract_id,
                "entry_date": position.entry_date,
                "expiration": position.expiration,
                "strike": position.strike,
                "quantity": position.quantity,
                "entry_fill": position.entry_fill,
                "entry_cost": position.entry_cost,
                "realized_short_cash": position.realized_short_cash,
                "active_short_contract": position.short_call.contract_id if position.short_call else "",
            }
            for position in positions
        ]
    )
    return metrics, equity, trades_df, pd.concat([shorts_df, open_rows], ignore_index=True, sort=False)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    market, options = load_market_data()
    all_metrics: list[dict[str, Any]] = []
    all_equity: list[pd.DataFrame] = []
    all_trades: list[pd.DataFrame] = []
    all_events: list[pd.DataFrame] = []

    for strategy in ("dte_v1", "deployed"):
        for scenario, fraction in SCENARIOS.items():
            metrics, equity, trades, events = run_strategy(market, options, strategy, scenario, fraction)
            all_metrics.append(metrics)
            all_equity.append(equity)
            if not trades.empty:
                all_trades.append(trades)
            if not events.empty:
                all_events.append(events)
            print(strategy, scenario, metrics["ending_equity"], metrics["total_return"])

    metrics_df = pd.DataFrame(all_metrics)
    metrics_df.to_csv(OUTPUT / "real_chain_scenario_metrics.csv", index=False)
    pd.concat(all_equity, ignore_index=True).to_csv(OUTPUT / "real_chain_equity_curves.csv", index=False)
    (pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()).to_csv(
        OUTPUT / "real_chain_trades.csv", index=False
    )
    (pd.concat(all_events, ignore_index=True, sort=False) if all_events else pd.DataFrame()).to_csv(
        OUTPUT / "real_chain_short_events_and_open_positions.csv", index=False
    )
    (OUTPUT / "real_chain_scenario_metrics.json").write_text(
        json.dumps(all_metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
