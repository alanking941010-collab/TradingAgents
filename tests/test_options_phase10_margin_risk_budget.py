"""Phase 10 tests for simplified margin and risk-budget checks."""

from __future__ import annotations

import pytest

from tests.test_options_phase5_strategy_structurer import shfe_options_db  # noqa: F401
from tests.test_options_phase9_execution_liquidity import _install_akshare_bid_ask_snapshot


def test_strategy_candidate_adds_execution_adjusted_defined_risk_margin(shfe_options_db):
    _install_akshare_bid_ask_snapshot(shfe_options_db)

    from tradingagents.options.strategies import build_option_strategy_candidate

    candidate = build_option_strategy_candidate(
        "CU",
        strategy_type="bull_call_spread",
        trade_date="2026-05-01",
        expiry="20260625",
        risk_budget_cash=6_000,
    )

    margin = candidate["margin"]
    assert margin["method"] == "defined_risk_execution_adjusted_max_loss"
    assert margin["defined_risk"] is True
    assert margin["margin_required_cash"] == pytest.approx(candidate["execution"]["net_execution_premium"] * 5)
    assert margin["margin_required_cash"] == pytest.approx(5_175)
    assert margin["margin_required_pct_of_notional"] == pytest.approx(5_175 / (80_500 * 5))
    assert margin["notes"]

    risk_budget = candidate["risk_budget"]
    assert risk_budget["risk_budget_cash"] == 6_000
    assert risk_budget["passes"] is True
    assert risk_budget["status"] == "pass"
    assert risk_budget["margin_pct_of_risk_budget"] == pytest.approx(5_175 / 6_000)
    assert risk_budget["max_loss_pct_of_risk_budget"] == pytest.approx(candidate["cash_risk"]["max_loss_cash"] / 6_000)
    assert risk_budget["no_trade_reasons"] == []


def test_strategy_candidate_flags_trade_when_execution_adjusted_margin_exceeds_budget(shfe_options_db):
    _install_akshare_bid_ask_snapshot(shfe_options_db)

    from tradingagents.options.strategies import build_option_strategy_candidate

    candidate = build_option_strategy_candidate(
        "CU",
        strategy_type="bull_call_spread",
        trade_date="2026-05-01",
        expiry="20260625",
        risk_budget_cash=5_000,
    )

    risk_budget = candidate["risk_budget"]
    assert risk_budget["passes"] is False
    assert risk_budget["status"] == "fail"
    assert risk_budget["margin_pct_of_risk_budget"] > 1
    assert any("margin_required_cash exceeds risk_budget_cash" in reason for reason in risk_budget["no_trade_reasons"])


def test_strategy_candidate_reports_budget_not_provided_without_failing_trade(shfe_options_db):
    from tradingagents.options.strategies import build_option_strategy_candidate

    candidate = build_option_strategy_candidate(
        "CU",
        strategy_type="long_straddle",
        trade_date="2026-05-01",
        expiry="20260625",
    )

    assert candidate["margin"]["margin_required_cash"] == pytest.approx(candidate["cash_risk"]["max_loss_cash"])
    assert candidate["risk_budget"]["risk_budget_cash"] is None
    assert candidate["risk_budget"]["passes"] is None
    assert candidate["risk_budget"]["status"] == "not_provided"


def test_scenario_matrix_carries_margin_and_risk_budget_summary(shfe_options_db):
    _install_akshare_bid_ask_snapshot(shfe_options_db)

    from tradingagents.options.scenarios import build_option_strategy_scenarios

    matrix = build_option_strategy_scenarios(
        "CU",
        strategy_type="bull_call_spread",
        trade_date="2026-05-01",
        expiry="20260625",
        price_shocks=(-0.03, 0.03),
        iv_shocks=(0.0,),
        days_forward=(0,),
        risk_budget_cash=6_000,
    )

    assert matrix["margin"]["margin_required_cash"] == pytest.approx(5_175)
    assert matrix["risk_budget"]["passes"] is True
    assert matrix["summary"]["worst_pnl_pct_of_margin"] == pytest.approx(matrix["summary"]["worst_pnl_cash"] / 5_175)
    assert matrix["assumptions"]["margin_model"] == "simplified_defined_risk"


def test_options_prompts_reference_margin_required_and_risk_budget_pass_fail():
    from tradingagents.agents.utils.options_integration import (
        options_portfolio_instruction,
        options_risk_debator_instruction,
        options_trader_instruction,
    )

    prompts = [
        options_trader_instruction("CU").lower(),
        options_risk_debator_instruction("CU", "neutral").lower(),
        options_portfolio_instruction("CU").lower(),
    ]
    for prompt in prompts:
        assert "margin required" in prompt
        assert "risk budget pass/fail" in prompt
        assert "no-trade" in prompt
