"""Runtime schema contracts for options payload dictionaries.

The project intentionally returns plain dictionaries for LangChain tool payloads and
JSON artifacts. These TypedDict declarations document the public contract while
small runtime validators catch key drift at builder boundaries.
"""

from __future__ import annotations

from typing import Any, TypedDict, TypeVar, cast


class StrategyLeg(TypedDict, total=False):
    ts_code: str
    side: str
    quantity: int
    call_put: str
    strike: float
    expiry: str
    price: float | None
    bid: float | None
    ask: float | None
    bid_ask_status: str
    execution_price: float | None


class StrategyCandidate(TypedDict, total=False):
    strategy_type: str
    product: str
    trade_date: str
    underlying_symbol: str
    underlying_price: float
    expiry: str | None
    price_basis: str
    price_basis_detail: dict[str, Any]
    risk_free_rate: float
    contract_multiplier: int
    legs: list[StrategyLeg]
    net_premium: float
    premium_type: str
    max_loss: float | None
    max_profit: float | None
    breakevens: list[float]
    cash_risk: dict[str, Any]
    greeks: dict[str, float | None]
    liquidity: dict[str, Any]
    execution: dict[str, Any]
    credit_execution: dict[str, Any] | None
    margin: dict[str, Any]
    risk_budget: dict[str, Any]
    assumptions: dict[str, Any]


class RankedCandidate(TypedDict, total=False):
    strategy_type: str
    score: float
    decision: str
    ranking_reasons: list[str]
    no_trade_reasons: list[str]
    risk_budget_status: str | None
    margin_required_cash: float | None
    max_loss_cash: float | None
    execution_liquidity_grade: str | None
    credit_execution: dict[str, Any] | None
    candidate: StrategyCandidate


class SelectionResult(TypedDict, total=False):
    selection_type: str
    product: str
    trade_date: str
    underlying_symbol: str
    underlying_price: float
    expiry: str | None
    price_basis: str
    risk_free_rate: float
    directional_bias: str | None
    volatility_view: str | None
    surface_regime: dict[str, Any]
    selected_strategy: str | None
    ranked_candidates: list[RankedCandidate]
    portfolio_summary: dict[str, Any]
    errors: list[dict[str, str]]
    assumptions: dict[str, Any]
    markdown: str


class ResearchPack(TypedDict, total=False):
    pack_type: str
    product: str
    trade_date: str
    expiry: str | None
    selected_strategy: str
    selection_mode: str
    summary: dict[str, Any]
    payloads: dict[str, Any]
    assumptions: dict[str, Any]
    markdown: str


class CronHandoffSpec(TypedDict, total=False):
    scheduler: str
    no_agent: bool
    schedule: str
    deliver: str
    script_path: str
    command: str
    stdout_mode: str
    delivery_note: str
    payload_preview: dict[str, Any]
    artifacts: dict[str, Any]
    side_effect_free: bool


PayloadT = TypeVar("PayloadT", bound=dict[str, Any])

STRATEGY_CANDIDATE_REQUIRED_KEYS = frozenset({
    "strategy_type",
    "product",
    "trade_date",
    "underlying_symbol",
    "underlying_price",
    "expiry",
    "price_basis",
    "risk_free_rate",
    "contract_multiplier",
    "legs",
    "net_premium",
    "premium_type",
    "cash_risk",
    "liquidity",
    "execution",
    "margin",
    "risk_budget",
    "assumptions",
})

SELECTION_RESULT_REQUIRED_KEYS = frozenset({
    "selection_type",
    "product",
    "trade_date",
    "underlying_symbol",
    "underlying_price",
    "price_basis",
    "surface_regime",
    "selected_strategy",
    "ranked_candidates",
    "portfolio_summary",
    "errors",
    "assumptions",
    "markdown",
})

RESEARCH_PACK_REQUIRED_KEYS = frozenset({
    "pack_type",
    "product",
    "trade_date",
    "selected_strategy",
    "selection_mode",
    "summary",
    "payloads",
    "assumptions",
    "markdown",
})

CRON_HANDOFF_SPEC_REQUIRED_KEYS = frozenset({
    "scheduler",
    "no_agent",
    "schedule",
    "deliver",
    "script_path",
    "command",
    "stdout_mode",
    "delivery_note",
    "payload_preview",
    "artifacts",
    "side_effect_free",
})


def _validate_required(payload: dict[str, Any], *, name: str, required: frozenset[str]) -> dict[str, Any]:
    missing = sorted(required.difference(payload))
    if missing:
        raise ValueError(f"{name} missing required keys: {missing}")
    return payload


def validate_strategy_candidate(payload: dict[str, Any]) -> StrategyCandidate:
    return cast(StrategyCandidate, _validate_required(payload, name="StrategyCandidate", required=STRATEGY_CANDIDATE_REQUIRED_KEYS))


def validate_selection_result(payload: dict[str, Any]) -> SelectionResult:
    return cast(SelectionResult, _validate_required(payload, name="SelectionResult", required=SELECTION_RESULT_REQUIRED_KEYS))


def validate_research_pack(payload: dict[str, Any]) -> ResearchPack:
    return cast(ResearchPack, _validate_required(payload, name="ResearchPack", required=RESEARCH_PACK_REQUIRED_KEYS))


def validate_cron_handoff_spec(payload: dict[str, Any]) -> CronHandoffSpec:
    return cast(CronHandoffSpec, _validate_required(payload, name="CronHandoffSpec", required=CRON_HANDOFF_SPEC_REQUIRED_KEYS))
