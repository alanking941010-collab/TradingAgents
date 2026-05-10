"""Tests for SHFE options analytics core.

The options core should do deterministic calculations in Python and read Alan's
local SHFE options warehouse in read-only mode. LLM agents can explain these
outputs later, but they must not be responsible for IV/Greeks/GEX arithmetic.
"""

from __future__ import annotations

import math

import pytest


def test_black76_implied_volatility_roundtrips_to_price():
    from tradingagents.options.pricing import black76_price, implied_volatility

    price = black76_price(
        futures_price=80500,
        strike=80000,
        time_to_expiry=55 / 365,
        risk_free_rate=0.015,
        volatility=0.28,
        option_type="C",
    )

    iv = implied_volatility(
        option_price=price,
        futures_price=80500,
        strike=80000,
        time_to_expiry=55 / 365,
        risk_free_rate=0.015,
        option_type="C",
    )

    assert iv == pytest.approx(0.28, rel=1e-4)


def test_black76_greeks_have_expected_signs_for_calls_and_puts():
    from tradingagents.options.greeks import black76_greeks

    call = black76_greeks(80500, 80000, 55 / 365, 0.015, 0.28, "C")
    put = black76_greeks(80500, 80000, 55 / 365, 0.015, 0.28, "P")

    assert 0 < call.delta < 1
    assert -1 < put.delta < 0
    assert call.gamma > 0
    assert put.gamma > 0
    assert call.vega > 0
    assert put.vega > 0
    assert math.isfinite(call.theta)
    assert math.isfinite(put.theta)


def test_load_option_chain_snapshot_normalizes_contract_rows(shfe_options_db):
    from tradingagents.options.data_loader import load_option_chain_snapshot

    snapshot = load_option_chain_snapshot("铜", trade_date="2026-05-01", expiry="20260625")

    assert snapshot.product == "CU"
    assert snapshot.trade_date == "2026-05-01"
    assert snapshot.underlying_price == pytest.approx(80500)
    assert len(snapshot.options) == 6
    assert {row.call_put for row in snapshot.options} == {"C", "P"}
    assert {row.strike for row in snapshot.options} == {78000, 80000, 82000}
    assert snapshot.options[0].source == "shfe_options.db:vw_shfe_option_chain_latest"


def test_option_quote_mid_price_prefers_close_over_settle_for_trading_analysis(shfe_options_db):
    from tradingagents.options.data_loader import load_option_chain_snapshot

    snapshot = load_option_chain_snapshot("CU", trade_date="2026-05-01", expiry="20260625")
    atm_call = next(row for row in snapshot.options if row.ts_code == "CU2606C80000.SHF")

    assert atm_call.close == pytest.approx(2450)
    assert atm_call.settle == pytest.approx(2400)
    assert atm_call.mid_price == pytest.approx(2450)


def test_analyze_option_chain_computes_core_metrics(shfe_options_db):
    from tradingagents.options.analytics import analyze_option_chain

    report = analyze_option_chain("CU", trade_date="2026-05-01", risk_free_rate=0.015)

    assert report.product == "CU"
    assert report.trade_date == "2026-05-01"
    assert report.underlying_price == pytest.approx(80500)
    assert report.pcr_open_interest > 0
    assert report.call_wall.strike == 82000
    assert report.put_wall.strike == 78000
    assert report.atm_iv is not None and report.atm_iv > 0
    assert report.skew_25d is not None
    assert report.term_structure
    assert report.gamma_flip is None or isinstance(report.gamma_flip, float)
    assert report.exposure.total_abs_gex > 0
    assert "dealer_position_unknown" in report.assumptions


def test_analyze_option_chain_can_return_markdown_summary(shfe_options_db):
    from tradingagents.options.analytics import analyze_option_chain

    markdown = analyze_option_chain("CU", trade_date="2026-05-01").to_markdown()

    assert "# Options analytics core: CU" in markdown
    assert "PCR" in markdown
    assert "Call Wall" in markdown
    assert "Put Wall" in markdown
    assert "GEX" in markdown
    assert "dealer_position_unknown" in markdown
