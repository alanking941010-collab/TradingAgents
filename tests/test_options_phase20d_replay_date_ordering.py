"""Phase 20D tests for chronological replay date ordering."""

from __future__ import annotations

import pytest

from tests.test_options_phase5_strategy_structurer import shfe_options_db  # noqa: F401
from tests.test_options_phase12_replay import _insert_review_day
from tests.test_options_phase18b_replay_performance import _insert_second_review_day


def test_replay_sorts_review_dates_chronologically_before_summary_and_drawdown(shfe_options_db):
    _insert_review_day(shfe_options_db)
    _insert_second_review_day(shfe_options_db)

    from tradingagents.options.replay import build_option_strategy_replay

    replay = build_option_strategy_replay(
        "CU",
        strategy_type="bull_call_spread",
        entry_date="2026-05-01",
        review_dates=["2026-05-11", "2026-05-01", "2026-05-06"],
        expiry="20260625",
        risk_budget_cash=10_000,
    )

    assert replay["input_review_dates"] == ["2026-05-11", "2026-05-01", "2026-05-06"]
    assert replay["resolved_review_dates"] == ["2026-05-01", "2026-05-06", "2026-05-11"]
    assert replay["assumptions"]["review_date_ordering"] == "chronological"
    assert [mark["trade_date"] for mark in replay["marks"]] == ["2026-05-01", "2026-05-06", "2026-05-11"]

    summary = replay["summary"]
    assert summary["final_trade_date"] == "2026-05-11"
    assert summary["final_pnl_cash"] == pytest.approx(-250)
    assert summary["post_trade_review"]["outcome"] == "loss_making"

    performance = replay["performance_summary"]
    assert [row["trade_date"] for row in performance["pnl_path"]] == ["2026-05-01", "2026-05-06", "2026-05-11"]
    assert performance["final_pnl_cash"] == pytest.approx(-250)
    assert performance["max_drawdown_cash"] == pytest.approx(1750)


def test_replay_rejects_review_dates_before_entry_date(shfe_options_db):
    from tradingagents.options.replay import build_option_strategy_replay

    with pytest.raises(ValueError, match="review_date.*before entry_date"):
        build_option_strategy_replay(
            "CU",
            strategy_type="bull_call_spread",
            entry_date="2026-05-01",
            review_dates=["2026-04-30", "2026-05-01"],
            expiry="20260625",
            risk_budget_cash=10_000,
        )
