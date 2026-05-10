"""Phase 19C tests for Hermes/Feishu research-pack handoff specs."""

from __future__ import annotations

import json
import sys

from scripts.options_cli_common import run_subprocess_checked
from tests.test_options_phase17_strategy_selector import _install_selector_fixture


def test_research_pack_hermes_cron_spec_describes_no_agent_markdown_delivery(shfe_options_db):
    _install_selector_fixture(shfe_options_db)

    from tradingagents.options.research_pack import build_option_research_pack_hermes_cron_spec

    spec = build_option_research_pack_hermes_cron_spec(
        "CU",
        trade_date="2026-05-01",
        expiry="20260625",
        directional_bias="neutral",
        volatility_view="range_bound_high_iv",
        risk_budget_cash=6_000,
        min_credit_pct_of_wing_width=0.20,
        max_bid_ask_spread_pct=0.50,
        target="feishu:oc_test",
        schedule="0 8 * * 1-5",
        output_dir="/tmp/research-packs",
    )

    assert spec["scheduler"] == "hermes_cron"
    assert spec["no_agent"] is True
    assert spec["deliver"] == "feishu:oc_test"
    assert spec["schedule"] == "0 8 * * 1-5"
    assert spec["stdout_mode"] == "markdown"
    assert spec["script_path"] == "scripts/build_option_research_pack.py"
    assert "scripts/build_option_research_pack.py" in spec["command"]
    assert "--stdout markdown" in spec["command"]
    assert "--target feishu:oc_test" in spec["command"]
    assert "--directional-bias neutral" in spec["command"]
    assert "--volatility-view range_bound_high_iv" in spec["command"]
    assert "--risk-budget-cash 6000" in spec["command"]
    assert spec["payload_preview"]["selected_strategy"]
    assert spec["payload_preview"]["message_length"] > 0
    assert spec["artifacts"]["output_dir"] == "/tmp/research-packs"
    assert "non-empty stdout" in spec["delivery_note"]


def test_research_pack_hermes_cron_spec_tool_returns_parseable_json(shfe_options_db):
    _install_selector_fixture(shfe_options_db)

    from tradingagents.agents.utils.options_tools import get_option_research_pack_hermes_cron_spec

    raw = get_option_research_pack_hermes_cron_spec.invoke({
        "symbol": "CU",
        "trade_date": "2026-05-01",
        "expiry": "20260625",
        "directional_bias": "neutral",
        "volatility_view": "range_bound_high_iv",
        "risk_budget_cash": 6_000,
        "target": "feishu:oc_test",
        "schedule": "0 8 * * 1-5",
    })
    spec = json.loads(raw)

    assert spec["no_agent"] is True
    assert spec["deliver"] == "feishu:oc_test"
    assert "--stdout markdown" in spec["command"]
    schema_text = str(get_option_research_pack_hermes_cron_spec.args_schema.model_fields)
    assert "schedule" in schema_text
    assert "target" in schema_text


def test_research_pack_cli_can_print_hermes_cron_spec(tmp_path, shfe_options_db):
    _install_selector_fixture(shfe_options_db)
    outdir = tmp_path / "packs"
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
            "--target",
            "feishu:oc_test",
            "--cron-schedule",
            "0 8 * * 1-5",
            "--output-dir",
            str(outdir),
            "--stdout",
            "hermes-cron-spec",
        ],
        env_extra={"TRADINGAGENTS_SHFE_OPTIONS_DB": str(shfe_options_db)},
        timeout=30,
    )

    spec = json.loads(result.stdout)
    assert spec["no_agent"] is True
    assert spec["deliver"] == "feishu:oc_test"
    assert spec["schedule"] == "0 8 * * 1-5"
    assert spec["stdout_mode"] == "markdown"
    assert "--output-dir" in spec["command"]
    assert str(outdir) in spec["command"]
    assert spec["payload_preview"]["selected_strategy"]
