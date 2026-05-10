"""Phase 14B tests for expanded credit defined-risk option strategies."""

from __future__ import annotations

import json
import sqlite3

import pytest


def _install_iron_condor_wings(db_path):
    """Add wider wings and coherent mid prices for a short iron condor fixture."""
    con = sqlite3.connect(db_path)
    try:
        con.executescript(
            """
            insert into vw_shfe_option_chain_latest values
                ('20260501','CU2606C84000.SHF','铜看涨84000','CU','C',84000,'20260625','OPCU2606.SHF','OPCU2606.SHF','CU2606',500,480,520,600,280,300,295,1600,2600,4200),
                ('20260501','CU2606P76000.SHF','铜看跌76000','CU','P',76000,'20260625','OPCU2606.SHF','OPCU2606.SHF','CU2606',500,480,520,600,280,300,295,1600,2600,4200);
            update vw_shfe_option_chain_latest set close=900, settle=890 where ts_code='CU2606P78000.SHF';
            update vw_shfe_option_chain_latest set close=900, settle=890 where ts_code='CU2606C82000.SHF';
            """
        )
        con.commit()
    finally:
        con.close()


def test_short_iron_condor_uses_four_otm_legs_and_credit_payoff(shfe_options_db):
    _install_iron_condor_wings(shfe_options_db)

    from tradingagents.options.strategies import build_option_strategy_candidate

    candidate = build_option_strategy_candidate(
        "CU",
        strategy_type="short_iron_condor",
        trade_date="2026-05-01",
        expiry="20260625",
        risk_budget_cash=5_000,
    )

    assert candidate["strategy_type"] == "short_iron_condor"
    assert [leg["side"] for leg in candidate["legs"]] == ["BUY", "SELL", "SELL", "BUY"]
    assert [leg["quantity"] for leg in candidate["legs"]] == [1, 1, 1, 1]
    assert [(leg["call_put"], leg["strike"]) for leg in candidate["legs"]] == [
        ("P", 76000),
        ("P", 78000),
        ("C", 82000),
        ("C", 84000),
    ]
    assert candidate["net_premium"] == pytest.approx(-1200)
    assert candidate["premium_type"] == "credit"
    assert candidate["max_profit"] == pytest.approx(1200)
    assert candidate["max_loss"] == pytest.approx(800)
    assert candidate["breakevens"] == [pytest.approx(76800), pytest.approx(83200)]
    assert candidate["cash_risk"]["net_premium_cash"] == pytest.approx(-6000)
    assert candidate["cash_risk"]["max_profit_cash"] == pytest.approx(6000)
    assert candidate["cash_risk"]["max_loss_cash"] == pytest.approx(4000)
    assert candidate["margin"]["margin_required_cash"] == pytest.approx(4000)
    assert candidate["risk_budget"]["passes"] is True
    assert candidate["assumptions"]["margin_model"] == "simplified_defined_risk"


def test_short_iron_condor_scenarios_report_and_tool_payload_are_supported(shfe_options_db):
    _install_iron_condor_wings(shfe_options_db)

    from tradingagents.agents.utils.options_tools import get_option_strategy_candidate
    from tradingagents.options.reports import build_option_strategy_report
    from tradingagents.options.scenarios import build_option_strategy_scenarios

    raw = get_option_strategy_candidate.invoke({
        "symbol": "CU",
        "strategy_type": "short_iron_condor",
        "trade_date": "2026-05-01",
        "expiry": "20260625",
        "risk_budget_cash": 5_000,
    })
    payload = json.loads(raw)
    assert payload["strategy_type"] == "short_iron_condor"
    assert payload["premium_type"] == "credit"
    assert len(payload["legs"]) == 4

    matrix = build_option_strategy_scenarios(
        "CU",
        strategy_type="short_iron_condor",
        trade_date="2026-05-01",
        expiry="20260625",
        price_shocks=(-0.03, 0.0, 0.03),
        iv_shocks=(0.0,),
        days_forward=(0,),
        risk_budget_cash=5_000,
    )
    assert matrix["strategy"]["strategy_type"] == "short_iron_condor"
    assert matrix["margin"]["margin_required_cash"] == pytest.approx(4000)
    assert len(matrix["scenarios"]) == 3
    assert all(len(row["leg_values"]) == 4 for row in matrix["scenarios"])

    report = build_option_strategy_report(
        "CU",
        strategy_type="short_iron_condor",
        trade_date="2026-05-01",
        expiry="20260625",
        risk_budget_cash=5_000,
    )
    assert report["strategy_type"] == "short_iron_condor"
    assert "short_iron_condor" in report["markdown"]
    assert "权利金类型 `credit`" in report["markdown"]


def test_options_tools_describe_short_iron_condor_strategy_type():
    from tradingagents.agents.utils.options_tools import get_option_strategy_candidate, get_option_strategy_scenarios

    candidate_schema = str(get_option_strategy_candidate.args_schema.model_fields["strategy_type"].description)
    scenario_schema = str(get_option_strategy_scenarios.args_schema.model_fields["strategy_type"].description)
    for description in [candidate_schema, scenario_schema]:
        assert "short_iron_condor" in description
