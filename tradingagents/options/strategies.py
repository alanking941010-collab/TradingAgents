"""Deterministic option strategy structurer for SHFE options.

The strategy structurer turns the option analytics report into auditable option
combination candidates. It does not decide whether a trade should be taken;
TradingAgents' trader/risk/portfolio agents interpret these candidates.
"""

from __future__ import annotations

from typing import Any

from tradingagents.options.analytics import DEFAULT_RISK_FREE_RATE, analyze_option_chain
from tradingagents.options.contract_specs import contract_multiplier_for_product, multiplier_unit_for_product
from tradingagents.options.data_loader import format_iso
from tradingagents.options.models import EnrichedOptionQuote


_SUPPORTED_STRATEGIES = {
    "bull_call_spread",
    "bear_put_spread",
    "long_straddle",
    "long_strangle",
    "long_call_butterfly",
    "long_put_butterfly",
    "short_iron_condor",
}


def _round(value: float | None, digits: int = 8) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _rows_for_expiry(rows: list[EnrichedOptionQuote], expiry: str | None) -> list[EnrichedOptionQuote]:
    liquid = [row for row in rows if row.quote.mid_price is not None and row.greeks is not None]
    if not liquid:
        raise ValueError("No priced option rows available for strategy structuring")
    target = format_iso(expiry) if expiry else min(row.quote.maturity_date for row in liquid)
    selected = [row for row in liquid if row.quote.maturity_date == target]
    if not selected:
        raise ValueError(f"No priced option rows available for expiry={expiry!r}")
    return selected


def _by_type(rows: list[EnrichedOptionQuote], call_put: str) -> list[EnrichedOptionQuote]:
    selected = sorted([row for row in rows if row.quote.call_put == call_put], key=lambda row: row.quote.strike)
    if not selected:
        raise ValueError(f"No {call_put} option rows available")
    return selected


def _nearest_strike(rows: list[EnrichedOptionQuote], underlying_price: float) -> float:
    strikes = sorted({row.quote.strike for row in rows})
    return min(strikes, key=lambda strike: (abs(strike - underlying_price), strike))


def _row_at(rows: list[EnrichedOptionQuote], call_put: str, strike: float) -> EnrichedOptionQuote:
    for row in rows:
        if row.quote.call_put == call_put and row.quote.strike == strike:
            return row
    raise ValueError(f"Missing {call_put} option at strike={strike}")


def _next_higher(strikes: list[float], strike: float) -> float:
    for item in sorted(strikes):
        if item > strike:
            return item
    raise ValueError("Cannot find higher strike for spread")


def _next_lower(strikes: list[float], strike: float) -> float:
    for item in sorted(strikes, reverse=True):
        if item < strike:
            return item
    raise ValueError("Cannot find lower strike for spread")


def _nth_higher(strikes: list[float], strike: float, n: int) -> float:
    higher = [item for item in sorted(strikes) if item > strike]
    if len(higher) < n:
        raise ValueError(f"Cannot find {n} higher strikes for spread")
    return higher[n - 1]


def _nth_lower(strikes: list[float], strike: float, n: int) -> float:
    lower = [item for item in sorted(strikes, reverse=True) if item < strike]
    if len(lower) < n:
        raise ValueError(f"Cannot find {n} lower strikes for spread")
    return lower[n - 1]


def _cash(value: float | None, contract_multiplier: int, digits: int = 4) -> float | None:
    if value is None:
        return None
    return _round(float(value) * contract_multiplier, digits)


