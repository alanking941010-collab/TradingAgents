"""Phase 22A DOCX report export tests."""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

from scripts.options_cli_common import run_subprocess_checked
from tests.test_options_phase17_strategy_selector import _install_selector_fixture


def _docx_text(path: Path) -> str:
    assert path.exists()
    assert zipfile.is_zipfile(path)
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    return xml


def test_daily_workflow_writes_combined_and_per_symbol_docx(tmp_path, shfe_options_db):
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

    combined_docx = tmp_path / workflow["output_docx"]
    combined_xml = _docx_text(combined_docx)
    assert "Daily Options Research Pack" in combined_xml
    assert "short_iron_condor" in combined_xml

    run = workflow["runs"][0]
    symbol_docx = tmp_path / run["output_docx"]
    symbol_xml = _docx_text(symbol_docx)
    assert "Options Research Pack" in symbol_xml
    assert "CU 2026-05-01" in symbol_xml
    assert "short_iron_condor" in symbol_xml

    index = json.loads((tmp_path / workflow["artifact_index"]).read_text(encoding="utf-8"))
    assert index["output_docx"] == workflow["output_docx"]
    assert index["runs"][0]["output_docx"] == run["output_docx"]


def test_daily_cli_summary_json_reports_docx_artifacts(tmp_path, shfe_options_db):
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
            "--output-dir",
            str(tmp_path),
            "--stdout",
            "summary-json",
        ],
        env_extra={"TRADINGAGENTS_SHFE_OPTIONS_DB": str(shfe_options_db)},
        timeout=30,
    )

    summary = json.loads(result.stdout)
    assert summary["output_docx"].endswith("_daily_research_pack.docx")
    assert (tmp_path / summary["output_docx"]).exists()
    assert summary["runs"][0]["output_docx"].endswith("_research_pack.docx")
    assert (tmp_path / summary["runs"][0]["output_docx"]).exists()


def test_single_research_pack_cli_writes_docx_artifact(tmp_path, shfe_options_db):
    _install_selector_fixture(shfe_options_db)

    result = run_subprocess_checked(
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
            "--output-dir",
            str(tmp_path),
            "--stdout",
            "summary-json",
        ],
        env_extra={"TRADINGAGENTS_SHFE_OPTIONS_DB": str(shfe_options_db)},
        timeout=30,
    )

    summary = json.loads(result.stdout)
    assert summary["output_docx"].endswith("_research_pack.docx")
    docx_path = Path(summary["output_docx"])
    xml = _docx_text(docx_path)
    assert "Options Research Pack" in xml
    assert "short_iron_condor" in xml
