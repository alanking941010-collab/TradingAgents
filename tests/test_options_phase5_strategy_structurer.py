"""Phase 5 tests for deterministic option strategy structuring."""

from __future__ import annotations

import json
import sqlite3
from unittest.mock import MagicMock

import pytest

from tradingagents.agents.schemas import TraderAction, TraderProposal, render_trader_proposal
from tradingagents.agents.trader.trader import create_trader


@pytest.fixture()
def shfe_options_db(tmp_path, monkeypatch):
    db_path = tmp_path / "shfe_options.db"
    con = sqlite3.connect(db_path)
    try:
        con.executescript(
            """
            create table futures_daily (
                trade_date text, ts_code text, pre_close real, pre_settle real,
                open real, high real, low real, close real, settle real,
                change1 real, change2 real, vol real, amount real, oi real
            );
            insert into futures_daily values
                ('20260501','CU2606.SHF',79800,79750,80000,81200,79000,80500,80400,700,650,120000,500000,220000),
                ('20260501','CU.SHF',79800,79750,80000,81200,79000,80500,80400,700,650,120000,500000,220000);

            create table vw_shfe_option_chain_latest (
                trade_date text, ts_code text, name text, metal text, call_put text,
                strike real, maturity_date text, opt_code text, underlying_fut_code text,
                underlying_symbol text, pre_settle real, pre_close real, open real, high real,
                low real, close real, settle real, volume real, amount real, open_interest real
            );
            insert into vw_shfe_option_chain_latest values
                ('20260501','CU2606C78000.SHF','铜看涨78000','CU','C',78000,'20260625','OPCU2606.SHF','OPCU2606.SHF','CU2606',3200,3150,3300,3500,3100,3400,3380,900,2000,1200),
                ('20260501','CU2606C80000.SHF','铜看涨80000','CU','C',80000,'20260625','OPCU2606.SHF','OPCU2606.SHF','CU2606',2200,2150,2300,2500,2100,2450,2400,1200,2600,3000),
                ('20260501','CU2606C82000.SHF','铜看涨82000','CU','C',82000,'20260625','OPCU2606.SHF','OPCU2606.SHF','CU2606',1200,1180,1300,1500,1150,1450,1420,1800,3000,5000),
                ('20260501','CU2606P78000.SHF','铜看跌78000','CU','P',78000,'20260625','OPCU2606.SHF','OPCU2606.SHF','CU2606',900,880,950,1100,850,1000,980,1600,2200,7000),
                ('20260501','CU2606P80000.SHF','铜看跌80000','CU','P',80000,'20260625','OPCU2606.SHF','OPCU2606.SHF','CU2606',1300,1280,1350,1550,1250,1500,1480,1300,2100,2500),
                ('20260501','CU2606P82000.SHF','铜看跌82000','CU','P',82000,'20260625','OPCU2606.SHF','OPCU2606.SHF','CU2606',1900,1880,1950,2150,1850,2100,2080,1100,2000,1500);
            """
        )
        con.commit()
    finally:
        con.close()
    monkeypatch.setenv("TRADINGAGENTS_SHFE_OPTIONS_DB", str(db_path))
    return db_path


def test_bull_call_spread_strategy_has_auditable_legs_payoff_greeks_and_liquidity(shfe_options_db):
    from tradingagents.options.strategies import build_option_strategy_candidate

    candidate = build_option_strategy_candidate(
        "CU",
        strategy_type="bull_call_spread",
        trade_date="2026-05-01",
        expiry="20260625",
    )

    assert candidate["strategy_type"] == "bull_call_spread"
    assert candidate["price_basis"] == "option close + futures close"
    assert candidate["net_premium"] > 0
    assert candidate["premium_type"] == "debit"
    assert candidate["max_loss"] == pytest.approx(candidate["net_premium"])
    assert candidate["max_profit"] == pytest.approx(candidate["legs"][1]["strike"] - candidate["legs"][0]["strike"] - candidate["net_premium"])
    assert candidate["breakevens"] == [pytest.approx(candidate["legs"][0]["strike"] + candidate["net_premium"])]
    assert [leg["side"] for leg in candidate["legs"]] == ["BUY", "SELL"]
    assert [leg["call_put"] for leg in candidate["legs"]] == ["C", "C"]
    assert all(key in candidate["greeks"] for key in ["delta", "gamma", "theta", "vega"])
    assert candidate["liquidity"]["passes"] is True
    assert candidate["liquidity"]["min_open_interest"] >= 1000


