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
from tradingagents.options.models import EnrichedOptionQuote, OptionAnalyticsReport


_AGENT_LENS = {
    "market_analyst": "underlying trend, RV, technical context, and futures anchor",
    "fundamentals_analyst": "inventory, term structure, macro anchors, and volatility regime context",
    "news_analyst": "event risks that can reprice IV, skew, and tail demand",
    "bull_researcher": "bullish directional or bullish-volatility option structures supported by data",
    "bear_researcher": "bearish directional or bearish-volatility option structures supported by data",
    "trader": "translate validated views into option structures, entry conditions, and no-trade alternatives",
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
        "price_basis": "close" if row.quote.close is not None and row.quote.close > 0 else "settle_fallback",
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
        "price_basis": "close",
        "risk_free_rate": risk_free_rate,
        "atm_iv": _round_or_none(report.atm_iv),
        "skew_25d": _round_or_none(report.skew_25d),
        "term_structure": {k: _round_or_none(v) for k, v in sorted(report.term_structure.items())},
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
            "contract_multiplier_note": "Phase-1 exposure is relative unless multiplier enrichment is added.",
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
            "price_basis": "close",
        },
        "volatility": {
            "atm_iv": _round_or_none(report.atm_iv),
            "skew_25d": _round_or_none(report.skew_25d),
            "nearest_expiry": nearest_expiry,
            "nearest_expiry_iv": _round_or_none(report.term_structure.get(nearest_expiry)) if nearest_expiry else None,
            "term_structure": {k: _round_or_none(v) for k, v in sorted(report.term_structure.items())},
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
