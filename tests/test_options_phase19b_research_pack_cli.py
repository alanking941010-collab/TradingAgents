"""Phase 19B CLI tests for building options research pack artifacts."""

from __future__ import annotations

import json
import os
import subprocess
import sys

from tests.test_options_phase12_replay import _insert_review_day
from tests.test_options_phase17_strategy_selector import _install_selector_fixture
from tests.test_options_phase18b_replay_performance import _insert_second_review_day


def test_research_pack_cli_writes_json_markdown_payload_and_summary(tmp_path, shfe_options_db):
    _install_selector_fixture(shfe_options_db)
    outdir = tmp_path / "research_pack"
    env = os.environ.copy()
    env["TRADINGAGENTS_SHFE_OPTIONS_DB"] = str(shfe_options_db)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_option_research_pack.py",
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
            "--output-dir",
            str(outdir),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    summary = json.loads(result.stdout)
    assert summary["product"] == "CU"
    assert summary["trade_date"] == "2026-05-01"
    assert summary["selection_mode"] == "selector_auto"
    assert summary["selected_strategy"]
    assert summary["dry_run"] is True

    pack_path = outdir / "CU_2026-05-01_selector_auto_research_pack.json"
    markdown_path = outdir / "CU_2026-05-01_selector_auto_research_pack.md"
    payload_path = outdir / "CU_2026-05-01_selector_auto_feishu_payload.json"
    assert summary["output_pack"] == str(pack_path)
    assert summary["output_markdown"] == str(markdown_path)
    assert summary["output_payload"] == str(payload_path)
    assert pack_path.exists()
    assert markdown_path.exists()
    assert payload_path.exists()

    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    assert pack["pack_type"] == "shfe_option_research_pack"
    assert pack["payloads"]["feishu_delivery_payload"]["dry_run"] is True
    assert payload["dry_run"] is True
    assert "Options Research Pack" in markdown_path.read_text(encoding="utf-8")


def test_research_pack_cli_can_print_markdown_for_explicit_replay_pack(tmp_path, shfe_options_db):
    _insert_review_day(shfe_options_db)
    _insert_second_review_day(shfe_options_db)
    outdir = tmp_path / "explicit_pack"
    env = os.environ.copy()
    env["TRADINGAGENTS_SHFE_OPTIONS_DB"] = str(shfe_options_db)

    result = subprocess.run(
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
            "--directional-bias",
            "bullish",
            "--volatility-view",
            "moderate_iv",
            "--review-date",
            "2026-05-01",
            "--review-date",
            "2026-05-06",
            "--review-date",
            "2026-05-11",
            "--risk-budget-cash",
            "10000",
            "--output-dir",
            str(outdir),
            "--stdout",
            "markdown",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.stdout.startswith("# Options Research Pack")
    assert "bull_call_spread" in result.stdout
    assert "Replay Performance Distribution" in result.stdout
    pack_path = outdir / "CU_2026-05-01_bull_call_spread_research_pack.json"
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    assert pack["selection_mode"] == "explicit_strategy_override"
    assert pack["summary"]["replay_max_drawdown_cash"] == 1750
