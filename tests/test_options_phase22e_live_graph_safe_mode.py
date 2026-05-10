"""Phase 22E live graph safe-mode timeout tests."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tests.test_options_phase17_strategy_selector import _install_selector_fixture


def _slow_graph_runner(*, pack: dict, config: dict, selected_analysts: list[str]):
    time.sleep(2)
    return {"final_state": {}, "decision": "unreachable"}


def _slow_subprocess_value():
    time.sleep(2)
    return {"ok": False}


def test_subprocess_timeout_terminates_hung_live_graph_worker():
    from tradingagents.options.agent_debate import AgentDebateTimeoutError, _run_in_subprocess_with_timeout

    with pytest.raises(AgentDebateTimeoutError):
        _run_in_subprocess_with_timeout(_slow_subprocess_value, timeout_seconds=0.1)


def test_live_agent_debate_provider_returns_timeout_debate_in_safe_mode():
    from tradingagents.options.agent_debate import build_live_agent_debate_provider

    provider = build_live_agent_debate_provider(
        selected_analysts=["market"],
        config_overrides={"llm_provider": "kimi-coding"},
        timeout_seconds=0.1,
        timeout_fallback=True,
        graph_runner=_slow_graph_runner,
    )

    debate = provider({"product": "CU", "trade_date": "2026-05-01"})

    assert debate["status"] == "timeout"
    assert debate["source"] == "tradingagents_graph_live_timeout"
    assert debate["symbol"] == "CU"
    assert debate["trade_date"] == "2026-05-01"
    assert "超时" in debate["final_decision"]
    assert debate["sections"][0]["title"] == "Live Graph Timeout"


def test_daily_workflow_writes_artifacts_when_live_debate_times_out(tmp_path: Path, shfe_options_db):
    _install_selector_fixture(shfe_options_db)

    from tradingagents.options.agent_debate import build_live_agent_debate_provider
    from tradingagents.options.research_pack_workflow import build_daily_options_research_pack_workflow

    provider = build_live_agent_debate_provider(
        selected_analysts=["market"],
        config_overrides={"llm_provider": "kimi-coding"},
        timeout_seconds=0.1,
        timeout_fallback=True,
        graph_runner=_slow_graph_runner,
    )

    workflow = build_daily_options_research_pack_workflow(
        symbols=["CU"],
        trade_date="2026-05-01",
        expiry="20260625",
        directional_bias="neutral",
        volatility_view="range_bound_high_iv",
        risk_budget_cash=6000,
        constraint_mode="relaxed",
        output_dir=tmp_path,
        agent_debate_provider=provider,
    )

    assert workflow["success_count"] == 1
    run = workflow["runs"][0]
    assert run["status"] == "success"
    assert run["agent_debate_status"] == "timeout"
    assert (tmp_path / run["output_pack"]).exists()
    assert (tmp_path / run["output_markdown"]).exists()
    assert (tmp_path / run["output_docx"]).exists()
    assert (tmp_path / workflow["artifact_index"]).exists()

    pack = json.loads((tmp_path / run["output_pack"]).read_text(encoding="utf-8"))
    assert pack["agent_debate"]["status"] == "timeout"
    assert "TradingAgents 多智能体辩论" in pack["markdown"]
    assert "超时" in pack["markdown"]
