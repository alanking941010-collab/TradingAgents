"""TradingAgents debate attachment helpers for options research packs.

The deterministic research pack remains the source of auditable option math. This
module optionally appends the full TradingAgents graph's qualitative debate
sections so final DOCX/Markdown reports can show analyst/research/trader/risk
and portfolio-manager reasoning without changing deterministic calculations.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterable
from typing import Any

AgentDebateProvider = Callable[[dict[str, Any]], dict[str, Any]]


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def extract_agent_debate_from_final_state(
    final_state: dict[str, Any],
    *,
    source: str = "tradingagents_graph",
    symbol: str | None = None,
    trade_date: str | None = None,
) -> dict[str, Any]:
    """Extract report-ready debate sections from a TradingAgents final state."""
    invest = final_state.get("investment_debate_state") or {}
    risk = final_state.get("risk_debate_state") or {}
    sections = [
        ("Market Analyst", final_state.get("market_report")),
        ("Sentiment Analyst", final_state.get("sentiment_report")),
        ("News Analyst", final_state.get("news_report")),
        ("Fundamentals Analyst", final_state.get("fundamentals_report")),
        ("Bull/Bear Research Debate", invest.get("history") or "\n".join(filter(None, [invest.get("bull_history"), invest.get("bear_history")]))),
        ("Research Manager", invest.get("judge_decision") or invest.get("current_response")),
        ("Trader", final_state.get("trader_investment_plan") or final_state.get("investment_plan")),
        ("Risk Debate", risk.get("history") or "\n".join(filter(None, [risk.get("aggressive_history"), risk.get("neutral_history"), risk.get("conservative_history")]))),
        ("Portfolio Manager", risk.get("judge_decision") or final_state.get("final_trade_decision")),
    ]
    rendered_sections = [
        {"title": title, "content": content}
        for title, content in ((title, _text(content)) for title, content in sections)
        if content
    ]
    return {
        "debate_type": "tradingagents_graph_debate",
        "source": source,
        "status": "success",
        "symbol": symbol or final_state.get("company_of_interest"),
        "trade_date": trade_date or final_state.get("trade_date"),
        "final_decision": _text(final_state.get("final_trade_decision")),
        "sections": rendered_sections,
    }


_SECTION_TITLE_ZH = {
    "Market Analyst": "市场分析师",
    "Sentiment Analyst": "情绪分析师",
    "News Analyst": "新闻分析师",
    "Fundamentals Analyst": "基本面分析师",
    "Bull/Bear Research Debate": "多空研究辩论",
    "Research Manager": "研究经理",
    "Trader": "交易员",
    "Risk Debate": "风险辩论",
    "Portfolio Manager": "组合经理",
    "Bull Researcher": "多头研究员",
    "Bear Researcher": "空头研究员",
    "Risk Manager": "风险经理",
}


def _section_title_zh(title: str) -> str:
    return _SECTION_TITLE_ZH.get(title, title)


def render_agent_debate_markdown(debate: dict[str, Any]) -> str:
    """Render a debate payload as a Chinese Markdown section for reports."""
    lines = [
        "## TradingAgents 多智能体辩论",
        f"- 辩论状态: {debate.get('status')}",
        f"- 来源: {debate.get('source')}",
        f"- 最终结论: {debate.get('final_decision')}",
        "- 说明：确定性期权 analytics 仍然是价格、风险预算、流动性和情景 PnL 的审计来源。",
        "",
    ]
    for section in debate.get("sections") or []:
        title = _text(section.get("title")) or "Agent Section"
        content = _text(section.get("content"))
        if not content:
            continue
        lines.extend([f"### {_section_title_zh(title)}", content, ""])
    return "\n".join(lines).strip() + "\n"


def append_agent_debate_to_research_pack(pack: dict[str, Any], debate: dict[str, Any] | None) -> dict[str, Any]:
    """Return a pack copy with an agent-debate section appended to Markdown/payload."""
    if not debate:
        return pack
    enriched = copy.deepcopy(pack)
    enriched["agent_debate"] = debate
    debate_markdown = render_agent_debate_markdown(debate)
    enriched["markdown"] = enriched.get("markdown", "").rstrip() + "\n\n---\n\n" + debate_markdown
    payload = ((enriched.get("payloads") or {}).get("feishu_delivery_payload") or {})
    if isinstance(payload, dict):
        if "message" in payload:
            payload["message"] = enriched["markdown"]
        if "content" in payload:
            payload["content"] = enriched["markdown"]
        payload["agent_debate_attached"] = True
    enriched.setdefault("assumptions", {})["agent_debate_attached"] = True
    return enriched


def load_agent_debate_json(path: str) -> AgentDebateProvider:
    """Return a provider that loads a precomputed debate JSON file for offline workflows/tests."""
    import json
    from pathlib import Path

    payload = json.loads(Path(path).read_text(encoding="utf-8"))

    def _provider(pack: dict[str, Any]) -> dict[str, Any]:
        debate = copy.deepcopy(payload)
        debate.setdefault("debate_type", "tradingagents_graph_debate")
        debate.setdefault("source", "json_file")
        debate.setdefault("status", "success")
        debate.setdefault("symbol", pack.get("product"))
        debate.setdefault("trade_date", pack.get("trade_date"))
        return debate

    return _provider


def build_live_agent_debate_provider(
    *,
    selected_analysts: Iterable[str] | None = None,
    config_overrides: dict[str, Any] | None = None,
) -> AgentDebateProvider:
    """Build a provider that runs the live TradingAgentsGraph for each pack.

    This is intentionally opt-in because it can call LLMs and external tools. Tests
    should use an injected provider or JSON file instead of live graph execution.
    """
    resolved_config_overrides = {"output_language": "Chinese"}
    if config_overrides:
        resolved_config_overrides.update(config_overrides)

    def _provider(pack: dict[str, Any]) -> dict[str, Any]:
        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        config = DEFAULT_CONFIG.copy()
        config.update(resolved_config_overrides)
        graph = TradingAgentsGraph(
            selected_analysts=list(selected_analysts or ["market", "news", "fundamentals"]),
            debug=False,
            config=config,
        )
        final_state, decision = graph.propagate(pack["product"], pack["trade_date"])
        debate = extract_agent_debate_from_final_state(
            final_state,
            source="tradingagents_graph_live",
            symbol=pack.get("product"),
            trade_date=pack.get("trade_date"),
        )
        debate["processed_signal"] = decision
        return debate

    return _provider