def _leg(row: EnrichedOptionQuote, side: str, quantity: int = 1, contract_multiplier: int = 1) -> dict[str, Any]:
    greeks = row.greeks
    price = row.quote.mid_price
    bid = row.quote.bid if row.quote.bid is not None and row.quote.bid > 0 else None
    ask = row.quote.ask if row.quote.ask is not None and row.quote.ask > 0 else None
    bid_ask_mid = row.quote.bid_ask_mid
    bid_ask_spread = row.quote.bid_ask_spread
    bid_ask_spread_pct = row.quote.bid_ask_spread_pct
    if side == "BUY":
        execution_price = ask if ask is not None else price
        execution_basis = "ask" if ask is not None else "analysis_price_proxy"
        slippage_points = max(float(execution_price or 0.0) - float(price or 0.0), 0.0)
    else:
        execution_price = bid if bid is not None else price
        execution_basis = "bid" if bid is not None else "analysis_price_proxy"
        slippage_points = max(float(price or 0.0) - float(execution_price or 0.0), 0.0)
    signed_price = (1 if side == "BUY" else -1) * quantity * float(price or 0.0)
    signed_execution_price = (1 if side == "BUY" else -1) * quantity * float(execution_price or 0.0)
    return {
        "ts_code": row.quote.ts_code,
        "side": side,
        "quantity": quantity,
        "call_put": row.quote.call_put,
        "strike": row.quote.strike,
        "expiry": row.quote.maturity_date,
        "price": price,
        "price_basis": "close" if row.quote.close is not None and row.quote.close > 0 else "settle_fallback",
        "bid": bid,
        "ask": ask,
        "bid_ask_mid": _round(bid_ask_mid, 4) if bid_ask_mid is not None else None,
        "bid_ask_spread": _round(bid_ask_spread, 4) if bid_ask_spread is not None else None,
        "bid_ask_spread_pct": _round(bid_ask_spread_pct, 8) if bid_ask_spread_pct is not None else None,
        "execution_price": execution_price,
        "execution_price_basis": execution_basis,
        "slippage_points": _round(slippage_points, 4),
        "slippage_cash": _cash(slippage_points * quantity, contract_multiplier),
        "signed_execution_premium_cash": _cash(signed_execution_price, contract_multiplier),
        "contract_multiplier": contract_multiplier,
        "premium_cash": _cash(float(price or 0.0) * quantity, contract_multiplier),
        "signed_premium_cash": _cash(signed_price, contract_multiplier),
        "implied_volatility": _round(row.implied_volatility),
        "delta": _round(greeks.delta) if greeks else None,
        "gamma": _round(greeks.gamma) if greeks else None,
        "theta": _round(greeks.theta) if greeks else None,
        "vega": _round(greeks.vega) if greeks else None,
        "volume": row.quote.volume,
        "open_interest": row.quote.open_interest,
    }


def _signed_multiplier(leg: dict[str, Any]) -> int:
    return (1 if leg["side"] == "BUY" else -1) * int(leg.get("quantity") or 1)


def _net_premium(legs: list[dict[str, Any]]) -> float:
    return sum(_signed_multiplier(leg) * float(leg["price"] or 0.0) for leg in legs)


def _net_execution_premium(legs: list[dict[str, Any]]) -> float:
    return sum(_signed_multiplier(leg) * float(leg.get("execution_price") or leg.get("price") or 0.0) for leg in legs)


def _short_iron_condor_wing_width(legs: list[dict[str, Any]]) -> float | None:
    put_strikes = sorted(float(leg["strike"]) for leg in legs if leg["call_put"] == "P")
    call_strikes = sorted(float(leg["strike"]) for leg in legs if leg["call_put"] == "C")
    if len(put_strikes) != 2 or len(call_strikes) != 2:
        return None
    put_width = put_strikes[1] - put_strikes[0]
    call_width = call_strikes[1] - call_strikes[0]
    return max(put_width, call_width)


