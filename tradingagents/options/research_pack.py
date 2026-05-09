"""Unified SHFE option research pack orchestration.

This module stitches together the deterministic selector, report composer, replay
summary, and Feishu-ready payload into one side-effect-free research package.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from tradingagents.options.analytics import DEFAULT_RISK_FREE_RATE
from tradingagents.options.reports import build_feishu_delivery_payload, build_option_strategy_report
from tradingagents.options.selector import build_option_strategy_selection


def _find_ranked_row(selection: dict[str, Any], strategy_type: str | None) -> dict[str, Any] | None:
    if not strategy_type:
        return None
    return next(
        (row for row in selection.get("ranked_candidates", []) if row.get("strategy_type") == strategy_type),
        None,
    )


def _render_markdown(pack: dict[str, Any]) -> str:
    summary = pack["summary"]
    report = pack["payloads"]["selected_strategy_report"]
    selection = pack["payloads"]["selection"]
    lines = [
        f"# Options Research Pack — {pack['product']} {pack['trade_date']}",
        "",
        "## Executive Summary",
        f"- Selection mode: {pack['selection_mode']}",
        f"- Selected strategy: {pack['selected_strategy']}",
        f"- Selected decision: {summary.get('selected_decision')}",
        f"- Selected score: {summary.get('selected_score')}",
        f"- Risk budget cash: {summary.get('risk_budget_cash')}",
        f"- Risk budget status: {summary.get('risk_budget_status')}",
        f"- Worst scenario PnL cash: {summary.get('worst_scenario_pnl_cash')}",
        f"- Replay max drawdown cash: {summary.get('replay_max_drawdown_cash')}",
        f"- Replay win rate: {summary.get('replay_win_rate')}",
        "",
        "## Strategy Selection",
        selection.get("markdown", "").strip(),
        "",
        "## Selected Strategy Report",
        report.get("markdown", "").strip(),
        "",
        "## Research Pack Assumptions",
        "- Side-effect-free: no orders are sent and Feishu delivery is only a payload handoff.",
        "- Price basis: option close + futures close unless explicitly requested otherwise.",
        "- This pack is an auditable research workflow, not an execution instruction.",
    ]
    return "\n".join(line for line in lines if line is not None).strip() + "\n"


def build_option_research_pack(
    symbol: str,
    trade_date: str | None = None,
    expiry: str | None = None,
    strategy_type: str | None = None,
    directional_bias: str | None = "neutral",
    volatility_view: str | None = None,
    review_dates: Iterable[str] | None = None,
    risk_budget_cash: float | None = None,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    min_credit_pct_of_wing_width: float | None = None,
    max_bid_ask_spread_pct: float | None = None,
    delivery_target: str | None = None,
) -> dict[str, Any]:
    """Build one side-effect-free research pack from selector + selected report.

    If ``strategy_type`` is omitted, the selector's best non-no-trade candidate is
    used. If it is supplied, the pack still includes the full selector/ranking but
    reports the explicit override strategy for auditability.
    """
    selection = build_option_strategy_selection(
        symbol,
        trade_date=trade_date,
        expiry=expiry,
        directional_bias=directional_bias,
        volatility_view=volatility_view,
        risk_budget_cash=risk_budget_cash,
        risk_free_rate=risk_free_rate,
        min_credit_pct_of_wing_width=min_credit_pct_of_wing_width,
        max_bid_ask_spread_pct=max_bid_ask_spread_pct,
    )
    selected_strategy = strategy_type or selection.get("selected_strategy")
    if not selected_strategy:
        raise ValueError("No option strategy could be selected for research pack")

    report = build_option_strategy_report(
        symbol,
        strategy_type=selected_strategy,
        trade_date=trade_date or selection.get("trade_date"),
        expiry=expiry,
        review_dates=review_dates,
        risk_budget_cash=risk_budget_cash,
        risk_free_rate=risk_free_rate,
    )
    delivery_payload = build_feishu_delivery_payload(report, target=delivery_target, dry_run=True)
    selected_row = _find_ranked_row(selection, selected_strategy) or {}
    report_summary = report.get("summary", {})
    pack = {
        "pack_type": "shfe_option_research_pack",
        "product": selection.get("product") or report.get("product"),
        "trade_date": report.get("trade_date") or selection.get("trade_date"),
        "expiry": report.get("expiry") or selection.get("expiry"),
        "selected_strategy": selected_strategy,
        "selection_mode": "explicit_strategy_override" if strategy_type else "selector_auto",
        "summary": {
            "selected_strategy": selected_strategy,
            "selected_decision": selected_row.get("decision"),
            "selected_score": selected_row.get("score"),
            "risk_budget_cash": risk_budget_cash,
            "risk_budget_status": report_summary.get("risk_budget_status") or selected_row.get("risk_budget_status"),
            "selected_risk_budget_utilization": selection.get("portfolio_summary", {}).get("selected_risk_budget_utilization"),
            "execution_liquidity_grade": report_summary.get("execution_liquidity_grade"),
            "worst_scenario_pnl_cash": report_summary.get("worst_scenario_pnl_cash"),
            "replay_final_pnl_cash": report_summary.get("replay_final_pnl_cash"),
            "replay_max_drawdown_cash": report_summary.get("replay_max_drawdown_cash"),
            "replay_win_rate": report_summary.get("replay_win_rate"),
            "report_title": report.get("title"),
        },
        "payloads": {
            "selection": selection,
            "portfolio_summary": selection.get("portfolio_summary"),
            "selected_strategy_report": report,
            "feishu_delivery_payload": delivery_payload,
        },
        "assumptions": {
            "price_basis": "option close + futures close",
            "risk_free_rate": risk_free_rate,
            "side_effect_free": True,
            "not_execution_instruction": True,
            "selector_model": selection.get("assumptions", {}).get("selector_model"),
            "report_side_effect_free": report.get("assumptions", {}).get("feishu_delivery_side_effect_free"),
        },
    }
    pack["markdown"] = _render_markdown(pack)
    return pack
