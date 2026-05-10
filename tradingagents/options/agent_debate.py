"""TradingAgents debate attachment helpers for options research packs.

The deterministic research pack remains the source of auditable option math. This
module optionally appends the full TradingAgents graph's qualitative debate
sections so final DOCX/Markdown reports can show analyst/research/trader/risk
and portfolio-manager reasoning without changing deterministic calculations.
"""

from __future__ import annotations

import copy
import multiprocessing as mp
import queue
import signal
import threading
from collections.abc import Callable, Iterable
from typing import Any

AgentDebateProvider = Callable[[dict[str, Any]], dict[str, Any]]
GraphRunner = Callable[..., dict[str, Any]]


class AgentDebateTimeoutError(TimeoutError):
    """Raised when live TradingAgentsGraph debate exceeds its safe-mode budget."""


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _timeout_message(timeout_seconds: float | int | None) -> str:
    seconds = "unknown" if timeout_seconds is None else f"{float(timeout_seconds):g}s"
    return (
        f"TradingAgents full graph live debate 超时（timeout={seconds}）。"
        "已保留确定性期权研究包；本节不是交易指令，建议后续使用 graph-live-safe checkpoint 模式重跑。"
    )


def _failure_debate(
    *,
    status: str,
    source: str,
    symbol: str | None,
    trade_date: str | None,
    final_decision: str,
    section_title: str,
    section_content: str,
) -> dict[str, Any]:
    return {
        "debate_type": "tradingagents_graph_debate",
        "source": source,
        "status": status,
        "symbol": symbol,
        "trade_date": trade_date,
        "final_decision": final_decision,
        "sections": [
            {
                "title": section_title,
                "content": section_content,
            }
        ],
    }


def _run_with_timeout(fn: Callable[[], Any], timeout_seconds: float | int | None) -> Any:
    """Run ``fn`` with a best-effort wall-clock timeout on Unix main threads."""
    if timeout_seconds is None or timeout_seconds <= 0:
        return fn()
    if threading.current_thread() is not threading.main_thread():
        return fn()

    def _handle_timeout(signum, frame):  # noqa: ARG001
        raise AgentDebateTimeoutError(_timeout_message(timeout_seconds))

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, float(timeout_seconds))
    signal.signal(signal.SIGALRM, _handle_timeout)
    try:
        return fn()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)


def _subprocess_target(result_queue, fn: Callable[[], Any]) -> None:
    try:
        result_queue.put({"ok": True, "result": fn()})
    except BaseException as exc:  # noqa: BLE001
        result_queue.put(
            {
                "ok": False,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }
        )


def _run_in_subprocess_with_timeout(fn: Callable[[], Any], timeout_seconds: float | int | None) -> Any:
    """Run ``fn`` in an isolated process and terminate it on timeout."""
    if timeout_seconds is None or timeout_seconds <= 0:
        return fn()
    ctx = mp.get_context("fork")
    result_queue = ctx.Queue(maxsize=1)
    process = ctx.Process(target=_subprocess_target, args=(result_queue, fn))
    process.start()
    process.join(float(timeout_seconds))
    if process.is_alive():
        process.terminate()
        process.join(2)
        if process.is_alive():
            process.kill()
            process.join(2)
        raise AgentDebateTimeoutError(_timeout_message(timeout_seconds))
    try:
        payload = result_queue.get_nowait()
    except queue.Empty as exc:
        raise RuntimeError("live graph worker exited without returning a result") from exc
    if payload.get("ok"):
        return payload.get("result")
    raise RuntimeError(f"{payload.get('error_type')}: {payload.get('error_message')}")


def _default_graph_runner(
    *,
    pack: dict[str, Any],
    config: dict[str, Any],
    selected_analysts: list[str],
) -> dict[str, Any]:
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = TradingAgentsGraph(
        selected_analysts=selected_analysts,
        debug=False,
        config=config,
    )
    final_state, decision = graph.propagate(pack["product"], pack["trade_date"])
    return {"final_state": final_state, "decision": decision}


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
    timeout_seconds: float | int | None = None,
    timeout_fallback: bool = False,
    graph_runner: GraphRunner | None = None,
) -> AgentDebateProvider:
    """Build a provider that runs the live TradingAgentsGraph for each pack.

    This is intentionally opt-in because it can call LLMs and external tools. Tests
    should use an injected provider or JSON file instead of live graph execution.
    When ``timeout_fallback`` is true, live graph timeout/errors return a reportable
    debate payload so deterministic research-pack artifacts can still be written.
    """
    resolved_config_overrides = {"output_language": "Chinese"}
    if config_overrides:
        resolved_config_overrides.update(config_overrides)
    resolved_analysts = list(selected_analysts or ["market", "news", "fundamentals"])
    resolved_runner = graph_runner or _default_graph_runner

    def _provider(pack: dict[str, Any]) -> dict[str, Any]:
        from tradingagents.default_config import DEFAULT_CONFIG

        config = DEFAULT_CONFIG.copy()
        config.update(resolved_config_overrides)

        def _run() -> dict[str, Any]:
            return resolved_runner(
                pack=pack,
                config=config,
                selected_analysts=resolved_analysts,
            )

        try:
            if timeout_fallback and timeout_seconds and graph_runner is None:
                result = _run_in_subprocess_with_timeout(_run, timeout_seconds)
            else:
                result = _run_with_timeout(_run, timeout_seconds)
        except AgentDebateTimeoutError as exc:
            if not timeout_fallback:
                raise
            return _failure_debate(
                status="timeout",
                source="tradingagents_graph_live_timeout",
                symbol=pack.get("product"),
                trade_date=pack.get("trade_date"),
                final_decision=str(exc),
                section_title="Live Graph Timeout",
                section_content=(
                    f"{exc}\n\n"
                    "根因：完整 TradingAgentsGraph 是同步执行的多节点 LLM/tool 图；"
                    "如果某个节点或工具调用超过预算，原始 graph.invoke 不会先落盘中间产物。"
                ),
            )
        except Exception as exc:
            if not timeout_fallback:
                raise
            message = (
                f"TradingAgents full graph live debate 失败：{type(exc).__name__}: {exc}. "
                "已保留确定性期权研究包；本节不是交易指令。"
            )
            return _failure_debate(
                status="failed",
                source="tradingagents_graph_live_failed",
                symbol=pack.get("product"),
                trade_date=pack.get("trade_date"),
                final_decision=message,
                section_title="Live Graph Failure",
                section_content=message,
            )

        final_state = result["final_state"]
        decision = result.get("decision")
        debate = extract_agent_debate_from_final_state(
            final_state,
            source="tradingagents_graph_live",
            symbol=pack.get("product"),
            trade_date=pack.get("trade_date"),
        )
        debate["processed_signal"] = decision
        return debate

    return _provider
