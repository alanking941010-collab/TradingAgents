"""Deterministic strategy selector for SHFE option strategy candidates.

The selector ranks already-auditable strategy candidates using the deterministic
analytics, volatility-surface diagnostics, execution feasibility, margin, and
risk-budget fields. It is a pre-trade research/ranking layer, not an execution
instruction.
"""

from __future__ import annotations

from typing import Any, Iterable

from tradingagents.options.analytics import DEFAULT_RISK_FREE_RATE
from tradingagents.options.context import OptionAnalysisContext
from tradingagents.options.schemas import validate_selection_result

_DEFAULT_STRATEGIES = (
    "bull_call_spread",
    "bear_put_spread",
    "long_straddle",
    "long_strangle",
    "long_call_butterfly",
    "long_put_butterfly",
    "short_iron_condor",
)


def _round(value: float | None, digits: int = 8) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _contains_any(text: str, words: Iterable[str]) -> bool:
    normalized = (text or "").strip().lower().replace("-", "_")
    return any(word in normalized for word in words)


def _surface_regime(report) -> dict[str, Any]:
    surface = report.vol_surface or {}
    skew = surface.get("skew", {})
    term = surface.get("term_regime", {})
    return {
        "nearest_expiry": surface.get("nearest_expiry"),
        "term_shape": term.get("shape"),
        "term_slope": term.get("slope"),
        "put_call_skew": skew.get("put_call_skew"),
        "risk_reversal_proxy": skew.get("risk_reversal_proxy"),
        "smile_curvature_proxy": skew.get("smile_curvature_proxy"),
        "atm_iv": _round(report.atm_iv),
        "note": "Surface regime is a deterministic diagnostic from close-based IV buckets, not an executable volatility quote.",
    }


def _cash_number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _risk_budget_utilization(amount: float | None, risk_budget_cash: float | None) -> float | None:
    if amount is None or risk_budget_cash in (None, 0):
        return None
    return _round(amount / float(risk_budget_cash), 6)


def _portfolio_row(row: dict[str, Any], rank: int, risk_budget_cash: float | None) -> dict[str, Any]:
    margin_cash = _cash_number(row.get("margin_required_cash"))
    max_loss_cash = _cash_number(row.get("max_loss_cash"))
    risk_basis = max(value for value in (margin_cash, max_loss_cash) if value is not None) if any(
        value is not None for value in (margin_cash, max_loss_cash)
    ) else None
    credit = row.get("credit_execution") or {}
    return {
        "rank": rank,
        "strategy_type": row.get("strategy_type"),
        "decision": row.get("decision"),
        "score": row.get("score"),
        "margin_required_cash": margin_cash,
        "max_loss_cash": max_loss_cash,
        "risk_budget_utilization": _risk_budget_utilization(risk_basis, risk_budget_cash),
        "execution_liquidity_grade": row.get("execution_liquidity_grade"),
        "risk_budget_status": row.get("risk_budget_status"),
        "executable_credit_cash": _cash_number(credit.get("executable_credit_cash")),
        "credit_pct_of_wing_width": credit.get("executable_credit_pct_of_wing_width"),
    }


def _build_portfolio_summary(
    ranked: list[dict[str, Any]],
    selected_strategy: str | None,
    risk_budget_cash: float | None,
) -> dict[str, Any]:
    comparison = [_portfolio_row(row, idx, risk_budget_cash) for idx, row in enumerate(ranked, start=1)]
    tradable = [row for row in comparison if row.get("decision") != "no_trade"]
    allocation_rows = tradable or comparison

    def _sum(field: str) -> float:
        return _round(sum(float(row[field]) for row in allocation_rows if isinstance(row.get(field), (int, float))), 4) or 0.0

    selected = next((row for row in comparison if row.get("strategy_type") == selected_strategy), None)
    margin_rows = [row for row in comparison if isinstance(row.get("margin_required_cash"), (int, float))]
    max_loss_rows = [row for row in comparison if isinstance(row.get("max_loss_cash"), (int, float))]
    no_trade_rows = [row for row in comparison if row.get("decision") == "no_trade"]

    all_margin = _sum("margin_required_cash")
    all_max_loss = _sum("max_loss_cash")
    summary = {
        "summary_type": "option_strategy_portfolio_risk_summary",
        "risk_budget_cash": risk_budget_cash,
        "candidate_count": len(comparison),
        "tradable_candidate_count": len(tradable),
        "no_trade_count": len(no_trade_rows),
        "selected_strategy": selected,
        "selected_risk_budget_utilization": selected.get("risk_budget_utilization") if selected else None,
        "all_candidate_margin_cash": all_margin,
        "all_candidate_max_loss_cash": all_max_loss,
        "all_candidate_margin_utilization": _risk_budget_utilization(all_margin, risk_budget_cash),
        "all_candidate_max_loss_utilization": _risk_budget_utilization(all_max_loss, risk_budget_cash),
        "highest_margin_strategy": max(margin_rows, key=lambda row: float(row["margin_required_cash"])) if margin_rows else None,
        "lowest_max_loss_strategy": min(max_loss_rows, key=lambda row: float(row["max_loss_cash"])) if max_loss_rows else None,
        "watchlist": [row for row in comparison if row.get("decision") == "watch"],
        "no_trade_strategies": [row for row in comparison if row.get("decision") == "no_trade"],
        "comparison_table": comparison,
        "notes": [
            "Portfolio summary compares strategy candidates side by side; it is not a recommendation to allocate to every row.",
            "Risk-budget utilization uses the larger of margin_required_cash and max_loss_cash when both are available.",
            "All-candidate totals sum tradable rows only; no-trade rows remain visible in comparison_table but are excluded from totals.",
        ],
    }
    return summary


