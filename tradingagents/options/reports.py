"""Report pipeline and Feishu-ready delivery payloads for SHFE option strategies.

The functions in this module compose the deterministic option analytics,
strategy, scenario, and replay layers into a human-readable Markdown report.
They do not send messages themselves; delivery wrappers are side-effect free so
an external Hermes/Gateway caller can decide where and when to publish.
"""

from __future__ import annotations

from typing import Any, Iterable

from tradingagents.options.analytics import DEFAULT_RISK_FREE_RATE, analyze_option_chain
from tradingagents.options.replay import build_option_strategy_replay
from tradingagents.options.scenarios import build_option_strategy_scenarios
from tradingagents.options.strategies import build_option_strategy_candidate


def _round(value: float | None, digits: int = 8) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _fmt_cash(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):,.2f} CNY"


def _fmt_points(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):,.4f} pts"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.2f}%"


def _leg_line(leg: dict[str, Any]) -> str:
    return (
        f"- {leg.get('side')} x{leg.get('quantity', 1)} {leg.get('call_put')} "
        f"{leg.get('strike')} exp {leg.get('expiry')} "
        f"@ {_fmt_points(leg.get('price'))}; code={leg.get('ts_code')}; "
        f"IV={_fmt_pct(leg.get('implied_volatility'))}; "
        f"bid/ask={leg.get('bid')}/{leg.get('ask')}"
    )


def _scenario_summary_lines(summary: dict[str, Any]) -> list[str]:
    return [
        f"- Worst scenario: `{summary.get('worst_scenario')}` / {_fmt_points(summary.get('worst_pnl'))} / {_fmt_cash(summary.get('worst_pnl_cash'))}",
        f"- Best scenario: `{summary.get('best_scenario')}` / {_fmt_points(summary.get('best_pnl'))} / {_fmt_cash(summary.get('best_pnl_cash'))}",
        f"- Worst PnL / margin: {_fmt_pct(summary.get('worst_pnl_pct_of_margin'))}",
        f"- Best PnL / margin: {_fmt_pct(summary.get('best_pnl_pct_of_margin'))}",
        f"- Breakeven proximity: {_fmt_points(summary.get('breakeven_proximity'))}",
    ]


def _render_markdown(
    *,
    product: str,
    strategy_type: str,
    trade_date: str,
    analytics: dict[str, Any],
    strategy: dict[str, Any],
    scenarios: dict[str, Any],
    replay: dict[str, Any] | None,
    risk_budget_cash: float | None,
) -> str:
    title = f"{product} {strategy_type} option strategy report — {trade_date}"
    cash_risk = strategy.get("cash_risk", {})
    margin = strategy.get("margin", {})
    risk_budget = strategy.get("risk_budget", {})
    execution = strategy.get("execution", {})
    scenario_summary = scenarios.get("summary", {})

    lines = [
        f"# {title}",
        "",
        "## Volatility Snapshot",
        f"- Underlying: `{strategy.get('underlying_symbol')}` @ {strategy.get('underlying_price')}",
        f"- ATM IV: {_fmt_pct(analytics.get('atm_iv'))}",
        f"- 25Δ skew: {_fmt_pct(analytics.get('skew_25d'))}",
        f"- PCR OI / volume: {analytics.get('pcr_open_interest')} / {analytics.get('pcr_volume')}",
        f"- Gamma flip: {analytics.get('gamma_flip')}",
        f"- Price basis: {strategy.get('price_basis')}",
        "",
        "## Strategy Candidate",
        f"- Strategy: `{strategy_type}` / expiry `{strategy.get('expiry')}` / premium type `{strategy.get('premium_type')}`",
        f"- Net premium: {_fmt_points(strategy.get('net_premium'))} / {_fmt_cash(cash_risk.get('net_premium_cash'))}",
        f"- Max loss: {_fmt_points(strategy.get('max_loss'))} / {_fmt_cash(cash_risk.get('max_loss_cash'))}",
        f"- Max profit: {_fmt_points(strategy.get('max_profit'))} / {_fmt_cash(cash_risk.get('max_profit_cash'))}",
        f"- Breakevens: {strategy.get('breakevens')}",
        f"- Margin required: {_fmt_cash(margin.get('margin_required_cash'))}",
        f"- Risk budget: {_fmt_cash(risk_budget_cash)} / status `{risk_budget.get('status')}`",
        f"- Execution liquidity score: {execution.get('execution_liquidity_score')} / `{execution.get('execution_liquidity_grade')}`",
        "",
        "### Legs",
    ]
    lines.extend(_leg_line(leg) for leg in strategy.get("legs", []))
    lines.extend([
        "",
        "## Scenario PnL",
        *_scenario_summary_lines(scenario_summary),
    ])

    if replay is not None:
        replay_summary = replay.get("summary", {})
        post_trade = replay_summary.get("post_trade_review", {})
        lines.extend([
            "",
            "## Historical Replay",
            f"- Review count: {replay_summary.get('review_count')}",
            f"- Final date: {replay_summary.get('final_trade_date')}",
            f"- Final PnL: {_fmt_points(replay_summary.get('final_pnl'))} / {_fmt_cash(replay_summary.get('final_pnl_cash'))}",
            f"- Best/Worst cash PnL: {_fmt_cash(replay_summary.get('best_pnl_cash'))} / {_fmt_cash(replay_summary.get('worst_pnl_cash'))}",
            f"- Post-trade outcome: `{post_trade.get('outcome')}` — {post_trade.get('diagnosis')}",
        ])

    lines.extend([
        "",
        "## Assumptions and Delivery Notes",
        "- Default analysis basis is option close + futures close; settlement basis is only for explicit settlement/risk-control requests.",
        "- Contract multipliers are applied to premium, max-loss, scenario PnL, replay PnL, and margin cash fields.",
        "- Exchange/SPAN margin is not modeled; margin required is the simplified defined-risk estimate from the strategy layer.",
        "- Feishu delivery payloads generated from this report are side-effect free; an external Hermes/Gateway caller must explicitly send them.",
    ])
    return "\n".join(lines) + "\n"


