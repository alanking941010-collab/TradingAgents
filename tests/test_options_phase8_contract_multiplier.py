"""Phase 8 tests for contract multipliers and cash risk/PnL fields."""

from __future__ import annotations

import pytest


def test_strategy_candidate_applies_contract_multiplier_to_cash_risk_fields(shfe_options_db):
    from tradingagents.options.strategies import build_option_strategy_candidate

    candidate = build_option_strategy_candidate(
        "CU",
        strategy_type="bull_call_spread",
        trade_date="2026-05-01",
        expiry="20260625",
        risk_budget_cash=50_000,
    )

    assert candidate["contract_multiplier"] == 5
    assert candidate["cash_risk"]["contract_multiplier"] == 5
    assert candidate["cash_risk"]["multiplier_unit"] == "CNY per option-price point"
    assert candidate["cash_risk"]["net_premium_cash"] == pytest.approx(candidate["net_premium"] * 5)
    assert candidate["cash_risk"]["max_loss_cash"] == pytest.approx(candidate["max_loss"] * 5)
    assert candidate["cash_risk"]["max_profit_cash"] == pytest.approx(candidate["max_profit"] * 5)
    assert candidate["cash_risk"]["underlying_notional_per_lot"] == pytest.approx(candidate["underlying_price"] * 5)
    assert candidate["cash_risk"]["max_loss_pct_of_risk_budget"] == pytest.approx(candidate["cash_risk"]["max_loss_cash"] / 50_000)
    assert candidate["assumptions"]["contract_multiplier_applied"] is True


def test_strategy_legs_include_cash_premium_fields(shfe_options_db):
    from tradingagents.options.strategies import build_option_strategy_candidate

    candidate = build_option_strategy_candidate(
        "CU",
        strategy_type="bull_call_spread",
        trade_date="2026-05-01",
        expiry="20260625",
    )

    buy_leg, sell_leg = candidate["legs"]
    assert buy_leg["contract_multiplier"] == 5
    assert buy_leg["premium_cash"] == pytest.approx(buy_leg["price"] * 5)
    assert buy_leg["signed_premium_cash"] == pytest.approx(buy_leg["price"] * 5)
    assert sell_leg["signed_premium_cash"] == pytest.approx(-sell_leg["price"] * 5)


def test_scenario_matrix_includes_cash_pnl_and_risk_budget_metrics(shfe_options_db):
    from tradingagents.options.scenarios import build_option_strategy_scenarios

    matrix = build_option_strategy_scenarios(
        "CU",
        strategy_type="bull_call_spread",
        trade_date="2026-05-01",
        expiry="20260625",
        price_shocks=(-0.03, 0.03),
        iv_shocks=(0.0,),
        days_forward=(0,),
        risk_budget_cash=20_000,
    )

    assert matrix["assumptions"]["contract_multiplier_applied"] is True
    assert matrix["assumptions"]["pnl_unit"] == "option_price_points_and_cash"
    assert matrix["cash_risk"]["contract_multiplier"] == 5
    assert matrix["summary"]["worst_pnl_cash"] == pytest.approx(matrix["summary"]["worst_pnl"] * 5)
    assert matrix["summary"]["best_pnl_cash"] == pytest.approx(matrix["summary"]["best_pnl"] * 5)

    first = matrix["scenarios"][0]
    assert first["scenario_value_cash"] == pytest.approx(first["scenario_value"] * 5)
    assert first["pnl_cash"] == pytest.approx(first["pnl"] * 5)
    assert first["pnl_pct_of_risk_budget"] == pytest.approx(first["pnl_cash"] / 20_000)
    assert first["leg_values"][0]["scenario_option_value_cash"] == pytest.approx(first["leg_values"][0]["scenario_option_value"] * 5)
    assert "pnl_cash" in first["leg_values"][0]


def test_options_prompts_reference_cash_risk_after_multiplier_enrichment():
    from tradingagents.agents.utils.options_integration import (
        options_portfolio_instruction,
        options_risk_debator_instruction,
        options_trader_instruction,
    )

    trader_prompt = options_trader_instruction("CU").lower()
    risk_prompt = options_risk_debator_instruction("CU", "neutral").lower()
    portfolio_prompt = options_portfolio_instruction("CU").lower()

    for prompt in [trader_prompt, risk_prompt, portfolio_prompt]:
        assert "contract multiplier" in prompt
        assert "cash" in prompt
        assert "risk budget" in prompt


def test_contract_multiplier_defaults_cover_core_shfe_metals():
    from tradingagents.options.contract_specs import contract_multiplier_for_product

    assert contract_multiplier_for_product("CU") == 5
    assert contract_multiplier_for_product("AL") == 5
    assert contract_multiplier_for_product("ZN") == 5
    assert contract_multiplier_for_product("PB") == 5
    assert contract_multiplier_for_product("NI") == 1
    assert contract_multiplier_for_product("SN") == 1
    assert contract_multiplier_for_product("AU") == 1000
    assert contract_multiplier_for_product("AG") == 15
    assert contract_multiplier_for_product("AO") == 20
    assert contract_multiplier_for_product("铜") == 5