def _score_candidate(
    candidate: dict[str, Any],
    surface_regime: dict[str, Any],
    directional_bias: str | None,
    volatility_view: str | None,
    constraint_mode: str = "strict",
) -> dict[str, Any]:
    strategy = candidate["strategy_type"]
    bias = (directional_bias or "neutral").strip().lower().replace("-", "_")
    vol_view = (volatility_view or "").strip().lower().replace("-", "_")
    score = 50.0
    reasons: list[str] = []
    no_trade_reasons: list[str] = []

    risk_budget = candidate.get("risk_budget", {})
    execution = candidate.get("execution", {})
    liquidity = candidate.get("liquidity", {})
    credit_execution = candidate.get("credit_execution")
    term_shape = surface_regime.get("term_shape")
    smile_curvature = surface_regime.get("smile_curvature_proxy")
    put_call_skew = surface_regime.get("put_call_skew")
    risk_reversal = surface_regime.get("risk_reversal_proxy")

    if bias in {"bullish", "up", "long_delta"}:
        if strategy == "bull_call_spread":
            score += 28
            reasons.append("Bullish directional bias favors bull_call_spread.")
        elif strategy == "bear_put_spread":
            score -= 18
            reasons.append("Bullish directional bias penalizes bear_put_spread.")
        elif strategy in {"long_straddle", "long_strangle"}:
            score += 4
            reasons.append("Long-vol structures can still express bullish volatility uncertainty.")
    elif bias in {"bearish", "down", "short_delta"}:
        if strategy == "bear_put_spread":
            score += 28
            reasons.append("Bearish directional bias favors bear_put_spread.")
        elif strategy == "bull_call_spread":
            score -= 18
            reasons.append("Bearish directional bias penalizes bull_call_spread.")
        elif strategy in {"long_straddle", "long_strangle"}:
            score += 4
            reasons.append("Long-vol structures can still express bearish volatility uncertainty.")
    else:
        if strategy == "short_iron_condor":
            score += 25
            reasons.append("Neutral/range directional bias favors short_iron_condor when risk is defined.")
        if strategy in {"long_call_butterfly", "long_put_butterfly"}:
            score += 8
            reasons.append("Neutral/range directional bias can support butterfly structures.")

    if _contains_any(vol_view, ["range", "range_bound", "sideways", "high_iv", "iv_fall", "vol_fall", "short_vol"]):
        if strategy == "short_iron_condor":
            score += 24
            reasons.append("Range/high-IV or falling-volatility view favors defined-risk credit collection.")
        elif strategy in {"long_straddle", "long_strangle"}:
            score -= 18
            reasons.append("Range/high-IV or falling-volatility view penalizes long premium structures.")
    if _contains_any(vol_view, ["iv_up", "vol_up", "rising", "breakout", "low_iv", "long_vol"]):
        if strategy in {"long_straddle", "long_strangle"}:
            score += 24
            reasons.append("Rising-volatility view favors long premium convexity.")
        elif strategy == "short_iron_condor":
            score -= 20
            reasons.append("Rising-volatility view penalizes short_iron_condor short-vol exposure.")

    if isinstance(put_call_skew, (int, float)) and put_call_skew > 0:
        if strategy == "bear_put_spread":
            score += 6
            reasons.append("Positive put-call skew highlights downside/tail demand; bear_put_spread deserves review.")
    if isinstance(risk_reversal, (int, float)) and risk_reversal > 0:
        if strategy == "bull_call_spread":
            score += 5
            reasons.append("Positive risk-reversal proxy highlights call-side richness/momentum context.")
    if isinstance(smile_curvature, (int, float)) and abs(smile_curvature) > 0.005:
        if strategy in {"long_call_butterfly", "long_put_butterfly"}:
            score += 6
            reasons.append("Smile curvature makes butterfly structures worth ranking.")

    if term_shape in {"flat", "contango"} and strategy == "short_iron_condor":
        score += 4
        reasons.append(f"Term regime `{term_shape}` is compatible with defined-risk range structures.")

    strict_constraints = (constraint_mode or "strict").strip().lower() != "relaxed"

    if liquidity.get("passes") is False:
        score -= 18 if strict_constraints else 8
        if strict_constraints:
            no_trade_reasons.append("liquidity filter failed")
        else:
            reasons.append("Relaxed constraint mode: liquidity filter failed, but the structure remains for review.")
    if execution.get("execution_liquidity_grade") in {"weak", "poor"}:
        score -= 14
        reasons.append("Execution liquidity grade is weak/poor; keep the structure on watch unless other risk checks fail.")
    if risk_budget.get("passes") is False:
        score -= 35 if strict_constraints else 18
        budget_reasons = risk_budget.get("no_trade_reasons") or ["risk budget failed"]
        if strict_constraints:
            no_trade_reasons.extend(budget_reasons)
        else:
            reasons.append(
                "Relaxed constraint mode: risk budget failed, but the structure remains for sizing/manual review."
            )
            reasons.extend(f"Soft risk-budget warning: {reason}" for reason in budget_reasons[:3])
    elif risk_budget.get("passes") is True:
        score += 8
        reasons.append("Risk budget check passes.")

    if credit_execution is not None:
        if credit_execution.get("passes_credit_quality") is False:
            score -= 25 if strict_constraints else 12
            credit_reasons = credit_execution.get("no_trade_reasons") or ["credit quality filter failed"]
            if strict_constraints:
                no_trade_reasons.extend(credit_reasons)
            else:
                reasons.append(
                    "Relaxed constraint mode: credit-quality filter failed, but the structure remains for review."
                )
                reasons.extend(f"Soft credit-quality warning: {reason}" for reason in credit_reasons[:3])
        executable_credit_pct = credit_execution.get("executable_credit_pct_of_wing_width")
        if isinstance(executable_credit_pct, (int, float)) and executable_credit_pct >= 0.2:
            score += 8
            reasons.append("Executable credit is meaningful versus wing width.")

    score = max(0.0, min(100.0, score))
    if no_trade_reasons:
        decision = "no_trade"
    elif score >= 70:
        decision = "candidate"
    elif score >= 45:
        decision = "watch"
    else:
        decision = "low_priority"

    return {
        "strategy_type": strategy,
        "score": _round(score, 4),
        "decision": decision,
        "ranking_reasons": reasons or ["No strong deterministic ranking reason; keep as baseline comparison."],
        "no_trade_reasons": list(dict.fromkeys(no_trade_reasons)),
        "risk_budget_status": risk_budget.get("status"),
        "margin_required_cash": candidate.get("margin", {}).get("margin_required_cash"),
        "max_loss_cash": candidate.get("cash_risk", {}).get("max_loss_cash"),
        "execution_liquidity_grade": execution.get("execution_liquidity_grade"),
        "credit_execution": credit_execution,
        "candidate": candidate,
    }


