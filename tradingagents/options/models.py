"""Shared dataclasses for options analytics core."""

from __future__ import annotations

from dataclasses import dataclass, field

from tradingagents.options.greeks import Greeks


@dataclass(frozen=True)
class OptionQuote:
    trade_date: str
    ts_code: str
    product: str
    call_put: str
    strike: float
    maturity_date: str
    underlying_symbol: str
    close: float | None
    settle: float | None
    volume: float
    open_interest: float
    source: str
    bid: float | None = None
    ask: float | None = None

    @property
    def price_basis(self) -> str:
        if self.close is not None and self.close > 0:
            return "close"
        if self.settle is not None and self.settle > 0:
            return "settle_fallback"
        return "unavailable"

    @property
    def mid_price(self) -> float | None:
        # Trading-analysis default follows Alan's convention: option close
        # with futures close. If close is unavailable, settle is an explicit
        # fallback and must be exposed via price_basis metadata.
        if self.close is not None and self.close > 0:
            return self.close
        if self.settle is not None and self.settle > 0:
            return self.settle
        return None

    @property
    def bid_ask_mid(self) -> float | None:
        """Return executable quote midpoint when both bid and ask are valid."""
        if self.bid is not None and self.ask is not None and self.bid > 0 and self.ask > 0 and self.ask >= self.bid:
            return (self.bid + self.ask) / 2.0
        return None

    @property
    def bid_ask_spread(self) -> float | None:
        """Return quoted bid/ask spread in option-price points."""
        if self.bid is not None and self.ask is not None and self.bid > 0 and self.ask > 0 and self.ask >= self.bid:
            return self.ask - self.bid
        return None

    @property
    def bid_ask_spread_pct(self) -> float | None:
        """Return bid/ask spread divided by quoted midpoint."""
        spread = self.bid_ask_spread
        mid = self.bid_ask_mid
        if spread is None or not mid:
            return None
        return spread / mid


@dataclass(frozen=True)
class OptionChainSnapshot:
    product: str
    trade_date: str
    underlying_symbol: str
    underlying_price: float
    options: list[OptionQuote]
    source: str
    requested_trade_date: str | None = None
    trade_date_mode: str = "latest"
    trade_date_fallback_used: bool = False
    underlying_price_trade_date: str | None = None
    underlying_price_basis: str = "close"

    @property
    def option_price_basis(self) -> str:
        bases = {row.price_basis for row in self.options}
        if not bases:
            return "unavailable"
        if bases == {"close"}:
            return "close"
        if bases == {"settle_fallback"}:
            return "settle_fallback"
        return "mixed"

    @property
    def price_basis(self) -> dict[str, object]:
        return {
            "analysis_basis": "option close + futures close with explicit fallback metadata",
            "option_price_basis": self.option_price_basis,
            "underlying_price_basis": self.underlying_price_basis,
            "requested_trade_date": self.requested_trade_date,
            "resolved_trade_date": self.trade_date,
            "trade_date_mode": self.trade_date_mode,
            "trade_date_fallback_used": self.trade_date_fallback_used,
            "underlying_price_trade_date": self.underlying_price_trade_date,
        }


@dataclass(frozen=True)
class WallLevel:
    option_type: str
    strike: float
    open_interest: float
    volume: float


@dataclass(frozen=True)
class ExposureSummary:
    total_gex: float
    total_abs_gex: float
    total_dex: float
    by_strike: list[dict[str, float]] = field(default_factory=list)


@dataclass(frozen=True)
class EnrichedOptionQuote:
    quote: OptionQuote
    time_to_expiry: float
    implied_volatility: float | None
    greeks: Greeks | None
    gex_per_1pct: float | None
    dex: float | None


@dataclass(frozen=True)
class OptionAnalyticsReport:
    product: str
    trade_date: str
    underlying_symbol: str
    underlying_price: float
    atm_iv: float | None
    skew_25d: float | None
    term_structure: dict[str, float]
    vol_surface: dict[str, object]
    pcr_open_interest: float | None
    pcr_volume: float | None
    call_wall: WallLevel
    put_wall: WallLevel
    gamma_flip: float | None
    exposure: ExposureSummary
    options: list[EnrichedOptionQuote]
    assumptions: list[str]
    price_basis: dict[str, object] = field(default_factory=dict)

    def to_markdown(self) -> str:
        def fmt(value: float | None, digits: int = 4) -> str:
            if value is None:
                return "N/A"
            return f"{value:.{digits}f}"

        lines = [
            f"# Options analytics core: {self.product}",
            "",
            f"- Trade date: {self.trade_date}",
            f"- Underlying: {self.underlying_symbol} @ {self.underlying_price:.4f}",
            f"- Price basis: option={self.price_basis.get('option_price_basis', 'unknown')} / underlying={self.price_basis.get('underlying_price_basis', 'unknown')}",
            f"- ATM IV: {fmt(self.atm_iv)}",
            f"- 25Δ skew: {fmt(self.skew_25d)} (method {self.vol_surface.get('skew', {}).get('method', 'unknown') if self.vol_surface else 'unknown'})",
            f"- Term regime: {self.vol_surface.get('term_regime', {}).get('shape', 'N/A')}",
            f"- Risk reversal proxy: {fmt(self.vol_surface.get('skew', {}).get('risk_reversal_proxy') if self.vol_surface else None)}",
            f"- PCR OI: {fmt(self.pcr_open_interest)}",
            f"- PCR Volume: {fmt(self.pcr_volume)}",
            f"- Call Wall: {self.call_wall.strike:.4f} / OI {self.call_wall.open_interest:.0f}",
            f"- Put Wall: {self.put_wall.strike:.4f} / OI {self.put_wall.open_interest:.0f}",
            f"- Gamma Flip: {fmt(self.gamma_flip, 2)}",
            f"- GEX total: {self.exposure.total_gex:.4f}",
            f"- GEX abs: {self.exposure.total_abs_gex:.4f}",
            "",
            "## Term structure",
        ]
        for maturity, iv in sorted(self.term_structure.items()):
            lines.append(f"- {maturity}: {iv:.4f}")
        lines.extend(["", "## Volatility Surface"])
        buckets = self.vol_surface.get("moneyness_buckets", {}) if self.vol_surface else {}
        for maturity, bucket_map in sorted(buckets.items()):
            lines.append(f"- {maturity}:")
            for bucket_name in ["otm_put", "atm", "otm_call"]:
                bucket = bucket_map.get(bucket_name, {}) if isinstance(bucket_map, dict) else {}
                lines.append(
                    f"  - {bucket_name}: IV {fmt(bucket.get('avg_iv'))}, "
                    f"strike {fmt(bucket.get('representative_strike'), 2)}, count {bucket.get('option_count', 0)}"
                )
        lines.extend(["", "## Assumptions"])
        for item in self.assumptions:
            lines.append(f"- {item}")
        return "\n".join(lines)
