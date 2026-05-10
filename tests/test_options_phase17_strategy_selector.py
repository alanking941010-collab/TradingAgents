"""Phase 17 tests for deterministic strategy selector and regime-to-strategy ranking."""

from __future__ import annotations

import json

from tests.test_options_phase14b_credit_strategies import _install_iron_condor_wings
from tests.test_options_phase15_credit_execution import _install_iron_condor_bid_ask_snapshot


def _install_selector_fixture(db_path):
    _install_iron_condor_wings(db_path)
    _install_iron_condor_bid_ask_snapshot(db_path)


def test_strategy_selector_ranks_iron_condor_for_neutral_range_view(shfe_options_db):
    _install_selector_fixture(shfe_options_db)

    from tradingagents.options.selector import build_option_strategy_selection

    selection = build_option_strategy_selection(
        "CU",
        trade_date="2026-05-01",
        expiry="20260625",
        directional_bias="neutral",
        volatility_view="range_bound_high_iv",
        risk_budget_cash=6_000,
        min_credit_pct_of_wing_width=0.20,
        max_bid_ask_spread_pct=0.50,
    )

    assert selection["selection_type"] == "option_strategy_ranking"
    assert selection["selected_strategy"] == "short_iron_condor"
    assert selection["surface_regime"]["term_shape"] in {"contango", "backwardation", "flat", "single_expiry"}
    assert selection["surface_regime"]["nearest_expiry"] == "2026-06-25"
    assert len(selection["ranked_candidates"]) >= 4

    top = selection["ranked_candidates"][0]
    assert top["strategy_type"] == "short_iron_condor"
    assert top["score"] > 0
    assert top["decision"] in {"candidate", "watch"}
    assert any("range" in reason.lower() or "neutral" in reason.lower() for reason in top["ranking_reasons"])
    assert top["risk_budget_status"] == "pass"
    assert top["credit_execution"]["executable_credit_points"] > 0
    assert "策略排序" in selection["markdown"]


def test_strategy_selector_uses_directional_bias_to_rank_bullish_spread(shfe_options_db):
    _install_selector_fixture(shfe_options_db)

    from tradingagents.options.selector import build_option_strategy_selection

    selection = build_option_strategy_selection(
        "CU",
        trade_date="2026-05-01",
        expiry="20260625",
        directional_bias="bullish",
        volatility_view="moderate_iv",
        risk_budget_cash=10_000,
    )

    ranked_types = [row["strategy_type"] for row in selection["ranked_candidates"]]
    assert "bull_call_spread" in ranked_types
    assert ranked_types.index("bull_call_spread") < ranked_types.index("bear_put_spread")
    bull = next(row for row in selection["ranked_candidates"] if row["strategy_type"] == "bull_call_spread")
    assert any("bullish" in reason.lower() for reason in bull["ranking_reasons"])
    assert bull["risk_budget_status"] in {"pass", "fail", "not_provided"}


def test_strategy_selector_tool_returns_parseable_json_and_schema_mentions_bias(shfe_options_db):
    _install_selector_fixture(shfe_options_db)

    from tradingagents.agents.utils.options_tools import get_option_strategy_selection

    raw = get_option_strategy_selection.invoke({
        "symbol": "CU",
        "trade_date": "2026-05-01",
        "expiry": "20260625",
        "directional_bias": "neutral",
        "volatility_view": "range_bound_high_iv",
        "risk_budget_cash": 6_000,
        "min_credit_pct_of_wing_width": 0.20,
        "max_bid_ask_spread_pct": 0.50,
    })
    payload = json.loads(raw)

    assert payload["selected_strategy"] == "short_iron_condor"
    assert payload["ranked_candidates"][0]["strategy_type"] == "short_iron_condor"
    schema_text = str(get_option_strategy_selection.args_schema.model_fields)
    assert "directional_bias" in schema_text
    assert "volatility_view" in schema_text
