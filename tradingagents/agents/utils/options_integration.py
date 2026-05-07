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


def options_researcher_instruction(symbol: str | None, stance: str) -> str:
    """Return bull/bear debate guidance for volatility-first option research."""
    if not is_options_analytics_symbol(symbol):
        return ""

    product = normalize_product(symbol)
    stance_word = "rising" if stance == "bull" else "falling"
    counter_word = "falling" if stance == "bull" else "rising"
    return (
        f"\n\nSHFE options research mode is active for {product}. Reframe the debate around implied volatility, not only outright direction. "
        "For each horizon, explicitly compare the probability of implied volatility rising versus falling: 5-day, 20-day, and 40-day. Use the explicit rise/fall framing so the trader can compare paths. "
        f"As the {stance} researcher, make the strongest evidence-based case for {stance_word} volatility where justified, while acknowledging conditions that would favor {counter_word} volatility. "
        "Anchor the argument in the analyst reports' option context: ATM IV, term structure, skew, PCR, walls, gamma flip, event risk, and inventory/macro drivers. "
        "Do not recalculate IV/Greeks/GEX/DEX; treat deterministic option analytics from the tools/reports as source-of-truth inputs. "
        "End with a concise horizon table: 5-day / 20-day / 40-day, IV-up probability, IV-down probability, key catalysts, and preferred option structure bias."
    )


def options_trader_instruction(symbol: str | None) -> str:
    """Return trader guidance for options mode."""
    if not is_options_analytics_symbol(symbol):
        return ""

    product = normalize_product(symbol)
    return (
        f"\n\nSHFE options trading mode is active for {product}. Before proposing any option structure, first state your volatility view. "
        "Synthesize the previous analyst evidence plus the bull and bear debate about whether implied volatility is more likely to rise or fall over the 5-day, 20-day, and 40-day horizons. "
        "Only after that volatility view should you propose option structures. Prefer defined-risk structures unless the evidence and liquidity justify otherwise. "
        "Tie every structure to the vol view, directional view, expiry, strike area, liquidity, Greeks, and no-trade conditions. "
        "Do not recalculate IV/Greeks/GEX/DEX; use the prior deterministic analytics as source-of-truth inputs. "
        "Default basis remains option close + futures close, r = 1.5%, with GEX/DEX treated only as exchange-OI scenario metrics."
    )


def options_research_manager_instruction(symbol: str | None) -> str:
    """Return research-manager guidance for preserving the volatility debate handoff."""
    if not is_options_analytics_symbol(symbol):
        return ""

    product = normalize_product(symbol)
    return (
        f"\n\nSHFE options research-manager mode is active for {product}. Your investment plan must preserve a Volatility Debate Summary for the trader. "
        "Compare the bull and bear arguments on the probability of implied volatility rising versus falling across 5-day, 20-day, and 40-day horizons. "
        "State which horizon has the clearest edge, which horizons are balanced, and what catalysts would flip the view. "
        "The trader must first state a volatility view before selecting option structures, so make this handoff explicit."
    )
