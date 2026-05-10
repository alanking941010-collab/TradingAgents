"""Phase 13 tests for option report pipeline and Feishu delivery payloads."""

from __future__ import annotations

import json

import pytest

from tests.test_options_phase12_replay import _insert_review_day


def test_option_strategy_report_pipeline_builds_markdown_with_auditable_sections(shfe_options_db):
    _insert_review_day(shfe_options_db)

    from tradingagents.options.reports import build_option_strategy_report

    report = build_option_strategy_report(
        "CU",
        strategy_type="bull_call_spread",
        trade_date="2026-05-01",
        expiry="20260625",
        review_dates=["2026-05-06"],
        risk_budget_cash=10_000,
    )

    assert report["report_type"] == "shfe_option_strategy_report"
    assert report["product"] == "CU"
    assert report["strategy_type"] == "bull_call_spread"
    assert report["title"] == "CU bull_call_spread option strategy report — 2026-05-01"
    assert report["summary"]["price_basis"] == "option close + futures close"
    assert report["summary"]["risk_budget_status"] == "pass"
    assert report["payloads"]["strategy"]["margin"]["margin_required_cash"] == pytest.approx(5000)
    assert report["payloads"]["scenario_summary"]["worst_pnl_cash"] is not None
    assert report["payloads"]["replay_summary"]["final_pnl_cash"] == pytest.approx(1500)

    markdown = report["markdown"]
    for heading in [
        "# CU bull_call_spread option strategy report",
        "## Volatility Snapshot",
        "## Strategy Candidate",
        "## Scenario PnL",
        "## Historical Replay",
        "## Assumptions and Delivery Notes",
    ]:
        assert heading in markdown
    assert "option close + futures close" in markdown
    assert "Exchange/SPAN margin is not modeled" in markdown


def test_feishu_delivery_payload_is_side_effect_free_and_ready_to_send(shfe_options_db):
    _insert_review_day(shfe_options_db)

    from tradingagents.options.reports import build_feishu_delivery_payload, build_option_strategy_report

    report = build_option_strategy_report(
        "CU",
        strategy_type="bull_call_spread",
        trade_date="2026-05-01",
        expiry="20260625",
        review_dates=["2026-05-06"],
        risk_budget_cash=10_000,
    )
    payload = build_feishu_delivery_payload(report, target="feishu:oc_test", dry_run=True)

    assert payload["channel"] == "feishu"
    assert payload["target"] == "feishu:oc_test"
    assert payload["dry_run"] is True
    assert payload["side_effect_free"] is True
    assert payload["title"] == report["title"]
    assert payload["message"] == report["markdown"]
    assert payload["delivery_hint"] == "Use Hermes send_message(target, message) or Gateway Feishu delivery to send this Markdown."


def test_option_report_and_feishu_delivery_tools_return_parseable_json(shfe_options_db):
    _insert_review_day(shfe_options_db)

    from tradingagents.agents.utils.options_tools import get_option_feishu_delivery_payload, get_option_strategy_report

    raw_report = get_option_strategy_report.invoke({
        "symbol": "CU",
        "strategy_type": "bull_call_spread",
        "trade_date": "2026-05-01",
        "expiry": "20260625",
        "review_dates": ["2026-05-06"],
        "risk_budget_cash": 10_000,
    })
    report = json.loads(raw_report)
    assert report["payloads"]["replay_summary"]["post_trade_review"]["outcome"] == "profitable"
    assert "markdown" in report

    raw_payload = get_option_feishu_delivery_payload.invoke({
        "symbol": "CU",
        "strategy_type": "bull_call_spread",
        "trade_date": "2026-05-01",
        "expiry": "20260625",
        "review_dates": ["2026-05-06"],
        "risk_budget_cash": 10_000,
        "target": "feishu:oc_test",
        "dry_run": True,
    })
    delivery = json.loads(raw_payload)
    assert delivery["channel"] == "feishu"
    assert delivery["dry_run"] is True
    assert delivery["message"].startswith("# CU bull_call_spread option strategy report")
