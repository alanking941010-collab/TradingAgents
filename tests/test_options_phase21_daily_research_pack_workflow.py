"""Phase 21 daily/batch research-pack workflow tests."""

from __future__ import annotations

import json
import sys

from scripts.options_cli_common import run_subprocess_checked
from tests.test_options_phase17_strategy_selector import _install_selector_fixture


def test_daily_research_pack_workflow_writes_combined_artifacts_and_markdown(tmp_path, shfe_options_db):
    _install_selector_fixture(shfe_options_db)

    from tradingagents.options.research_pack_workflow import build_daily_options_research_pack_workflow

    workflow = build_daily_options_research_pack_workflow(
        symbols=["CU"],
        trade_date="2026-05-01",
        expiry="20260625",
        directional_bias="neutral",
        volatility_view="range_bound_high_iv",
        risk_budget_cash=6_000,
        min_credit_pct_of_wing_width=0.20,
        max_bid_ask_spread_pct=0.50,
        output_dir=tmp_path,
        delivery_target="feishu:test-target",
    )

    assert workflow["workflow_type"] == "daily_options_research_pack"
    assert workflow["side_effect_free"] is True
    assert workflow["success_count"] == 1
    assert workflow["failure_count"] == 0
    assert workflow["symbols_requested"] == ["CU"]
    assert workflow["combined_markdown"].startswith("# 每日期权研究包")
    assert "CU" in workflow["combined_markdown"]

    run = workflow["runs"][0]
    assert run["symbol"] == "CU"
    assert run["status"] == "success"
    assert run["selected_strategy"]
    for key in ["output_pack", "output_markdown", "output_payload"]:
        assert run[key]
        assert (tmp_path / run[key]).exists()

    index_path = tmp_path / workflow["artifact_index"]
    combined_path = tmp_path / workflow["output_markdown"]
    assert index_path.exists()
    assert combined_path.exists()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index["success_count"] == 1
    assert index["runs"][0]["symbol"] == "CU"


def test_daily_research_pack_cli_prints_markdown_for_no_agent_handoff(tmp_path, shfe_options_db):
    _install_selector_fixture(shfe_options_db)

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
            "--directional-bias",
            "neutral",
            "--volatility-view",
            "range_bound_high_iv",
            "--risk-budget-cash",
            "6000",
            "--min-credit-pct-of-wing-width",
            "0.20",
            "--max-bid-ask-spread-pct",
            "0.50",
            "--target",
            "feishu:test-target",
            "--output-dir",
            str(tmp_path),
            "--stdout",
            "markdown",
        ],
        env_extra={"TRADINGAGENTS_SHFE_OPTIONS_DB": str(shfe_options_db)},
        timeout=30,
    )

    assert result.stdout.startswith("# 每日期权研究包")
    assert "CU" in result.stdout
    assert "全流程无副作用" in result.stdout
    assert list(tmp_path.glob("*_daily_research_pack_index.json"))
    assert list(tmp_path.glob("*_daily_research_pack.md"))


def test_daily_research_pack_cron_spec_is_side_effect_free_and_uses_batch_script(tmp_path):
    from tradingagents.options.research_pack_workflow import build_daily_options_research_pack_hermes_cron_spec

    spec = build_daily_options_research_pack_hermes_cron_spec(
        symbols=["CU", "AU"],
        trade_date=None,
        target="feishu:test-target",
        schedule="30 15 * * 1-5",
        output_dir=str(tmp_path),
    )

    assert spec["scheduler"] == "hermes_cron"
    assert spec["no_agent"] is True
    assert spec["side_effect_free"] is True
    assert spec["schedule"] == "30 15 * * 1-5"
    assert spec["deliver"] == "feishu:test-target"
    assert spec["script_path"] == "scripts/build_options_research_pack_daily.py"
    assert "--symbol CU" in spec["command"]
    assert "--symbol AU" in spec["command"]
    assert "--stdout markdown" in spec["command"]
    assert spec["payload_preview"]["symbols"] == ["CU", "AU"]
