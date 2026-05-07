"""Scenario PnL / payoff engine for structured SHFE option strategies."""

from __future__ import annotations

from datetime import datetime
from itertools import product
from typing import Any, Iterable

from tradingagents.options.analytics import DEFAULT_RISK_FREE_RATE
from tradingagents.options.pricing import black76_price
from tradingagents.options.strategies import build_option_strategy_candidate


def _round(value: float | None, digits: int = 8) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _cash(value: float | None, contract_multiplier: int, digits: int = 4) -> float | None:
    if value is None:
        return None
    return _round(float(value) * contract_multiplier, digits)


def _parse_date(value: str) -> datetime:
    s = str(value)
    if len(s) == 8 and s.isdigit():
        return datetime.strptime(s, "%Y%m%d")
    return datetime.strptime(s[:10], "%Y-%m-%d")


def _time_to_expiry(trade_date: str, expiry: str, days_forward: int) -> float:
    days = (_parse_date(expiry) - _parse_date(trade_date)).days - int(days_forward)
    return max(days, 0) / 365.0


def _as_list(values: Iterable[float | int]) -> list[float | int]:
    return list(values)


def _signed_multiplier(leg: dict[str, Any]) -> int:
    return (1 if leg["side"] == "BUY" else -1) * int(leg.get("quantity") or 1)


def _scenario_leg_value(
    leg: dict[str, Any],
    futures_price: float,
    time_to_expiry: float,
    risk_free_rate: float,
    iv_shock: float,
    contract_multiplier: int,
) -> dict[str, Any]:
    base_iv = leg.get("implied_volatility")
    scenario_iv = max(float(base_iv or 0.0) + float(iv_shock), 1e-6)
    option_value = black76_price(
        futures_price,
        float(leg["strike"]),
        time_to_expiry,
        risk_free_rate,
        scenario_iv,
        leg["call_put"],
    )
    signed_value = _signed_multiplier(leg) * option_value
    initial_signed_value = _signed_multiplier(leg) * float(leg.get("price") or 0.0)
    pnl = signed_value - initial_signed_value
    quantity = int(leg.get("quantity") or 1)
    return {
        "ts_code": leg.get("ts_code"),
        "side": leg["side"],
        "quantity": quantity,
        "call_put": leg["call_put"],
        "strike": leg["strike"],
        "expiry": leg["expiry"],
        "base_price": leg.get("price"),
        "base_iv": base_iv,
        "scenario_iv": _round(scenario_iv),
        "scenario_option_value": _round(option_value, 4),
        "scenario_option_value_cash": _cash(option_value * quantity, contract_multiplier),
        "signed_value": _round(signed_value, 4),
        "signed_value_cash": _cash(signed_value, contract_multiplier),
        "pnl": _round(pnl, 4),
        "pnl_cash": _cash(pnl, contract_multiplier),
    }


def _breakeven_proximity(underlying_price: float, breakevens: list[float]) -> float | None:
    if not breakevens:
        return None
    return _round(min(abs(float(item) - underlying_price) for item in breakevens), 4)


def _summary(scenarios: list[dict[str, Any]], breakevens: list[float], underlying_price: float) -> dict[str, Any]:
    worst = min(scenarios, key=lambda row: row["pnl"])
    best = max(scenarios, key=lambda row: row["pnl"])
    return {
        "worst_pnl": worst["pnl"],
        "worst_pnl_cash": worst.get("pnl_cash"),
        "best_pnl": best["pnl"],
        "best_pnl_cash": best.get("pnl_cash"),
        "worst_scenario": worst["scenario_id"],
        "best_scenario": best["scenario_id"],
        "breakeven_proximity": _breakeven_proximity(underlying_price, breakevens),
    }


