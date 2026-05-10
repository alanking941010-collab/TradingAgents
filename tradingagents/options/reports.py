"""Report pipeline and Feishu-ready delivery payloads for SHFE option strategies.

The functions in this module compose the deterministic option analytics,
strategy, scenario, and replay layers into a human-readable Markdown report.
They do not send messages themselves; delivery wrappers are side-effect free so
an external Hermes/Gateway caller can decide where and when to publish.
"""

from __future__ import annotations

from typing import Any, Iterable

from tradingagents.options.analytics import DEFAULT_RISK_FREE_RATE
from tradingagents.options.context import OptionAnalysisContext
from tradingagents.options.replay import build_option_strategy_replay
from tradingagents.options.scenarios import build_option_strategy_scenarios


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
    title = f"{product} {strategy_type} 期权策略报告 — {trade_date}"
    cash_risk = strategy.get("cash_risk", {})
    margin = strategy.get("margin", {})
    risk_budget = strategy.get("risk_budget", {})
    execution = strategy.get("execution", {})
    credit_execution = strategy.get("credit_execution") or {}
    scenario_summary = scenarios.get("summary", {})
    credit_quote_status = credit_execution.get("credit_quote_status") or ("executable" if credit_execution.get("executable_credit_points") is not None else "indicative")
    if credit_quote_status == "executable":
        credit_label = "可执行 credit"
        credit_points = credit_execution.get("executable_credit_points")
        credit_cash = credit_execution.get("executable_credit_cash")
    else:
        credit_label = "指示性 credit"
        credit_points = credit_execution.get("indicative_credit_points", credit_execution.get("mid_credit_points"))
        credit_cash = credit_execution.get("indicative_credit_cash")

    lines = [
        f"# {title}",
        "",
        "## 波动率快照 / 波动率曲面",
        f"- 标的: `{strategy.get('underlying_symbol')}` @ {strategy.get('underlying_price')}",
        f"- ATM IV: {_fmt_pct(analytics.get('atm_iv'))}",
        f"- 25Δ skew: {_fmt_pct(analytics.get('skew_25d'))}",
        f"- 期限结构状态: `{(analytics.get('vol_surface') or {}).get('term_regime', {}).get('shape')}`",
        f"- Risk reversal proxy: {_fmt_pct((analytics.get('vol_surface') or {}).get('skew', {}).get('risk_reversal_proxy'))}",
        f"- PCR 持仓 / 成交: {analytics.get('pcr_open_interest')} / {analytics.get('pcr_volume')}",
        f"- Gamma flip: {analytics.get('gamma_flip')}",
        f"- 价格口径: {strategy.get('price_basis')}",
        "",
        "## 策略候选",
        f"- 策略: `{strategy_type}` / 到期 `{strategy.get('expiry')}` / 权利金类型 `{strategy.get('premium_type')}`",
        f"- 净权利金: {_fmt_points(strategy.get('net_premium'))} / {_fmt_cash(cash_risk.get('net_premium_cash'))}",
        f"- 最大亏损: {_fmt_points(strategy.get('max_loss'))} / {_fmt_cash(cash_risk.get('max_loss_cash'))}",
        f"- 最大收益: {_fmt_points(strategy.get('max_profit'))} / {_fmt_cash(cash_risk.get('max_profit_cash'))}",
        f"- {credit_label}: {_fmt_points(credit_points)} / {_fmt_cash(credit_cash)}",
        f"- 按可执行 credit 估算的最大亏损: {_fmt_points(credit_execution.get('max_loss_at_execution_points'))} / {_fmt_cash(credit_execution.get('max_loss_at_execution_cash'))}",
        f"- Credit / 翼宽: {_fmt_pct(credit_execution.get('executable_credit_pct_of_wing_width'))}; credit / 可执行最大亏损: {_fmt_pct(credit_execution.get('executable_credit_to_max_loss_at_execution'))}",
        f"- 盈亏平衡点: {strategy.get('breakevens')}",
        f"- 保证金需求: {_fmt_cash(margin.get('margin_required_cash'))}",
        f"- 风险预算: {_fmt_cash(risk_budget_cash)} / 状态 `{risk_budget.get('status')}`",
        f"- 执行流动性评分: {execution.get('execution_liquidity_score')} / `{execution.get('execution_liquidity_grade')}`",
        "",
        "### 策略腿",
    ]
    lines.extend(_leg_line(leg) for leg in strategy.get("legs", []))
    lines.extend([
        "",
        "## 情景 PnL",
        *_scenario_summary_lines(scenario_summary),
    ])

    if replay is not None:
        replay_summary = replay.get("summary", {})
        replay_performance = replay.get("performance_summary", {})
        post_trade = replay_summary.get("post_trade_review", {})
        lines.extend([
            "",
            "## 历史回放",
            f"- 回放日期数: {replay_summary.get('review_count')}",
            f"- 最终日期: {replay_summary.get('final_trade_date')}",
            f"- 最终 PnL: {_fmt_points(replay_summary.get('final_pnl'))} / {_fmt_cash(replay_summary.get('final_pnl_cash'))}",
            f"- 最好/最差现金 PnL: {_fmt_cash(replay_summary.get('best_pnl_cash'))} / {_fmt_cash(replay_summary.get('worst_pnl_cash'))}",
            f"- 事后结果: `{post_trade.get('outcome')}` — {post_trade.get('diagnosis')}",
            "",
            "### 回放绩效分布",
            f"- 盈利/亏损/持平 mark 数: {replay_performance.get('winning_mark_count')} / {replay_performance.get('losing_mark_count')} / {replay_performance.get('flat_mark_count')}",
            f"- 胜率: {_fmt_pct(replay_performance.get('win_rate'))}",
            f"- 平均现金 PnL: {_fmt_cash(replay_performance.get('average_pnl_cash'))}",
            f"- 最大回撤现金: {_fmt_cash(replay_performance.get('max_drawdown_cash'))}",
            f"- IV regime 分组: {sorted((replay_performance.get('iv_regime_breakdown') or {}).keys())}",
        ])

    lines.extend([
        "",
        "## 假设与交付说明",
        "- 默认分析口径为期权 close + 期货 close；结算口径仅用于明确的结算/风控请求。",
        "- 合约乘数已应用于权利金、最大亏损、情景 PnL、回放 PnL 和保证金现金字段。",
        "- 未建模交易所/SPAN 保证金；保证金需求是策略层的简化 defined-risk 估计。",
        "- 本报告生成的飞书 payload 无副作用；必须由外部 Hermes/Gateway 调用方显式发送。",
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
    analysis_context: OptionAnalysisContext | None = None,
) -> dict[str, Any]:
    """Build a Markdown-first report from deterministic option pipeline outputs."""
    context = analysis_context or OptionAnalysisContext(symbol, trade_date=trade_date, expiry=expiry, risk_free_rate=risk_free_rate)
    analytics_report = context.get_analysis(symbol, trade_date=trade_date, expiry=expiry, risk_free_rate=risk_free_rate)
    strategy = context.get_strategy_candidate(
        strategy_type,
        symbol=symbol,
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
        analysis_context=context,
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
        "vol_surface": analytics_report.vol_surface,
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
    title = f"{product} {normalized_strategy} 期权策略报告 — {resolved_trade_date}"
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
            "credit_quote_status": strategy.get("credit_execution", {}).get("credit_quote_status") if strategy.get("credit_execution") else None,
            "executable_credit_cash": strategy.get("credit_execution", {}).get("executable_credit_cash") if strategy.get("credit_execution") else None,
            "indicative_credit_cash": strategy.get("credit_execution", {}).get("indicative_credit_cash") if strategy.get("credit_execution") else None,
            "max_loss_at_execution_cash": strategy.get("credit_execution", {}).get("max_loss_at_execution_cash") if strategy.get("credit_execution") else None,
            "credit_pct_of_wing_width": strategy.get("credit_execution", {}).get("executable_credit_pct_of_wing_width") if strategy.get("credit_execution") else None,
            "worst_scenario_pnl_cash": scenarios.get("summary", {}).get("worst_pnl_cash"),
            "replay_final_pnl_cash": replay.get("summary", {}).get("final_pnl_cash") if replay else None,
            "replay_max_drawdown_cash": replay.get("performance_summary", {}).get("max_drawdown_cash") if replay else None,
            "replay_win_rate": replay.get("performance_summary", {}).get("win_rate") if replay else None,
        },
        "payloads": {
            "volatility_snapshot": analytics,
            "strategy": strategy,
            "scenario_summary": scenarios.get("summary"),
            "replay_summary": replay.get("summary") if replay else None,
            "replay_performance_summary": replay.get("performance_summary") if replay else None,
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
