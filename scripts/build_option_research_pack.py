#!/usr/bin/env python3
"""Build a unified SHFE option research pack and local artifacts.

The script is side-effect-free: it writes JSON/Markdown artifacts and can print
Markdown for downstream Hermes delivery, but it never sends a message or order.
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

from tradingagents.options.research_pack import (  # noqa: E402
    build_option_research_pack,
    build_option_research_pack_hermes_cron_spec,
)

DEFAULT_OUTPUT_DIR = Path("/mnt/e/cautious_twinkle/outputs/tradingagents/options/research_packs")


def _safe_part(value: Any) -> str:
    if value is None:
        return "latest"
    return "".join(ch for ch in str(value) if ch.isalnum() or ch in ("-", "_")) or "latest"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build one side-effect-free SHFE option research pack with JSON, Markdown, and Feishu payload artifacts."
    )
    parser.add_argument("symbol", help="SHFE option product or alias, e.g. CU, copper, 铜, AU")
    parser.add_argument("--date", dest="trade_date", help="Trade date, e.g. 2026-05-01")
    parser.add_argument("--expiry", help="Optional maturity date, e.g. 20260625")
    parser.add_argument("--strategy-type", default=None, help="Optional explicit strategy override; omit for selector auto-pick")
    parser.add_argument("--directional-bias", default="neutral", help="Selector directional bias: bullish, bearish, neutral/range")
    parser.add_argument("--volatility-view", default=None, help="Volatility regime view, e.g. range_bound_high_iv, moderate_iv")
    parser.add_argument(
        "--review-date",
        dest="review_dates",
        action="append",
        default=None,
        help="Replay review date; repeat for multiple dates.",
    )
    parser.add_argument("--risk-budget-cash", type=float, default=None, help="Optional CNY risk budget")
    parser.add_argument(
        "--min-credit-pct-of-wing-width",
        type=float,
        default=None,
        help="Optional credit-quality filter for short iron condor",
    )
    parser.add_argument(
        "--max-bid-ask-spread-pct",
        type=float,
        default=None,
        help="Optional bid/ask quality filter",
    )
    parser.add_argument("--target", dest="delivery_target", default="feishu", help="Dry-run Feishu/Hermes target label")
    parser.add_argument("--cron-schedule", default="0 8 * * 1-5", help="Schedule used when printing a Hermes no-agent cron spec")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument(
        "--stdout",
        choices=["summary-json", "markdown", "hermes-cron-spec", "none"],
        default="summary-json",
        help="Print JSON summary, research-pack Markdown, Hermes cron spec, or nothing. Files are always written.",
    )
    return parser


def _artifact_paths(output_dir: Path, pack: dict[str, Any]) -> tuple[Path, Path, Path]:
    stem = f"{_safe_part(pack['product'])}_{_safe_part(pack['trade_date'])}_{_safe_part(pack['selected_strategy'] if pack.get('selection_mode') == 'explicit_strategy_override' else pack.get('selection_mode'))}"
    return (
        output_dir / f"{stem}_research_pack.json",
        output_dir / f"{stem}_research_pack.md",
        output_dir / f"{stem}_feishu_payload.json",
    )


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    pack = build_option_research_pack(
        args.symbol,
        trade_date=args.trade_date,
        expiry=args.expiry,
        strategy_type=args.strategy_type,
        directional_bias=args.directional_bias,
        volatility_view=args.volatility_view,
        review_dates=args.review_dates,
        risk_budget_cash=args.risk_budget_cash,
        min_credit_pct_of_wing_width=args.min_credit_pct_of_wing_width,
        max_bid_ask_spread_pct=args.max_bid_ask_spread_pct,
        delivery_target=args.delivery_target,
    )

    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    pack_path, markdown_path, payload_path = _artifact_paths(output_dir, pack)

    payload = pack["payloads"]["feishu_delivery_payload"]
    pack_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    markdown_path.write_text(pack["markdown"], encoding="utf-8")
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    summary = {
        "product": pack["product"],
        "trade_date": pack["trade_date"],
        "expiry": pack.get("expiry"),
        "selection_mode": pack["selection_mode"],
        "selected_strategy": pack["selected_strategy"],
        "risk_budget_cash": pack["summary"].get("risk_budget_cash"),
        "replay_max_drawdown_cash": pack["summary"].get("replay_max_drawdown_cash"),
        "replay_win_rate": pack["summary"].get("replay_win_rate"),
        "target": payload["target"],
        "dry_run": payload["dry_run"],
        "stdout_mode": args.stdout,
        "output_pack": str(pack_path),
        "output_markdown": str(markdown_path),
        "output_payload": str(payload_path),
        "side_effect_free_note": "This script writes artifacts only; it does not send Feishu messages or orders.",
    }

    if args.stdout == "summary-json":
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    elif args.stdout == "markdown":
        print(pack["markdown"], end="")
    elif args.stdout == "hermes-cron-spec":
        spec = build_option_research_pack_hermes_cron_spec(
            args.symbol,
            trade_date=args.trade_date,
            expiry=args.expiry,
            strategy_type=args.strategy_type,
            directional_bias=args.directional_bias,
            volatility_view=args.volatility_view,
            review_dates=args.review_dates,
            risk_budget_cash=args.risk_budget_cash,
            min_credit_pct_of_wing_width=args.min_credit_pct_of_wing_width,
            max_bid_ask_spread_pct=args.max_bid_ask_spread_pct,
            target=args.delivery_target,
            schedule=args.cron_schedule,
            output_dir=str(output_dir),
        )
        spec["current_run_artifacts"] = {
            "output_pack": str(pack_path),
            "output_markdown": str(markdown_path),
            "output_payload": str(payload_path),
        }
        print(json.dumps(spec, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