def build_option_strategy_scenarios(
    symbol: str,
    strategy_type: str,
    trade_date: str | None = None,
    expiry: str | None = None,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    price_shocks: Iterable[float] = (-0.05, -0.03, -0.01, 0.0, 0.01, 0.03, 0.05),
    iv_shocks: Iterable[float] = (-0.05, -0.02, 0.0, 0.02, 0.05),
    days_forward: Iterable[int] = (0, 1, 5, 20),
    risk_budget_cash: float | None = None,
) -> dict[str, Any]:
    """Return a deterministic scenario PnL matrix for a structured strategy.

    PnL is expressed both in option-price points and in cash after applying the
    SHFE contract multiplier. IV shocks are absolute volatility points, e.g.
    ``0.02`` means +2 vol points.
    """
    strategy = build_option_strategy_candidate(
        symbol,
        strategy_type=strategy_type,
        trade_date=trade_date,
        expiry=expiry,
        risk_free_rate=risk_free_rate,
        risk_budget_cash=risk_budget_cash,
    )
    contract_multiplier = int(strategy.get("contract_multiplier") or 1)
    price_grid = [float(x) for x in _as_list(price_shocks)]
    iv_grid = [float(x) for x in _as_list(iv_shocks)]
    time_grid = [int(x) for x in _as_list(days_forward)]
    scenarios: list[dict[str, Any]] = []
    max_loss = strategy.get("max_loss")
    max_loss_cash = strategy.get("cash_risk", {}).get("max_loss_cash")
    initial_value = float(strategy.get("net_premium") or 0.0)
    for idx, (price_shock, iv_shock, days) in enumerate(product(price_grid, iv_grid, time_grid), start=1):
        scenario_underlying = float(strategy["underlying_price"]) * (1.0 + price_shock)
        t = _time_to_expiry(strategy["trade_date"], strategy["expiry"], days)
        leg_values = [
            _scenario_leg_value(leg, scenario_underlying, t, risk_free_rate, iv_shock, contract_multiplier)
            for leg in strategy["legs"]
        ]
        scenario_value = sum(float(row["signed_value"] or 0.0) for row in leg_values)
        pnl = scenario_value - initial_value
        scenario_value_cash = _cash(scenario_value, contract_multiplier)
        pnl_cash = _cash(pnl, contract_multiplier)
        scenarios.append(
            {
                "scenario_id": f"S{idx:03d}",
                "price_shock": price_shock,
                "iv_shock": iv_shock,
                "days_forward": days,
                "underlying_price": _round(scenario_underlying, 4),
                "time_to_expiry": _round(t),
                "scenario_value": _round(scenario_value, 4),
                "scenario_value_cash": scenario_value_cash,
                "pnl": _round(pnl, 4),
                "pnl_cash": pnl_cash,
                "pnl_pct_of_max_loss": _round(pnl / max_loss, 6) if max_loss else None,
                "pnl_pct_of_max_loss_cash": _round(pnl_cash / max_loss_cash, 6) if pnl_cash is not None and max_loss_cash else None,
                "pnl_pct_of_risk_budget": _round(pnl_cash / risk_budget_cash, 8) if pnl_cash is not None and risk_budget_cash else None,
                "leg_values": leg_values,
            }
        )
    return {
        "strategy": strategy,
        "cash_risk": strategy.get("cash_risk"),
        "scenario_grid": {
            "price_shocks": price_grid,
            "iv_shocks": iv_grid,
            "days_forward": time_grid,
        },
        "scenarios": scenarios,
        "summary": _summary(scenarios, strategy.get("breakevens") or [], float(strategy["underlying_price"])),
        "assumptions": {
            "model": "Black-76 futures option model",
            "price_basis": "option close + futures close",
            "pnl_unit": "option_price_points_and_cash",
            "iv_shock_unit": "absolute_vol_points",
            "contract_multiplier_applied": True,
            "contract_multiplier_source": "static SHFE futures contract specification mapping",
            "execution_note": "Scenario matrix is analytical only; verify live bid/ask, margin, and exchange rules before execution.",
        },
    }
