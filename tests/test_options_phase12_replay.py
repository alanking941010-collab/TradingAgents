"""Phase 12 tests for historical replay/backtest and post-trade review."""

from __future__ import annotations

import json
import sqlite3

import pytest

from tests.test_options_phase5_strategy_structurer import shfe_options_db  # noqa: F401


def _insert_review_day(db_path):
    con = sqlite3.connect(db_path)
    try:
        con.executescript(
            """
            insert into futures_daily values
                ('20260506','CU2606.SHF',80500,80400,81200,83500,81000,83000,82800,2500,2400,150000,620000,240000),
                ('20260506','CU.SHF',80500,80400,81200,83500,81000,83000,82800,2500,2400,150000,620000,240000);

            insert into vw_shfe_option_chain_latest values
                ('20260506','CU2606C78000.SHF','铜看涨78000','CU','C',78000,'20260625','OPCU2606.SHF','OPCU2606.SHF','CU2606',3400,3400,4400,5600,4200,5200,5150,980,2600,1400),
                ('20260506','CU2606C80000.SHF','铜看涨80000','CU','C',80000,'20260625','OPCU2606.SHF','OPCU2606.SHF','CU2606',2450,2450,3000,3800,2900,3600,3550,1400,3200,3400),
                ('20260506','CU2606C82000.SHF','铜看涨82000','CU','C',82000,'20260625','OPCU2606.SHF','OPCU2606.SHF','CU2606',1450,1450,1900,2450,1800,2300,2260,1900,3600,5400),
                ('20260506','CU2606P78000.SHF','铜看跌78000','CU','P',78000,'20260625','OPCU2606.SHF','OPCU2606.SHF','CU2606',1000,1000,650,850,600,700,690,1550,2200,6900),
                ('20260506','CU2606P80000.SHF','铜看跌80000','CU','P',80000,'20260625','OPCU2606.SHF','OPCU2606.SHF','CU2606',1500,1500,950,1150,900,1000,990,1250,2100,2400),
                ('20260506','CU2606P82000.SHF','铜看跌82000','CU','P',82000,'20260625','OPCU2606.SHF','OPCU2606.SHF','CU2606',2100,2100,1400,1700,1350,1550,1530,1050,2000,1400);
            """
        )
        con.commit()
    finally:
        con.close()


def test_option_strategy_replay_marks_entry_legs_and_pnl_over_review_dates(shfe_options_db):
    _insert_review_day(shfe_options_db)

    from tradingagents.options.replay import build_option_strategy_replay

    replay = build_option_strategy_replay(
        "CU",
        strategy_type="bull_call_spread",
        entry_date="2026-05-01",
        review_dates=["2026-05-06"],
        expiry="20260625",
        risk_budget_cash=10_000,
    )

    assert replay["strategy_type"] == "bull_call_spread"
    assert replay["entry"]["trade_date"] == "2026-05-01"
    assert replay["entry"]["net_premium"] == pytest.approx(1000)
    assert replay["entry"]["net_premium_cash"] == pytest.approx(5000)
    assert replay["entry"]["margin_required_cash"] == pytest.approx(5000)

    mark = replay["marks"][0]
    assert mark["trade_date"] == "2026-05-06"
    assert mark["underlying_price"] == pytest.approx(83000)
    assert mark["mark_value"] == pytest.approx(1300)
    assert mark["pnl"] == pytest.approx(300)
    assert mark["pnl_cash"] == pytest.approx(1500)
    assert mark["pnl_pct_of_margin"] == pytest.approx(1500 / 5000)
    assert [leg["ts_code"] for leg in mark["leg_marks"]] == ["CU2606C80000.SHF", "CU2606C82000.SHF"]
    assert mark["leg_marks"][0]["mark_price"] == pytest.approx(3600)
    assert mark["leg_marks"][1]["mark_price"] == pytest.approx(2300)


def test_option_strategy_replay_summary_and_post_trade_review(shfe_options_db):
    _insert_review_day(shfe_options_db)

    from tradingagents.options.replay import build_option_strategy_replay

    replay = build_option_strategy_replay(
        "CU",
        strategy_type="bull_call_spread",
        entry_date="2026-05-01",
        review_dates=["2026-05-01", "2026-05-06"],
        expiry="20260625",
        risk_budget_cash=10_000,
    )

    summary = replay["summary"]
    assert summary["review_count"] == 2
    assert summary["final_pnl_cash"] == pytest.approx(1500)
    assert summary["best_pnl_cash"] == pytest.approx(1500)
    assert summary["worst_pnl_cash"] == pytest.approx(0)
    assert summary["best_trade_date"] == "2026-05-06"
    assert summary["worst_trade_date"] == "2026-05-01"
    assert summary["post_trade_review"]["outcome"] == "profitable"
    assert "favorable" in summary["post_trade_review"]["diagnosis"].lower()


def test_option_strategy_replay_tool_returns_parseable_json(shfe_options_db):
    _insert_review_day(shfe_options_db)

    from tradingagents.agents.utils.options_tools import get_option_strategy_replay

    raw = get_option_strategy_replay.invoke({
        "symbol": "CU",
        "strategy_type": "bull_call_spread",
        "entry_date": "2026-05-01",
        "review_dates": ["2026-05-06"],
        "expiry": "20260625",
        "risk_budget_cash": 10_000,
    })
    payload = json.loads(raw)

    assert payload["summary"]["final_pnl_cash"] == pytest.approx(1500)
    assert payload["assumptions"]["replay_price_basis"] == "option close + futures close"
    assert payload["assumptions"]["post_trade_review"] is True