def _credit_execution_fields(
    *,
    strategy_type: str,
    legs: list[dict[str, Any]],
    net_mid_premium: float,
    execution: dict[str, Any],
    contract_multiplier: int,
    min_credit_pct_of_wing_width: float | None,
    max_bid_ask_spread_pct: float | None,
) -> dict[str, Any] | None:
    """Return execution-adjusted credit/risk metrics for defined-risk credit structures."""
    if strategy_type != "short_iron_condor":
        return None

    wing_width = _short_iron_condor_wing_width(legs)
    net_execution = float(execution.get("net_execution_premium") or 0.0)
    mid_credit = max(-float(net_mid_premium), 0.0)
    executable_credit = max(-net_execution, 0.0)
    max_loss_at_execution = max(float(wing_width or 0.0) - executable_credit, 0.0) if wing_width is not None else None
    credit_slippage = max(mid_credit - executable_credit, 0.0)
    credit_pct_of_wing = executable_credit / wing_width if wing_width else None
    credit_to_max_loss = executable_credit / max_loss_at_execution if max_loss_at_execution else None
    filters_enabled = min_credit_pct_of_wing_width is not None or max_bid_ask_spread_pct is not None
    no_trade_reasons: list[str] = []

    if filters_enabled and not execution.get("bid_ask_complete"):
        no_trade_reasons.append("bid/ask incomplete for executable credit")
    if filters_enabled and executable_credit <= 0:
        no_trade_reasons.append("executable_credit_points is non-positive")
    if min_credit_pct_of_wing_width is not None:
        if credit_pct_of_wing is None or credit_pct_of_wing < float(min_credit_pct_of_wing_width):
            no_trade_reasons.append("executable_credit_pct_of_wing_width below min_credit_pct_of_wing_width")
    if max_bid_ask_spread_pct is not None:
        observed = execution.get("max_bid_ask_spread_pct")
        if observed is None:
            no_trade_reasons.append("max_bid_ask_spread_pct unavailable for threshold check")
        elif float(observed) > float(max_bid_ask_spread_pct):
            no_trade_reasons.append("max_bid_ask_spread_pct exceeds threshold")

    return {
        "applies": True,
        "basis": "sell_bid_buy_ask" if execution.get("bid_ask_complete") else "analysis_price_proxy",
        "mid_credit_points": _round(mid_credit, 4),
        "executable_credit_points": _round(executable_credit, 4),
        "credit_slippage_points": _round(credit_slippage, 4),
        "credit_slippage_cash": _cash(credit_slippage, contract_multiplier),
        "wing_width_points": _round(wing_width, 4) if wing_width is not None else None,
        "max_loss_at_execution_points": _round(max_loss_at_execution, 4) if max_loss_at_execution is not None else None,
        "executable_credit_cash": _cash(executable_credit, contract_multiplier),
        "max_loss_at_execution_cash": _cash(max_loss_at_execution, contract_multiplier) if max_loss_at_execution is not None else None,
        "executable_credit_pct_of_wing_width": _round(credit_pct_of_wing, 8) if credit_pct_of_wing is not None else None,
        "executable_credit_to_max_loss_at_execution": _round(credit_to_max_loss, 8) if credit_to_max_loss is not None else None,
        "quality_filters_enabled": filters_enabled,
        "min_credit_pct_of_wing_width": min_credit_pct_of_wing_width,
        "max_bid_ask_spread_pct_threshold": max_bid_ask_spread_pct,
        "passes_credit_quality": (not no_trade_reasons) if filters_enabled else None,
        "no_trade_reasons": no_trade_reasons,
        "note": "For defined-risk credit structures, executable credit sells short legs at bid and buys wings at ask when bid/ask are available; this remains a pre-trade feasibility proxy, not a live fill guarantee.",
    }


def _execution_summary(
    legs: list[dict[str, Any]],
    net_mid_premium: float,
    contract_multiplier: int,
    liquidity: dict[str, Any],
) -> dict[str, Any]:
    net_execution = _round(_net_execution_premium(legs), 4) or 0.0
    slippage_points = _round(sum(float(leg.get("slippage_points") or 0.0) * int(leg.get("quantity") or 1) for leg in legs), 4) or 0.0
    spread_pcts = [float(leg["bid_ask_spread_pct"]) for leg in legs if leg.get("bid_ask_spread_pct") is not None]
    bid_ask_complete = all(leg.get("bid") is not None and leg.get("ask") is not None for leg in legs)
    avg_spread_pct = _round(sum(spread_pcts) / len(spread_pcts), 8) if spread_pcts else None
    max_spread_pct = _round(max(spread_pcts), 8) if spread_pcts else None
    slippage_pct = _round(slippage_points / abs(net_mid_premium), 8) if net_mid_premium else None

    score = 100.0
    if not bid_ask_complete:
        score -= 30.0
    if not liquidity.get("passes"):
        score -= 25.0
    if avg_spread_pct is not None:
        score -= min(avg_spread_pct * 500.0, 35.0)
    else:
        score -= 15.0
    if slippage_pct is not None:
        score -= min(slippage_pct * 400.0, 35.0)
    else:
        score -= 10.0
    score = max(0.0, min(100.0, score))
    if score >= 80:
        grade = "good"
    elif score >= 60:
        grade = "acceptable"
    elif score >= 40:
        grade = "weak"
    else:
        grade = "poor"
    return {
        "bid_ask_complete": bid_ask_complete,
        "net_mid_premium": net_mid_premium,
        "net_execution_premium": net_execution,
        "slippage_points": slippage_points,
        "slippage_cash": _cash(slippage_points, contract_multiplier),
        "slippage_pct_of_mid_premium": slippage_pct,
        "avg_bid_ask_spread_pct": avg_spread_pct,
        "max_bid_ask_spread_pct": max_spread_pct,
        "execution_liquidity_score": _round(score, 4),
        "execution_liquidity_grade": grade,
        "scoring_note": "Score combines bid/ask completeness, quoted spread, slippage from mid/close analysis price, and exchange volume/OI filters; it is a pre-trade feasibility proxy, not a live executable quote.",
    }


