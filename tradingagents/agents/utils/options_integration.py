"""Helpers for attaching deterministic options analytics to analyst nodes.

The existing TradingAgents graph remains intact. These helpers only augment the
stock/futures-oriented analyst tools when the requested instrument is one of
Alan's SHFE metals option products.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from tradingagents.agents.utils.options_tools import (
    get_option_analytics_json,
    get_option_analytics_report,
    get_option_trade_context,
)
from tradingagents.options.data_loader import normalize_product

_OPTIONS_PRODUCTS = {"CU", "AU", "AG", "AL", "ZN", "NI", "PB", "SN", "AO"}

_ROLE_LENS = {
    "market": "underlying trend, realized volatility, technical context, futures anchor, and option-implied volatility.",
    "fundamentals": "inventory, warehouse receipts, term structure, macro anchors, and volatility regime drivers.",
    "news": "event risks, policy/macroeconomic shocks, supply disruptions, and tail-demand repricing for IV/skew.",
}


def is_options_analytics_symbol(symbol: str | None) -> bool:
    """Return True when a symbol can be analyzed by the SHFE options core."""
    if not symbol:
        return False
    return normalize_product(symbol) in _OPTIONS_PRODUCTS


def augment_tools_for_options(
    tools: Sequence[Any],
    symbol: str | None,
    analyst_role: str,
) -> list[Any]:
    """Add options analytics tools for supported SHFE metals symbols.

    The compact context tool is added to every analyst role. Market analysts
    also get the Markdown report and full audit JSON so they can inspect the
    deterministic calculations without asking the LLM to recompute metrics.
    """
    augmented = list(tools)
    if not is_options_analytics_symbol(symbol):
        return augmented

    if get_option_trade_context not in augmented:
        augmented.append(get_option_trade_context)

    if analyst_role == "market":
        for tool in (get_option_analytics_report, get_option_analytics_json):
            if tool not in augmented:
                augmented.append(tool)
    return augmented


def options_analyst_instruction(symbol: str | None, analyst_role: str) -> str:
    """Return volatility-first prompt guidance for SHFE options instruments."""
    if not is_options_analytics_symbol(symbol):
        return ""

    product = normalize_product(symbol)
    lens = _ROLE_LENS.get(analyst_role, "volatility regime, option positioning, and risk scenarios.")
    return (
        f"\n\nSHFE options analytics mode is active for {product}. "
        "Use get_option_trade_context first to obtain deterministic option analytics. "
        "Keep the analysis volatility-first: focus on IV level, term structure, skew, PCR, walls, gamma flip, and Greeks/risk scenarios. "
        "Do not recalculate IV/Greeks/GEX/DEX in the LLM; treat the tool JSON as the source of truth. "
        "Default price basis is option close + futures close, with r = 1.5%; use settlement only for explicit settlement/risk-control requests. "
        "GEX/DEX are exchange-OI scenario/concentration metrics because dealer position is unknown. "
        f"For this analyst role, emphasize {lens}"
    )
