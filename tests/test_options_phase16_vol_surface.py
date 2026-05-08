"""Phase 16 tests for volatility surface, skew buckets, and term-structure signals."""

from __future__ import annotations

import json

import pytest

from tests.test_options_analytics_core import shfe_options_db  # noqa: F401


def test_analyze_option_chain_adds_vol_surface_summary(shfe_options_db):
    from tradingagents.options.analytics import analyze_option_chain

    report = analyze_option_chain("CU", trade_date="2026-05-01", risk_free_rate=0.015)

    surface = report.vol_surface
    assert surface["nearest_expiry"] == "2026-06-25"
    assert surface["underlying_price"] == pytest.approx(80500)

    nearest = surface["moneyness_buckets"]["2026-06-25"]
    assert nearest["atm"]["representative_strike"] == pytest.approx(80000)
    assert nearest["otm_put"]["representative_strike"] < report.underlying_price
    assert nearest["otm_call"]["representative_strike"] > report.underlying_price
    for bucket in [nearest["otm_put"], nearest["atm"], nearest["otm_call"]]:
        assert bucket["avg_iv"] is not None and bucket["avg_iv"] > 0
        assert bucket["option_count"] >= 1

    skew = surface["skew"]
    assert skew["put_call_skew"] == pytest.approx(report.skew_25d)
    assert skew["risk_reversal_proxy"] is not None
    assert skew["smile_curvature_proxy"] is not None

    term = surface["term_regime"]
    assert term["front_expiry"] == "2026-06-25"
    assert term["back_expiry"] == "2026-07-25"
    assert term["slope"] == pytest.approx(term["back_iv"] - term["front_iv"])
    assert term["shape"] in {"contango", "backwardation", "flat", "single_expiry"}


def test_option_analytics_tool_and_markdown_expose_vol_surface(shfe_options_db):
    from tradingagents.agents.utils.options_tools import get_option_analytics_json, get_option_analytics_report

    payload = json.loads(get_option_analytics_json.invoke({"symbol": "CU", "trade_date": "2026-05-01"}))
    assert "vol_surface" in payload
    assert payload["vol_surface"]["term_regime"]["front_expiry"] == "2026-06-25"
    assert "risk_reversal_proxy" in payload["vol_surface"]["skew"]
    assert "moneyness_buckets" in payload["vol_surface"]

    markdown = get_option_analytics_report.invoke({"symbol": "CU", "trade_date": "2026-05-01"})
    assert "Volatility Surface" in markdown
    assert "Term regime" in markdown
    assert "Risk reversal proxy" in markdown


def test_strategy_report_carries_vol_surface_snapshot_and_prompts_reference_it(shfe_options_db):
    from tradingagents.agents.utils.options_integration import (
        options_analyst_instruction,
        options_risk_debator_instruction,
        options_trader_instruction,
    )
    from tradingagents.options.reports import build_option_strategy_report

    report = build_option_strategy_report(
        "CU",
        strategy_type="bull_call_spread",
        trade_date="2026-05-01",
        expiry="20260625",
        risk_budget_cash=6_000,
    )

    surface = report["payloads"]["volatility_snapshot"]["vol_surface"]
    assert surface["term_regime"]["front_expiry"] == "2026-06-25"
    assert surface["moneyness_buckets"]["2026-06-25"]["atm"]["representative_strike"] == pytest.approx(80000)
    assert "volatility surface" in report["markdown"].lower()

    prompts = [
        options_analyst_instruction("CU", "market").lower(),
        options_trader_instruction("CU").lower(),
        options_risk_debator_instruction("CU", "neutral").lower(),
    ]
    for prompt in prompts:
        assert "volatility surface" in prompt
        assert "skew" in prompt
        assert "term structure" in prompt
