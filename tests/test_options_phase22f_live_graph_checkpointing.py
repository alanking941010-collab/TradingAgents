"""Phase 22F live graph partial checkpoint tests."""

from __future__ import annotations

import time
from pathlib import Path


def _partial_then_slow_runner(
    *,
    pack: dict,
    config: dict,
    selected_analysts: list[str],
    checkpoint_dir: str | Path | None = None,
):
    from tradingagents.options.agent_debate import write_agent_debate_checkpoint

    write_agent_debate_checkpoint(
        checkpoint_dir,
        pack=pack,
        debate={
            "debate_type": "tradingagents_graph_debate",
            "source": "unit_test_partial",
            "status": "partial",
            "symbol": pack["product"],
            "trade_date": pack["trade_date"],
            "final_decision": "partial market analysis completed",
            "sections": [
                {
                    "title": "Market Analyst",
                    "content": "市场分析师已完成第一段 partial checkpoint。",
                }
            ],
        },
        progress_event={
            "event_index": 1,
            "elapsed_seconds": 1.25,
            "completed_sections": ["Market Analyst"],
            "tool_call_names": ["get_option_trade_context"],
        },
    )
    time.sleep(2)
    return {"final_state": {}, "decision": "unreachable"}


def test_timeout_debate_includes_latest_partial_checkpoint(tmp_path: Path):
    from tradingagents.options.agent_debate import build_live_agent_debate_provider

    provider = build_live_agent_debate_provider(
        selected_analysts=["market"],
        config_overrides={"llm_provider": "kimi-coding"},
        timeout_seconds=0.1,
        timeout_fallback=True,
        graph_runner=_partial_then_slow_runner,
        checkpoint_dir=tmp_path,
    )

    debate = provider({"product": "CU", "trade_date": "2026-05-08"})

    assert debate["status"] == "timeout"
    assert debate["partial_checkpoint"]["available"] is True
    assert debate["partial_checkpoint"]["completed_sections"] == ["Market Analyst"]
    assert any(section["title"] == "Market Analyst" for section in debate["sections"])
    assert "partial checkpoint" in debate["sections"][-1]["content"]
    assert (tmp_path / "CU_2026-05-08_agent_debate_checkpoint.json").exists()
    assert (tmp_path / "CU_2026-05-08_agent_debate_events.jsonl").exists()


def test_default_graph_runner_writes_stream_checkpoints_with_injected_graph(tmp_path: Path):
    from tradingagents.options.agent_debate import _run_streaming_graph_with_checkpoints

    chunks = [
        {"market_report": "市场报告完成", "messages": []},
        {
            "market_report": "市场报告完成",
            "investment_debate_state": {"history": "多空辩论完成", "judge_decision": "研究经理结论"},
            "final_trade_decision": "组合经理结论",
            "messages": [],
        },
    ]

    result = _run_streaming_graph_with_checkpoints(
        stream_iterable=chunks,
        pack={"product": "CU", "trade_date": "2026-05-08"},
        checkpoint_dir=tmp_path,
        process_signal=lambda decision: f"processed:{decision}",
    )

    assert result["decision"] == "processed:组合经理结论"
    checkpoint = tmp_path / "CU_2026-05-08_agent_debate_checkpoint.json"
    assert checkpoint.exists()
    assert "多空辩论完成" in checkpoint.read_text(encoding="utf-8")
