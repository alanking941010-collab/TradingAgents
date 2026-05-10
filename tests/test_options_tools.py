"""Tests for option analytics tools exposed to TradingAgents agents."""

from __future__ import annotations

import json

import pytest


def test_build_option_trade_context_is_compact_and_volatility_first(shfe_options_db):
    from tradingagents.agents.utils.options_tools import build_option_trade_context

    context = build_option_trade_context("铜", trade_date="2026-05-01", expiry="20260625")

    assert context["product"] == "CU"
    assert context["underlying"]["price"] == pytest.approx(80500)
    assert context["underlying"]["price_basis"] == "close"
    assert context["volatility"]["atm_iv"] > 0
    assert context["positioning"]["pcr_oi"] > 0
    assert context["positioning"]["call_wall"]["strike"] == 82000
    assert context["risk_assumptions"]["risk_free_rate"] == 0.015
    assert context["risk_assumptions"]["dealer_position_unknown"] is True
    assert context["agent_lens"]["market_analyst"] == "underlying trend, RV, technical context, and futures anchor"
    assert "volatility" in context["agent_lens"]["fundamentals_analyst"]
    assert "options" not in json.dumps(context).lower() or len(json.dumps(context)) < 6000


def test_get_option_trade_context_tool_returns_parseable_json(shfe_options_db):
    from tradingagents.agents.utils.options_tools import get_option_trade_context

    raw = get_option_trade_context.invoke({"symbol": "CU", "trade_date": "2026-05-01", "expiry": "20260625"})
    payload = json.loads(raw)

    assert payload["product"] == "CU"
    assert payload["risk_assumptions"]["price_basis"] == "option close + futures close"
    assert payload["volatility"]["atm_iv"] > 0


def test_get_option_analytics_report_tool_returns_markdown(shfe_options_db):
    from tradingagents.agents.utils.options_tools import get_option_analytics_report

    report = get_option_analytics_report.invoke({"symbol": "CU", "trade_date": "2026-05-01", "expiry": "20260625"})

    assert report.startswith("# Options analytics core: CU")
    assert "Price basis: option close + futures close" in report
    assert "dealer_position_unknown" in report


def test_get_option_analytics_json_tool_keeps_full_chain_for_audit(shfe_options_db):
    from tradingagents.agents.utils.options_tools import get_option_analytics_json

    raw = get_option_analytics_json.invoke({"symbol": "CU", "trade_date": "2026-05-01", "expiry": "20260625"})
    payload = json.loads(raw)

    assert payload["assumptions"]["price_basis"] == "option close + futures close"
    assert len(payload["options"]) == 6
    assert payload["options"][0]["price_used"] == payload["options"][0]["close"]
