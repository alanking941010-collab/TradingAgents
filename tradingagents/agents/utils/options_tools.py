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
from tradingagents.options.research_pack import build_option_research_pack
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
        "price_basis": "close",
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
            "price_basis": "close",
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
) -> str:
    """Return deterministic option strategy ranking from vol surface, execution, margin, and risk budget."""
    return json.dumps(
        build_option_strategy_selection(
            symbol,
            trade_date=trade_date,
            expiry=expiry,
            directional_bias=directional_bias,
            volatility_view=volatility_view,
            risk_budget_cash=risk_budget_cash,
            min_credit_pct_of_wing_width=min_credit_pct_of_wing_width,
            max_bid_ask_spread_pct=max_bid_ask_spread_pct,
        ),
        ensure_ascii=False,
        default=str,
    )


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
) -> str:
    """Return option strategy scenario PnL matrix JSON across price/IV/time shocks with cash PnL."""
    return json.dumps(
        build_option_strategy_scenarios(
            symbol,
            strategy_type,
            trade_date=trade_date,
            expiry=expiry,
            price_shocks=price_shocks or (-0.05, -0.03, -0.01, 0.0, 0.01, 0.03, 0.05),
            iv_shocks=iv_shocks or (-0.05, -0.02, 0.0, 0.02, 0.05),
            days_forward=days_forward or (0, 1, 5, 20),
            risk_budget_cash=risk_budget_cash,
        ),
        ensure_ascii=False,
        default=str,
    )


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
    strategy_type: Annotated[str, "Strategy type, e.g. bull_call_spread, bear_put_spread, long_straddle, long_strangle, long_call_butterfly, long_put_butterfly, short_iron_condor"],
    trade_date: Annotated[str | None, "Trade date in yyyy-mm-dd or yyyymmdd format"] = None,
    expiry: Annotated[str | None, "Optional option maturity date in yyyymmdd format"] = None,
    review_dates: Annotated[list[str] | None, "Optional historical review dates for replay section"] = None,
    risk_budget_cash: Annotated[float | None, "Optional risk budget in CNY"] = None,
) -> str:
    """Return a Feishu-ready Markdown report pipeline JSON for one structured option strategy."""
    return json.dumps(
        build_option_strategy_report(
            symbol,
            strategy_type=strategy_type,
            trade_date=trade_date,
            expiry=expiry,
            review_dates=review_dates,
            risk_budget_cash=risk_budget_cash,
        ),
        ensure_ascii=False,
        default=str,
    )


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
    delivery_target: Annotated[str | None, "Optional Feishu/Hermes target for dry-run delivery payload"] = None,
) -> str:
    """Return one side-effect-free research pack: selection, portfolio summary, selected report, replay, and Feishu payload."""
    return json.dumps(
        build_option_research_pack(
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
            delivery_target=delivery_target,
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
