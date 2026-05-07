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

    @property
    def mid_price(self) -> float | None:
        # Trading-analysis default follows Alan's convention: option close
        # with futures close. Settlement price should be used only when a
        # settlement/risk-control basis is explicitly requested upstream.
        if self.close is not None and self.close > 0:
            return self.close
        if self.settle is not None and self.settle > 0:
            return self.settle
        return None


@dataclass(frozen=True)
class OptionChainSnapshot:
    product: str
    trade_date: str
    underlying_symbol: str
    underlying_price: float
    options: list[OptionQuote]
    source: str


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
    pcr_open_interest: float | None
    pcr_volume: float | None
    call_wall: WallLevel
    put_wall: WallLevel
    gamma_flip: float | None
    exposure: ExposureSummary
    options: list[EnrichedOptionQuote]
    assumptions: list[str]

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
            f"- ATM IV: {fmt(self.atm_iv)}",
            f"- Skew: {fmt(self.skew_25d)}",
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
        lines.extend(["", "## Assumptions"])
        for item in self.assumptions:
            lines.append(f"- {item}")
        return "\n".join(lines)