def _net_greeks(legs: list[dict[str, Any]]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for greek in ["delta", "gamma", "theta", "vega"]:
        values = [leg.get(greek) for leg in legs]
        out[greek] = _round(sum(_signed_multiplier(leg) * float(leg[greek]) for leg in legs if leg.get(greek) is not None)) if any(v is not None for v in values) else None
    return out


def _liquidity(legs: list[dict[str, Any]], min_open_interest: float, min_volume: float) -> dict[str, Any]:
    min_oi = min(float(leg.get("open_interest") or 0.0) for leg in legs)
    min_vol = min(float(leg.get("volume") or 0.0) for leg in legs)
    return {
        "passes": min_oi >= min_open_interest and min_vol >= min_volume,
        "min_open_interest": min_oi,
        "min_volume": min_vol,
        "thresholds": {
            "min_open_interest": min_open_interest,
            "min_volume": min_volume,
        },
        "note": "Uses exchange volume/OI as a liquidity filter; bid/ask must still be checked before execution.",
    }


def _structure_legs(
    strategy_type: str,
    rows: list[EnrichedOptionQuote],
    underlying_price: float,
    contract_multiplier: int,
) -> list[dict[str, Any]]:
    strikes = sorted({row.quote.strike for row in rows})
    atm = _nearest_strike(rows, underlying_price)
    if strategy_type == "bull_call_spread":
        upper = _next_higher(strikes, atm)
        return [_leg(_row_at(rows, "C", atm), "BUY", contract_multiplier=contract_multiplier), _leg(_row_at(rows, "C", upper), "SELL", contract_multiplier=contract_multiplier)]
    if strategy_type == "bear_put_spread":
        lower = _next_lower(strikes, atm)
        return [_leg(_row_at(rows, "P", atm), "BUY", contract_multiplier=contract_multiplier), _leg(_row_at(rows, "P", lower), "SELL", contract_multiplier=contract_multiplier)]
    if strategy_type == "long_straddle":
        return [_leg(_row_at(rows, "C", atm), "BUY", contract_multiplier=contract_multiplier), _leg(_row_at(rows, "P", atm), "BUY", contract_multiplier=contract_multiplier)]
    if strategy_type == "long_strangle":
        lower = _next_lower(strikes, atm)
        upper = _next_higher(strikes, atm)
        return [_leg(_row_at(rows, "C", upper), "BUY", contract_multiplier=contract_multiplier), _leg(_row_at(rows, "P", lower), "BUY", contract_multiplier=contract_multiplier)]
    if strategy_type == "long_call_butterfly":
        lower = _next_lower(strikes, atm)
        upper = _next_higher(strikes, atm)
        return [
            _leg(_row_at(rows, "C", lower), "BUY", contract_multiplier=contract_multiplier),
            _leg(_row_at(rows, "C", atm), "SELL", quantity=2, contract_multiplier=contract_multiplier),
            _leg(_row_at(rows, "C", upper), "BUY", contract_multiplier=contract_multiplier),
        ]
    if strategy_type == "long_put_butterfly":
        lower = _next_lower(strikes, atm)
        upper = _next_higher(strikes, atm)
        return [
            _leg(_row_at(rows, "P", lower), "BUY", contract_multiplier=contract_multiplier),
            _leg(_row_at(rows, "P", atm), "SELL", quantity=2, contract_multiplier=contract_multiplier),
            _leg(_row_at(rows, "P", upper), "BUY", contract_multiplier=contract_multiplier),
        ]
    if strategy_type == "short_iron_condor":
        short_put = _nth_lower(strikes, atm, 1)
        long_put = _nth_lower(strikes, atm, 2)
        short_call = _nth_higher(strikes, atm, 1)
        long_call = _nth_higher(strikes, atm, 2)
        return [
            _leg(_row_at(rows, "P", long_put), "BUY", contract_multiplier=contract_multiplier),
            _leg(_row_at(rows, "P", short_put), "SELL", contract_multiplier=contract_multiplier),
            _leg(_row_at(rows, "C", short_call), "SELL", contract_multiplier=contract_multiplier),
            _leg(_row_at(rows, "C", long_call), "BUY", contract_multiplier=contract_multiplier),
        ]
    raise ValueError(f"Unsupported strategy_type={strategy_type!r}")


def _payoff(strategy_type: str, legs: list[dict[str, Any]], net_premium: float) -> dict[str, Any]:
    strikes = [float(leg["strike"]) for leg in legs]
    width = abs(strikes[1] - strikes[0]) if len(strikes) >= 2 else 0.0
    if strategy_type in {"bull_call_spread", "bear_put_spread"}:
        max_loss = max(net_premium, 0.0)
        max_profit = max(width - net_premium, 0.0)
        if strategy_type == "bull_call_spread":
            breakevens = [strikes[0] + net_premium]
        else:
            breakevens = [strikes[0] - net_premium]
    elif strategy_type == "long_straddle":
        max_loss = max(net_premium, 0.0)
        max_profit = None
        breakevens = [strikes[0] - net_premium, strikes[0] + net_premium]
    elif strategy_type == "long_strangle":
        max_loss = max(net_premium, 0.0)
        max_profit = None
        breakevens = [min(strikes) - net_premium, max(strikes) + net_premium]
    elif strategy_type in {"long_call_butterfly", "long_put_butterfly"}:
        ordered = sorted(strikes)
        lower, middle, upper = ordered[0], ordered[1], ordered[2]
        width = min(middle - lower, upper - middle)
        max_loss = max(net_premium, 0.0)
        max_profit = max(width - net_premium, 0.0)
        breakevens = [lower + net_premium, upper - net_premium]
    elif strategy_type == "short_iron_condor":
        put_strikes = sorted(float(leg["strike"]) for leg in legs if leg["call_put"] == "P")
        call_strikes = sorted(float(leg["strike"]) for leg in legs if leg["call_put"] == "C")
        if len(put_strikes) != 2 or len(call_strikes) != 2:
            raise ValueError("short_iron_condor requires two put strikes and two call strikes")
        long_put, short_put = put_strikes[0], put_strikes[1]
        short_call, long_call = call_strikes[0], call_strikes[1]
        put_width = short_put - long_put
        call_width = long_call - short_call
        credit = max(-net_premium, 0.0)
        max_loss = max(max(put_width, call_width) - credit, 0.0)
        max_profit = credit
        breakevens = [short_put - credit, short_call + credit]
    else:
        max_loss = None
        max_profit = None
        breakevens = []
    return {
        "max_loss": _round(max_loss, 4) if max_loss is not None else None,
        "max_profit": _round(max_profit, 4) if max_profit is not None else None,
        "breakevens": [_round(item, 4) for item in breakevens],
    }


def _cash_risk_fields(
    *,
    net_premium: float,
    max_loss: float | None,
    max_profit: float | None,
    underlying_price: float,
    contract_multiplier: int,
    multiplier_unit: str,
    risk_budget_cash: float | None,
) -> dict[str, Any]:
    net_premium_cash = _cash(net_premium, contract_multiplier)
    max_loss_cash = _cash(max_loss, contract_multiplier) if max_loss is not None else None
    max_profit_cash = _cash(max_profit, contract_multiplier) if max_profit is not None else None
    underlying_notional = _cash(underlying_price, contract_multiplier)
    return {
        "contract_multiplier": contract_multiplier,
        "multiplier_unit": "CNY per option-price point",
        "underlying_contract_unit": multiplier_unit,
        "net_premium_cash": net_premium_cash,
        "max_loss_cash": max_loss_cash,
        "max_profit_cash": max_profit_cash,
        "underlying_notional_per_lot": underlying_notional,
        "max_loss_pct_of_notional": _round(max_loss_cash / underlying_notional, 8) if max_loss_cash is not None and underlying_notional else None,
        "risk_budget_cash": risk_budget_cash,
        "max_loss_pct_of_risk_budget": _round(max_loss_cash / risk_budget_cash, 8) if max_loss_cash is not None and risk_budget_cash else None,
    }


def _margin_fields(
    *,
    strategy_type: str,
    payoff: dict[str, Any],
    execution: dict[str, Any],
    cash_risk: dict[str, Any],
    credit_execution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a simplified pre-trade margin estimate for defined-risk structures."""
    contract_multiplier = int(cash_risk.get("contract_multiplier") or 1)
    net_execution_premium = execution.get("net_execution_premium")
    max_loss = payoff.get("max_loss")
    if credit_execution is not None and credit_execution.get("max_loss_at_execution_cash") is not None:
        max_loss_at_execution_cash = credit_execution.get("max_loss_at_execution_cash")
        max_loss_at_execution = float(max_loss_at_execution_cash) / contract_multiplier if contract_multiplier else None
    elif max_loss is None:
        max_loss_at_execution = None
        max_loss_at_execution_cash = None
    elif net_execution_premium is not None and float(net_execution_premium) > 0:
        max_loss_at_execution = max(float(max_loss), float(net_execution_premium))
        max_loss_at_execution_cash = _cash(max_loss_at_execution, contract_multiplier)
    else:
        max_loss_at_execution = float(max_loss)
        max_loss_at_execution_cash = _cash(max_loss_at_execution, contract_multiplier)
    margin_required_cash = max_loss_at_execution_cash
    underlying_notional = cash_risk.get("underlying_notional_per_lot")
    return {
        "method": "defined_risk_execution_adjusted_max_loss",
        "margin_model": "simplified_defined_risk",
        "strategy_type": strategy_type,
        "defined_risk": True,
        "margin_required_cash": margin_required_cash,
        "max_loss_at_mid_cash": cash_risk.get("max_loss_cash"),
        "max_loss_at_execution_cash": max_loss_at_execution_cash,
        "margin_required_pct_of_notional": _round(margin_required_cash / underlying_notional, 8) if margin_required_cash is not None and underlying_notional else None,
        "notes": [
            "Current simplified margin model covers supported defined-risk option structures.",
            "Margin required uses execution-adjusted max loss when bid/ask execution premium or executable credit is available; this remains a pre-trade feasibility proxy.",
            "Exchange/SPAN margin, offsets, fees, and broker-specific add-ons are not modeled.",
        ],
    }


def _risk_budget_fields(
    *,
    margin: dict[str, Any],
    cash_risk: dict[str, Any],
    risk_budget_cash: float | None,
    execution_no_trade_reasons: list[str] | None = None,
) -> dict[str, Any]:
    margin_required = margin.get("margin_required_cash")
    max_loss_cash = cash_risk.get("max_loss_cash")
    reasons: list[str] = list(execution_no_trade_reasons or [])
    if risk_budget_cash is None:
        if reasons:
            status = "fail"
            passes = False
        else:
            status = "not_provided"
            passes = None
    else:
        if margin_required is not None and margin_required > risk_budget_cash:
            reasons.append("margin_required_cash exceeds risk_budget_cash")
        if max_loss_cash is not None and max_loss_cash > risk_budget_cash:
            reasons.append("max_loss_cash exceeds risk_budget_cash")
        passes = not reasons
        status = "pass" if passes else "fail"
    return {
        "risk_budget_cash": risk_budget_cash,
        "passes": passes,
        "status": status,
        "margin_pct_of_risk_budget": _round(margin_required / risk_budget_cash, 8) if margin_required is not None and risk_budget_cash else None,
        "max_loss_pct_of_risk_budget": _round(max_loss_cash / risk_budget_cash, 8) if max_loss_cash is not None and risk_budget_cash else None,
        "no_trade_reasons": reasons,
    }


def build_option_strategy_candidate(
    symbol: str,
    strategy_type: str,
    trade_date: str | None = None,
    expiry: str | None = None,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    min_open_interest: float = 1000.0,
    min_volume: float = 100.0,
    risk_budget_cash: float | None = None,
    min_credit_pct_of_wing_width: float | None = None,
    max_bid_ask_spread_pct: float | None = None,
) -> dict[str, Any]:
    """Build one deterministic, auditable option strategy candidate.

    The output is intended for LLM agents to interpret and risk-manage, not as
    an execution instruction. Premiums are kept in option-price points and also
    converted to cash values with the SHFE contract multiplier.
    """
    normalized_strategy = (strategy_type or "").strip().lower().replace("-", "_")
    if normalized_strategy not in _SUPPORTED_STRATEGIES:
        raise ValueError(f"Unsupported strategy_type={strategy_type!r}; supported={sorted(_SUPPORTED_STRATEGIES)}")

    report = analyze_option_chain(symbol, trade_date=trade_date, expiry=expiry, risk_free_rate=risk_free_rate)
    contract_multiplier = contract_multiplier_for_product(report.product)
    multiplier_unit = multiplier_unit_for_product(report.product)
    rows = _rows_for_expiry(report.options, expiry)
    legs = _structure_legs(normalized_strategy, rows, report.underlying_price, contract_multiplier)
    net = _round(_net_premium(legs), 4) or 0.0
    payoff = _payoff(normalized_strategy, legs, net)
    liquidity = _liquidity(legs, min_open_interest, min_volume)
    execution = _execution_summary(legs, net, contract_multiplier, liquidity)
    credit_execution = _credit_execution_fields(
        strategy_type=normalized_strategy,
        legs=legs,
        net_mid_premium=net,
        execution=execution,
        contract_multiplier=contract_multiplier,
        min_credit_pct_of_wing_width=min_credit_pct_of_wing_width,
        max_bid_ask_spread_pct=max_bid_ask_spread_pct,
    )
    cash_risk = _cash_risk_fields(
        net_premium=net,
        max_loss=payoff["max_loss"],
        max_profit=payoff["max_profit"],
        underlying_price=report.underlying_price,
        contract_multiplier=contract_multiplier,
        multiplier_unit=multiplier_unit,
        risk_budget_cash=risk_budget_cash,
    )
    margin = _margin_fields(
        strategy_type=normalized_strategy,
        payoff=payoff,
        execution=execution,
        cash_risk=cash_risk,
        credit_execution=credit_execution,
    )
    risk_budget = _risk_budget_fields(
        margin=margin,
        cash_risk=cash_risk,
        risk_budget_cash=risk_budget_cash,
        execution_no_trade_reasons=credit_execution.get("no_trade_reasons") if credit_execution else None,
    )
    maturity = legs[0]["expiry"] if legs else None
    return {
        "strategy_type": normalized_strategy,
        "product": report.product,
        "trade_date": report.trade_date,
        "underlying_symbol": report.underlying_symbol,
        "underlying_price": report.underlying_price,
        "expiry": maturity,
        "price_basis": "option close + futures close",
        "risk_free_rate": risk_free_rate,
        "contract_multiplier": contract_multiplier,
        "legs": legs,
        "net_premium": net,
        "premium_type": "debit" if net > 0 else "credit" if net < 0 else "zero-cost",
        "max_loss": payoff["max_loss"],
        "max_profit": payoff["max_profit"],
        "breakevens": payoff["breakevens"],
        "cash_risk": cash_risk,
        "greeks": _net_greeks(legs),
        "liquidity": liquidity,
        "execution": execution,
        "credit_execution": credit_execution,
        "margin": margin,
        "risk_budget": risk_budget,
        "assumptions": {
            "model": "Black-76 futures option model",
            "price_basis": "option close + futures close",
            "contract_multiplier_applied": True,
            "contract_multiplier_source": "static SHFE futures contract specification mapping",
            "margin_model": "simplified_defined_risk",
            "execution_note": "Candidate is analytical only; verify live bid/ask, slippage, margin, and exchange rules before trading.",
        },
    }
