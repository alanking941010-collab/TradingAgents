"""TradingAgents debate attachment helpers for options research packs.

The deterministic research pack remains the source of auditable option math. This
module optionally appends the full TradingAgents graph's qualitative debate
sections so final DOCX/Markdown reports can show analyst/research/trader/risk
and portfolio-manager reasoning without changing deterministic calculations.
"""

from __future__ import annotations

import copy
import inspect
import json
import multiprocessing as mp
import queue
import re
import signal
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path
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
    partial_checkpoint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sections = [
        {
            "title": section_title,
            "content": section_content,
        }
    ]
    if partial_checkpoint and partial_checkpoint.get("available"):
        sections.extend(partial_checkpoint.get("sections") or [])
    payload = {
        "debate_type": "tradingagents_graph_debate",
        "source": source,
        "status": status,
        "symbol": symbol,
        "trade_date": trade_date,
        "final_decision": final_decision,
        "sections": sections,
    }
    if partial_checkpoint is not None:
        payload["partial_checkpoint"] = partial_checkpoint
    return payload


def _safe_component(value: Any) -> str:
    text = _text(value) or "unknown"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_") or "unknown"


def _checkpoint_paths(checkpoint_dir: str | Path | None, *, symbol: str | None, trade_date: str | None) -> tuple[Path, Path] | None:
    if checkpoint_dir is None:
        return None
    directory = Path(checkpoint_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"{_safe_component(symbol)}_{_safe_component(trade_date)}_agent_debate"
    return directory / f"{stem}_checkpoint.json", directory / f"{stem}_events.jsonl"


def _completed_sections(debate: dict[str, Any]) -> list[str]:
    return [_text(section.get("title")) for section in debate.get("sections") or [] if _text(section.get("title"))]


_REQUIRED_CHECKPOINT_SECTIONS = (
    "Market Analyst",
    "Bull/Bear Research Debate",
    "Research Manager",
    "Trader",
    "Risk Debate",
    "Portfolio Manager",
)


def _checkpoint_completion_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Return whether a partial checkpoint is complete enough for reports."""
    completed = set(payload.get("completed_sections") or _completed_sections(payload))
    missing = [title for title in _REQUIRED_CHECKPOINT_SECTIONS if title not in completed]
    final_decision = _text(payload.get("final_decision"))
    if not final_decision:
        for section in payload.get("sections") or []:
            if section.get("title") == "Portfolio Manager":
                final_decision = _text(section.get("content"))
                break
    return {
        "complete": not missing and bool(final_decision),
        "required_sections": list(_REQUIRED_CHECKPOINT_SECTIONS),
        "missing_required_sections": missing,
        "checkpoint_final_decision": final_decision,
    }


def _checkpoint_complete_debate(*, partial_checkpoint: dict[str, Any], symbol: str | None, trade_date: str | None) -> dict[str, Any]:
    """Promote a timed-out worker's complete checkpoint to a reportable result."""
    final_decision = _text(partial_checkpoint.get("checkpoint_final_decision") or partial_checkpoint.get("final_decision"))
    note = (
        "Live graph worker reached the timeout boundary after checkpointing all required "
        "TradingAgents sections. The graph finalization/return path did not complete in time, "
        "so this report uses the latest complete checkpoint instead of labeling the debate as a pure timeout."
    )
    return {
        "debate_type": "tradingagents_graph_debate",
        "source": "tradingagents_graph_live_checkpoint_complete",
        "status": "checkpoint_complete",
        "symbol": symbol,
        "trade_date": trade_date,
        "final_decision": final_decision,
        "sections": [{"title": "Live Graph Checkpoint Complete", "content": note}] + list(partial_checkpoint.get("sections") or []),
        "partial_checkpoint": partial_checkpoint,
    }


def write_agent_debate_checkpoint(
    checkpoint_dir: str | Path | None,
    *,
    pack: dict[str, Any],
    debate: dict[str, Any],
    progress_event: dict[str, Any] | None = None,
) -> Path | None:
    """Persist latest partial live-graph debate state for timeout diagnostics."""
    paths = _checkpoint_paths(checkpoint_dir, symbol=pack.get("product"), trade_date=pack.get("trade_date"))
    if paths is None:
        return None
    checkpoint_path, events_path = paths
    event = {
        "event_index": None,
        "elapsed_seconds": None,
        "completed_sections": _completed_sections(debate),
    }
    if progress_event:
        event.update(progress_event)
    payload = copy.deepcopy(debate)
    payload.setdefault("status", "partial")
    payload.setdefault("source", "tradingagents_graph_live_partial")
    payload.setdefault("symbol", pack.get("product"))
    payload.setdefault("trade_date", pack.get("trade_date"))
    payload["checkpoint_path"] = str(checkpoint_path)
    payload["events_path"] = str(events_path)
    payload["last_progress_event"] = event
    payload["completed_sections"] = _completed_sections(payload)
    checkpoint_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    with events_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    return checkpoint_path


def load_agent_debate_checkpoint(
    checkpoint_dir: str | Path | None,
    *,
    symbol: str | None,
    trade_date: str | None,
) -> dict[str, Any]:
    paths = _checkpoint_paths(checkpoint_dir, symbol=symbol, trade_date=trade_date)
    if paths is None:
        return {"available": False}
    checkpoint_path, events_path = paths
    if not checkpoint_path.exists():
        return {"available": False, "checkpoint_path": str(checkpoint_path)}
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    event_count = 0
    if events_path.exists():
        event_count = sum(1 for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip())
    completion = _checkpoint_completion_fields(payload)
    return {
        "available": True,
        "checkpoint_path": str(checkpoint_path),
        "events_path": str(events_path),
        "event_count": event_count,
        "status": payload.get("status"),
        "source": payload.get("source"),
        "final_decision": payload.get("final_decision"),
        "sections": payload.get("sections") or [],
        "completed_sections": payload.get("completed_sections") or _completed_sections(payload),
        "last_progress_event": payload.get("last_progress_event"),
        **completion,
    }


def _progress_event_from_state(state: dict[str, Any], *, event_index: int, elapsed_seconds: float, previous_elapsed: float) -> dict[str, Any]:
    messages = state.get("messages") or []
    msg = messages[-1] if messages else None
    tool_calls = getattr(msg, "tool_calls", None) if msg is not None else None
    content = getattr(msg, "content", "") if msg is not None else ""
    debate = extract_agent_debate_from_final_state(state, source="tradingagents_graph_live_partial")
    return {
        "event_index": event_index,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "delta_seconds": round(elapsed_seconds - previous_elapsed, 3),
        "completed_sections": _completed_sections(debate),
        "tool_call_names": [tc.get("name") for tc in (tool_calls or [])],
        "message_type": type(msg).__name__ if msg is not None else None,
        "message_content_length": len(str(content or "")),
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


def _run_streaming_graph_with_checkpoints(
    *,
    stream_iterable,
    pack: dict[str, Any],
    checkpoint_dir: str | Path | None,
    process_signal: Callable[[str], Any],
) -> dict[str, Any]:
    """Consume a LangGraph stream, checkpoint partial debate state, and return final state."""
    final_state: dict[str, Any] | None = None
    started = time.monotonic()
    previous_elapsed = 0.0
    for event_index, state in enumerate(stream_iterable, start=1):
        final_state = state
        elapsed = time.monotonic() - started
        debate = extract_agent_debate_from_final_state(
            state,
            source="tradingagents_graph_live_partial",
            symbol=pack.get("product"),
            trade_date=pack.get("trade_date"),
        )
        debate["status"] = "partial"
        progress_event = _progress_event_from_state(
            state,
            event_index=event_index,
            elapsed_seconds=elapsed,
            previous_elapsed=previous_elapsed,
        )
        write_agent_debate_checkpoint(
            checkpoint_dir,
            pack=pack,
            debate=debate,
            progress_event=progress_event,
        )
        previous_elapsed = elapsed
    if final_state is None:
        raise RuntimeError("TradingAgentsGraph stream produced no states")
    decision_text = _text(final_state.get("final_trade_decision"))
    return {"final_state": final_state, "decision": process_signal(decision_text)}


def _runner_accepts_checkpoint_dir(runner: GraphRunner) -> bool:
    signature = inspect.signature(runner)
    return "checkpoint_dir" in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


def _call_graph_runner(
    runner: GraphRunner,
    *,
    pack: dict[str, Any],
    config: dict[str, Any],
    selected_analysts: list[str],
    checkpoint_dir: str | Path | None,
) -> dict[str, Any]:
    kwargs = {
        "pack": pack,
        "config": config,
        "selected_analysts": selected_analysts,
    }
    if _runner_accepts_checkpoint_dir(runner):
        kwargs["checkpoint_dir"] = checkpoint_dir
    return runner(**kwargs)


def _default_graph_runner(
    *,
    pack: dict[str, Any],
    config: dict[str, Any],
    selected_analysts: list[str],
    checkpoint_dir: str | Path | None = None,
) -> dict[str, Any]:
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = TradingAgentsGraph(
        selected_analysts=selected_analysts,
        debug=False,
        config=config,
    )
    if checkpoint_dir is None:
        final_state, decision = graph.propagate(pack["product"], pack["trade_date"])
        return {"final_state": final_state, "decision": decision}

    past_context = graph.memory_log.get_past_context(pack["product"])
    init_state = graph.propagator.create_initial_state(
        pack["product"],
        pack["trade_date"],
        past_context=past_context,
    )
    args = graph.propagator.get_graph_args()
    result = _run_streaming_graph_with_checkpoints(
        stream_iterable=graph.graph.stream(init_state, **args),
        pack=pack,
        checkpoint_dir=checkpoint_dir,
        process_signal=graph.process_signal,
    )
    graph.curr_state = result["final_state"]
    return result


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
    checkpoint_dir: str | Path | None = None,
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
            return _call_graph_runner(
                resolved_runner,
                pack=pack,
                config=config,
                selected_analysts=resolved_analysts,
                checkpoint_dir=checkpoint_dir,
            )

        try:
            if timeout_fallback and timeout_seconds and graph_runner is None:
                result = _run_in_subprocess_with_timeout(_run, timeout_seconds)
            else:
                result = _run_with_timeout(_run, timeout_seconds)
        except AgentDebateTimeoutError as exc:
            if not timeout_fallback:
                raise
            partial_checkpoint = load_agent_debate_checkpoint(
                checkpoint_dir,
                symbol=pack.get("product"),
                trade_date=pack.get("trade_date"),
            )
            if partial_checkpoint.get("complete"):
                return _checkpoint_complete_debate(
                    partial_checkpoint=partial_checkpoint,
                    symbol=pack.get("product"),
                    trade_date=pack.get("trade_date"),
                )
            partial_note = ""
            if partial_checkpoint.get("available"):
                partial_note = (
                    "\n\n已载入最近一次 partial checkpoint："
                    f"{partial_checkpoint.get('checkpoint_path')}，"
                    f"已完成 sections={partial_checkpoint.get('completed_sections')}。"
                )
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
                    f"{partial_note}"
                ),
                partial_checkpoint=partial_checkpoint,
            )
        except Exception as exc:
            if not timeout_fallback:
                raise
            partial_checkpoint = load_agent_debate_checkpoint(
                checkpoint_dir,
                symbol=pack.get("product"),
                trade_date=pack.get("trade_date"),
            )
            if partial_checkpoint.get("complete"):
                return _checkpoint_complete_debate(
                    partial_checkpoint=partial_checkpoint,
                    symbol=pack.get("product"),
                    trade_date=pack.get("trade_date"),
                )
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
                partial_checkpoint=partial_checkpoint,
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
