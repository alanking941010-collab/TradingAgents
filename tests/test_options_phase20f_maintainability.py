"""Phase 20F tests for schema hardening, shared context caching, and CLI configurability."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


def test_core_options_payloads_validate_against_runtime_schemas(shfe_options_db):
    from tradingagents.options.research_pack import build_option_research_pack, build_option_research_pack_hermes_cron_spec
    from tradingagents.options.schemas import (
        validate_cron_handoff_spec,
        validate_research_pack,
        validate_selection_result,
        validate_strategy_candidate,
    )
    from tradingagents.options.selector import build_option_strategy_selection
    from tradingagents.options.strategies import build_option_strategy_candidate

    candidate = build_option_strategy_candidate("CU", "bull_call_spread", trade_date="2026-05-01", expiry="20260625")
    selection = build_option_strategy_selection("CU", trade_date="2026-05-01", expiry="20260625", strategy_types=("bull_call_spread",))
    pack = build_option_research_pack("CU", trade_date="2026-05-01", expiry="20260625", strategy_type="bull_call_spread")
    spec = build_option_research_pack_hermes_cron_spec(
        "CU",
        trade_date="2026-05-01",
        expiry="20260625",
        strategy_type="bull_call_spread",
        output_dir="/tmp/options-pack",
    )

    assert validate_strategy_candidate(candidate) is candidate
    assert validate_selection_result(selection) is selection
    assert validate_research_pack(pack) is pack
    assert validate_cron_handoff_spec(spec) is spec

    with pytest.raises(ValueError, match="StrategyCandidate missing required keys"):
        validate_strategy_candidate({"strategy_type": "bull_call_spread"})


def test_option_analysis_context_reuses_analysis_and_strategy_candidates(shfe_options_db):
    from tradingagents.options.context import OptionAnalysisContext
    from tradingagents.options.reports import build_option_strategy_report

    context = OptionAnalysisContext("CU", trade_date="2026-05-01", expiry="20260625")
    first = context.get_analysis()
    second = context.get_analysis()
    assert first is second

    report = build_option_strategy_report(
        "CU",
        strategy_type="bull_call_spread",
        trade_date="2026-05-01",
        expiry="20260625",
        analysis_context=context,
    )

    assert report["strategy_type"] == "bull_call_spread"
    stats = context.cache_stats()
    assert stats["analysis_misses"] == 1
    assert stats["analysis_hits"] >= 2
    assert stats["strategy_misses"] == 1
    assert stats["strategy_hits"] >= 1


def test_research_pack_cli_output_dir_is_env_configurable_and_subprocess_env_is_sanitized(shfe_options_db, tmp_path, monkeypatch):
    from scripts.options_cli_common import DEFAULT_OPTIONS_OUTPUT_ROOT, run_subprocess_checked, sanitized_subprocess_env

    output_root = tmp_path / "configured-root"
    monkeypatch.setenv("TRADINGAGENTS_OPTIONS_OUTPUT_ROOT", str(output_root))
    monkeypatch.setenv("KIMI_API_KEY", "secret-should-not-leak")

    env = sanitized_subprocess_env({"TRADINGAGENTS_SHFE_OPTIONS_DB": str(shfe_options_db)})
    assert env["TRADINGAGENTS_SHFE_OPTIONS_DB"] == str(shfe_options_db)
    assert "KIMI_API_KEY" not in env
    legacy_output_root = Path("/mnt") / "e" / "cautious_twinkle" / "outputs" / "tradingagents" / "options"
    assert DEFAULT_OPTIONS_OUTPUT_ROOT != legacy_output_root

    proc = run_subprocess_checked(
        [
            sys.executable,
            "scripts/build_option_research_pack.py",
            "CU",
            "--date",
            "2026-05-01",
            "--expiry",
            "20260625",
            "--strategy-type",
            "bull_call_spread",
            "--stdout",
            "summary-json",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env_extra={
            "TRADINGAGENTS_SHFE_OPTIONS_DB": str(shfe_options_db),
            "TRADINGAGENTS_OPTIONS_OUTPUT_ROOT": str(output_root),
        },
        timeout=30,
    )

    assert str(output_root) in proc.stdout
    assert list((output_root / "research_packs").glob("*_research_pack.json"))


def test_options_hardcoded_path_audit_documents_remaining_findings():
    audit = Path(__file__).resolve().parents[1] / "docs" / "options_hardcoded_paths_audit.md"
    assert audit.exists()
    text = audit.read_text(encoding="utf-8")
    assert "Phase 20F hardcoded path audit" in text
    assert "TRADINGAGENTS_OPTIONS_OUTPUT_ROOT" in text
    legacy_output_prefix = str(Path("/mnt") / "e" / "cautious_twinkle" / "outputs")
    assert legacy_output_prefix not in text
