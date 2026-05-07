"""Phase 6 tests for option scenario PnL / payoff engine."""

from __future__ import annotations

import json

import pytest

from tests.test_options_phase5_strategy_structurer import shfe_options_db  # noqa: F401


def test_strategy_scenario_matrix_contains_price_iv_and_time_dimensions(shfe_options_db):
    from tradingagents.options.scenarios import build_option_strategy_scenarios

    matrix = build_option_strategy_scenarios(
        "CU",
        strategy_type="bull_call_spread",
        trade_date="2026-05-01",
        expiry="20260625",
        price_shocks=(-0.03, 0.0, 0.03),
        iv_shocks=(-0.02, 0.0, 0.02),
        days_forward=(0, 5, 20),
    )

    assert matrix["strategy"]["strategy_type"] == "bull_call_spread"
    assert matrix["scenario_grid"] == {
        "price_shocks": [-0.03, 0.0, 0.03],
        "iv_shocks": [-0.02, 0.0, 0.02],
        "days_forward": [0, 5, 20],
    }
    assert len(matrix["scenarios"]) == 27
    first = matrix["scenarios"][0]
    for key in [
        "scenario_id",
        "price_shock",
        "iv_shock",
        "days_forward",
        "underlying_price",
        "time_to_expiry",
        "scenario_value",
        "pnl",
        "pnl_pct_of_max_loss",
        "leg_values",
    ]:
        assert key in first
    assert len(first["leg_values"]) == 2
    assert matrix["summary"]["best_pnl"] >= matrix["summary"]["worst_pnl"]
    assert "breakeven_proximity" in matrix["summary"]
    assert matrix["assumptions"]["contract_multiplier_applied"] is False
    assert matrix["assumptions"]["iv_shock_unit"] == "absolute_vol_points"


def test_bull_call_spread_pnl_improves_when_underlying_rises(shfe_options_db):
    from tradingagents.options.scenarios import build_option_strategy_scenarios

    matrix = build_option_strategy_scenarios(
        "CU",
        strategy_type="bull_call_spread",
        trade_date="2026-05-01",
        expiry="20260625",
        price_shocks=(-0.03, 0.03),
        iv_shocks=(0.0,),
        days_forward=(0,),
    )
    by_shock = {row["price_shock"]: row for row in matrix["scenarios"]}

    assert by_shock[0.03]["pnl"] > by_shock[-0.03]["pnl"]


def test_long_straddle_benefits_from_large_price_move_or_iv_lift(shfe_options_db):
    from tradingagents.options.scenarios import build_option_strategy_scenarios

    matrix = build_option_strategy_scenarios(
        "CU",
        strategy_type="long_straddle",
        trade_date="2026-05-01",
        expiry="20260625",
        price_shocks=(0.0, 0.05),
        iv_shocks=(0.0, 0.05),
        days_forward=(0,),
    )
    lookup = {(row["price_shock"], row["iv_shock"]): row for row in matrix["scenarios"]}

    assert lookup[(0.05, 0.0)]["pnl"] > lookup[(0.0, 0.0)]["pnl"]
    assert lookup[(0.0, 0.05)]["pnl"] > lookup[(0.0, 0.0)]["pnl"]


def test_option_scenario_tool_returns_parseable_json(shfe_options_db):
    from tradingagents.agents.utils.options_tools import get_option_strategy_scenarios

    raw = get_option_strategy_scenarios.invoke(
        {
            "symbol": "CU",
            "strategy_type": "bull_call_spread",
            "trade_date": "2026-05-01",
            "expiry": "20260625",
            "price_shocks": [-0.01, 0.0, 0.01],
            "iv_shocks": [-0.02, 0.0, 0.02],
            "days_forward": [0, 5],
        }
    )
    payload = json.loads(raw)

    assert payload["strategy"]["strategy_type"] == "bull_call_spread"
    assert len(payload["scenarios"]) == 18
    assert "summary" in payload
    assert "worst_scenario" in payload["summary"]
    assert "best_scenario" in payload["summary"]
