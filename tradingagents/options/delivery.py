"""Feishu/Hermes delivery helpers for option strategy reports.

This module is the Phase 14A bridge from Phase 13's side-effect-free payloads
to explicit delivery actions.  It keeps the default code path safe by requiring
an injected sender for live sends, while also documenting the Hermes no-agent
cron pattern: a script prints the Markdown report to stdout and Hermes delivers
that stdout to the configured Feishu target.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Sender = Callable[..., dict[str, Any] | str | None]


def _extract_message_id(response: dict[str, Any] | str | None) -> str | None:
    if isinstance(response, dict):
        for key in ("message_id", "id", "messageId", "msg_id"):
            value = response.get(key)
            if value:
                return str(value)
    if isinstance(response, str) and response:
        return response
    return None


def send_feishu_delivery_payload(
    payload: dict[str, Any],
    *,
    sender: Sender | None = None,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    """Send a Feishu delivery payload through an explicit sender callable.

    The callable must accept keyword arguments ``target`` and ``message``.  This
    keeps TradingAgents independent from a specific Feishu SDK, webhook, or
    Hermes runtime while still providing a real, testable live-send boundary.
    """
    should_dry_run = bool(payload.get("dry_run", True)) if dry_run is None else bool(dry_run)
    target = str(payload.get("target") or "feishu")
    message = str(payload.get("message") or "")
    if not message:
        raise ValueError("payload message is required for Feishu delivery")

    if should_dry_run:
        return {
            "status": "dry_run",
            "sent": False,
            "channel": "feishu",
            "target": target,
            "title": payload.get("title"),
            "message_length": len(message),
            "side_effect_free": True,
        }

    if sender is None:
        raise RuntimeError(
            "A sender callable is required for live Feishu delivery. "
            "Pass a Hermes/Gateway adapter or schedule the CLI in a Hermes no-agent cron job."
        )

    response = sender(target=target, message=message)
    return {
        "status": "sent",
        "sent": True,
        "channel": "feishu",
        "target": target,
        "title": payload.get("title"),
        "message_length": len(message),
        "message_id": _extract_message_id(response),
        "sender_response": response,
        "side_effect_free": False,
    }


def build_hermes_cron_delivery_spec(
    payload: dict[str, Any],
    *,
    script_path: str = "scripts/deliver_option_strategy_report.py",
    schedule: str = "0 8 * * 1-5",
) -> dict[str, Any]:
    """Describe how Hermes no-agent cron can deliver this payload's stdout.

    The concrete script arguments still need symbol/date/strategy parameters;
    this spec records the invariant delivery side: use no-agent mode and print
    the Markdown message to stdout so Hermes delivers it to ``payload['target']``.
    """
    target = str(payload.get("target") or "feishu")
    return {
        "scheduler": "hermes_cron",
        "no_agent": True,
        "schedule": schedule,
        "deliver": target,
        "script_path": script_path,
        "command": f"{script_path} ... --target {target} --stdout message",
        "stdout_mode": "message",
        "delivery_note": "Hermes no-agent cron delivers non-empty stdout to the configured Feishu target; empty stdout is silent.",
    }