def _render_markdown(selection: dict[str, Any]) -> str:
    lines = [
        f"# Option Strategy Ranking — {selection['product']} {selection['trade_date']}",
        "",
        "## Surface Regime",
    ]
    regime = selection["surface_regime"]
    lines.extend([
        f"- Nearest expiry: {regime.get('nearest_expiry')}",
        f"- Term shape: `{regime.get('term_shape')}` / slope {regime.get('term_slope')}",
        f"- Put-call skew: {regime.get('put_call_skew')}",
        f"- Risk reversal proxy: {regime.get('risk_reversal_proxy')}",
        f"- Smile curvature proxy: {regime.get('smile_curvature_proxy')}",
        "",
        "## Strategy Ranking",
    ])
    for idx, row in enumerate(selection["ranked_candidates"], start=1):
        lines.append(
            f"{idx}. `{row['strategy_type']}` — score {row['score']} / `{row['decision']}`; "
            f"margin={row.get('margin_required_cash')}; max_loss={row.get('max_loss_cash')}; liquidity={row.get('execution_liquidity_grade')}"
        )
        for reason in row.get("ranking_reasons", [])[:3]:
            lines.append(f"   - {reason}")
        for reason in row.get("no_trade_reasons", [])[:3]:
            lines.append(f"   - no-trade: {reason}")
    lines.extend([
        "",
        "## Portfolio Risk Summary",
    ])
    portfolio = selection.get("portfolio_summary") or {}
    selected = portfolio.get("selected_strategy") or {}
    lines.extend([
        f"- Risk budget: {portfolio.get('risk_budget_cash')}",
        f"- Candidate count: {portfolio.get('candidate_count')} total / {portfolio.get('tradable_candidate_count')} tradable / {portfolio.get('no_trade_count')} no-trade",
        f"- Selected strategy: `{selected.get('strategy_type')}`; risk-budget utilization={selected.get('risk_budget_utilization')}",
        f"- Total candidate margin: {portfolio.get('all_candidate_margin_cash')}; utilization={portfolio.get('all_candidate_margin_utilization')}",
        f"- Total candidate max loss: {portfolio.get('all_candidate_max_loss_cash')}; utilization={portfolio.get('all_candidate_max_loss_utilization')}",
        "",
        "| Rank | Strategy | Decision | Score | Margin cash | Max loss cash | Risk budget use | Liquidity |",
        "|---:|---|---|---:|---:|---:|---:|---|",
    ])
    for row in portfolio.get("comparison_table", [])[:8]:
        lines.append(
            f"| {row.get('rank')} | `{row.get('strategy_type')}` | `{row.get('decision')}` | {row.get('score')} | "
            f"{row.get('margin_required_cash')} | {row.get('max_loss_cash')} | {row.get('risk_budget_utilization')} | `{row.get('execution_liquidity_grade')}` |"
        )
    lines.extend([
        "",
        "## Assumptions",
        "- Ranking is deterministic and pre-trade only; it is not an execution instruction.",
        "- Portfolio summary compares candidates side by side; it is not a recommendation to allocate to every listed strategy.",
        "- Uses option close + futures close analytics, bid/ask execution proxies when available, simplified defined-risk margin, and risk-budget checks.",
    ])
    return "\n".join(lines) + "\n"


