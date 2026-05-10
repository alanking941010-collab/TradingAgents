"""Shared cached context for option analytics workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tradingagents.options.analytics import DEFAULT_RISK_FREE_RATE, analyze_option_chain
from tradingagents.options.models import OptionAnalyticsReport


def _none_safe_tuple(items: tuple[Any, ...]) -> tuple[Any, ...]:
    return tuple("<none>" if item is None else item for item in items)


@dataclass
class OptionAnalysisContext:
    """Cache analytics and strategy candidates within one research/report workflow."""

    symbol: str
    trade_date: str | None = None
    expiry: str | None = None
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE
    _analysis_cache: dict[tuple[Any, ...], OptionAnalyticsReport] = field(default_factory=dict, init=False)
    _strategy_cache: dict[tuple[Any, ...], dict[str, Any]] = field(default_factory=dict, init=False)
    _stats: dict[str, int] = field(
        default_factory=lambda: {
            "analysis_hits": 0,
            "analysis_misses": 0,
            "strategy_hits": 0,
            "strategy_misses": 0,
        },
        init=False,
    )

    def analysis_key(
        self,
        symbol: str | None = None,
        trade_date: str | None = None,
        expiry: str | None = None,
        risk_free_rate: float | None = None,
    ) -> tuple[Any, ...]:
        return _none_safe_tuple((
            symbol or self.symbol,
            self.trade_date if trade_date is None else trade_date,
            self.expiry if expiry is None else expiry,
            self.risk_free_rate if risk_free_rate is None else risk_free_rate,
        ))

    def get_analysis(
        self,
        symbol: str | None = None,
        trade_date: str | None = None,
        expiry: str | None = None,
        risk_free_rate: float | None = None,
    ) -> OptionAnalyticsReport:
        key = self.analysis_key(symbol, trade_date, expiry, risk_free_rate)
        if key in self._analysis_cache:
            self._stats["analysis_hits"] += 1
            return self._analysis_cache[key]
        self._stats["analysis_misses"] += 1
        report = analyze_option_chain(
            symbol or self.symbol,
            trade_date=self.trade_date if trade_date is None else trade_date,
            expiry=self.expiry if expiry is None else expiry,
            risk_free_rate=self.risk_free_rate if risk_free_rate is None else risk_free_rate,
        )
        self._analysis_cache[key] = report
        return report

    def strategy_key(
        self,
        strategy_type: str,
        *,
        symbol: str | None = None,
        trade_date: str | None = None,
        expiry: str | None = None,
        risk_free_rate: float | None = None,
        min_open_interest: float = 1000.0,
        min_volume: float = 100.0,
        risk_budget_cash: float | None = None,
        min_credit_pct_of_wing_width: float | None = None,
        max_bid_ask_spread_pct: float | None = None,
    ) -> tuple[Any, ...]:
        return _none_safe_tuple((
            symbol or self.symbol,
            strategy_type,
            self.trade_date if trade_date is None else trade_date,
            self.expiry if expiry is None else expiry,
            self.risk_free_rate if risk_free_rate is None else risk_free_rate,
            min_open_interest,
            min_volume,
            risk_budget_cash,
            min_credit_pct_of_wing_width,
            max_bid_ask_spread_pct,
        ))

    def get_strategy_candidate(
        self,
        strategy_type: str,
        *,
        symbol: str | None = None,
        trade_date: str | None = None,
        expiry: str | None = None,
        risk_free_rate: float | None = None,
        min_open_interest: float = 1000.0,
        min_volume: float = 100.0,
        risk_budget_cash: float | None = None,
        min_credit_pct_of_wing_width: float | None = None,
        max_bid_ask_spread_pct: float | None = None,
    ) -> dict[str, Any]:
        key = self.strategy_key(
            strategy_type,
            symbol=symbol,
            trade_date=trade_date,
            expiry=expiry,
            risk_free_rate=risk_free_rate,
            min_open_interest=min_open_interest,
            min_volume=min_volume,
            risk_budget_cash=risk_budget_cash,
            min_credit_pct_of_wing_width=min_credit_pct_of_wing_width,
            max_bid_ask_spread_pct=max_bid_ask_spread_pct,
        )
        if key in self._strategy_cache:
            self._stats["strategy_hits"] += 1
            return self._strategy_cache[key]
        self._stats["strategy_misses"] += 1
        from tradingagents.options.strategies import build_option_strategy_candidate

        candidate = build_option_strategy_candidate(
            symbol or self.symbol,
            strategy_type=strategy_type,
            trade_date=self.trade_date if trade_date is None else trade_date,
            expiry=self.expiry if expiry is None else expiry,
            risk_free_rate=self.risk_free_rate if risk_free_rate is None else risk_free_rate,
            min_open_interest=min_open_interest,
            min_volume=min_volume,
            risk_budget_cash=risk_budget_cash,
            min_credit_pct_of_wing_width=min_credit_pct_of_wing_width,
            max_bid_ask_spread_pct=max_bid_ask_spread_pct,
            analysis_context=self,
        )
        self._strategy_cache[key] = candidate
        return candidate

    def cache_stats(self) -> dict[str, int]:
        return dict(self._stats)
