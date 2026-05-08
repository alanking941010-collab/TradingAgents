"""Phase 14A tests for real Feishu/Hermes delivery handoff and scheduling entrypoints."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_options_phase12_replay import _insert_review_day
from tests.test_options_phase5_strategy_structurer import shfe_options_db  # noqa: F401


def _build_delivery_payload(shfe_options_db):
    _insert_review_day(shfe_options_db)
    from tradingagents.options.reports import build_feishu_delivery_payload, build_option_strategy_report

    report = build_option_strategy_report(
        "CU",
        strategy_type="bull_call_spread",
        trade_date="2026-05-01",
        expiry="20260625",
        review_dates=["2026-05-06"],
        risk_budget_cash=10_000,
    )
    return build_feishu_delivery_payload(report, target="feishu:oc_test", dry_run=False)


def test_send_feishu_delivery_payload_invokes_injected_sender_for_live_delivery(shfe_options_db):
    payload = _build_delivery_payload(shfe_options_db)

    from tradingagents.options.delivery import send_feishu_delivery_payload

    calls: list[dict[str, str]] = []

    def fake_sender(*, target: str, message: str) -> dict[str, str]:
        calls.append({"target": target, "message": message})
        return {"message_id": "msg_test_001", "status": "ok"}

    result = send_feishu_delivery_payload(payload, sender=fake_sender)

    assert result["status"] == "sent"
    assert result["sent"] is True
    assert result["channel"] == "feishu"
    assert result["target"] == "feishu:oc_test"
    assert result["message_id"] == "msg_test_001"
    assert result["sender_response"] == {"message_id": "msg_test_001", "status": "ok"}
    assert calls == [{"target": "feishu:oc_test", "message": payload["message"]}]


def test_send_feishu_delivery_payload_requires_sender_when_not_dry_run(shfe_options_db):
    payload = _build_delivery_payload(shfe_options_db)

    from tradingagents.options.delivery import send_feishu_delivery_payload

    with pytest.raises(RuntimeError, match="sender callable is required"):
        send_feishu_delivery_payload(payload)


def test_schedule_payload_documents_no_agent_stdout_delivery_command(shfe_options_db):
    payload = _build_delivery_payload(shfe_options_db)

    from tradingagents.options.delivery import build_hermes_cron_delivery_spec

    spec = build_hermes_cron_delivery_spec(
        payload,
        script_path="scripts/deliver_option_strategy_report.py",
        schedule="0 8 * * 1-5",
    )

    assert spec["no_agent"] is True
    assert spec["deliver"] == "feishu:oc_test"
    assert spec["schedule"] == "0 8 * * 1-5"
    assert "--stdout message" in spec["command"]
    assert "Hermes no-agent cron delivers non-empty stdout" in spec["delivery_note"]


def test_option_hermes_cron_delivery_spec_tool_returns_parseable_json(shfe_options_db):
    _insert_review_day(shfe_options_db)

    from tradingagents.agents.utils.options_tools import get_option_hermes_cron_delivery_spec

    raw = get_option_hermes_cron_delivery_spec.invoke({
        "symbol": "CU",
        "strategy_type": "bull_call_spread",
        "trade_date": "2026-05-01",
        "expiry": "20260625",
        "review_dates": ["2026-05-06"],
        "risk_budget_cash": 10_000,
        "target": "feishu:oc_test",
        "schedule": "0 8 * * 1-5",
    })
    spec = json.loads(raw)

    assert spec["no_agent"] is True
    assert spec["deliver"] == "feishu:oc_test"
    assert spec["schedule"] == "0 8 * * 1-5"
    assert spec["payload_preview"]["title"].startswith("CU bull_call_spread")


def test_deliver_option_strategy_report_cli_prints_markdown_for_hermes_cron(shfe_options_db, tmp_path):
    _insert_review_day(shfe_options_db)
    env = {"TRADINGAGENTS_SHFE_OPTIONS_DB": str(shfe_options_db)}
    output_dir = tmp_path / "out"

    proc = subprocess.run(
        [
            sys.executable,
            "scripts/deliver_option_strategy_report.py",
            "CU",
            "--strategy-type",
            "bull_call_spread",
            "--date",
            "2026-05-01",
            "--expiry",
            "20260625",
            "--review-date",
            "2026-05-06",
            "--risk-budget-cash",
            "10000",
            "--target",
            "feishu:oc_test",
            "--output-dir",
            str(output_dir),
            "--stdout",
            "message",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=True,
    )

    assert proc.stdout.startswith("# CU bull_call_spread option strategy report")
    assert "## Historical Replay" in proc.stdout
    assert not proc.stdout.lstrip().startswith("{")

    payload_files = list(output_dir.glob("CU_2026-05-01_bull_call_spread_feishu_payload.json"))
    assert len(payload_files) == 1
    saved_payload = json.loads(payload_files[0].read_text(encoding="utf-8"))
    assert saved_payload["target"] == "feishu:oc_test"
    assert saved_payload["message"] == proc.stdout
    assert saved_payload["dry_run"] is False
