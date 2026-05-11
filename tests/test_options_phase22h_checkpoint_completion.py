"""Phase 22H checkpoint-complete timeout recovery tests."""

from __future__ import annotations

import time
from pathlib import Path

_COMPLETE_SECTION_TITLES = [
    "Market Analyst",
    "Bull/Bear Research Debate",
    "Research Manager",
    "Trader",
    "Risk Debate",
    "Portfolio Manager",
]


def _complete_checkpoint_then_slow_runner(
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
            "source": "unit_test_complete_checkpoint",
            "status": "partial",
            "symbol": pack["product"],
            "trade_date": pack["trade_date"],
            "final_decision": "组合经理最终建议：观望，等待波动率回落后再评估。",
            "sections": [
                {"title": title, "content": f"{title} 已完成。"}
                for title in _COMPLETE_SECTION_TITLES
            ],
        },
        progress_event={
            "event_index": 9,
            "elapsed_seconds": 256.0,
            "completed_sections": _COMPLETE_SECTION_TITLES,
            "tool_call_names": [],
        },
    )
    time.sleep(2)
    return {"final_state": {}, "decision": "unreachable"}


def _incomplete_checkpoint_then_slow_runner(
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
            "source": "unit_test_partial_checkpoint",
            "status": "partial",
            "symbol": pack["product"],
            "trade_date": pack["trade_date"],
            "final_decision": "只完成市场分析。",
            "sections": [{"title": "Market Analyst", "content": "市场分析师已完成。"}],
        },
        progress_event={"event_index": 1, "completed_sections": ["Market Analyst"]},
    )
    time.sleep(2)
    return {"final_state": {}, "decision": "unreachable"}


def test_timeout_with_complete_checkpoint_promotes_to_checkpoint_complete(tmp_path: Path):
    from tradingagents.options.agent_debate import build_live_agent_debate_provider

    provider = build_live_agent_debate_provider(
        selected_analysts=["market"],
        config_overrides={"llm_provider": "kimi-coding"},
        timeout_seconds=0.1,
        timeout_fallback=True,
        graph_runner=_complete_checkpoint_then_slow_runner,
        checkpoint_dir=tmp_path,
    )

    debate = provider({"product": "CU", "trade_date": "2026-05-08"})

    assert debate["status"] == "checkpoint_complete"
    assert debate["source"] == "tradingagents_graph_live_checkpoint_complete"
    assert debate["final_decision"] == "组合经理最终建议：观望，等待波动率回落后再评估。"
    assert debate["partial_checkpoint"]["available"] is True
    assert debate["partial_checkpoint"]["complete"] is True
    assert debate["partial_checkpoint"]["missing_required_sections"] == []
    assert [section["title"] for section in debate["sections"] if section["title"] in _COMPLETE_SECTION_TITLES] == _COMPLETE_SECTION_TITLES
    assert "checkpoint" in debate["sections"][0]["content"].lower()


def test_timeout_with_incomplete_checkpoint_stays_timeout(tmp_path: Path):
    from tradingagents.options.agent_debate import build_live_agent_debate_provider

    provider = build_live_agent_debate_provider(
        selected_analysts=["market"],
        config_overrides={"llm_provider": "kimi-coding"},
        timeout_seconds=0.1,
        timeout_fallback=True,
        graph_runner=_incomplete_checkpoint_then_slow_runner,
        checkpoint_dir=tmp_path,
    )

    debate = provider({"product": "CU", "trade_date": "2026-05-08"})

    assert debate["status"] == "timeout"
    assert debate["partial_checkpoint"]["available"] is True
    assert debate["partial_checkpoint"]["complete"] is False
    assert "Portfolio Manager" in debate["partial_checkpoint"]["missing_required_sections"]
