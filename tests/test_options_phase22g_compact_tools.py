"""Phase 22G tests for compact LLM-facing options tools.

The full deterministic research-pack artifacts remain available, but live
TradingAgents analyst nodes should receive compact tool payloads by default so
full graph runs do not spend minutes digesting 50k+ character option outputs.
"""

from __future__ import annotations

import json


def test_strategy_selection_tool_defaults_to_compact_payload_and_full_is_opt_in(shfe_options_db):
    from tests.test_options_phase17_strategy_selector import _install_selector_fixture
    from tradingagents.agents.utils.options_tools import get_option_strategy_selection

    _install_selector_fixture(shfe_options_db)

    args = {
        "symbol": "CU",
        "trade_date": "2026-05-01",
        "expiry": "20260625",
        "directional_bias": "neutral",
        "volatility_view": "range_bound_high_iv",
        "risk_budget_cash": 6_000,
        "min_credit_pct_of_wing_width": 0.20,
        "max_bid_ask_spread_pct": 0.50,
        "constraint_mode": "relaxed",
    }
    compact = json.loads(get_option_strategy_selection.invoke(args))
    full = json.loads(get_option_strategy_selection.invoke({**args, "detail_level": "full"}))

    assert compact["detail_level"] == "compact"
    assert compact["selected_strategy"] == "short_iron_condor"
    assert compact["ranked_candidates"][0]["strategy_type"] == "short_iron_condor"
    assert "candidate" not in compact["ranked_candidates"][0]
    assert compact["portfolio_summary"]["selected_strategy"]["strategy_type"] == "short_iron_condor"
    assert "markdown" not in compact
    assert full["detail_level"] == "full"
    assert "candidate" in full["ranked_candidates"][0]
    assert "markdown" in full
    assert len(json.dumps(compact, ensure_ascii=False, default=str)) < len(json.dumps(full, ensure_ascii=False, default=str)) * 0.35


def test_strategy_scenarios_tool_defaults_to_compact_grid_without_leg_values(shfe_options_db):
    from tradingagents.agents.utils.options_tools import get_option_strategy_scenarios

    args = {
        "symbol": "CU",
        "strategy_type": "bull_call_spread",
        "trade_date": "2026-05-01",
        "expiry": "20260625",
    }
    compact = json.loads(get_option_strategy_scenarios.invoke(args))
    full = json.loads(get_option_strategy_scenarios.invoke({**args, "detail_level": "full"}))

    assert compact["detail_level"] == "compact"
    assert compact["scenario_grid"]["price_shocks"] == [-0.03, 0.0, 0.03]
    assert compact["scenario_grid"]["iv_shocks"] == [-0.02, 0.0, 0.02]
    assert compact["scenario_grid"]["days_forward"] == [0, 5, 20]
    assert len(compact["scenarios"]) == 27
    assert "leg_values" not in compact["scenarios"][0]
    assert compact["strategy"]["strategy_type"] == "bull_call_spread"
    assert "legs" not in compact["strategy"]
    assert full["detail_level"] == "full"
    assert len(full["scenarios"]) > len(compact["scenarios"])
    assert "leg_values" in full["scenarios"][0]


def test_market_analyst_options_toolset_defaults_to_compact_tools_only():
    from tests.test_options_analyst_integration import SpyLLM, _state
    from tradingagents.agents.analysts.market_analyst import create_market_analyst

    llm = SpyLLM()
    node = create_market_analyst(llm)
    node(_state("CU"))

    assert "get_option_trade_context" in llm.bound_tool_names
    assert "get_option_strategy_selection" in llm.bound_tool_names
    assert "get_option_research_pack" in llm.bound_tool_names
    assert "get_option_strategy_report" not in llm.bound_tool_names
    assert "get_option_strategy_scenarios" not in llm.bound_tool_names
    assert "get_option_analytics_report" not in llm.bound_tool_names
    assert "get_option_analytics_json" not in llm.bound_tool_names
    prompt = "\n".join(llm.prompt_messages).lower()
    assert "compact" in prompt
    assert "detail_level='full'" in prompt or 'detail_level="full"' in prompt


def test_trading_graph_market_tool_node_uses_compact_options_surface():
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    tool_nodes = graph._create_tool_nodes()
    market_tools = set(getattr(tool_nodes["market"], "tools_by_name", {}).keys())

    assert {"get_option_trade_context", "get_option_strategy_selection", "get_option_research_pack"}.issubset(market_tools)
    assert "get_option_strategy_report" not in market_tools
    assert "get_option_strategy_scenarios" not in market_tools
    assert "get_option_analytics_json" not in market_tools
