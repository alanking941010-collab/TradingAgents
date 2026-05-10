#!/usr/bin/env python3
"""Build daily/batch SHFE options research packs for Hermes handoff.

The script is side-effect-free: it writes local artifacts and can print combined
Markdown for Hermes no-agent cron delivery, but it never sends messages or orders.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.options_cli_common import resolve_output_dir  # noqa: E402
from tradingagents.options.agent_debate import build_live_agent_debate_provider, load_agent_debate_json  # noqa: E402
from tradingagents.options.research_pack_workflow import (  # noqa: E402
    DEFAULT_DAILY_CRON_SCHEDULE,
    DEFAULT_DAILY_SYMBOLS,
    build_daily_options_research_pack_hermes_cron_spec,
    build_daily_options_research_pack_workflow,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build side-effect-free daily/batch SHFE option research packs with combined Markdown handoff."
    )
    parser.add_argument(
        "--symbol",
        dest="symbols",
        action="append",
        default=None,
        help="SHFE option product or alias. Repeat for multiple symbols. Defaults to CU/AU/AG/AL.",
    )
    parser.add_argument("--date", dest="trade_date", help="Trade date, e.g. 2026-05-01; omit for latest")
    parser.add_argument("--expiry", help="Optional maturity date, e.g. 20260625")
    parser.add_argument("--strategy-type", default=None, help="Optional explicit strategy override for every symbol")
    parser.add_argument("--directional-bias", default="neutral", help="Selector directional bias")
    parser.add_argument("--volatility-view", default=None, help="Volatility regime view, e.g. range_bound_high_iv")
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
    parser.add_argument(
        "--constraint-mode",
        choices=["strict", "relaxed"],
        default="relaxed",
        help="Selector constraint handling. relaxed keeps liquidity/risk-budget failures as review candidates with warnings.",
    )
    parser.add_argument("--target", dest="delivery_target", default="feishu", help="Hermes delivery target label")
    parser.add_argument(
        "--cron-schedule",
        default=DEFAULT_DAILY_CRON_SCHEDULE,
        help="Schedule used when printing a Hermes no-agent cron spec",
    )
    parser.add_argument(
        "--agent-debate-json",
        default=None,
        help="Optional precomputed TradingAgents debate JSON to append to each pack without live LLM calls.",
    )
    parser.add_argument(
        "--with-agent-debate",
        action="store_true",
        help="Run the live TradingAgentsGraph for each successful pack and append debate sections. This can call LLMs.",
    )
    parser.add_argument(
        "--agent-llm-provider",
        default=None,
        help="Optional provider for --with-agent-debate, e.g. kimi-coding. Defaults to project config.",
    )
    parser.add_argument(
        "--agent-deep-model",
        default=None,
        help="Optional deep_think_llm model for --with-agent-debate.",
    )
    parser.add_argument(
        "--agent-quick-model",
        default=None,
        help="Optional quick_think_llm model for --with-agent-debate.",
    )
    parser.add_argument(
        "--agent-backend-url",
        default=None,
        help="Optional backend_url for --with-agent-debate provider routing.",
    )
    parser.add_argument(
        "--agent-analyst",
        dest="agent_analysts",
        action="append",
        default=None,
        choices=["market", "social", "news", "fundamentals"],
        help="Analyst to include in live --with-agent-debate; repeatable. Defaults to market/news/fundamentals.",
    )
    parser.add_argument(
        "--agent-debate-mode",
        choices=["graph-live", "graph-live-safe"],
        default="graph-live-safe",
        help="Live graph mode. graph-live-safe returns a timeout/failure debate so deterministic artifacts are still written.",
    )
    parser.add_argument(
        "--agent-debate-timeout-seconds",
        type=float,
        default=300,
        help="Wall-clock timeout for --agent-debate-mode graph-live-safe.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Artifact directory; defaults to TRADINGAGENTS_OPTIONS_RESEARCH_PACKS_OUTPUT_DIR or TRADINGAGENTS_OPTIONS_OUTPUT_ROOT/research_packs",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Abort on the first symbol failure instead of recording it and continuing.",
    )
    parser.add_argument(
        "--stdout",
        choices=["summary-json", "markdown", "hermes-cron-spec", "none"],
        default="summary-json",
        help="Print JSON summary, combined Markdown, Hermes cron spec, or nothing.",
    )
    return parser


def _agent_debate_config_overrides(args: argparse.Namespace) -> dict:
    """Build TradingAgentsGraph config overrides for live agent debate."""
    overrides = {"output_language": "Chinese"}
    if args.agent_llm_provider:
        overrides["llm_provider"] = args.agent_llm_provider
        if args.agent_llm_provider == "kimi-coding":
            overrides["deep_think_llm"] = "kimi-k2.6"
            overrides["quick_think_llm"] = "kimi-k2.6"
    if args.agent_deep_model:
        overrides["deep_think_llm"] = args.agent_deep_model
    if args.agent_quick_model:
        overrides["quick_think_llm"] = args.agent_quick_model
    if args.agent_backend_url:
        overrides["backend_url"] = args.agent_backend_url
    return overrides


def _summary(workflow: dict) -> dict:
    return {
        "workflow_type": workflow["workflow_type"],
        "symbols_requested": workflow["symbols_requested"],
        "trade_date": workflow.get("trade_date"),
        "success_count": workflow["success_count"],
        "failure_count": workflow["failure_count"],
        "target": workflow.get("target"),
        "constraint_mode": workflow.get("constraint_mode"),
        "agent_debate_enabled": workflow.get("agent_debate_enabled"),
        "stdout_mode": "summary-json",
        "output_dir": workflow["output_dir"],
        "output_markdown": workflow["output_markdown"],
        "output_docx": workflow["output_docx"],
        "artifact_index": workflow["artifact_index"],
        "runs": workflow["runs"],
        "side_effect_free_note": "This script writes artifacts and prints stdout only; it does not send Feishu messages or orders.",
    }


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    symbols = args.symbols or list(DEFAULT_DAILY_SYMBOLS)
    output_dir = resolve_output_dir(args.output_dir, kind="research_packs")

    if args.stdout == "hermes-cron-spec":
        spec = build_daily_options_research_pack_hermes_cron_spec(
            symbols=symbols,
            trade_date=args.trade_date,
            expiry=args.expiry,
            strategy_type=args.strategy_type,
            directional_bias=args.directional_bias,
            volatility_view=args.volatility_view,
            review_dates=args.review_dates,
            risk_budget_cash=args.risk_budget_cash,
            min_credit_pct_of_wing_width=args.min_credit_pct_of_wing_width,
            max_bid_ask_spread_pct=args.max_bid_ask_spread_pct,
            constraint_mode=args.constraint_mode,
            target=args.delivery_target,
            schedule=args.cron_schedule,
            output_dir=str(output_dir),
        )
        print(json.dumps(spec, ensure_ascii=False, indent=2, default=str))
        return 0

    if args.agent_debate_json and args.with_agent_debate:
        raise ValueError("Use either --agent-debate-json or --with-agent-debate, not both")
    agent_debate_provider = None
    if args.agent_debate_json:
        agent_debate_provider = load_agent_debate_json(args.agent_debate_json)
    elif args.with_agent_debate:
        agent_debate_provider = build_live_agent_debate_provider(
            selected_analysts=args.agent_analysts,
            config_overrides=_agent_debate_config_overrides(args),
            timeout_seconds=(
                args.agent_debate_timeout_seconds
                if args.agent_debate_mode == "graph-live-safe"
                else None
            ),
            timeout_fallback=args.agent_debate_mode == "graph-live-safe",
            checkpoint_dir=output_dir / "agent_debate_checkpoints",
        )

    workflow = build_daily_options_research_pack_workflow(
        symbols=symbols,
        trade_date=args.trade_date,
        expiry=args.expiry,
        strategy_type=args.strategy_type,
        directional_bias=args.directional_bias,
        volatility_view=args.volatility_view,
        review_dates=args.review_dates,
        risk_budget_cash=args.risk_budget_cash,
        min_credit_pct_of_wing_width=args.min_credit_pct_of_wing_width,
        max_bid_ask_spread_pct=args.max_bid_ask_spread_pct,
        constraint_mode=args.constraint_mode,
        delivery_target=args.delivery_target,
        output_dir=output_dir,
        continue_on_error=not args.fail_fast,
        agent_debate_provider=agent_debate_provider,
    )

    if args.stdout == "summary-json":
        print(json.dumps(_summary(workflow), ensure_ascii=False, indent=2, default=str))
    elif args.stdout == "markdown":
        print(workflow["combined_markdown"], end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
