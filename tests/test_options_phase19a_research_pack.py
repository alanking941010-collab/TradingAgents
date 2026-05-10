"""Phase 19A tests for unified option research pack orchestration."""

from __future__ import annotations

import json

import pytest

from tests.test_options_phase12_replay import _insert_review_day
from tests.test_options_phase17_strategy_selector import _install_selector_fixture
from tests.test_options_phase18b_replay_performance import _insert_second_review_day


def test_research_pack_auto_selects_strategy_and_embeds_auditable_sections(shfe_options_db):
    _install_selector_fixture(shfe_options_db)

    from tradingagents.options.research_pack import build_option_research_pack

    pack = build_option_research_pack(
        "CU",
        trade_date="2026-05-01",
        expiry="20260625",
        directional_bias="neutral",
        volatility_view="range_bound_high_iv",
        risk_budget_cash=6_000,
        min_credit_pct_of_wing_width=0.20,
        max_bid_ask_spread_pct=0.50,
    )

    assert pack["pack_type"] == "shfe_option_research_pack"
    assert pack["product"] == "CU"
    assert pack["trade_date"] == "2026-05-01"
    assert pack["selected_strategy"] == pack["payloads"]["selection"]["selected_strategy"]
    assert pack["payloads"]["portfolio_summary"] == pack["payloads"]["selection"]["portfolio_summary"]
    assert pack["payloads"]["selected_strategy_report"]["strategy_type"] == pack["selected_strategy"]
    assert pack["payloads"]["feishu_delivery_payload"]["dry_run"] is True
    assert pack["summary"]["risk_budget_cash"] == 6_000
    assert pack["summary"]["selected_decision"] in {"candidate", "watch", "no_trade"}
    assert "Options Research Pack" in pack["markdown"]
    assert "Strategy Selection" in pack["markdown"]
    assert "Selected Strategy Report" in pack["markdown"]
    assert pack["assumptions"]["side_effect_free"] is True
    assert pack["assumptions"]["not_execution_instruction"] is True


def test_research_pack_can_override_strategy_and_include_replay_performance(shfe_options_db):
    _insert_review_day(shfe_options_db)
    _insert_second_review_day(shfe_options_db)

    from tradingagents.options.research_pack import build_option_research_pack

    pack = build_option_research_pack(
        "CU",
        trade_date="2026-05-01",
        expiry="20260625",
        strategy_type="bull_call_spread",
        directional_bias="bullish",
        volatility_view="moderate_iv",
        review_dates=["2026-05-01", "2026-05-06", "2026-05-11"],
        risk_budget_cash=10_000,
    )

    assert pack["selection_mode"] == "explicit_strategy_override"
    assert pack["selected_strategy"] == "bull_call_spread"
    report = pack["payloads"]["selected_strategy_report"]
    assert report["payloads"]["replay_performance_summary"]["summary_type"] == "option_replay_performance_distribution"
    assert pack["summary"]["replay_max_drawdown_cash"] == pytest.approx(1750)
    assert pack["summary"]["replay_win_rate"] == pytest.approx(1 / 3)
    assert "Replay Performance Distribution" in pack["markdown"]


def test_research_pack_tool_returns_parseable_json_and_schema_mentions_override(shfe_options_db):
    _install_selector_fixture(shfe_options_db)

    from tradingagents.agents.utils.options_tools import get_option_research_pack

    raw = get_option_research_pack.invoke({
        "symbol": "CU",
        "trade_date": "2026-05-01",
        "expiry": "20260625",
        "directional_bias": "neutral",
        "volatility_view": "range_bound_high_iv",
        "risk_budget_cash": 6_000,
        "min_credit_pct_of_wing_width": 0.20,
        "max_bid_ask_spread_pct": 0.50,
    })
    payload = json.loads(raw)

    assert payload["pack_type"] == "shfe_option_research_pack"
    assert payload["payloads"]["selected_strategy_report"]["strategy_type"] == payload["selected_strategy"]
    schema_text = str(get_option_research_pack.args_schema.model_fields)
    assert "strategy_type" in schema_text
    assert "review_dates" in schema_text