def build_option_strategy_report(
    symbol: str,
    strategy_type: str,
    trade_date: str | None = None,
    expiry: str | None = None,
    review_dates: Iterable[str] | None = None,
    risk_budget_cash: float | None = None,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> dict[str, Any]:
    """Build a Markdown-first report from deterministic option pipeline outputs."""
    analytics_report = analyze_option_chain(symbol, trade_date=trade_date, expiry=expiry, risk_free_rate=risk_free_rate)
    strategy = build_option_strategy_candidate(
        symbol,
        strategy_type=strategy_type,
        trade_date=trade_date,
        expiry=expiry,
        risk_free_rate=risk_free_rate,
        risk_budget_cash=risk_budget_cash,
    )
    scenarios = build_option_strategy_scenarios(
        symbol,
        strategy_type=strategy_type,
        trade_date=trade_date,
        expiry=expiry,
        risk_free_rate=risk_free_rate,
        risk_budget_cash=risk_budget_cash,
    )
    replay = None
    if review_dates is not None:
        replay = build_option_strategy_replay(
            symbol,
            strategy_type=strategy_type,
            entry_date=trade_date or strategy["trade_date"],
            review_dates=review_dates,
            expiry=expiry,
            risk_budget_cash=risk_budget_cash,
        )

    normalized_strategy = strategy["strategy_type"]
    product = strategy["product"]
    resolved_trade_date = strategy["trade_date"]
    analytics = {
        "atm_iv": _round(analytics_report.atm_iv),
        "skew_25d": _round(analytics_report.skew_25d),
        "term_structure": {k: _round(v) for k, v in sorted(analytics_report.term_structure.items())},
        "pcr_open_interest": _round(analytics_report.pcr_open_interest),
        "pcr_volume": _round(analytics_report.pcr_volume),
        "gamma_flip": _round(analytics_report.gamma_flip, 4),
    }
    markdown = _render_markdown(
        product=product,
        strategy_type=normalized_strategy,
        trade_date=resolved_trade_date,
        analytics=analytics,
        strategy=strategy,
        scenarios=scenarios,
        replay=replay,
        risk_budget_cash=risk_budget_cash,
    )
    title = f"{product} {normalized_strategy} option strategy report — {resolved_trade_date}"
    return {
        "report_type": "shfe_option_strategy_report",
        "title": title,
        "product": product,
        "strategy_type": normalized_strategy,
        "trade_date": resolved_trade_date,
        "expiry": strategy.get("expiry"),
        "summary": {
            "price_basis": strategy.get("price_basis"),
            "atm_iv": analytics["atm_iv"],
            "net_premium_cash": strategy.get("cash_risk", {}).get("net_premium_cash"),
            "max_loss_cash": strategy.get("cash_risk", {}).get("max_loss_cash"),
            "margin_required_cash": strategy.get("margin", {}).get("margin_required_cash"),
            "risk_budget_status": strategy.get("risk_budget", {}).get("status"),
            "execution_liquidity_grade": strategy.get("execution", {}).get("execution_liquidity_grade"),
            "worst_scenario_pnl_cash": scenarios.get("summary", {}).get("worst_pnl_cash"),
            "replay_final_pnl_cash": replay.get("summary", {}).get("final_pnl_cash") if replay else None,
        },
        "payloads": {
            "volatility_snapshot": analytics,
            "strategy": strategy,
            "scenario_summary": scenarios.get("summary"),
            "replay_summary": replay.get("summary") if replay else None,
        },
        "markdown": markdown,
        "assumptions": {
            "price_basis": "option close + futures close",
            "risk_free_rate": risk_free_rate,
            "contract_multiplier_applied": True,
            "margin_model": "simplified_defined_risk",
            "feishu_delivery_side_effect_free": True,
        },
    }


def build_feishu_delivery_payload(
    report: dict[str, Any],
    target: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Wrap a report as a Feishu-ready Markdown message without sending it."""
    return {
        "channel": "feishu",
        "target": target or "feishu",
        "dry_run": bool(dry_run),
        "side_effect_free": True,
        "title": report["title"],
        "message": report["markdown"],
        "message_format": "markdown",
        "delivery_hint": "Use Hermes send_message(target, message) or Gateway Feishu delivery to send this Markdown.",
    }
