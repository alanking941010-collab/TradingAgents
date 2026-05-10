#!/usr/bin/env python3
"""Build a SHFE option strategy report for Feishu/Hermes delivery.

The script is designed for Hermes no-agent cron jobs: when `--stdout message` is
used, stdout contains only the Markdown report. Hermes can then deliver that
stdout directly to the configured Feishu target.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.options_cli_common import resolve_output_dir  # noqa: E402
from tradingagents.options.reports import build_feishu_delivery_payload, build_option_strategy_report  # noqa: E402


def _safe_part(value: Any) -> str:
    if value is None:
        return "latest"
    return "".join(ch for ch in str(value) if ch.isalnum() or ch in ("-", "_")) or "latest"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an SHFE option strategy Markdown report and Feishu delivery payload."
    )
    parser.add_argument("symbol", help="SHFE option product or alias, e.g. CU, copper, 铜, AU")
    parser.add_argument("--strategy-type", required=True, help="Strategy type, e.g. bull_call_spread")
    parser.add_argument("--date", dest="trade_date", help="Entry/trade date, e.g. 2026-05-01")
    parser.add_argument("--expiry", help="Optional maturity date, e.g. 20260625")
    parser.add_argument(
        "--review-date",
        dest="review_dates",
        action="append",
        default=None,
        help="Replay review date; repeat for multiple dates.",
    )
    parser.add_argument("--risk-budget-cash", type=float, default=None)
    parser.add_argument("--target", default="feishu", help="Hermes/Feishu target, e.g. feishu:oc_xxx")
    parser.add_argument("--output-dir", default=None, help="Artifact directory; defaults to TRADINGAGENTS_OPTIONS_REPORTS_OUTPUT_DIR or TRADINGAGENTS_OPTIONS_OUTPUT_ROOT/reports")
    parser.add_argument("--dry-run", action="store_true", help="Mark the payload as dry-run rather than cron-deliverable.")
    parser.add_argument(
        "--stdout",
        choices=["message", "summary-json", "none"],
        default="summary-json",
        help="Print Markdown message for Hermes cron, a JSON summary, or nothing.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report = build_option_strategy_report(
        args.symbol,
        strategy_type=args.strategy_type,
        trade_date=args.trade_date,
        expiry=args.expiry,
        review_dates=args.review_dates,
        risk_budget_cash=args.risk_budget_cash,
    )
    payload = build_feishu_delivery_payload(report, target=args.target, dry_run=args.dry_run)

    output_dir = resolve_output_dir(args.output_dir, kind="reports")
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{_safe_part(report['product'])}_{_safe_part(report['trade_date'])}_{_safe_part(report['strategy_type'])}"
    report_path = output_dir / f"{stem}_report.json"
    payload_path = output_dir / f"{stem}_feishu_payload.json"
    markdown_path = output_dir / f"{stem}_report.md"

    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    markdown_path.write_text(report["markdown"], encoding="utf-8")

    summary = {
        "product": report["product"],
        "strategy_type": report["strategy_type"],
        "trade_date": report["trade_date"],
        "target": payload["target"],
        "dry_run": payload["dry_run"],
        "stdout_mode": args.stdout,
        "output_report": str(report_path),
        "output_markdown": str(markdown_path),
        "output_payload": str(payload_path),
        "hermes_no_agent_delivery_note": "Use --stdout message in a Hermes no-agent cron job so non-empty stdout is delivered to the configured Feishu target.",
    }

    if args.stdout == "message":
        print(payload["message"], end="")
    elif args.stdout == "summary-json":
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
