"""Phase 20C tests for bid/ask validity and credit wording."""

from __future__ import annotations

import sqlite3

import pytest

from tests.test_options_phase5_strategy_structurer import shfe_options_db  # noqa: F401
from tests.test_options_phase14b_credit_strategies import _install_iron_condor_wings


def _install_crossed_iron_condor_bid_ask_snapshot(db_path):
    """Install bid/ask rows where one selected leg has an invalid crossed market."""
    with sqlite3.connect(db_path) as con:
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
                -- crossed market: bid > ask; must not be treated as executable
                ('20260501','CU','cu2606','2606',82000,'C','cu2606C82000',900,970,830,1800,5000,0,'akshare_sina_option','2026-05-01 15:01:00'),
                ('20260501','CU','cu2606','2606',84000,'C','cu2606C84000',300,240,360,1600,4200,0,'akshare_sina_option','2026-05-01 15:01:00');
            """
        )
        con.commit()


def test_crossed_bid_ask_is_not_used_as_executable_credit(shfe_options_db):
    _install_iron_condor_wings(shfe_options_db)
    _install_crossed_iron_condor_bid_ask_snapshot(shfe_options_db)

    from tradingagents.options.strategies import build_option_strategy_candidate

    candidate = build_option_strategy_candidate(
        "CU",
        strategy_type="short_iron_condor",
        trade_date="2026-05-01",
        expiry="20260625",
        risk_budget_cash=6_000,
        min_credit_pct_of_wing_width=0.20,
        max_bid_ask_spread_pct=0.20,
    )

    crossed_leg = next(leg for leg in candidate["legs"] if leg["ts_code"] == "CU2606C82000.SHF")
    assert crossed_leg["raw_bid"] == pytest.approx(970)
    assert crossed_leg["raw_ask"] == pytest.approx(830)
    assert crossed_leg["bid"] is None
    assert crossed_leg["ask"] is None
    assert crossed_leg["bid_ask_status"] == "invalid_crossed"
    assert crossed_leg["execution_price_basis"] == "analysis_price_proxy"

    execution = candidate["execution"]
    assert execution["bid_ask_complete"] is False
    assert execution["bid_ask_valid"] is False
    assert execution["invalid_bid_ask_count"] == 1

    credit_execution = candidate["credit_execution"]
    assert credit_execution["credit_quote_status"] == "indicative"
    assert credit_execution["is_executable"] is False
    assert credit_execution["basis"] == "indicative_analysis_price_proxy"
    assert credit_execution["executable_credit_points"] is None
    assert credit_execution["indicative_credit_points"] == pytest.approx(1200)
    assert credit_execution["max_loss_at_execution_cash"] is None
    assert any("bid/ask incomplete or invalid for executable credit" in reason for reason in credit_execution["no_trade_reasons"])
    assert candidate["margin"]["margin_required_cash"] == pytest.approx(candidate["cash_risk"]["max_loss_cash"])
    assert candidate["risk_budget"]["passes"] is False


def test_report_marks_non_executable_credit_as_indicative(shfe_options_db):
    _install_iron_condor_wings(shfe_options_db)
    _install_crossed_iron_condor_bid_ask_snapshot(shfe_options_db)

    from tradingagents.options.reports import build_option_strategy_report

    report = build_option_strategy_report(
        "CU",
        strategy_type="short_iron_condor",
        trade_date="2026-05-01",
        expiry="20260625",
        risk_budget_cash=6_000,
    )

    assert report["summary"]["credit_quote_status"] == "indicative"
    assert report["summary"]["executable_credit_cash"] is None
    assert "Indicative credit" in report["markdown"]
    assert "Executable credit: N/A" not in report["markdown"]
