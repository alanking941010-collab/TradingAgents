"""Phase 5 tests for deterministic option strategy structuring."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from tradingagents.agents.schemas import TraderAction, TraderProposal, render_trader_proposal
from tradingagents.agents.trader.trader import create_trader


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
