"""Historical replay and post-trade review for structured SHFE option strategies."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from tradingagents.options.data_loader import load_option_chain_snapshot
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


def _as_review_dates(entry_date: str, review_dates: Iterable[str] | None) -> list[str]:
    if review_dates is None:
        return [entry_date]
    dates = [str(item) for item in review_dates]
    return dates or [entry_date]


def _signed_multiplier(leg: dict[str, Any]) -> int:
    return (1 if leg["side"] == "BUY" else -1) * int(leg.get("quantity") or 1)


def _mark_leg(leg: dict[str, Any], quote_by_code: dict[str, Any], contract_multiplier: int) -> dict[str, Any]:
    ts_code = str(leg["ts_code"])
    row = quote_by_code.get(ts_code)
    if row is None:
        raise ValueError(f"Replay quote not found for entry leg {ts_code}")
    mark_price = row.mid_price
    if mark_price is None:
        raise ValueError(f"Replay quote has no valid close/settle price for entry leg {ts_code}")
    quantity = int(leg.get("quantity") or 1)
    signed = _signed_multiplier(leg)
    entry_price = float(leg.get("price") or 0.0)
    mark_value = signed * float(mark_price)
    entry_value = signed * entry_price
    pnl = mark_value - entry_value
    return {
        "ts_code": ts_code,
        "side": leg["side"],
        "quantity": quantity,
        "call_put": leg["call_put"],
        "strike": leg["strike"],
        "expiry": leg["expiry"],
        "entry_price": entry_price,
        "mark_price": float(mark_price),
        "signed_entry_value": _round(entry_value, 4),
        "signed_mark_value": _round(mark_value, 4),
        "pnl": _round(pnl, 4),
        "pnl_cash": _cash(pnl, contract_multiplier),
    }


def _mark_strategy(
    *,
    entry_strategy: dict[str, Any],
    review_date: str,
    expiry: str | None,
) -> dict[str, Any]:
    contract_multiplier = int(entry_strategy.get("contract_multiplier") or 1)
    snapshot = load_option_chain_snapshot(entry_strategy["product"], trade_date=review_date, expiry=expiry)
    quote_by_code = {row.ts_code: row for row in snapshot.options}
    leg_marks = [_mark_leg(leg, quote_by_code, contract_multiplier) for leg in entry_strategy["legs"]]
    mark_value = sum(float(row["signed_mark_value"] or 0.0) for row in leg_marks)
    entry_value = float(entry_strategy.get("net_premium") or 0.0)
    pnl = mark_value - entry_value
    pnl_cash = _cash(pnl, contract_multiplier)
    margin_required_cash = entry_strategy.get("margin", {}).get("margin_required_cash")
    return {
        "trade_date": snapshot.trade_date,
        "underlying_symbol": snapshot.underlying_symbol,
        "underlying_price": snapshot.underlying_price,
        "mark_value": _round(mark_value, 4),
        "mark_value_cash": _cash(mark_value, contract_multiplier),
        "entry_value": entry_value,
        "entry_value_cash": _cash(entry_value, contract_multiplier),
        "pnl": _round(pnl, 4),
        "pnl_cash": pnl_cash,
        "pnl_pct_of_entry_value": _round(pnl / abs(entry_value), 8) if entry_value else None,
        "pnl_pct_of_margin": _round(pnl_cash / margin_required_cash, 8) if pnl_cash is not None and margin_required_cash else None,
        "leg_marks": leg_marks,
    }


def _post_trade_review(final_mark: dict[str, Any]) -> dict[str, Any]:
    pnl_cash = float(final_mark.get("pnl_cash") or 0.0)
    if pnl_cash > 0:
        outcome = "profitable"
        diagnosis = "Favorable post-trade replay: marked PnL is positive versus the entry structure."
    elif pnl_cash < 0:
        outcome = "loss_making"
        diagnosis = "Adverse post-trade replay: marked PnL is negative versus the entry structure."
    else:
        outcome = "flat"
        diagnosis = "Flat post-trade replay: marked PnL is unchanged versus the entry structure."
    return {
        "outcome": outcome,
        "diagnosis": diagnosis,
        "final_trade_date": final_mark["trade_date"],
        "final_pnl_cash": final_mark.get("pnl_cash"),
    }


def _summary(marks: list[dict[str, Any]]) -> dict[str, Any]:
    final = marks[-1]
    best = max(marks, key=lambda row: float(row.get("pnl_cash") or 0.0))
    worst = min(marks, key=lambda row: float(row.get("pnl_cash") or 0.0))
    return {
        "review_count": len(marks),
        "final_trade_date": final["trade_date"],
        "final_pnl": final.get("pnl"),
        "final_pnl_cash": final.get("pnl_cash"),
        "best_trade_date": best["trade_date"],
        "best_pnl_cash": best.get("pnl_cash"),
        "worst_trade_date": worst["trade_date"],
        "worst_pnl_cash": worst.get("pnl_cash"),
        "post_trade_review": _post_trade_review(final),
    }


def build_option_strategy_replay(
    symbol: str,
    strategy_type: str,
    entry_date: str,
    review_dates: Iterable[str] | None = None,
    expiry: str | None = None,
    risk_budget_cash: float | None = None,
) -> dict[str, Any]:
    """Replay an entry strategy over historical review dates using option close prices.

    The entry structure is selected deterministically on ``entry_date``.  Each
    review date marks the same entry legs by ``ts_code`` using Alan's default
    trading-analysis basis: option close plus futures close.
    """
    entry_strategy = build_option_strategy_candidate(
        symbol,
        strategy_type=strategy_type,
        trade_date=entry_date,
        expiry=expiry,
        risk_budget_cash=risk_budget_cash,
    )
    contract_multiplier = int(entry_strategy.get("contract_multiplier") or 1)
    dates = _as_review_dates(entry_date, review_dates)
    marks = [_mark_strategy(entry_strategy=entry_strategy, review_date=date, expiry=expiry) for date in dates]
    return {
        "strategy_type": entry_strategy["strategy_type"],
        "product": entry_strategy["product"],
        "entry": {
            "trade_date": entry_strategy["trade_date"],
            "underlying_symbol": entry_strategy["underlying_symbol"],
            "underlying_price": entry_strategy["underlying_price"],
            "expiry": entry_strategy["expiry"],
            "net_premium": entry_strategy["net_premium"],
            "net_premium_cash": _cash(entry_strategy.get("net_premium"), contract_multiplier),
            "margin_required_cash": entry_strategy.get("margin", {}).get("margin_required_cash"),
            "risk_budget": entry_strategy.get("risk_budget"),
            "legs": entry_strategy["legs"],
        },
        "marks": marks,
        "summary": _summary(marks),
        "assumptions": {
            "replay_price_basis": "option close + futures close",
            "entry_selection": "deterministic strategy structurer on entry_date",
            "same_legs_marked_by_ts_code": True,
            "post_trade_review": True,
            "fees_and_slippage_after_entry_modeled": False,
            "date_order_days": [(_parse_date(date) - _parse_date(entry_date)).days for date in dates],
        },
    }
