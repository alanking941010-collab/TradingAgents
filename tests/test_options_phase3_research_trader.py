"""Phase 3 tests for volatility-first researchers and trader output."""

from __future__ import annotations

from unittest.mock import MagicMock

from tradingagents.agents.managers.research_manager import create_research_manager
from tradingagents.agents.researchers.bear_researcher import create_bear_researcher
from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
from tradingagents.agents.schemas import (
    PortfolioRating,
    ResearchPlan,
    TraderAction,
    TraderProposal,
    render_research_plan,
    render_trader_proposal,
)
from tradingagents.agents.trader.trader import create_trader


class CaptureLLM:
    def __init__(self, content: str = "captured response"):
        self.prompts: list[object] = []
        self.content = content

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return MagicMock(content=self.content)


def _debate_state(symbol: str = "CU") -> dict:
    return {
        "company_of_interest": symbol,
        "market_report": "Options analytics mode: ATM IV 16.35%, term structure flat, gamma flip near spot.",
        "sentiment_report": "No social signal.",
        "news_report": "Macro events may reprice copper IV.",
        "fundamentals_report": "Inventory draw and macro uncertainty support volatility regime discussion.",
        "investment_debate_state": {
            "history": "",
            "bull_history": "",
            "bear_history": "",
            "current_response": "",
            "judge_decision": "",
            "count": 0,
        },
    }


def _trader_state(symbol: str = "CU") -> dict:
    return {
        "company_of_interest": symbol,
        "investment_plan": (
            "**Recommendation**: Overweight\n"
            "**Rationale**: Bull argues 5-day IV may rise on event risk; bear argues 20/40-day IV may mean revert.\n"
            "**Strategic Actions**: Trader should decide vol up/down view before selecting option structures."
        ),
    }


def _research_manager_state(symbol: str = "CU") -> dict:
    state = _debate_state(symbol)
    state["investment_debate_state"]["history"] = (
        "Bull Analyst: 5-day IV-up probability is high on event risk.\n"
        "Bear Analyst: 20-day and 40-day IV-down probability rises if realized volatility normalizes."
    )
    state["investment_debate_state"]["count"] = 2
    return state


def test_research_plan_can_carry_volatility_debate_summary_before_actions():
    plan = ResearchPlan(
        recommendation=PortfolioRating.OVERWEIGHT,
        rationale="Bull evidence is stronger but bear mean-reversion risk matters.",
        volatility_debate_summary="5-day IV up, 20-day balanced, 40-day IV down probability slightly higher.",
        strategic_actions="Trader must choose structures after stating the volatility view.",
    )

    rendered = render_research_plan(plan)

    assert "**Volatility Debate Summary**" in rendered
    assert rendered.index("**Volatility Debate Summary**") < rendered.index("**Strategic Actions**")


def test_options_research_manager_prompt_preserves_5_20_40_day_vol_debate_for_trader():
    captured: dict[str, object] = {}
    plan = ResearchPlan(
        recommendation=PortfolioRating.HOLD,
        rationale="Volatility paths are mixed.",
        volatility_debate_summary="5-day up probability; 20-day balanced; 40-day down probability.",
        strategic_actions="Wait for trader to map vol view to structures.",
    )
    structured = MagicMock()
    structured.invoke.side_effect = lambda prompt: captured.__setitem__("prompt", prompt) or plan
    llm = MagicMock()
    llm.with_structured_output.return_value = structured

    manager = create_research_manager(llm)
    result = manager(_research_manager_state("CU"))

    prompt = str(captured["prompt"]).lower()
    assert "5-day" in prompt and "20-day" in prompt and "40-day" in prompt
    assert "volatility debate summary" in prompt
    assert "trader" in prompt
    assert "**Volatility Debate Summary**" in result["investment_plan"]


def test_bull_and_bear_researchers_frame_options_debate_around_5_20_40_day_vol_probabilities():
    for factory, label in [(create_bull_researcher, "bull"), (create_bear_researcher, "bear")]:
        llm = CaptureLLM(f"{label} argument")
        node = factory(llm)
        result = node(_debate_state("CU"))

        assert result["investment_debate_state"]["current_response"].startswith(label.capitalize())
        prompt = str(llm.prompts[-1]).lower()
        assert "5-day" in prompt
        assert "20-day" in prompt
        assert "40-day" in prompt
        assert "probability" in prompt
        assert "implied volatility" in prompt
        assert "rise" in prompt and "fall" in prompt


def test_non_options_researcher_prompt_keeps_original_stock_framing():
    llm = CaptureLLM("stock bull")
    node = create_bull_researcher(llm)
    node(_debate_state("AAPL"))

    prompt = str(llm.prompts[-1]).lower()
    assert "5-day" not in prompt
    assert "20-day" not in prompt
    assert "40-day" not in prompt
    assert "implied volatility" not in prompt


def test_trader_proposal_renders_volatility_view_before_option_strategy():
    proposal = TraderProposal(
        action=TraderAction.BUY,
        reasoning="Event risk supports defined-risk long volatility.",
        volatility_view="5-day IV rise probability is higher; 20/40-day are mixed but skew supports upside vol.",
        option_strategy="Buy a near-month call spread or long strangle only if liquidity is sufficient.",
        position_sizing="Small premium budget; no naked short gamma.",
    )

    rendered = render_trader_proposal(proposal)

    assert "**Volatility View**" in rendered
    assert "**Option Strategy**" in rendered
    assert rendered.index("**Volatility View**") < rendered.index("**Option Strategy**")
    assert rendered.index("**Volatility View**") < rendered.index("**Reasoning**")


def test_options_trader_prompt_requires_view_before_strategy_and_uses_bull_bear_vol_debate():
    captured: dict[str, object] = {}
    proposal = TraderProposal(
        action=TraderAction.BUY,
        volatility_view="5-day IV up, 20-day balanced, 40-day down probability slightly higher.",
        option_strategy="Use a defined-risk calendar/vertical structure after confirming liquidity.",
        reasoning="Synthesizes bull and bear volatility debate before selecting structure.",
    )
    structured = MagicMock()
    structured.invoke.side_effect = lambda prompt: captured.__setitem__("prompt", prompt) or proposal
    llm = MagicMock()
    llm.with_structured_output.return_value = structured

    trader = create_trader(llm)
    result = trader(_trader_state("铜"))

    prompt_text = "\n".join(message["content"] for message in captured["prompt"])
    assert "first state your volatility view" in prompt_text.lower()
    assert "5-day" in prompt_text
    assert "20-day" in prompt_text
    assert "40-day" in prompt_text
    assert "bull" in prompt_text.lower() and "bear" in prompt_text.lower()
    plan = result["trader_investment_plan"]
    assert plan.index("**Volatility View**") < plan.index("**Option Strategy**")
