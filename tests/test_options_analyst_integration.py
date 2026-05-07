"""Tests for wiring SHFE options analytics into existing analyst nodes."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda


class SpyLLM:
    def __init__(self):
        self.bound_tool_names: list[str] = []
        self.prompt_messages: list[str] = []

    def bind_tools(self, tools):
        self.bound_tool_names = [tool.name for tool in tools]

        def _capture(prompt_value):
            messages = prompt_value.to_messages()
            self.prompt_messages = [getattr(message, "content", "") for message in messages]
            return AIMessage(content="done", tool_calls=[])

        return RunnableLambda(_capture)


def _state(symbol: str = "CU") -> dict:
    return {
        "company_of_interest": symbol,
        "trade_date": "2026-05-06",
        "messages": [HumanMessage(content=f"Analyze {symbol}")],
    }


def test_options_symbol_enables_options_tools_and_volatility_first_prompt_for_market_analyst():
    from tradingagents.agents.analysts.market_analyst import create_market_analyst

    llm = SpyLLM()
    node = create_market_analyst(llm)
    result = node(_state("CU"))

    assert result["market_report"] == "done"
    assert "get_option_trade_context" in llm.bound_tool_names
    assert "get_option_analytics_report" in llm.bound_tool_names
    prompt = "\n".join(llm.prompt_messages).lower()
    assert "volatility-first" in prompt
    assert "do not recalculate iv/greeks/gex/dex" in prompt
    assert "option close + futures close" in prompt


def test_non_options_symbol_keeps_stock_style_market_toolset():
    from tradingagents.agents.analysts.market_analyst import create_market_analyst

    llm = SpyLLM()
    node = create_market_analyst(llm)
    node(_state("AAPL"))

    assert "get_stock_data" in llm.bound_tool_names
    assert "get_indicators" in llm.bound_tool_names
    assert "get_option_trade_context" not in llm.bound_tool_names
    prompt = "\n".join(llm.prompt_messages).lower()
    assert "volatility-first" not in prompt


def test_fundamentals_and_news_analysts_receive_compact_options_context_tool():
    from tradingagents.agents.analysts.fundamentals_analyst import create_fundamentals_analyst
    from tradingagents.agents.analysts.news_analyst import create_news_analyst

    for factory, report_key, lens in [
        (create_fundamentals_analyst, "fundamentals_report", "inventory"),
        (create_news_analyst, "news_report", "event risks"),
    ]:
        llm = SpyLLM()
        node = factory(llm)
        result = node(_state("铜"))

        assert result[report_key] == "done"
        assert "get_option_trade_context" in llm.bound_tool_names
        prompt = "\n".join(llm.prompt_messages).lower()
        assert "volatility-first" in prompt
        assert lens in prompt


def test_trading_graph_tool_nodes_include_options_tools_for_analyst_tool_execution():
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    tool_nodes = graph._create_tool_nodes()

    for node_name in ["market", "news", "fundamentals"]:
        node = tool_nodes[node_name]
        available_tools = set(getattr(node, "tools_by_name", {}).keys())
        assert "get_option_trade_context" in available_tools

    assert "get_option_analytics_report" in getattr(tool_nodes["market"], "tools_by_name", {})
