"""Historical replay and post-trade review for structured SHFE option strategies."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from tradingagents.options.analytics import analyze_option_chain
from tradingagents.options.data_loader import format_iso, load_option_chain_snapshot
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


def _as_review_dates(entry_date: str, review_dates: Iterable[str] | None) -> tuple[list[str], list[str]]:
    raw_dates = [entry_date] if review_dates is None else [str(item) for item in review_dates]
    if not raw_dates:
        raw_dates = [entry_date]
    input_dates = [format_iso(item) or str(item) for item in raw_dates]
    entry_dt = _parse_date(entry_date)
    for item in input_dates:
        if _parse_date(item) < entry_dt:
            raise ValueError(f"review_date {item!r} is before entry_date {format_iso(entry_date)!r}")
    resolved_dates = sorted(input_dates, key=_parse_date)
    return input_dates, resolved_dates


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
    iv_context = _mark_iv_context(entry_strategy["product"], snapshot.trade_date, expiry)
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
        "iv_context": iv_context,
        "leg_marks": leg_marks,
    }


def _iv_regime(atm_iv: float | None) -> str:
    if atm_iv is None:
        return "unknown"
    if atm_iv < 0.20:
        return "low_iv"
    if atm_iv < 0.35:
        return "moderate_iv"
    return "high_iv"


def _mark_iv_context(product: str, trade_date: str, expiry: str | None) -> dict[str, Any]:
    try:
        report = analyze_option_chain(product, trade_date=trade_date, expiry=expiry)
    except Exception as exc:
        return {
            "atm_iv": None,
            "iv_regime": "unknown",
            "term_shape": None,
            "risk_reversal_proxy": None,
            "smile_curvature_proxy": None,
            "error": str(exc),
        }
    surface = report.vol_surface or {}
    return {
        "atm_iv": _round(report.atm_iv),
        "iv_regime": _iv_regime(report.atm_iv),
        "term_shape": (surface.get("term_regime") or {}).get("shape"),
        "risk_reversal_proxy": _round((surface.get("skew") or {}).get("risk_reversal_proxy")),
        "smile_curvature_proxy": _round((surface.get("skew") or {}).get("smile_curvature_proxy")),
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


def _performance_summary(marks: list[dict[str, Any]]) -> dict[str, Any]:
    pnl_values = [float(mark.get("pnl_cash") or 0.0) for mark in marks]
    positive = [value for value in pnl_values if value > 0]
    negative = [value for value in pnl_values if value < 0]
    flat = [value for value in pnl_values if value == 0]
    running_peak = pnl_values[0] if pnl_values else 0.0
    max_drawdown = 0.0
    pnl_path: list[dict[str, Any]] = []
    regime_buckets: dict[str, dict[str, Any]] = {}

    for mark, pnl_cash in zip(marks, pnl_values):
        running_peak = max(running_peak, pnl_cash)
        max_drawdown = max(max_drawdown, running_peak - pnl_cash)
        iv_context = mark.get("iv_context") or {}
        regime = iv_context.get("iv_regime") or "unknown"
        row = {
            "trade_date": mark.get("trade_date"),
            "underlying_price": mark.get("underlying_price"),
            "pnl_cash": mark.get("pnl_cash"),
            "pnl_pct_of_margin": mark.get("pnl_pct_of_margin"),
            "atm_iv": iv_context.get("atm_iv"),
            "iv_regime": regime,
            "term_shape": iv_context.get("term_shape"),
        }
        pnl_path.append(row)
        bucket = regime_buckets.setdefault(
            regime,
            {"count": 0, "average_pnl_cash": 0.0, "best_pnl_cash": None, "worst_pnl_cash": None},
        )
        bucket["count"] += 1
        bucket["average_pnl_cash"] += pnl_cash
        bucket["best_pnl_cash"] = pnl_cash if bucket["best_pnl_cash"] is None else max(float(bucket["best_pnl_cash"]), pnl_cash)
        bucket["worst_pnl_cash"] = pnl_cash if bucket["worst_pnl_cash"] is None else min(float(bucket["worst_pnl_cash"]), pnl_cash)

    for bucket in regime_buckets.values():
        if bucket["count"]:
            bucket["average_pnl_cash"] = _round(float(bucket["average_pnl_cash"]) / int(bucket["count"]), 4)
        bucket["best_pnl_cash"] = _round(bucket["best_pnl_cash"], 4)
        bucket["worst_pnl_cash"] = _round(bucket["worst_pnl_cash"], 4)

    count = len(pnl_values)
    return {
        "summary_type": "option_replay_performance_distribution",
        "review_count": count,
        "winning_mark_count": len(positive),
        "losing_mark_count": len(negative),
        "flat_mark_count": len(flat),
        "win_rate": _round(len(positive) / count, 8) if count else None,
        "average_pnl_cash": _round(sum(pnl_values) / count, 4) if count else None,
        "median_pnl_cash": _round(sorted(pnl_values)[count // 2], 4) if count else None,
        "final_pnl_cash": _round(pnl_values[-1], 4) if pnl_values else None,
        "max_drawdown_cash": _round(max_drawdown, 4),
        "pnl_path": pnl_path,
        "iv_regime_breakdown": regime_buckets,
        "notes": [
            "Performance distribution is based on deterministic mark-to-market replay of the same entry legs by ts_code.",
            "IV regime buckets are diagnostics from close-based implied volatility snapshots, not executable volatility quotes.",
        ],
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
    input_review_dates, dates = _as_review_dates(entry_date, review_dates)
    marks = [_mark_strategy(entry_strategy=entry_strategy, review_date=date, expiry=expiry) for date in dates]
    performance_summary = _performance_summary(marks)
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
        "input_review_dates": input_review_dates,
        "resolved_review_dates": dates,
        "marks": marks,
        "summary": _summary(marks),
        "performance_summary": performance_summary,
        "assumptions": {
            "replay_price_basis": "option close + futures close",
            "entry_selection": "deterministic strategy structurer on entry_date",
            "same_legs_marked_by_ts_code": True,
            "post_trade_review": True,
            "performance_distribution_included": True,
            "review_date_ordering": "chronological",
            "input_review_dates": input_review_dates,
            "resolved_review_dates": dates,
            "iv_regime_grouping": "close_based_atm_iv_diagnostic",
            "fees_and_slippage_after_entry_modeled": False,
            "date_order_days": [(_parse_date(date) - _parse_date(entry_date)).days for date in dates],
        },
    }
