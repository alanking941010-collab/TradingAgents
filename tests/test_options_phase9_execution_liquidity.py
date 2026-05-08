"""Phase 9 tests for bid/ask, slippage, and execution liquidity scoring."""

from __future__ import annotations

import sqlite3

import pytest

from tests.test_options_phase5_strategy_structurer import shfe_options_db  # noqa: F401


def _install_akshare_bid_ask_snapshot(db_path):
    con = sqlite3.connect(db_path)
    try:
        con.executescript(
            """
            create table akshare_option_snapshot (
                trade_date text, metal text, contract_code text, contract_month text,
                strike real, call_put text, contract_name text, close real, bid real,
                ask real, volume real, open_interest real, change real, source text,
                updated_at text
            );
            insert into akshare_option_snapshot values
                ('20260501','CU','cu2606','2606',80000,'C','cu2606C80000',2450,2430,2470,900,3000,0,'akshare_sina_option','2026-05-01 15:01:00'),
                ('20260501','CU','cu2606','2606',82000,'C','cu2606C82000',1450,1435,1460,600,5000,0,'akshare_sina_option','2026-05-01 15:01:00'),
                ('20260501','CU','cu2606','2606',80000,'P','cu2606P80000',1500,1485,1525,700,2500,0,'akshare_sina_option','2026-05-01 15:01:00');
            """
        )
        con.commit()
    finally:
        con.close()


def test_option_loader_enriches_quote_bid_ask_from_akshare_snapshot(shfe_options_db):
    _install_akshare_bid_ask_snapshot(shfe_options_db)

    from tradingagents.options.data_loader import load_option_chain_snapshot

    snapshot = load_option_chain_snapshot("CU", trade_date="2026-05-01", expiry="20260625")
    atm_call = next(row for row in snapshot.options if row.ts_code == "CU2606C80000.SHF")

    assert atm_call.bid == pytest.approx(2430)
    assert atm_call.ask == pytest.approx(2470)
    assert atm_call.bid_ask_mid == pytest.approx(2450)
    assert atm_call.bid_ask_spread == pytest.approx(40)
    assert atm_call.bid_ask_spread_pct == pytest.approx(40 / 2450)
    # Trading-analysis price basis remains Alan's default close price.
    assert atm_call.mid_price == pytest.approx(2450)


def test_strategy_candidate_uses_buy_ask_sell_bid_for_execution_slippage(shfe_options_db):
    _install_akshare_bid_ask_snapshot(shfe_options_db)

    from tradingagents.options.strategies import build_option_strategy_candidate

    candidate = build_option_strategy_candidate(
        "CU",
        strategy_type="bull_call_spread",
        trade_date="2026-05-01",
        expiry="20260625",
    )

    buy_leg, sell_leg = candidate["legs"]
    assert buy_leg["execution_price"] == pytest.approx(2470)
    assert buy_leg["execution_price_basis"] == "ask"
    assert sell_leg["execution_price"] == pytest.approx(1435)
    assert sell_leg["execution_price_basis"] == "bid"

    execution = candidate["execution"]
    assert execution["bid_ask_complete"] is True
    assert execution["net_mid_premium"] == pytest.approx(1000)
    assert execution["net_execution_premium"] == pytest.approx(2470 - 1435)
    assert execution["slippage_points"] == pytest.approx(35)
    assert execution["slippage_cash"] == pytest.approx(35 * 5)
    assert execution["slippage_pct_of_mid_premium"] == pytest.approx(35 / 1000)
    assert 0 <= execution["execution_liquidity_score"] <= 100
    assert execution["execution_liquidity_score"] >= 70


def test_options_prompts_reference_execution_liquidity_and_slippage():
    from tradingagents.agents.utils.options_integration import (
        options_portfolio_instruction,
        options_risk_debator_instruction,
        options_trader_instruction,
    )

    trader_prompt = options_trader_instruction("CU").lower()
    risk_prompt = options_risk_debator_instruction("CU", "neutral").lower()
    portfolio_prompt = options_portfolio_instruction("CU").lower()

    for prompt in [trader_prompt, risk_prompt, portfolio_prompt]:
        assert "execution liquidity" in prompt
        assert "slippage" in prompt
        assert "bid/ask" in prompt
