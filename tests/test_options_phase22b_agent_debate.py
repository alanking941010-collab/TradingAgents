"""Phase 22B agent-debate integration and relaxed selector tests."""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

from scripts.options_cli_common import run_subprocess_checked
from tests.test_options_phase17_strategy_selector import _install_selector_fixture


def _docx_xml(path: Path) -> str:
    assert path.exists()
    assert zipfile.is_zipfile(path)
    with zipfile.ZipFile(path) as zf:
        return zf.read("word/document.xml").decode("utf-8")


def _fake_agent_debate(pack: dict) -> dict:
    return {
        "debate_type": "tradingagents_graph_debate",
        "source": "test_double",
        "status": "success",
        "symbol": pack["product"],
        "trade_date": pack["trade_date"],
        "final_decision": "WATCH — wait for better liquidity but keep short_iron_condor candidate.",
        "sections": [
            {"title": "Market Analyst", "content": "Copper options surface is range-bound with elevated IV."},
            {"title": "Bull Researcher", "content": "Bull case: tight inventories support upside tails."},
            {"title": "Bear Researcher", "content": "Bear case: macro softness caps rallies."},
            {"title": "Risk Manager", "content": "Relaxed constraints keep the trade for review; do not treat as executable."},
            {"title": "组合经理", "content": "Final stance is watch, not automatic execution."},
        ],
    }


def test_relaxed_selector_keeps_risk_budget_failures_as_review_candidates(shfe_options_db):
    _install_selector_fixture(shfe_options_db)

    from tradingagents.options.selector import build_option_strategy_selection

    strict = build_option_strategy_selection(
        "CU",
        trade_date="2026-05-01",
        expiry="20260625",
        directional_bias="neutral",
        volatility_view="range_bound_high_iv",
        risk_budget_cash=100,
        constraint_mode="strict",
    )
    relaxed = build_option_strategy_selection(
        "CU",
        trade_date="2026-05-01",
        expiry="20260625",
        directional_bias="neutral",
        volatility_view="range_bound_high_iv",
        risk_budget_cash=100,
        constraint_mode="relaxed",
    )

    strict_row = next(row for row in strict["ranked_candidates"] if row["strategy_type"] == "short_iron_condor")
    relaxed_row = next(row for row in relaxed["ranked_candidates"] if row["strategy_type"] == "short_iron_condor")
    assert strict_row["risk_budget_status"] == "fail"
    assert strict_row["decision"] == "no_trade"
    assert relaxed_row["risk_budget_status"] == "fail"
    assert relaxed_row["decision"] != "no_trade"
    assert relaxed["assumptions"]["selector_constraint_mode"] == "relaxed"
    assert any("relaxed" in reason.lower() for reason in relaxed_row["ranking_reasons"])


def test_daily_workflow_appends_agent_debate_to_markdown_docx_and_index(tmp_path, shfe_options_db):
    _install_selector_fixture(shfe_options_db)

    from tradingagents.options.research_pack_workflow import build_daily_options_research_pack_workflow

    workflow = build_daily_options_research_pack_workflow(
        symbols=["CU"],
        trade_date="2026-05-01",
        expiry="20260625",
        directional_bias="neutral",
        volatility_view="range_bound_high_iv",
        risk_budget_cash=100,
        constraint_mode="relaxed",
        output_dir=tmp_path,
        agent_debate_provider=_fake_agent_debate,
    )

    assert workflow["agent_debate_enabled"] is True
    assert workflow["runs"][0]["agent_debate_status"] == "success"
    assert "TradingAgents 多智能体辩论" in workflow["combined_markdown"]
    assert "组合经理" in workflow["combined_markdown"]
    assert "Relaxed constraints" in workflow["combined_markdown"]

    pack = json.loads((tmp_path / workflow["runs"][0]["output_pack"]).read_text(encoding="utf-8"))
    assert pack["agent_debate"]["status"] == "success"
    assert "TradingAgents 多智能体辩论" in pack["markdown"]

    symbol_docx = tmp_path / workflow["runs"][0]["output_docx"]
    combined_docx = tmp_path / workflow["output_docx"]
    assert "TradingAgents 多智能体辩论" in _docx_xml(symbol_docx)
    assert "TradingAgents 多智能体辩论" in _docx_xml(combined_docx)

    index = json.loads((tmp_path / workflow["artifact_index"]).read_text(encoding="utf-8"))
    assert index["agent_debate_enabled"] is True
    assert index["runs"][0]["agent_debate_status"] == "success"


