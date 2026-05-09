"""Phase 20A cleanup tests for date and price-basis audit contracts."""

from __future__ import annotations

import sqlite3

import pytest

from tests.test_options_phase5_strategy_structurer import shfe_options_db  # noqa: F401
from tests.test_options_phase17_strategy_selector import _install_selector_fixture


def test_explicit_trade_date_defaults_to_exact_match_and_asof_is_explicit(shfe_options_db):
    from tradingagents.options.data_loader import load_option_chain_snapshot

    with pytest.raises(ValueError, match="exact trade_date"):
        load_option_chain_snapshot("CU", trade_date="2026-05-02", expiry="20260625")

    snapshot = load_option_chain_snapshot(
        "CU",
        trade_date="2026-05-02",
        expiry="20260625",
        date_mode="asof",
    )

    assert snapshot.requested_trade_date == "2026-05-02"
    assert snapshot.trade_date == "2026-05-01"
    assert snapshot.trade_date_mode == "asof"
    assert snapshot.trade_date_fallback_used is True


def test_snapshot_exposes_option_and_underlying_price_basis_fallbacks(shfe_options_db):
    with sqlite3.connect(shfe_options_db) as con:
        con.execute("update vw_shfe_option_chain_latest set close=null where ts_code='CU2606C80000.SHF'")
        con.execute("update futures_daily set close=null where ts_code='CU2606.SHF'")
        con.commit()

    from tradingagents.options.data_loader import load_option_chain_snapshot

    snapshot = load_option_chain_snapshot("CU", trade_date="2026-05-01", expiry="20260625")
    atm_call = next(row for row in snapshot.options if row.ts_code == "CU2606C80000.SHF")

    assert atm_call.mid_price == pytest.approx(2400)
    assert atm_call.price_basis == "settle_fallback"
    assert snapshot.option_price_basis == "mixed"
    assert snapshot.underlying_price == pytest.approx(80400)
    assert snapshot.underlying_price_basis == "settle_fallback"
    assert snapshot.underlying_price_trade_date == "2026-05-01"
    assert snapshot.price_basis["analysis_basis"] == "option close + futures close with explicit fallback metadata"
    assert snapshot.price_basis["option_price_basis"] == "mixed"
    assert snapshot.price_basis["underlying_price_basis"] == "settle_fallback"


def test_research_pack_summary_exposes_selected_risk_budget_utilization(shfe_options_db):
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

    selected_utilization = pack["payloads"]["portfolio_summary"]["selected_strategy"]["risk_budget_utilization"]
    assert selected_utilization is not None
    assert pack["summary"]["selected_risk_budget_utilization"] == selected_utilization
    assert "Risk budget utilization" in pack["markdown"]
