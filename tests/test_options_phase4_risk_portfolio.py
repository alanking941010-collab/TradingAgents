"""Phase 4 tests for options risk managers and portfolio manager."""

from __future__ import annotations

from unittest.mock import MagicMock

from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
from tradingagents.agents.risk_mgmt.aggressive_debator import create_aggressive_debator
from tradingagents.agents.risk_mgmt.conservative_debator import create_conservative_debator
from tradingagents.agents.risk_mgmt.neutral_debator import create_neutral_debator
from tradingagents.agents.schemas import PortfolioDecision, PortfolioRating, render_pm_decision


class CaptureLLM:
    def __init__(self, content: str = "risk response"):
        self.prompts: list[object] = []
        self.content = content

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return MagicMock(content=self.content)


def _risk_state(symbol: str = "CU") -> dict:
    return {
        "company_of_interest": symbol,
        "market_report": "Options analytics: ATM IV 16.35%, gamma flip near spot, walls concentrated.",
        "sentiment_report": "No sentiment edge.",
        "news_report": "Event risk can reprice IV and skew.",
        "fundamentals_report": "Inventory and macro uncertainty support volatility risk checks.",
        "investment_plan": (
            "**Recommendation**: Overweight\n"
            "**Volatility Debate Summary**: 5-day IV up probability; 20-day balanced; 40-day mean reversion risk."
        ),
        "trader_investment_plan": (
            "**Action**: Buy\n\n"
            "**Volatility View**: 5-day IV-up probability dominates; 20-day balanced; 40-day may mean revert.\n\n"
            "**Option Strategy**: Defined-risk call spread/calendar after liquidity check."
        ),
        "risk_debate_state": {
            "history": "",
            "aggressive_history": "",
            "conservative_history": "",
            "neutral_history": "",
            "latest_speaker": "",
            "current_aggressive_response": "",
            "current_conservative_response": "",
            "current_neutral_response": "",
            "judge_decision": "",
            "count": 0,
        },
    }


def test_options_risk_debators_must_cover_greeks_liquidity_margin_and_no_trade_conditions():
    cases = [
        (create_aggressive_debator, "Aggressive"),
        (create_conservative_debator, "Conservative"),
        (create_neutral_debator, "Neutral"),
    ]
    for factory, speaker in cases:
        llm = CaptureLLM(f"{speaker} risk response")
        node = factory(llm)
        result = node(_risk_state("CU"))

        assert result["risk_debate_state"]["latest_speaker"] == speaker
        prompt = str(llm.prompts[-1]).lower()
        for phrase in [
            "greeks",
            "gamma",
            "theta",
            "vega",
            "liquidity",
            "margin",
            "max loss",
            "expiry",
            "no-trade",
            "dealer position is unknown",
        ]:
            assert phrase in prompt


def test_non_options_risk_debator_keeps_original_stock_style_prompt():
    llm = CaptureLLM("stock risk")
    node = create_conservative_debator(llm)
    node(_risk_state("AAPL"))

    prompt = str(llm.prompts[-1]).lower()
    assert "dealer position is unknown" not in prompt
    assert "no-trade" not in prompt


def test_portfolio_decision_renders_options_risk_assessment_and_no_trade_conditions():
    decision = PortfolioDecision(
        rating=PortfolioRating.HOLD,
        executive_summary="Wait for better risk/reward.",
        investment_thesis="Vol view is plausible but risk budget is not favorable.",
        options_risk_assessment="Check delta/gamma/theta/vega, expiry, liquidity, margin, and max loss before entry.",
        no_trade_conditions="Do not trade if bid/ask is wide, gamma/theta is unstable, or max loss exceeds budget.",
        time_horizon="5-20 trading days",
    )

    rendered = render_pm_decision(decision)

    assert "**Options Risk Assessment**" in rendered
    assert "**No-Trade Conditions**" in rendered
    assert rendered.index("**Options Risk Assessment**") < rendered.index("**No-Trade Conditions**")
    assert "delta/gamma/theta/vega" in rendered


def test_options_portfolio_manager_prompt_requires_final_options_risk_budget_and_no_trade_filter():
    captured: dict[str, object] = {}
    decision = PortfolioDecision(
        rating=PortfolioRating.HOLD,
        executive_summary="Trade only if risk filters pass.",
        investment_thesis="Volatility view has edge but structure risk must be controlled.",
        options_risk_assessment="Defined-risk only; verify Greeks, liquidity, expiry, margin and max loss.",
        no_trade_conditions="No trade if liquidity is poor, theta bleed is too high, or dealer-position assumption dominates.",
    )
    structured = MagicMock()
    structured.invoke.side_effect = lambda prompt: captured.__setitem__("prompt", prompt) or decision
    llm = MagicMock()
    llm.with_structured_output.return_value = structured

    manager = create_portfolio_manager(llm)
    result = manager(_risk_state("铜"))

    prompt = str(captured["prompt"]).lower()
    for phrase in [
        "options risk assessment",
        "no-trade conditions",
        "greeks",
        "gamma",
        "theta",
        "vega",
        "liquidity",
        "margin",
        "max loss",
        "risk budget",
    ]:
        assert phrase in prompt
    assert "**Options Risk Assessment**" in result["final_trade_decision"]
    assert "**No-Trade Conditions**" in result["final_trade_decision"]