def build_option_strategy_selection(
    symbol: str,
    trade_date: str | None = None,
    expiry: str | None = None,
    directional_bias: str | None = "neutral",
    volatility_view: str | None = None,
    risk_budget_cash: float | None = None,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    strategy_types: Iterable[str] = _DEFAULT_STRATEGIES,
    min_credit_pct_of_wing_width: float | None = None,
    max_bid_ask_spread_pct: float | None = None,
    constraint_mode: str = "strict",
    analysis_context: OptionAnalysisContext | None = None,
) -> dict[str, Any]:
    """Rank supported option strategies using deterministic analytics and risk fields."""
    context = analysis_context or OptionAnalysisContext(symbol, trade_date=trade_date, expiry=expiry, risk_free_rate=risk_free_rate)
    report = context.get_analysis(symbol, trade_date=trade_date, expiry=expiry, risk_free_rate=risk_free_rate)
    regime = _surface_regime(report)
    ranked: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for strategy_type in strategy_types:
        try:
            candidate = context.get_strategy_candidate(
                strategy_type,
                symbol=symbol,
                trade_date=trade_date,
                expiry=expiry,
                risk_free_rate=risk_free_rate,
                risk_budget_cash=risk_budget_cash,
                min_credit_pct_of_wing_width=min_credit_pct_of_wing_width,
                max_bid_ask_spread_pct=max_bid_ask_spread_pct,
            )
        except Exception as exc:  # keep selector robust to missing wings/rows for specific structures
            errors.append({"strategy_type": strategy_type, "error": str(exc)})
            continue
        ranked.append(_score_candidate(candidate, regime, directional_bias, volatility_view, constraint_mode=constraint_mode))

    ranked.sort(key=lambda row: (-float(row["score"]), row["strategy_type"]))
    selected = next((row["strategy_type"] for row in ranked if row["decision"] != "no_trade"), ranked[0]["strategy_type"] if ranked else None)
    portfolio_summary = _build_portfolio_summary(ranked, selected, risk_budget_cash)
    selection = {
        "selection_type": "option_strategy_ranking",
        "product": report.product,
        "trade_date": report.trade_date,
        "underlying_symbol": report.underlying_symbol,
        "underlying_price": report.underlying_price,
        "expiry": expiry,
        "price_basis": "option close + futures close",
        "risk_free_rate": risk_free_rate,
        "directional_bias": directional_bias,
        "volatility_view": volatility_view,
        "surface_regime": regime,
        "selected_strategy": selected,
        "ranked_candidates": ranked,
        "portfolio_summary": portfolio_summary,
        "errors": errors,
        "assumptions": {
            "selector_model": "deterministic_rules_v1",
            "selector_constraint_mode": constraint_mode,
            "margin_model": "simplified_defined_risk",
            "execution_model": "bid/ask proxy when available",
            "not_execution_instruction": True,
        },
    }
    selection["markdown"] = _render_markdown(selection)
    return validate_selection_result(selection)
