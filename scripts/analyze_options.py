#!/usr/bin/env python3
"""Lightweight CLI for deterministic SHFE options analytics.

Example:
    python scripts/analyze_options.py CU --date 2026-05-06

The script writes both JSON and Markdown artifacts so a user can run options
analytics without opening a Python REPL.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Make the script work when executed as `python scripts/analyze_options.py`
# from a checkout without installing the package first.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.options_cli_common import resolve_output_dir  # noqa: E402
from tradingagents.options.analytics import DEFAULT_RISK_FREE_RATE, analyze_option_chain  # noqa: E402
from tradingagents.options.models import EnrichedOptionQuote, OptionAnalyticsReport  # noqa: E402


def _safe_part(value: str | None) -> str:
    if not value:
        return "latest"
    return "".join(ch for ch in str(value) if ch.isalnum() or ch in ("-", "_")) or "latest"


def _round_or_none(value: float | None, digits: int = 8) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def enriched_option_to_dict(row: EnrichedOptionQuote) -> dict[str, Any]:
    greeks = row.greeks
    return {
        "ts_code": row.quote.ts_code,
        "trade_date": row.quote.trade_date,
        "call_put": row.quote.call_put,
        "strike": row.quote.strike,
        "maturity_date": row.quote.maturity_date,
        "underlying_symbol": row.quote.underlying_symbol,
        "close": row.quote.close,
        "settle": row.quote.settle,
        "price_used": row.quote.mid_price,
        "price_basis": "close" if row.quote.close is not None and row.quote.close > 0 else "settle_fallback",
        "volume": row.quote.volume,
        "open_interest": row.quote.open_interest,
        "time_to_expiry": _round_or_none(row.time_to_expiry),
        "implied_volatility": _round_or_none(row.implied_volatility),
        "delta": _round_or_none(greeks.delta) if greeks else None,
        "gamma": _round_or_none(greeks.gamma) if greeks else None,
        "vega": _round_or_none(greeks.vega) if greeks else None,
        "theta": _round_or_none(greeks.theta) if greeks else None,
        "gex_per_1pct": _round_or_none(row.gex_per_1pct, 4),
        "dex": _round_or_none(row.dex, 4),
        "source": row.quote.source,
    }


def report_to_dict(report: OptionAnalyticsReport) -> dict[str, Any]:
    return {
        "product": report.product,
        "trade_date": report.trade_date,
        "underlying_symbol": report.underlying_symbol,
        "underlying_price": report.underlying_price,
        "price_basis": "close",
        "risk_free_rate": DEFAULT_RISK_FREE_RATE,
        "atm_iv": _round_or_none(report.atm_iv),
        "skew_25d": _round_or_none(report.skew_25d),
        "term_structure": {k: _round_or_none(v) for k, v in sorted(report.term_structure.items())},
        "pcr_open_interest": _round_or_none(report.pcr_open_interest),
        "pcr_volume": _round_or_none(report.pcr_volume),
        "call_wall": {
            "strike": report.call_wall.strike,
            "open_interest": report.call_wall.open_interest,
            "volume": report.call_wall.volume,
        },
        "put_wall": {
            "strike": report.put_wall.strike,
            "open_interest": report.put_wall.open_interest,
            "volume": report.put_wall.volume,
        },
        "gamma_flip": _round_or_none(report.gamma_flip, 4),
        "exposure": {
            "total_gex": _round_or_none(report.exposure.total_gex, 4),
            "total_abs_gex": _round_or_none(report.exposure.total_abs_gex, 4),
            "total_dex": _round_or_none(report.exposure.total_dex, 4),
            "by_strike": report.exposure.by_strike,
        },
        "assumptions": {
            "model": "Black-76 futures option model",
            "risk_free_rate": DEFAULT_RISK_FREE_RATE,
            "price_basis": "option_close + futures_close",
            "settlement_basis_note": "Use option_settle + futures_settle only for explicit settlement/risk-control requests.",
            "dealer_position_unknown": True,
            "gex_dex_note": "Exchange OI does not reveal true dealer inventory; GEX/DEX are scenario/concentration metrics.",
            "contract_multiplier_note": "Phase-1 exposure is relative unless multiplier enrichment is added.",
        },
        "options": [enriched_option_to_dict(row) for row in report.options],
    }


def markdown_with_cli_context(
    report: OptionAnalyticsReport,
    output_json: Path | None = None,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> str:
    lines = report.to_markdown().splitlines()
    insert_at = 5 if len(lines) >= 5 else len(lines)
    lines.insert(insert_at, "- Price basis: option close + futures close")
    lines.insert(insert_at + 1, f"- Risk-free rate: {risk_free_rate:.4f}")
    if output_json is not None:
        lines.extend(["", "## Artifacts", f"- JSON: `{output_json}`"])
    return "\n".join(lines) + "\n"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze SHFE options and write JSON + Markdown artifacts.")
    parser.add_argument("symbol", help="Product/instrument alias, e.g. CU, copper, 铜, AU")
    parser.add_argument("--date", dest="trade_date", help="Trade date, e.g. 2026-05-06 or 20260506")
    parser.add_argument("--expiry", help="Optional maturity date, e.g. 20260525")
    parser.add_argument("--risk-free-rate", type=float, default=DEFAULT_RISK_FREE_RATE)
    parser.add_argument("--output-dir", default=None, help="Artifact directory; defaults to TRADINGAGENTS_OPTIONS_ANALYTICS_OUTPUT_DIR or TRADINGAGENTS_OPTIONS_OUTPUT_ROOT/analytics")
    parser.add_argument(
        "--stdout",
        choices=["summary-json", "markdown", "none"],
        default="summary-json",
        help="What to print to stdout. Files are always written.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report = analyze_option_chain(
        args.symbol,
        trade_date=args.trade_date,
        expiry=args.expiry,
        risk_free_rate=args.risk_free_rate,
    )
    output_dir = resolve_output_dir(args.output_dir, kind="analytics")
    output_dir.mkdir(parents=True, exist_ok=True)

    date_part = _safe_part(report.trade_date)
    expiry_part = _safe_part(args.expiry)
    stem = f"{report.product}_{date_part}_{expiry_part}_options"
    json_path = output_dir / f"{stem}.json"
    markdown_path = output_dir / f"{stem}.md"

    data = report_to_dict(report)
    data["risk_free_rate"] = args.risk_free_rate
    data["assumptions"]["risk_free_rate"] = args.risk_free_rate
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    markdown = markdown_with_cli_context(report, output_json=json_path, risk_free_rate=args.risk_free_rate)
    markdown_path.write_text(markdown, encoding="utf-8")

    summary = {
        "product": report.product,
        "trade_date": report.trade_date,
        "underlying_symbol": report.underlying_symbol,
        "underlying_price": report.underlying_price,
        "price_basis": "close",
        "risk_free_rate": args.risk_free_rate,
        "atm_iv": report.atm_iv,
        "pcr_open_interest": report.pcr_open_interest,
        "call_wall": {"strike": report.call_wall.strike, "open_interest": report.call_wall.open_interest},
        "put_wall": {"strike": report.put_wall.strike, "open_interest": report.put_wall.open_interest},
        "gamma_flip": report.gamma_flip,
        "output_json": str(json_path),
        "output_markdown": str(markdown_path),
    }

    if args.stdout == "summary-json":
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    elif args.stdout == "markdown":
        print(markdown, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
