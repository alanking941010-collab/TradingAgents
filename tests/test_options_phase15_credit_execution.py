"""Phase 15 tests for credit strategy execution realism and quality filters."""

from __future__ import annotations

import json
import sqlite3

import pytest

from tests.test_options_phase14b_credit_strategies import _install_iron_condor_wings


def _install_iron_condor_bid_ask_snapshot(db_path):
    """Install executable bid/ask quotes for the Phase 14B short iron condor fixture."""
    con = sqlite3.connect(db_path)
    try:
        con.executescript(
            """
            create table akshare_option_snapshot (
                trade_date text, metal text, contract_code text, contract_month text,
                strike real, call_put text, contract_name text, close real, bid real,
                ask real, volume real, open_interest real, change real, source text,
                updated_at text
            );
            insert into akshare_option_snapshot values
                ('20260501','CU','cu2606','2606',76000,'P','cu2606P76000',300,260,340,1600,4200,0,'akshare_sina_option','2026-05-01 15:01:00'),
                ('20260501','CU','cu2606','2606',78000,'P','cu2606P78000',900,840,960,1600,7000,0,'akshare_sina_option','2026-05-01 15:01:00'),
                ('20260501','CU','cu2606','2606',82000,'C','cu2606C82000',900,830,970,1800,5000,0,'akshare_sina_option','2026-05-01 15:01:00'),
                ('20260501','CU','cu2606','2606',84000,'C','cu2606C84000',300,240,360,1600,4200,0,'akshare_sina_option','2026-05-01 15:01:00');
            """
        )
        con.commit()
    finally:
        con.close()


def test_short_iron_condor_uses_bid_ask_executable_credit_for_margin(shfe_options_db):
    _install_iron_condor_wings(shfe_options_db)
    _install_iron_condor_bid_ask_snapshot(shfe_options_db)

    from tradingagents.options.strategies import build_option_strategy_candidate

    candidate = build_option_strategy_candidate(
        "CU",
        strategy_type="short_iron_condor",
        trade_date="2026-05-01",
        expiry="20260625",
        risk_budget_cash=6_000,
    )

    assert candidate["net_premium"] == pytest.approx(-1200)
    assert candidate["execution"]["net_execution_premium"] == pytest.approx(-970)

    credit_execution = candidate["credit_execution"]
    assert credit_execution["basis"] == "sell_bid_buy_ask"
    assert credit_execution["mid_credit_points"] == pytest.approx(1200)
    assert credit_execution["executable_credit_points"] == pytest.approx(970)
    assert credit_execution["credit_slippage_points"] == pytest.approx(230)
    assert credit_execution["wing_width_points"] == pytest.approx(2000)
    assert credit_execution["max_loss_at_execution_points"] == pytest.approx(1030)
    assert credit_execution["executable_credit_cash"] == pytest.approx(4_850)
    assert credit_execution["max_loss_at_execution_cash"] == pytest.approx(5_150)
    assert credit_execution["executable_credit_pct_of_wing_width"] == pytest.approx(970 / 2000)
    assert credit_execution["executable_credit_to_max_loss_at_execution"] == pytest.approx(970 / 1030)

    assert candidate["cash_risk"]["max_loss_cash"] == pytest.approx(4_000)
    assert candidate["margin"]["margin_required_cash"] == pytest.approx(5_150)
    assert candidate["margin"]["max_loss_at_mid_cash"] == pytest.approx(4_000)
    assert candidate["margin"]["max_loss_at_execution_cash"] == pytest.approx(5_150)
    assert candidate["risk_budget"]["passes"] is True
    assert candidate["risk_budget"]["no_trade_reasons"] == []


def test_credit_quality_thresholds_add_actionable_no_trade_reasons(shfe_options_db):
    _install_iron_condor_wings(shfe_options_db)
    _install_iron_condor_bid_ask_snapshot(shfe_options_db)

    from tradingagents.options.strategies import build_option_strategy_candidate

    candidate = build_option_strategy_candidate(
        "CU",
        strategy_type="short_iron_condor",
        trade_date="2026-05-01",
        expiry="20260625",
        risk_budget_cash=6_000,
        min_credit_pct_of_wing_width=0.50,
        max_bid_ask_spread_pct=0.20,
    )

    assert candidate["credit_execution"]["passes_credit_quality"] is False
    assert candidate["risk_budget"]["passes"] is False
    assert candidate["risk_budget"]["status"] == "fail"
    reasons = candidate["risk_budget"]["no_trade_reasons"]
    assert any("executable_credit_pct_of_wing_width below min_credit_pct_of_wing_width" in reason for reason in reasons)
    assert any("max_bid_ask_spread_pct exceeds threshold" in reason for reason in reasons)


def test_credit_execution_metrics_are_visible_in_report_and_tool_schema(shfe_options_db):
    _install_iron_condor_wings(shfe_options_db)
    _install_iron_condor_bid_ask_snapshot(shfe_options_db)

    from tradingagents.agents.utils.options_tools import get_option_strategy_candidate
    from tradingagents.options.reports import build_option_strategy_report

    report = build_option_strategy_report(
        "CU",
        strategy_type="short_iron_condor",
        trade_date="2026-05-01",
        expiry="20260625",
        risk_budget_cash=6_000,
    )
    assert report["summary"]["executable_credit_cash"] == pytest.approx(4_850)
    assert report["summary"]["max_loss_at_execution_cash"] == pytest.approx(5_150)
    assert "Executable credit" in report["markdown"]
    assert "Credit / wing width" in report["markdown"]

    schema_text = str(get_option_strategy_candidate.args_schema.model_fields)
    assert "min_credit_pct_of_wing_width" in schema_text
    assert "max_bid_ask_spread_pct" in schema_text

    raw = get_option_strategy_candidate.invoke({
        "symbol": "CU",
        "strategy_type": "short_iron_condor",
        "trade_date": "2026-05-01",
        "expiry": "20260625",
        "risk_budget_cash": 6_000,
        "min_credit_pct_of_wing_width": 0.50,
        "max_bid_ask_spread_pct": 0.20,
    })
    payload = json.loads(raw)
    assert payload["credit_execution"]["passes_credit_quality"] is False
