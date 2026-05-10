"""Option analytics tools for TradingAgents agent nodes.

These tools expose Alan's deterministic SHFE options analytics core to the
existing TradingAgents analyst/researcher/trader/risk-manager workflow. The
important boundary is: Python computes IV/Greeks/GEX/PCR/walls; LLM agents
interpret the structured result and debate trade ideas.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from langchain_core.tools import tool

from tradingagents.options.analytics import DEFAULT_RISK_FREE_RATE, analyze_option_chain
from tradingagents.options.delivery import build_hermes_cron_delivery_spec
from tradingagents.options.models import EnrichedOptionQuote, OptionAnalyticsReport
from tradingagents.options.replay import build_option_strategy_replay
from tradingagents.options.reports import build_feishu_delivery_payload, build_option_strategy_report
from tradingagents.options.research_pack import build_option_research_pack, build_option_research_pack_hermes_cron_spec
from tradingagents.options.scenarios import build_option_strategy_scenarios
from tradingagents.options.selector import build_option_strategy_selection
from tradingagents.options.strategies import build_option_strategy_candidate

_AGENT_LENS = {
    "market_analyst": "underlying trend, RV, technical context, and futures anchor",
    "fundamentals_analyst": "inventory, term structure, macro anchors, and volatility regime context",
    "news_analyst": "event risks that can reprice IV, skew, and tail demand",
    "bull_researcher": "bullish directional or bullish-volatility option structures supported by data",
    "bear_researcher": "bearish directional or bearish-volatility option structures supported by data",
    "trader": "translate validated views into structured option strategies with auditable legs and payoff",
    "risk_manager": "stress-test delta/gamma/vega/theta, liquidity, expiry, and margin assumptions",
    "portfolio_manager": "decide trade/watch/no-trade with risk budget and scenario checklist",
}


def _round_or_none(value: float | None, digits: int = 8) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _wall_to_dict(wall) -> dict[str, float]:
    return {
        "strike": wall.strike,
        "open_interest": wall.open_interest,
        "volume": wall.volume,
    }


def _normalize_detail_level(detail_level: str | None) -> str:
    value = (detail_level or "compact").strip().lower()
    if value not in {"compact", "full"}:
        raise ValueError("detail_level must be 'compact' or 'full'")
    return value


def _compact_strategy(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not candidate:
        return None
    keys = (
        "strategy_type",
        "decision",
        "expiry",
        "underlying_price",
        "max_loss_cash",
        "max_profit_cash",
        "net_premium_cash",
        "margin_required_cash",
        "risk_budget_cash",
        "risk_budget_status",
        "risk_budget_utilization",
        "execution_liquidity",
        "credit_execution",
        "no_trade_reasons",
    )
    return {key: candidate.get(key) for key in keys if key in candidate}


def _compact_ranked_candidate(row: dict[str, Any]) -> dict[str, Any]:
    compact = {
        "strategy_type": row.get("strategy_type"),
        "score": row.get("score"),
        "decision": row.get("decision"),
        "ranking_reasons": row.get("ranking_reasons", [])[:6],
        "no_trade_reasons": row.get("no_trade_reasons", [])[:6],
        "risk_budget_status": row.get("risk_budget_status"),
        "margin_required_cash": row.get("margin_required_cash"),
        "max_loss_cash": row.get("max_loss_cash"),
        "execution_liquidity_grade": row.get("execution_liquidity_grade"),
    }
    if row.get("credit_execution"):
        compact["credit_execution"] = row["credit_execution"]
    return compact


def _compact_portfolio_summary(portfolio: dict[str, Any] | None) -> dict[str, Any] | None:
    if not portfolio:
        return None
    keep = (
        "summary_type",
        "risk_budget_cash",
        "candidate_count",
        "tradable_candidate_count",
        "watch_candidate_count",
        "no_trade_count",
        "selected_strategy",
        "all_candidate_margin_cash",
        "all_candidate_max_loss_cash",
        "highest_margin_strategy",
        "lowest_max_loss_strategy",
        "comparison_table",
    )
    return {key: portfolio.get(key) for key in keep if key in portfolio}


def _compact_selection_payload(selection: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "detail_level": "compact",
        "selection_type": selection.get("selection_type"),
        "product": selection.get("product"),
        "trade_date": selection.get("trade_date"),
        "underlying_symbol": selection.get("underlying_symbol"),
        "underlying_price": selection.get("underlying_price"),
        "expiry": selection.get("expiry"),
        "price_basis": selection.get("price_basis"),
        "risk_free_rate": selection.get("risk_free_rate"),
        "directional_bias": selection.get("directional_bias"),
        "volatility_view": selection.get("volatility_view"),
        "surface_regime": selection.get("surface_regime"),
        "selected_strategy": selection.get("selected_strategy"),
        "ranked_candidates": [_compact_ranked_candidate(row) for row in selection.get("ranked_candidates", [])],
        "portfolio_summary": _compact_portfolio_summary(selection.get("portfolio_summary")),
        "errors": selection.get("errors", []),
        "assumptions": {
            **selection.get("assumptions", {}),
            "detail_level": "compact",
            "full_detail_hint": "Call the tool with detail_level='full' for full candidate payloads and Markdown.",
        },
    }
    return {key: value for key, value in payload.items() if value is not None}


def _compact_scenarios_payload(payload: dict[str, Any]) -> dict[str, Any]:
    compact_strategy = _compact_strategy(payload.get("strategy")) or {
        "strategy_type": (payload.get("strategy") or {}).get("strategy_type")
    }
    scenarios = []
    for row in payload.get("scenarios", []):
        scenarios.append({key: value for key, value in row.items() if key != "leg_values"})
    return {
        "detail_level": "compact",
        "strategy": compact_strategy,
        "cash_risk": payload.get("cash_risk"),
        "margin": payload.get("margin"),
        "risk_budget": payload.get("risk_budget"),
        "scenario_grid": payload.get("scenario_grid"),
        "scenarios": scenarios,
        "summary": payload.get("summary"),
        "assumptions": {
            **payload.get("assumptions", {}),
            "detail_level": "compact",
            "full_detail_hint": "Call the tool with detail_level='full' for per-leg scenario values and the full strategy payload.",
        },
    }


def _compact_report_payload(report: dict[str, Any]) -> dict[str, Any]:
    payloads = report.get("payloads", {})
    compact_payloads = {
        "volatility_snapshot": payloads.get("volatility_snapshot"),
        "strategy": _compact_strategy(payloads.get("strategy")),
        "scenario_summary": payloads.get("scenario_summary"),
        "replay_summary": payloads.get("replay_summary"),
        "replay_performance_summary": payloads.get("replay_performance_summary"),
    }
    compact = {
        "detail_level": "compact",
        "report_type": report.get("report_type"),
        "title": report.get("title"),
        "product": report.get("product"),
        "strategy_type": report.get("strategy_type"),
        "trade_date": report.get("trade_date"),
        "expiry": report.get("expiry"),
        "summary": report.get("summary"),
        "payloads": {key: value for key, value in compact_payloads.items() if value is not None},
        "markdown": report.get("markdown"),
        "assumptions": {
            **report.get("assumptions", {}),
            "detail_level": "compact",
            "full_detail_hint": "Call the tool with detail_level='full' for full report payloads.",
        },
    }
    return {key: value for key, value in compact.items() if value is not None}


def _compact_research_pack_payload(pack: dict[str, Any]) -> dict[str, Any]:
    payloads = pack.get("payloads", {})
    delivery = payloads.get("feishu_delivery_payload") or {}
    compact_payloads = {
        "selection": _compact_selection_payload(payloads["selection"]) if payloads.get("selection") else None,
        "portfolio_summary": _compact_portfolio_summary(payloads.get("portfolio_summary")),
        "selected_strategy_report": _compact_report_payload(payloads["selected_strategy_report"]) if payloads.get("selected_strategy_report") else None,
        "feishu_delivery_payload": {
            key: delivery.get(key)
            for key in ("channel", "target", "dry_run", "title", "delivery_hint")
            if key in delivery
        },
    }
    compact = {
        "detail_level": "compact",
        "pack_type": pack.get("pack_type"),
        "product": pack.get("product"),
        "trade_date": pack.get("trade_date"),
        "expiry": pack.get("expiry"),
        "selected_strategy": pack.get("selected_strategy"),
        "selection_mode": pack.get("selection_mode"),
        "summary": pack.get("summary"),
        "payloads": {key: value for key, value in compact_payloads.items() if value is not None},
        "assumptions": {
            **pack.get("assumptions", {}),
            "detail_level": "compact",
            "full_detail_hint": "Call the tool with detail_level='full' for complete JSON, Markdown, and delivery message payloads.",
        },
    }
    return {key: value for key, value in compact.items() if value is not None}


def _enriched_option_to_dict(row: EnrichedOptionQuote) -> dict[str, Any]:
    greeks = row.greeks
    return {
        "ts_code": row.quote.ts_code,
        "trade_date": row.quote.trade_date,
        "call_put": row.quote.call_put,
        "strike": row.quote.strike,
        "maturity_date": row.quote.maturity_date,
        "underlying_symbol": row.quote.underlying_symbol,
        "close": row.quote.close,
        "settle": row.quote.settle,
        "price_used": row.quote.mid_price,
        "price_basis": row.quote.price_basis,
        "bid": row.quote.bid,
        "ask": row.quote.ask,
        "bid_ask_mid": _round_or_none(row.quote.bid_ask_mid, 4),
        "bid_ask_spread": _round_or_none(row.quote.bid_ask_spread, 4),
        "bid_ask_spread_pct": _round_or_none(row.quote.bid_ask_spread_pct),
        "volume": row.quote.volume,
        "open_interest": row.quote.open_interest,
        "time_to_expiry": _round_or_none(row.time_to_expiry),
        "implied_volatility": _round_or_none(row.implied_volatility),
        "delta": _round_or_none(greeks.delta) if greeks else None,
        "gamma": _round_or_none(greeks.gamma) if greeks else None,
        "vega": _round_or_none(greeks.vega) if greeks else None,
        "theta": _round_or_none(greeks.theta) if greeks else None,
        "gex_per_1pct": _round_or_none(row.gex_per_1pct, 4),
        "dex": _round_or_none(row.dex, 4),
        "source": row.quote.source,
    }


def build_option_analytics_payload(
    symbol: str,
    trade_date: str | None = None,
    expiry: str | None = None,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> dict[str, Any]:
    """Return full audit JSON for one SHFE option analytics run."""
    report = analyze_option_chain(symbol, trade_date=trade_date, expiry=expiry, risk_free_rate=risk_free_rate)
    return {
        "product": report.product,
        "trade_date": report.trade_date,
        "underlying_symbol": report.underlying_symbol,
        "underlying_price": report.underlying_price,
        "price_basis": report.price_basis.get("option_price_basis", "unknown"),
        "price_basis_detail": report.price_basis,
        "risk_free_rate": risk_free_rate,
        "atm_iv": _round_or_none(report.atm_iv),
        "skew_25d": _round_or_none(report.skew_25d),
        "term_structure": {k: _round_or_none(v) for k, v in sorted(report.term_structure.items())},
        "vol_surface": report.vol_surface,
        "pcr_open_interest": _round_or_none(report.pcr_open_interest),
        "pcr_volume": _round_or_none(report.pcr_volume),
        "call_wall": _wall_to_dict(report.call_wall),
        "put_wall": _wall_to_dict(report.put_wall),
        "gamma_flip": _round_or_none(report.gamma_flip, 4),
        "exposure": {
            "total_gex": _round_or_none(report.exposure.total_gex, 4),
            "total_abs_gex": _round_or_none(report.exposure.total_abs_gex, 4),
            "total_dex": _round_or_none(report.exposure.total_dex, 4),
            "by_strike": report.exposure.by_strike,
        },
        "assumptions": {
            "model": "Black-76 futures option model",
            "risk_free_rate": risk_free_rate,
            "price_basis": "option close + futures close",
            "settlement_basis_note": "Use option settle + futures settle only for explicit settlement/risk-control requests.",
            "dealer_position_unknown": True,
            "gex_dex_note": "Exchange OI does not reveal true dealer inventory; GEX/DEX are scenario/concentration metrics.",
            "contract_multiplier_note": "Strategy/scenario tools apply static SHFE contract multipliers to premium/risk/PnL cash fields.",
            "execution_liquidity_note": "When bid/ask snapshots are available, strategy tools include execution price, slippage, and execution liquidity score; otherwise bid/ask fields remain null and execution is proxy-based.",
            "credit_execution_note": "Defined-risk credit structures such as short_iron_condor include executable credit, credit slippage, execution-adjusted max loss, and optional credit/width and bid/ask spread no-trade filters.",
            "margin_note": "Strategy/scenario tools include simplified defined-risk margin required and risk budget pass/fail fields; exchange/SPAN margin is not modeled.",
        },
        "options": [_enriched_option_to_dict(row) for row in report.options],
    }


def build_option_trade_context(
    symbol: str,
    trade_date: str | None = None,
    expiry: str | None = None,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> dict[str, Any]:
    """Return compact JSON for LLM agents to interpret, not recalculate."""
    report = analyze_option_chain(symbol, trade_date=trade_date, expiry=expiry, risk_free_rate=risk_free_rate)
    nearest_expiry = min(report.term_structure) if report.term_structure else None
    return {
        "product": report.product,
        "trade_date": report.trade_date,
        "underlying": {
            "symbol": report.underlying_symbol,
            "price": report.underlying_price,
            "price_basis": report.price_basis.get("underlying_price_basis", "unknown"),
            "price_basis_detail": report.price_basis,
        },
        "volatility": {
            "atm_iv": _round_or_none(report.atm_iv),
            "skew_25d": _round_or_none(report.skew_25d),
            "nearest_expiry": nearest_expiry,
            "nearest_expiry_iv": _round_or_none(report.term_structure.get(nearest_expiry)) if nearest_expiry else None,
            "term_structure": {k: _round_or_none(v) for k, v in sorted(report.term_structure.items())},
            "vol_surface": report.vol_surface,
        },
        "positioning": {
            "pcr_oi": _round_or_none(report.pcr_open_interest),
            "pcr_volume": _round_or_none(report.pcr_volume),
            "call_wall": _wall_to_dict(report.call_wall),
            "put_wall": _wall_to_dict(report.put_wall),
            "gamma_flip": _round_or_none(report.gamma_flip, 4),
            "total_gex": _round_or_none(report.exposure.total_gex, 4),
            "total_abs_gex": _round_or_none(report.exposure.total_abs_gex, 4),
            "total_dex": _round_or_none(report.exposure.total_dex, 4),
        },
        "risk_assumptions": {
            "model": "Black-76",
            "risk_free_rate": risk_free_rate,
            "price_basis": "option close + futures close",
            "price_basis_detail": report.price_basis,
            "dealer_position_unknown": True,
            "gex_dex_are_scenario_metrics": True,
            "contract_multiplier_applied": False,
        },
        "agent_lens": _AGENT_LENS,
    }


def build_option_analytics_markdown(
    symbol: str,
    trade_date: str | None = None,
    expiry: str | None = None,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> str:
    """Return Markdown report for humans/agents."""
    report: OptionAnalyticsReport = analyze_option_chain(
        symbol, trade_date=trade_date, expiry=expiry, risk_free_rate=risk_free_rate
    )
    lines = report.to_markdown().splitlines()
    insert_at = 5 if len(lines) >= 5 else len(lines)
    lines.insert(insert_at, "- Price basis: option close + futures close")
    lines.insert(insert_at + 1, f"- Risk-free rate: {risk_free_rate:.4f}")
    return "\n".join(lines) + "\n"


@tool
def get_option_trade_context(
    symbol: Annotated[str, "SHFE option product or alias, e.g. CU, copper, 铜, AU"],
    trade_date: Annotated[str | None, "Trade date in yyyy-mm-dd or yyyymmdd format"] = None,
    expiry: Annotated[str | None, "Optional option maturity date in yyyymmdd format"] = None,
) -> str:
    """Return compact option trade context JSON for TradingAgents LLM agents."""
    return json.dumps(build_option_trade_context(symbol, trade_date, expiry), ensure_ascii=False, default=str)


@tool
def get_option_analytics_json(
    symbol: Annotated[str, "SHFE option product or alias, e.g. CU, copper, 铜, AU"],
    trade_date: Annotated[str | None, "Trade date in yyyy-mm-dd or yyyymmdd format"] = None,
    expiry: Annotated[str | None, "Optional option maturity date in yyyymmdd format"] = None,
) -> str:
    """Return full option analytics audit JSON including individual option rows."""
    return json.dumps(build_option_analytics_payload(symbol, trade_date, expiry), ensure_ascii=False, default=str)


@tool
def get_option_analytics_report(
    symbol: Annotated[str, "SHFE option product or alias, e.g. CU, copper, 铜, AU"],
    trade_date: Annotated[str | None, "Trade date in yyyy-mm-dd or yyyymmdd format"] = None,
    expiry: Annotated[str | None, "Optional option maturity date in yyyymmdd format"] = None,
) -> str:
    """Return a Markdown option analytics report for a SHFE option product."""
    return build_option_analytics_markdown(symbol, trade_date, expiry)


@tool
def get_option_strategy_candidate(
    symbol: Annotated[str, "SHFE option product or alias, e.g. CU, copper, 铜, AU"],
    strategy_type: Annotated[str, "Strategy type, e.g. bull_call_spread, bear_put_spread, long_straddle, long_strangle, long_call_butterfly, long_put_butterfly, short_iron_condor"],
    trade_date: Annotated[str | None, "Trade date in yyyy-mm-dd or yyyymmdd format"] = None,
    expiry: Annotated[str | None, "Optional option maturity date in yyyymmdd format"] = None,
    risk_budget_cash: Annotated[float | None, "Optional risk budget in CNY for max-loss utilization"] = None,
    min_credit_pct_of_wing_width: Annotated[float | None, "Optional credit quality filter for defined-risk credit structures; executable credit divided by wing width must be at least this ratio"] = None,
    max_bid_ask_spread_pct: Annotated[float | None, "Optional bid/ask quality filter; maximum leg bid/ask spread percentage must be at or below this ratio"] = None,
) -> str:
    """Return a structured option strategy candidate JSON with legs/payoff/Greeks/liquidity/cash risk."""
    return json.dumps(
        build_option_strategy_candidate(
            symbol,
            strategy_type,
            trade_date=trade_date,
            expiry=expiry,
            risk_budget_cash=risk_budget_cash,
            min_credit_pct_of_wing_width=min_credit_pct_of_wing_width,
            max_bid_ask_spread_pct=max_bid_ask_spread_pct,
        ),
        ensure_ascii=False,
        default=str,
    )


@tool
def get_option_strategy_selection(
    symbol: Annotated[str, "SHFE option product or alias, e.g. CU, copper, 铜, AU"],
    trade_date: Annotated[str | None, "Trade date in yyyy-mm-dd or yyyymmdd format"] = None,
    expiry: Annotated[str | None, "Optional option maturity date in yyyymmdd format"] = None,
    directional_bias: Annotated[str | None, "Directional bias: bullish, bearish, neutral/range"] = "neutral",
    volatility_view: Annotated[str | None, "Volatility regime view, e.g. range_bound_high_iv, iv_up, low_iv, moderate_iv"] = None,
    risk_budget_cash: Annotated[float | None, "Optional risk budget in CNY for ranking and no-trade checks"] = None,
    min_credit_pct_of_wing_width: Annotated[float | None, "Optional credit filter for short iron condor; executable credit divided by wing width must be at least this ratio"] = None,
    max_bid_ask_spread_pct: Annotated[float | None, "Optional bid/ask filter; maximum leg bid/ask spread percentage must be at or below this ratio"] = None,
    constraint_mode: Annotated[str, "Constraint handling: strict turns liquidity/risk-budget/credit filter failures into no_trade; relaxed keeps them as review candidates with warnings"] = "strict",
    detail_level: Annotated[str, "Payload detail level: compact for LLM-facing summaries, full for audit/debug JSON"] = "compact",
) -> str:
    """Return deterministic option strategy ranking; compact by default for LLM agents."""
    selection = build_option_strategy_selection(
        symbol,
        trade_date=trade_date,
        expiry=expiry,
        directional_bias=directional_bias,
        volatility_view=volatility_view,
        risk_budget_cash=risk_budget_cash,
        min_credit_pct_of_wing_width=min_credit_pct_of_wing_width,
        max_bid_ask_spread_pct=max_bid_ask_spread_pct,
        constraint_mode=constraint_mode,
    )
    level = _normalize_detail_level(detail_level)
    payload = selection if level == "full" else _compact_selection_payload(selection)
    if level == "full":
        payload = {"detail_level": "full", **payload}
    return json.dumps(payload, ensure_ascii=False, default=str)


@tool
def get_option_strategy_scenarios(
    symbol: Annotated[str, "SHFE option product or alias, e.g. CU, copper, 铜, AU"],
    strategy_type: Annotated[str, "Strategy type, e.g. bull_call_spread, bear_put_spread, long_straddle, long_strangle, long_call_butterfly, long_put_butterfly, short_iron_condor"],
    trade_date: Annotated[str | None, "Trade date in yyyy-mm-dd or yyyymmdd format"] = None,
    expiry: Annotated[str | None, "Optional option maturity date in yyyymmdd format"] = None,
    price_shocks: Annotated[list[float] | None, "Underlying shocks, e.g. [-0.03, 0, 0.03]"] = None,
    iv_shocks: Annotated[list[float] | None, "Absolute IV shocks, e.g. [-0.02, 0, 0.02]"] = None,
    days_forward: Annotated[list[int] | None, "Forward days, e.g. [0, 5, 20]"] = None,
    risk_budget_cash: Annotated[float | None, "Optional risk budget in CNY for scenario loss utilization"] = None,
    detail_level: Annotated[str, "Payload detail level: compact omits per-leg values and uses a smaller default grid; full keeps audit/debug detail"] = "compact",
) -> str:
    """Return option strategy scenario PnL matrix; compact by default for LLM agents."""
    level = _normalize_detail_level(detail_level)
    payload = build_option_strategy_scenarios(
        symbol,
        strategy_type,
        trade_date=trade_date,
        expiry=expiry,
        price_shocks=price_shocks or ((-0.05, -0.03, -0.01, 0.0, 0.01, 0.03, 0.05) if level == "full" else (-0.03, 0.0, 0.03)),
        iv_shocks=iv_shocks or ((-0.05, -0.02, 0.0, 0.02, 0.05) if level == "full" else (-0.02, 0.0, 0.02)),
        days_forward=days_forward or ((0, 1, 5, 20) if level == "full" else (0, 5, 20)),
        risk_budget_cash=risk_budget_cash,
    )
    if level == "full":
        payload = {"detail_level": "full", **payload}
    else:
        payload = _compact_scenarios_payload(payload)
    return json.dumps(payload, ensure_ascii=False, default=str)


@tool
def get_option_strategy_replay(
    symbol: Annotated[str, "SHFE option product or alias, e.g. CU, copper, 铜, AU"],
    strategy_type: Annotated[str, "Strategy type, e.g. bull_call_spread, bear_put_spread, long_straddle, long_strangle, long_call_butterfly, long_put_butterfly, short_iron_condor"],
    entry_date: Annotated[str, "Entry trade date in yyyy-mm-dd or yyyymmdd format"],
    review_dates: Annotated[list[str] | None, "Historical review dates to mark the same entry legs, e.g. ['2026-05-06']"] = None,
    expiry: Annotated[str | None, "Optional option maturity date in yyyymmdd format"] = None,
    risk_budget_cash: Annotated[float | None, "Optional risk budget in CNY for replay utilization"] = None,
) -> str:
    """Return historical replay/post-trade review JSON for a structured option strategy."""
    return json.dumps(
        build_option_strategy_replay(
            symbol,
            strategy_type=strategy_type,
            entry_date=entry_date,
            review_dates=review_dates,
            expiry=expiry,
            risk_budget_cash=risk_budget_cash,
        ),
        ensure_ascii=False,
        default=str,
    )


@tool
def get_option_strategy_report(
    symbol: Annotated[str, "SHFE option product or alias, e.g. CU, copper, 铜, AU"],
    strategy_type: Annotated[str, "Strategy type, e.g. bull_call_spread, bear_put_spread, long_straddle, long_call_butterfly, long_put_butterfly, short_iron_condor"],
    trade_date: Annotated[str | None, "Trade date in yyyy-mm-dd or yyyymmdd format"] = None,
    expiry: Annotated[str | None, "Optional option maturity date in yyyymmdd format"] = None,
    review_dates: Annotated[list[str] | None, "Optional historical review dates for replay section"] = None,
    risk_budget_cash: Annotated[float | None, "Optional risk budget in CNY"] = None,
    detail_level: Annotated[str, "Payload detail level: compact for LLM-facing summaries, full for audit/debug JSON"] = "compact",
) -> str:
    """Return a Feishu-ready option report; compact by default for LLM agents."""
    report = build_option_strategy_report(
        symbol,
        strategy_type=strategy_type,
        trade_date=trade_date,
        expiry=expiry,
        review_dates=review_dates,
        risk_budget_cash=risk_budget_cash,
    )
    level = _normalize_detail_level(detail_level)
    payload = {"detail_level": "full", **report} if level == "full" else _compact_report_payload(report)
    return json.dumps(payload, ensure_ascii=False, default=str)


@tool
def get_option_research_pack(
    symbol: Annotated[str, "SHFE option product or alias, e.g. CU, copper, 铜, AU"],
    trade_date: Annotated[str | None, "Trade date in yyyy-mm-dd or yyyymmdd format"] = None,
    expiry: Annotated[str | None, "Optional option maturity date in yyyymmdd format"] = None,
    strategy_type: Annotated[str | None, "Optional explicit strategy override; omit to use selector_auto"] = None,
    directional_bias: Annotated[str | None, "Directional bias for selector: bullish, bearish, neutral/range"] = "neutral",
    volatility_view: Annotated[str | None, "Volatility regime view, e.g. range_bound_high_iv, iv_up, low_iv, moderate_iv"] = None,
    review_dates: Annotated[list[str] | None, "Optional historical review dates for replay performance section"] = None,
    risk_budget_cash: Annotated[float | None, "Optional risk budget in CNY"] = None,
    min_credit_pct_of_wing_width: Annotated[float | None, "Optional credit filter for short iron condor; executable credit divided by wing width must be at least this ratio"] = None,
    max_bid_ask_spread_pct: Annotated[float | None, "Optional bid/ask filter; maximum leg bid/ask spread percentage must be at or below this ratio"] = None,
    constraint_mode: Annotated[str, "Constraint handling for selector_auto: strict or relaxed"] = "strict",
    delivery_target: Annotated[str | None, "Optional Feishu/Hermes target for dry-run delivery payload"] = None,
    detail_level: Annotated[str, "Payload detail level: compact for LLM-facing summaries, full for complete artifacts/debug JSON"] = "compact",
) -> str:
    """Return one side-effect-free research pack; compact by default for LLM agents."""
    pack = build_option_research_pack(
        symbol,
        trade_date=trade_date,
        expiry=expiry,
        strategy_type=strategy_type,
        directional_bias=directional_bias,
        volatility_view=volatility_view,
        review_dates=review_dates,
        risk_budget_cash=risk_budget_cash,
        min_credit_pct_of_wing_width=min_credit_pct_of_wing_width,
        max_bid_ask_spread_pct=max_bid_ask_spread_pct,
        constraint_mode=constraint_mode,
        delivery_target=delivery_target,
    )
    level = _normalize_detail_level(detail_level)
    payload = {"detail_level": "full", **pack} if level == "full" else _compact_research_pack_payload(pack)
    return json.dumps(payload, ensure_ascii=False, default=str)


@tool
def get_option_research_pack_hermes_cron_spec(
    symbol: Annotated[str, "SHFE option product or alias, e.g. CU, copper, 铜, AU"],
    trade_date: Annotated[str | None, "Trade date in yyyy-mm-dd or yyyymmdd format"] = None,
    expiry: Annotated[str | None, "Optional option maturity date in yyyymmdd format"] = None,
    strategy_type: Annotated[str | None, "Optional explicit strategy override; omit to use selector_auto"] = None,
    directional_bias: Annotated[str | None, "Directional bias for selector: bullish, bearish, neutral/range"] = "neutral",
    volatility_view: Annotated[str | None, "Volatility regime view, e.g. range_bound_high_iv, iv_up, low_iv, moderate_iv"] = None,
    review_dates: Annotated[list[str] | None, "Optional historical review dates for replay performance section"] = None,
    risk_budget_cash: Annotated[float | None, "Optional risk budget in CNY"] = None,
    min_credit_pct_of_wing_width: Annotated[float | None, "Optional credit filter for short iron condor; executable credit divided by wing width must be at least this ratio"] = None,
    max_bid_ask_spread_pct: Annotated[float | None, "Optional bid/ask filter; maximum leg bid/ask spread percentage must be at or below this ratio"] = None,
    constraint_mode: Annotated[str, "Constraint handling for selector_auto: strict or relaxed"] = "strict",
    target: Annotated[str | None, "Feishu/Hermes delivery target, e.g. feishu:oc_xxx"] = None,
    schedule: Annotated[str, "Hermes cron schedule, e.g. '0 8 * * 1-5'"] = "0 8 * * 1-5",
    output_dir: Annotated[str | None, "Optional artifact output directory for the cron script"] = None,
) -> str:
    """Return a Hermes no-agent cron spec for research-pack Markdown stdout delivery."""
    return json.dumps(
        build_option_research_pack_hermes_cron_spec(
            symbol,
            trade_date=trade_date,
            expiry=expiry,
            strategy_type=strategy_type,
            directional_bias=directional_bias,
            volatility_view=volatility_view,
            review_dates=review_dates,
            risk_budget_cash=risk_budget_cash,
            min_credit_pct_of_wing_width=min_credit_pct_of_wing_width,
            max_bid_ask_spread_pct=max_bid_ask_spread_pct,
            constraint_mode=constraint_mode,
            target=target,
            schedule=schedule,
            output_dir=output_dir,
        ),
        ensure_ascii=False,
        default=str,
    )


@tool
def get_option_feishu_delivery_payload(
    symbol: Annotated[str, "SHFE option product or alias, e.g. CU, copper, 铜, AU"],
    strategy_type: Annotated[str, "Strategy type, e.g. bull_call_spread, bear_put_spread, long_straddle, long_strangle, long_call_butterfly, long_put_butterfly, short_iron_condor"],
    trade_date: Annotated[str | None, "Trade date in yyyy-mm-dd or yyyymmdd format"] = None,
    expiry: Annotated[str | None, "Optional option maturity date in yyyymmdd format"] = None,
    review_dates: Annotated[list[str] | None, "Optional historical review dates for replay section"] = None,
    risk_budget_cash: Annotated[float | None, "Optional risk budget in CNY"] = None,
    target: Annotated[str | None, "Feishu/Hermes target, e.g. feishu:oc_xxx"] = None,
    dry_run: Annotated[bool, "When true, build a side-effect-free payload without sending"] = True,
) -> str:
    """Return a side-effect-free Feishu delivery payload for the option report."""
    report = build_option_strategy_report(
        symbol,
        strategy_type=strategy_type,
        trade_date=trade_date,
        expiry=expiry,
        review_dates=review_dates,
        risk_budget_cash=risk_budget_cash,
    )
    return json.dumps(
        build_feishu_delivery_payload(report, target=target, dry_run=dry_run),
        ensure_ascii=False,
        default=str,
    )


@tool
def get_option_hermes_cron_delivery_spec(
    symbol: Annotated[str, "SHFE option product or alias, e.g. CU, copper, 铜, AU"],
    strategy_type: Annotated[str, "Strategy type, e.g. bull_call_spread, bear_put_spread, long_straddle, long_strangle, long_call_butterfly, long_put_butterfly, short_iron_condor"],
    trade_date: Annotated[str | None, "Trade date in yyyy-mm-dd or yyyymmdd format"] = None,
    expiry: Annotated[str | None, "Optional option maturity date in yyyymmdd format"] = None,
    review_dates: Annotated[list[str] | None, "Optional historical review dates for replay section"] = None,
    risk_budget_cash: Annotated[float | None, "Optional risk budget in CNY"] = None,
    target: Annotated[str | None, "Feishu/Hermes target, e.g. feishu:oc_xxx"] = None,
    schedule: Annotated[str, "Hermes cron schedule, e.g. '0 8 * * 1-5'"] = "0 8 * * 1-5",
) -> str:
    """Return a Hermes no-agent cron spec for stdout-based Feishu report delivery."""
    report = build_option_strategy_report(
        symbol,
        strategy_type=strategy_type,
        trade_date=trade_date,
        expiry=expiry,
        review_dates=review_dates,
        risk_budget_cash=risk_budget_cash,
    )
    payload = build_feishu_delivery_payload(report, target=target, dry_run=False)
    spec = build_hermes_cron_delivery_spec(payload, schedule=schedule)
    spec["payload_preview"] = {
        "title": payload["title"],
        "target": payload["target"],
        "message_length": len(payload["message"]),
    }
    return json.dumps(spec, ensure_ascii=False, default=str)
