"""Phase 11 tests for expanded complex option strategy library."""

from __future__ import annotations

import json
import sqlite3

import pytest

from tests.test_options_phase5_strategy_structurer import shfe_options_db  # noqa: F401


def _set_symmetric_butterfly_prices(db_path):
    """Make fixture prices coherent for debit butterflies around ATM."""
    con = sqlite3.connect(db_path)
    try:
        con.executescript(
            """
            update vw_shfe_option_chain_latest set close=3200, settle=3180 where ts_code='CU2606C78000.SHF';
            update vw_shfe_option_chain_latest set close=1800, settle=1780 where ts_code='CU2606C80000.SHF';
            update vw_shfe_option_chain_latest set close=900, settle=880 where ts_code='CU2606C82000.SHF';
            update vw_shfe_option_chain_latest set close=800, settle=780 where ts_code='CU2606P78000.SHF';
            update vw_shfe_option_chain_latest set close=1500, settle=1480 where ts_code='CU2606P80000.SHF';
            update vw_shfe_option_chain_latest set close=2700, settle=2680 where ts_code='CU2606P82000.SHF';
            """
        )
        con.commit()
    finally:
        con.close()


def test_long_call_butterfly_uses_three_call_legs_with_two_short_atm(shfe_options_db):
    _set_symmetric_butterfly_prices(shfe_options_db)

    from tradingagents.options.strategies import build_option_strategy_candidate

    candidate = build_option_strategy_candidate(
        "CU",
        strategy_type="long_call_butterfly",
        trade_date="2026-05-01",
        expiry="20260625",
        risk_budget_cash=10_000,
    )

    assert candidate["strategy_type"] == "long_call_butterfly"
    assert [leg["side"] for leg in candidate["legs"]] == ["BUY", "SELL", "BUY"]
    assert [leg["quantity"] for leg in candidate["legs"]] == [1, 2, 1]
    assert [leg["call_put"] for leg in candidate["legs"]] == ["C", "C", "C"]
    assert [leg["strike"] for leg in candidate["legs"]] == [78000, 80000, 82000]
    assert candidate["net_premium"] == pytest.approx(500)
    assert candidate["premium_type"] == "debit"
    assert candidate["max_loss"] == pytest.approx(500)
    assert candidate["max_profit"] == pytest.approx(1500)
    assert candidate["breakevens"] == [pytest.approx(78500), pytest.approx(81500)]
    assert candidate["margin"]["margin_required_cash"] == pytest.approx(2500)
    assert candidate["risk_budget"]["passes"] is True


def test_long_put_butterfly_uses_three_put_legs_with_two_short_atm(shfe_options_db):
    _set_symmetric_butterfly_prices(shfe_options_db)

    from tradingagents.options.strategies import build_option_strategy_candidate

    candidate = build_option_strategy_candidate(
        "CU",
        strategy_type="long_put_butterfly",
        trade_date="2026-05-01",
        expiry="20260625",
    )

    assert candidate["strategy_type"] == "long_put_butterfly"
    assert [leg["side"] for leg in candidate["legs"]] == ["BUY", "SELL", "BUY"]
    assert [leg["quantity"] for leg in candidate["legs"]] == [1, 2, 1]
    assert [leg["call_put"] for leg in candidate["legs"]] == ["P", "P", "P"]
    assert [leg["strike"] for leg in candidate["legs"]] == [78000, 80000, 82000]
    assert candidate["net_premium"] == pytest.approx(500)
    assert candidate["max_loss"] == pytest.approx(500)
    assert candidate["max_profit"] == pytest.approx(1500)
    assert candidate["breakevens"] == [pytest.approx(78500), pytest.approx(81500)]


def test_complex_strategy_scenarios_and_tool_payload_are_supported(shfe_options_db):
    _set_symmetric_butterfly_prices(shfe_options_db)

    from tradingagents.agents.utils.options_tools import get_option_strategy_candidate
    from tradingagents.options.scenarios import build_option_strategy_scenarios

    raw = get_option_strategy_candidate.invoke({
        "symbol": "CU",
        "strategy_type": "long_call_butterfly",
        "trade_date": "2026-05-01",
        "expiry": "20260625",
    })
    payload = json.loads(raw)
    assert payload["strategy_type"] == "long_call_butterfly"
    assert len(payload["legs"]) == 3
    assert payload["margin"]["defined_risk"] is True

    matrix = build_option_strategy_scenarios(
        "CU",
        strategy_type="long_put_butterfly",
        trade_date="2026-05-01",
        expiry="20260625",
        price_shocks=(-0.03, 0.0, 0.03),
        iv_shocks=(0.0,),
        days_forward=(0,),
        risk_budget_cash=10_000,
    )
    assert matrix["strategy"]["strategy_type"] == "long_put_butterfly"
    assert matrix["margin"]["margin_required_cash"] == pytest.approx(2500)
    assert len(matrix["scenarios"]) == 3
    assert all(len(row["leg_values"]) == 3 for row in matrix["scenarios"])


def test_options_tools_describe_butterfly_strategy_types():
    from tradingagents.agents.utils.options_tools import get_option_strategy_candidate, get_option_strategy_scenarios

    candidate_schema = str(get_option_strategy_candidate.args_schema.model_fields["strategy_type"].description)
    scenario_schema = str(get_option_strategy_scenarios.args_schema.model_fields["strategy_type"].description)
    for description in [candidate_schema, scenario_schema]:
        assert "long_call_butterfly" in description
        assert "long_put_butterfly" in description
