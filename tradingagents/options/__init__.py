"""Options analytics core for commodity futures options.

This package keeps deterministic option calculations out of LLM prompts. Agents
should consume its structured outputs rather than asking an LLM to compute IV,
Greeks, PCR, walls, or exposure metrics.
"""

from tradingagents.options.analytics import analyze_option_chain
from tradingagents.options.contract_specs import contract_multiplier_for_product, multiplier_unit_for_product
from tradingagents.options.data_loader import load_option_chain_snapshot
from tradingagents.options.pricing import black76_price, implied_volatility
from tradingagents.options.delivery import build_hermes_cron_delivery_spec, send_feishu_delivery_payload
from tradingagents.options.reports import build_feishu_delivery_payload, build_option_strategy_report
from tradingagents.options.selector import build_option_strategy_selection

__all__ = [
    "analyze_option_chain",
    "black76_price",
    "build_feishu_delivery_payload",
    "build_hermes_cron_delivery_spec",
    "build_option_strategy_report",
    "build_option_strategy_selection",
    "contract_multiplier_for_product",
    "implied_volatility",
    "load_option_chain_snapshot",
    "multiplier_unit_for_product",
    "send_feishu_delivery_payload",
]
