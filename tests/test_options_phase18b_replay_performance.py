"""Phase 18B tests for multi-date replay performance and IV-regime grouping."""

from __future__ import annotations

import json
import sqlite3

import pytest

from tests.test_options_phase12_replay import _insert_review_day


def _insert_second_review_day(db_path):
    con = sqlite3.connect(db_path)
    try:
        con.executescript(
            """
            insert into futures_daily values
                ('20260511','CU2606.SHF',78500,78400,79200,80000,78000,79000,78800,1800,1700,130000,590000,230000),
                ('20260511','CU.SHF',78500,78400,79200,80000,78000,79000,78800,1800,1700,130000,590000,230000);

            insert into vw_shfe_option_chain_latest values
                ('20260511','CU2606C78000.SHF','铜看涨78000','CU','C',78000,'20260625','OPCU2606.SHF','OPCU2606.SHF','CU2606',2500,2500,2600,3300,2500,3100,3050,750,2300,1300),
                ('20260511','CU2606C80000.SHF','铜看涨80000','CU','C',80000,'20260625','OPCU2606.SHF','OPCU2606.SHF','CU2606',1800,1800,1700,2300,1600,2100,2050,950,3000,3300),
                ('20260511','CU2606C82000.SHF','铜看涨82000','CU','C',82000,'20260625','OPCU2606.SHF','OPCU2606.SHF','CU2606',1100,1100,900,1300,850,1150,1120,1250,3400,5300),
                ('20260511','CU2606P78000.SHF','铜看跌78000','CU','P',78000,'20260625','OPCU2606.SHF','OPCU2606.SHF','CU2606',1250,1250,1450,1800,1400,1650,1620,1350,2300,7000),
                ('20260511','CU2606P80000.SHF','铜看跌80000','CU','P',80000,'20260625','OPCU2606.SHF','OPCU2606.SHF','CU2606',1800,1800,2100,2600,2000,2400,2350,1200,2200,2500),
                ('20260511','CU2606P82000.SHF','铜看跌82000','CU','P',82000,'20260625','OPCU2606.SHF','OPCU2606.SHF','CU2606',2500,2500,3000,3600,2900,3400,3350,1000,2100,1500);
            """
        )
        con.commit()
    finally:
        con.close()


def test_replay_performance_summary_tracks_path_distribution_and_drawdown(shfe_options_db):
    _insert_review_day(shfe_options_db)
    _insert_second_review_day(shfe_options_db)

    from tradingagents.options.replay import build_option_strategy_replay

    replay = build_option_strategy_replay(
        "CU",
        strategy_type="bull_call_spread",
        entry_date="2026-05-01",
        review_dates=["2026-05-01", "2026-05-06", "2026-05-11"],
        expiry="20260625",
        risk_budget_cash=10_000,
    )

    performance = replay["performance_summary"]

    assert performance["summary_type"] == "option_replay_performance_distribution"
    assert performance["review_count"] == 3
    assert performance["winning_mark_count"] == 1
    assert performance["losing_mark_count"] == 1
    assert performance["flat_mark_count"] == 1
    assert performance["win_rate"] == pytest.approx(1 / 3)
    assert performance["average_pnl_cash"] == pytest.approx((0 + 1500 - 250) / 3)
    assert performance["final_pnl_cash"] == pytest.approx(-250)
    assert performance["max_drawdown_cash"] == pytest.approx(1750)
    assert performance["pnl_path"][0]["trade_date"] == "2026-05-01"
    assert performance["pnl_path"][-1]["pnl_cash"] == pytest.approx(-250)
    assert all("iv_regime" in row for row in performance["pnl_path"])
    assert performance["iv_regime_breakdown"]
    assert sum(bucket["count"] for bucket in performance["iv_regime_breakdown"].values()) == 3


def test_strategy_report_includes_replay_performance_summary(shfe_options_db):
    _insert_review_day(shfe_options_db)
    _insert_second_review_day(shfe_options_db)

    from tradingagents.options.reports import build_option_strategy_report

    report = build_option_strategy_report(
        "CU",
        strategy_type="bull_call_spread",
        trade_date="2026-05-01",
        expiry="20260625",
        review_dates=["2026-05-01", "2026-05-06", "2026-05-11"],
        risk_budget_cash=10_000,
    )

    assert report["payloads"]["replay_performance_summary"]["summary_type"] == "option_replay_performance_distribution"
    assert report["summary"]["replay_max_drawdown_cash"] == pytest.approx(1750)
    assert "Replay Performance Distribution" in report["markdown"]


def test_replay_tool_exposes_performance_summary(shfe_options_db):
    _insert_review_day(shfe_options_db)
    _insert_second_review_day(shfe_options_db)

    from tradingagents.agents.utils.options_tools import get_option_strategy_replay

    raw = get_option_strategy_replay.invoke({
        "symbol": "CU",
        "strategy_type": "bull_call_spread",
        "entry_date": "2026-05-01",
        "review_dates": ["2026-05-01", "2026-05-06", "2026-05-11"],
        "expiry": "20260625",
        "risk_budget_cash": 10_000,
    })
    payload = json.loads(raw)

    assert payload["performance_summary"]["summary_type"] == "option_replay_performance_distribution"
    assert payload["performance_summary"]["max_drawdown_cash"] == pytest.approx(1750)
    assert payload["assumptions"]["performance_distribution_included"] is True
