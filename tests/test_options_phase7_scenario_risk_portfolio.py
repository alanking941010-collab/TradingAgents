"""Phase 7 tests for wiring scenario PnL into options risk/portfolio prompts."""

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


def _state(symbol: str = "CU") -> dict:
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
            "**Option Strategy**: Defined-risk bull call spread.\n\n"
            "**Structured Option Strategy**:\n"
            "```json\n"
            "{\"strategy_type\": \"bull_call_spread\", \"max_loss\": 734.0, "
            "\"scenario_pnl\": {\"summary\": {\"worst_pnl\": -734.0, \"best_pnl\": 1266.0, "
            "\"worst_scenario\": \"S003\", \"best_scenario\": \"S021\", "
            "\"breakeven_proximity\": 74.0}}}\n"
            "```"
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


def test_options_risk_debators_must_use_scenario_pnl_matrix_terms():
    cases = [
        create_aggressive_debator,
        create_conservative_debator,
        create_neutral_debator,
    ]
    for factory in cases:
        llm = CaptureLLM()
        node = factory(llm)
        node(_state("CU"))

        prompt = str(llm.prompts[-1]).lower()
        for phrase in [
            "scenario pnl",
            "worst scenario",
            "best scenario",
            "t+5",
            "t+20",
            "iv up/down",
            "max loss",
            "breakeven proximity",
        ]:
            assert phrase in prompt


def test_non_options_risk_debator_does_not_add_scenario_pnl_requirements():
    llm = CaptureLLM()
    node = create_neutral_debator(llm)
    node(_state("AAPL"))

    prompt = str(llm.prompts[-1]).lower()
    assert "scenario pnl" not in prompt
    assert "breakeven proximity" not in prompt


def test_portfolio_decision_renders_scenario_pnl_before_options_risk_assessment():
    decision = PortfolioDecision(
        rating=PortfolioRating.HOLD,
        executive_summary="Approve only after stress matrix confirms acceptable loss.",
        investment_thesis="Vol edge is present but path risk matters.",
        scenario_pnl_assessment=(
            "Worst scenario is S003 at -734; best scenario is S021 at 1266; "
            "T+5/T+20 theta decay and IV up/down paths are acceptable."
        ),
        options_risk_assessment="Max loss matches debit and Greeks remain within budget.",
        no_trade_conditions="No trade if breakeven proximity worsens or scenario loss exceeds budget.",
    )

    rendered = render_pm_decision(decision)

    assert "**Scenario PnL Assessment**" in rendered
    assert "**Options Risk Assessment**" in rendered
    assert rendered.index("**Scenario PnL Assessment**") < rendered.index("**Options Risk Assessment**")
    assert "Worst scenario is S003" in rendered


def test_options_portfolio_prompt_requires_scenario_pnl_assessment_and_specific_stresses():
    captured: dict[str, object] = {}
    decision = PortfolioDecision(
        rating=PortfolioRating.HOLD,
        executive_summary="Trade only if scenario matrix passes.",
        investment_thesis="Volatility edge must survive stress testing.",
        scenario_pnl_assessment="Worst/best scenario, T+5/T+20 decay, IV up/down, and breakeven proximity checked.",
        options_risk_assessment="Defined-risk and max loss stay within budget.",
        no_trade_conditions="No trade if stress loss or breakeven proximity becomes unacceptable.",
    )
    structured = MagicMock()
    structured.invoke.side_effect = lambda prompt: captured.__setitem__("prompt", prompt) or decision
    llm = MagicMock()
    llm.with_structured_output.return_value = structured

    manager = create_portfolio_manager(llm)
    result = manager(_state("铜"))

    prompt = str(captured["prompt"]).lower()
    for phrase in [
        "scenario pnl assessment",
        "worst scenario",
        "best scenario",
        "t+5",
        "t+20",
        "iv up/down",
        "max loss",
        "breakeven proximity",
    ]:
        assert phrase in prompt
    assert "**Scenario PnL Assessment**" in result["final_trade_decision"]
    assert "**Options Risk Assessment**" in result["final_trade_decision"]