def test_daily_cli_live_agent_debate_defaults_to_safe_timeout_mode():
    from scripts.build_options_research_pack_daily import build_arg_parser

    args = build_arg_parser().parse_args([
        "--with-agent-debate",
        "--agent-llm-provider",
        "kimi-coding",
    ])

    assert args.agent_debate_mode == "graph-live-safe"
    assert args.agent_debate_timeout_seconds == 300


def test_daily_cli_agent_debate_config_overrides_support_kimi_coding():
    from scripts.build_options_research_pack_daily import _agent_debate_config_overrides, build_arg_parser

    args = build_arg_parser().parse_args([
        "--with-agent-debate",
        "--agent-llm-provider",
        "kimi-coding",
    ])

    overrides = _agent_debate_config_overrides(args)

    assert overrides["llm_provider"] == "kimi-coding"
    assert overrides["deep_think_llm"] == "kimi-k2.6"
    assert overrides["quick_think_llm"] == "kimi-k2.6"
    assert overrides["output_language"] == "Chinese"
    assert "backend_url" not in overrides


def test_single_cli_agent_debate_config_overrides_support_explicit_models():
    from scripts.build_option_research_pack import _agent_debate_config_overrides, build_arg_parser

    args = build_arg_parser().parse_args([
        "CU",
        "--with-agent-debate",
        "--agent-llm-provider",
        "kimi-coding",
        "--agent-deep-model",
        "kimi-for-coding",
        "--agent-quick-model",
        "kimi-k2.6",
        "--agent-backend-url",
        "https://proxy.example.com/coding",
    ])

    overrides = _agent_debate_config_overrides(args)

    assert overrides == {
        "output_language": "Chinese",
        "llm_provider": "kimi-coding",
        "deep_think_llm": "kimi-for-coding",
        "quick_think_llm": "kimi-k2.6",
        "backend_url": "https://proxy.example.com/coding",
    }


def test_daily_cli_can_append_precomputed_agent_debate_json(tmp_path, shfe_options_db):
    _install_selector_fixture(shfe_options_db)
    debate_path = tmp_path / "debate.json"
    debate_path.write_text(json.dumps(_fake_agent_debate({"product": "CU", "trade_date": "2026-05-01"})), encoding="utf-8")

    result = run_subprocess_checked(
        [
            sys.executable,
            "scripts/build_options_research_pack_daily.py",
            "--symbol",
            "CU",
            "--date",
            "2026-05-01",
            "--expiry",
            "20260625",
            "--risk-budget-cash",
            "100",
            "--constraint-mode",
            "relaxed",
            "--agent-debate-json",
            str(debate_path),
            "--output-dir",
            str(tmp_path),
            "--stdout",
            "summary-json",
        ],
        env_extra={"TRADINGAGENTS_SHFE_OPTIONS_DB": str(shfe_options_db)},
        timeout=30,
    )

    summary = json.loads(result.stdout)
    assert summary["constraint_mode"] == "relaxed"
    assert summary["agent_debate_enabled"] is True
    assert summary["runs"][0]["agent_debate_status"] == "success"
    assert "TradingAgents 多智能体辩论" in (tmp_path / summary["output_markdown"]).read_text(encoding="utf-8")
    assert "TradingAgents 多智能体辩论" in _docx_xml(tmp_path / summary["output_docx"])
