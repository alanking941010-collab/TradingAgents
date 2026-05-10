"""Phase 18A tests for portfolio-level option strategy comparison and risk summary."""

from __future__ import annotations

import json

from tests.test_options_phase14b_credit_strategies import _install_iron_condor_wings
from tests.test_options_phase15_credit_execution import _install_iron_condor_bid_ask_snapshot


def _install_phase18a_fixture(db_path):
    _install_iron_condor_wings(db_path)
    _install_iron_condor_bid_ask_snapshot(db_path)


def test_strategy_selection_includes_portfolio_risk_summary(shfe_options_db):
    _install_phase18a_fixture(shfe_options_db)

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

    portfolio = selection["portfolio_summary"]

    assert portfolio["summary_type"] == "option_strategy_portfolio_risk_summary"
    assert portfolio["risk_budget_cash"] == 6_000
    assert portfolio["candidate_count"] == len(selection["ranked_candidates"])
    assert portfolio["tradable_candidate_count"] >= 1
    assert portfolio["no_trade_count"] >= 0
    assert portfolio["selected_strategy"]["strategy_type"] == selection["selected_strategy"]
    assert portfolio["selected_strategy"]["risk_budget_utilization"] is not None
    assert portfolio["selected_strategy"]["risk_budget_utilization"] <= 1.0
    assert portfolio["all_candidate_margin_cash"] >= portfolio["selected_strategy"]["margin_required_cash"]
    assert portfolio["all_candidate_max_loss_cash"] >= portfolio["selected_strategy"]["max_loss_cash"]
    assert portfolio["highest_margin_strategy"]["strategy_type"]
    assert portfolio["lowest_max_loss_strategy"]["strategy_type"]
    assert portfolio["comparison_table"][0]["rank"] == 1
    assert {"rank", "strategy_type", "decision", "score", "margin_required_cash", "max_loss_cash", "risk_budget_utilization"}.issubset(
        portfolio["comparison_table"][0]
    )
    assert "组合风险摘要" in selection["markdown"]
    assert "候选总保证金" in selection["markdown"]


def test_strategy_selection_tool_exposes_portfolio_summary(shfe_options_db):
    _install_phase18a_fixture(shfe_options_db)

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

    assert payload["portfolio_summary"]["summary_type"] == "option_strategy_portfolio_risk_summary"
    assert payload["portfolio_summary"]["selected_strategy"]["strategy_type"] == payload["selected_strategy"]
    assert "comparison_table" in payload["portfolio_summary"]
