"""Phase 22C Chinese report defaults for options research packs."""

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


def test_research_pack_markdown_defaults_to_chinese(shfe_options_db):
    _install_selector_fixture(shfe_options_db)

    from tradingagents.options.research_pack import build_option_research_pack

    pack = build_option_research_pack(
        "CU",
        trade_date="2026-05-01",
        expiry="20260625",
        directional_bias="neutral",
        volatility_view="range_bound_high_iv",
        risk_budget_cash=6000,
        constraint_mode="relaxed",
    )

    markdown = pack["markdown"]
    assert markdown.startswith("# 期权研究包")
    assert "## 执行摘要" in markdown
    assert "## 策略筛选" in markdown
    assert "## 入选策略报告" in markdown
    assert "## 研究包假设" in markdown
    assert "## TradingAgents Debate" not in markdown


def test_agent_debate_markdown_uses_chinese_shell_and_live_provider_defaults_to_chinese():
    from tradingagents.options.agent_debate import build_live_agent_debate_provider, render_agent_debate_markdown

    debate_markdown = render_agent_debate_markdown(
        {
            "status": "success",
            "source": "test",
            "final_decision": "观察",
            "sections": [{"title": "Portfolio Manager", "content": "最终建议保持观察。"}],
        }
    )

    assert debate_markdown.startswith("## TradingAgents 多智能体辩论")
    assert "- 辩论状态: success" in debate_markdown
    assert "### 组合经理" in debate_markdown

    provider = build_live_agent_debate_provider()
    closure_cells = provider.__closure__ or ()
    config_overrides = next(cell.cell_contents for cell in closure_cells if isinstance(cell.cell_contents, dict))
    assert config_overrides["output_language"] == "Chinese"


def test_daily_cli_writes_chinese_markdown_and_docx(tmp_path, shfe_options_db):
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
            "--risk-budget-cash",
            "6000",
            "--constraint-mode",
            "relaxed",
            "--output-dir",
            str(tmp_path),
            "--stdout",
            "summary-json",
        ],
        env_extra={"TRADINGAGENTS_SHFE_OPTIONS_DB": str(shfe_options_db)},
        timeout=30,
    )

    summary = json.loads(result.stdout)
    combined_markdown = (tmp_path / summary["output_markdown"]).read_text(encoding="utf-8")
    assert combined_markdown.startswith("# 每日期权研究包")
    assert "## 工作流摘要" in combined_markdown
    assert "## 分品种结果" in combined_markdown
    assert "# 期权研究包" in combined_markdown
    assert "每日期权研究包" in _docx_xml(tmp_path / summary["output_docx"])
