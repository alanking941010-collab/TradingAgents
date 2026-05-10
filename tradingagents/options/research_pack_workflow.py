"""Daily/batch options research-pack workflow orchestration.

This module builds multiple side-effect-free SHFE options research packs, writes
per-symbol artifacts plus a combined Markdown handoff, and can describe the
Hermes no-agent cron command that would deliver non-empty stdout.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from tradingagents.options.research_pack import build_option_research_pack

DEFAULT_DAILY_SYMBOLS = ("CU", "AU", "AG", "AL")
DEFAULT_DAILY_CRON_SCHEDULE = "30 15 * * 1-5"
DEFAULT_DAILY_SCRIPT_PATH = "scripts/build_options_research_pack_daily.py"


def _safe_part(value: Any) -> str:
    if value is None:
        return "latest"
    return "".join(ch for ch in str(value) if ch.isalnum() or ch in ("-", "_")) or "latest"


def _fmt_cli_value(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _append_option(args: list[str], flag: str, value: Any) -> None:
    if value is None:
        return
    args.extend([flag, _fmt_cli_value(value)])


def _command_string(args: list[str]) -> str:
    return " ".join(shlex.quote(str(arg)) for arg in args)


def _artifact_paths(output_dir: Path, pack: dict[str, Any]) -> tuple[Path, Path, Path]:
    stem = (
        f"{_safe_part(pack['product'])}_"
        f"{_safe_part(pack['trade_date'])}_"
        f"{_safe_part(pack['selected_strategy'] if pack.get('selection_mode') == 'explicit_strategy_override' else pack.get('selection_mode'))}"
    )
    return (
        output_dir / f"{stem}_research_pack.json",
        output_dir / f"{stem}_research_pack.md",
        output_dir / f"{stem}_feishu_payload.json",
    )


def _daily_stem(trade_date: str | None, symbols: list[str]) -> str:
    symbol_part = "_".join(_safe_part(symbol) for symbol in symbols) or "symbols"
    return f"{_safe_part(trade_date)}_{symbol_part}"


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _render_combined_markdown(workflow: dict[str, Any], pack_markdowns: list[str]) -> str:
    lines = [
        f"# Daily Options Research Pack — {_safe_part(workflow.get('trade_date'))}",
        "",
        "## Workflow Summary",
        f"- Symbols requested: {', '.join(workflow['symbols_requested'])}",
        f"- Success count: {workflow['success_count']}",
        f"- Failure count: {workflow['failure_count']}",
        f"- Target: {workflow.get('target')}",
        "- Side-effect-free: this workflow writes artifacts and prints Markdown only; Hermes/Gateway delivery is external.",
        "- Not an execution instruction: no orders are sent.",
        "",
        "## Per-symbol Results",
    ]
    for run in workflow["runs"]:
        if run["status"] == "success":
            lines.append(
                f"- {run['symbol']}: {run['status']}, selected={run.get('selected_strategy')}, "
                f"trade_date={run.get('trade_date')}, markdown={run.get('output_markdown')}"
            )
        else:
            lines.append(f"- {run['symbol']}: {run['status']}, error={run.get('error_type')}: {run.get('error_message')}")
    if pack_markdowns:
        lines.extend(["", "---", ""])
        lines.append("\n\n---\n\n".join(markdown.strip() for markdown in pack_markdowns if markdown))
    return "\n".join(lines).strip() + "\n"


def build_daily_options_research_pack_workflow(
    symbols: Iterable[str] | None = None,
    trade_date: str | None = None,
    expiry: str | None = None,
    strategy_type: str | None = None,
    directional_bias: str | None = "neutral",
    volatility_view: str | None = None,
    review_dates: Iterable[str] | None = None,
    risk_budget_cash: float | None = None,
    min_credit_pct_of_wing_width: float | None = None,
    max_bid_ask_spread_pct: float | None = None,
    delivery_target: str | None = "feishu",
    output_dir: str | Path | None = None,
    continue_on_error: bool = True,
) -> dict[str, Any]:
    """Build multiple side-effect-free research packs and one combined handoff.

    The function performs local file writes only. It never sends Feishu messages
    or orders; live delivery should be handled by Hermes no-agent cron delivering
    the combined Markdown stdout.
    """
    resolved_symbols = [str(symbol).upper() for symbol in (symbols or DEFAULT_DAILY_SYMBOLS)]
    if not resolved_symbols:
        raise ValueError("At least one symbol is required for daily options research-pack workflow")
    outdir = Path(output_dir or ".").expanduser()
    outdir.mkdir(parents=True, exist_ok=True)
    review_date_list = list(review_dates or [])

    runs: list[dict[str, Any]] = []
    pack_markdowns: list[str] = []
    stem = _daily_stem(trade_date, resolved_symbols)
    combined_markdown_path = outdir / f"{stem}_daily_research_pack.md"
    index_path = outdir / f"{stem}_daily_research_pack_index.json"

    workflow: dict[str, Any] = {
        "workflow_type": "daily_options_research_pack",
        "symbols_requested": resolved_symbols,
        "trade_date": trade_date,
        "expiry": expiry,
        "target": delivery_target or "feishu",
        "side_effect_free": True,
        "not_execution_instruction": True,
        "runs": runs,
        "success_count": 0,
        "failure_count": 0,
        "output_dir": str(outdir),
        "output_markdown": _relative(combined_markdown_path, outdir),
        "artifact_index": _relative(index_path, outdir),
    }

    for symbol in resolved_symbols:
        try:
            pack = build_option_research_pack(
                symbol,
                trade_date=trade_date,
                expiry=expiry,
                strategy_type=strategy_type,
                directional_bias=directional_bias,
                volatility_view=volatility_view,
                review_dates=review_date_list,
                risk_budget_cash=risk_budget_cash,
                min_credit_pct_of_wing_width=min_credit_pct_of_wing_width,
                max_bid_ask_spread_pct=max_bid_ask_spread_pct,
                delivery_target=delivery_target,
            )
            pack_path, markdown_path, payload_path = _artifact_paths(outdir, pack)
            payload = pack["payloads"]["feishu_delivery_payload"]
            pack_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            markdown_path.write_text(pack["markdown"], encoding="utf-8")
            payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            runs.append(
                {
                    "symbol": symbol,
                    "status": "success",
                    "product": pack["product"],
                    "trade_date": pack["trade_date"],
                    "expiry": pack.get("expiry"),
                    "selection_mode": pack["selection_mode"],
                    "selected_strategy": pack["selected_strategy"],
                    "risk_budget_cash": pack["summary"].get("risk_budget_cash"),
                    "target": payload["target"],
                    "dry_run": payload["dry_run"],
                    "output_pack": _relative(pack_path, outdir),
                    "output_markdown": _relative(markdown_path, outdir),
                    "output_payload": _relative(payload_path, outdir),
                }
            )
            pack_markdowns.append(pack["markdown"])
        except Exception as exc:
            if not continue_on_error:
                raise
            runs.append(
                {
                    "symbol": symbol,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
            )

    workflow["success_count"] = sum(1 for run in runs if run["status"] == "success")
    workflow["failure_count"] = sum(1 for run in runs if run["status"] != "success")
    workflow["combined_markdown"] = _render_combined_markdown(workflow, pack_markdowns)
    combined_markdown_path.write_text(workflow["combined_markdown"], encoding="utf-8")
    index_payload = {key: value for key, value in workflow.items() if key != "combined_markdown"}
    index_path.write_text(json.dumps(index_payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return workflow


def build_daily_options_research_pack_hermes_cron_spec(
    symbols: Iterable[str] | None = None,
    trade_date: str | None = None,
    expiry: str | None = None,
    strategy_type: str | None = None,
    directional_bias: str | None = "neutral",
    volatility_view: str | None = None,
    review_dates: Iterable[str] | None = None,
    risk_budget_cash: float | None = None,
    min_credit_pct_of_wing_width: float | None = None,
    max_bid_ask_spread_pct: float | None = None,
    target: str | None = "feishu",
    schedule: str = DEFAULT_DAILY_CRON_SCHEDULE,
    output_dir: str | None = None,
    script_path: str = DEFAULT_DAILY_SCRIPT_PATH,
) -> dict[str, Any]:
    """Describe a Hermes no-agent cron job for the daily batch workflow.

    The spec is side-effect-free and does not create the cron job. Use Hermes cron
    separately after confirming schedule, symbols, and target.
    """
    resolved_symbols = [str(symbol).upper() for symbol in (symbols or DEFAULT_DAILY_SYMBOLS)]
    deliver_target = target or "feishu"
    args = [script_path]
    for symbol in resolved_symbols:
        args.extend(["--symbol", symbol])
    _append_option(args, "--date", trade_date)
    _append_option(args, "--expiry", expiry)
    _append_option(args, "--strategy-type", strategy_type)
    _append_option(args, "--directional-bias", directional_bias)
    _append_option(args, "--volatility-view", volatility_view)
    for review_date in review_dates or []:
        _append_option(args, "--review-date", review_date)
    _append_option(args, "--risk-budget-cash", risk_budget_cash)
    _append_option(args, "--min-credit-pct-of-wing-width", min_credit_pct_of_wing_width)
    _append_option(args, "--max-bid-ask-spread-pct", max_bid_ask_spread_pct)
    _append_option(args, "--target", deliver_target)
    _append_option(args, "--output-dir", output_dir)
    args.extend(["--stdout", "markdown"])
    return {
        "scheduler": "hermes_cron",
        "no_agent": True,
        "schedule": schedule,
        "deliver": deliver_target,
        "script_path": script_path,
        "command": _command_string(args),
        "stdout_mode": "markdown",
        "delivery_note": "Hermes no-agent cron delivers non-empty combined Markdown stdout to the configured target; empty stdout is silent.",
        "payload_preview": {
            "symbols": resolved_symbols,
            "trade_date": trade_date or "latest",
            "target": deliver_target,
            "schedule": schedule,
        },
        "artifacts": {
            "output_dir": output_dir,
            "writes_per_symbol_pack_json": True,
            "writes_per_symbol_markdown": True,
            "writes_per_symbol_feishu_payload_json": True,
            "writes_combined_markdown": True,
            "writes_index_json": True,
        },
        "side_effect_free": True,
    }