def test_long_straddle_strategy_uses_atm_call_and_put_with_symmetric_breakevens(shfe_options_db):
    from tradingagents.options.strategies import build_option_strategy_candidate

    candidate = build_option_strategy_candidate(
        "铜",
        strategy_type="long_straddle",
        trade_date="2026-05-01",
        expiry="20260625",
    )

    assert candidate["strategy_type"] == "long_straddle"
    assert len(candidate["legs"]) == 2
    assert {leg["call_put"] for leg in candidate["legs"]} == {"C", "P"}
    assert {leg["side"] for leg in candidate["legs"]} == {"BUY"}
    strike = candidate["legs"][0]["strike"]
    assert candidate["legs"][1]["strike"] == strike
    assert candidate["max_loss"] == pytest.approx(candidate["net_premium"])
    assert candidate["max_profit"] is None
    assert candidate["breakevens"] == [pytest.approx(strike - candidate["net_premium"]), pytest.approx(strike + candidate["net_premium"])]


def test_option_strategy_tool_returns_parseable_json(shfe_options_db):
    from tradingagents.agents.utils.options_tools import get_option_strategy_candidate

    raw = get_option_strategy_candidate.invoke({
        "symbol": "CU",
        "strategy_type": "bull_call_spread",
        "trade_date": "2026-05-01",
        "expiry": "20260625",
    })
    payload = json.loads(raw)

    assert payload["strategy_type"] == "bull_call_spread"
    assert "legs" in payload and len(payload["legs"]) == 2
    assert "max_loss" in payload
    assert "liquidity" in payload


def test_trader_proposal_renders_structured_strategy_after_option_strategy():
    structured_strategy = {
        "strategy_type": "bull_call_spread",
        "legs": [
            {"side": "BUY", "call_put": "C", "strike": 80000, "quantity": 1},
            {"side": "SELL", "call_put": "C", "strike": 82000, "quantity": 1},
        ],
        "max_loss": 1000,
        "max_profit": 1000,
        "breakevens": [81000],
    }
    proposal = TraderProposal(
        action=TraderAction.BUY,
        volatility_view="5-day IV-up probability dominates.",
        option_strategy="Bull call spread after liquidity check.",
        structured_strategy=structured_strategy,
        reasoning="Defined-risk upside expression.",
    )

    rendered = render_trader_proposal(proposal)

    assert "**Structured Option Strategy**" in rendered
    assert "bull_call_spread" in rendered
    assert rendered.index("**Option Strategy**") < rendered.index("**Structured Option Strategy**") < rendered.index("**Reasoning**")


def test_options_trader_prompt_requires_structured_strategy_fields():
    captured: dict[str, object] = {}
    structured = MagicMock()
    structured.invoke.side_effect = lambda prompt: captured.__setitem__("prompt", prompt) or TraderProposal(
        action=TraderAction.BUY,
        volatility_view="5-day IV-up edge.",
        option_strategy="Use bull call spread.",
        structured_strategy={"strategy_type": "bull_call_spread", "legs": [], "max_loss": 1},
        reasoning="Defined risk.",
    )
    llm = MagicMock()
    llm.with_structured_output.return_value = structured

    trader = create_trader(llm)
    trader({"company_of_interest": "CU", "investment_plan": "Use options after vol view."})

    prompt = "\n".join(message["content"] for message in captured["prompt"]).lower()
    for phrase in [
        "structured option strategy",
        "legs",
        "expiry",
        "strike",
        "side",
        "quantity",
        "debit",
        "credit",
        "max loss",
        "max profit",
        "breakeven",
        "greeks snapshot",
        "liquidity filter",
    ]:
        assert phrase in prompt
