"""Core metrics for futures option chains."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from statistics import mean

from tradingagents.options.data_loader import load_option_chain_snapshot
from tradingagents.options.greeks import black76_greeks
from tradingagents.options.models import (
    EnrichedOptionQuote,
    ExposureSummary,
    OptionAnalyticsReport,
    OptionChainSnapshot,
    OptionQuote,
    WallLevel,
)
from tradingagents.options.pricing import implied_volatility

DEFAULT_RISK_FREE_RATE = 0.015


def _parse_date(value: str) -> date:
    s = str(value)
    if len(s) == 8 and s.isdigit():
        return datetime.strptime(s, "%Y%m%d").date()
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def _time_to_expiry(trade_date: str, maturity_date: str) -> float:
    days = (_parse_date(maturity_date) - _parse_date(trade_date)).days
    return max(days, 0.5) / 365.0


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _wall(rows: list[OptionQuote], option_type: str) -> WallLevel:
    candidates = [row for row in rows if row.call_put == option_type]
    if not candidates:
        raise ValueError(f"Cannot compute {option_type} wall without {option_type} options")
    row = max(candidates, key=lambda item: item.open_interest)
    return WallLevel(option_type=option_type, strike=row.strike, open_interest=row.open_interest, volume=row.volume)


def _enrich(snapshot: OptionChainSnapshot, risk_free_rate: float) -> list[EnrichedOptionQuote]:
    enriched: list[EnrichedOptionQuote] = []
    for quote in snapshot.options:
        t = _time_to_expiry(snapshot.trade_date, quote.maturity_date)
        price = quote.mid_price
        iv = implied_volatility(
            price,
            snapshot.underlying_price,
            quote.strike,
            t,
            risk_free_rate,
            quote.call_put,
        )
        greeks = black76_greeks(snapshot.underlying_price, quote.strike, t, risk_free_rate, iv, quote.call_put) if iv else None
        if greeks:
            signed = 1.0 if quote.call_put == "C" else -1.0
            # GEX approximation per 1% futures move. Contract multiplier is not
            # embedded here yet; use it as a relative concentration metric.
            gex = signed * greeks.gamma * quote.open_interest * snapshot.underlying_price * snapshot.underlying_price * 0.01
            dex = signed * greeks.delta * quote.open_interest * snapshot.underlying_price
        else:
            gex = None
            dex = None
        enriched.append(
            EnrichedOptionQuote(
                quote=quote,
                time_to_expiry=t,
                implied_volatility=iv,
                greeks=greeks,
                gex_per_1pct=gex,
                dex=dex,
            )
        )
    return enriched


def _atm_iv(snapshot: OptionChainSnapshot, enriched: list[EnrichedOptionQuote]) -> float | None:
    rows = [row for row in enriched if row.implied_volatility is not None]
    if not rows:
        return None
    nearest_expiry = min(row.quote.maturity_date for row in rows)
    expiry_rows = [row for row in rows if row.quote.maturity_date == nearest_expiry]
    nearest_strike = min({row.quote.strike for row in expiry_rows}, key=lambda k: abs(k - snapshot.underlying_price))
    atm_rows = [row.implied_volatility for row in expiry_rows if row.quote.strike == nearest_strike and row.implied_volatility is not None]
    return mean(atm_rows) if atm_rows else None


def _term_structure(enriched: list[EnrichedOptionQuote]) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in enriched:
        if row.implied_volatility is not None:
            grouped[row.quote.maturity_date].append(row.implied_volatility)
    return {maturity: mean(values) for maturity, values in grouped.items() if values}


def _skew(snapshot: OptionChainSnapshot, enriched: list[EnrichedOptionQuote]) -> float | None:
    rows = [row for row in enriched if row.implied_volatility is not None]
    if not rows:
        return None
    nearest_expiry = min(row.quote.maturity_date for row in rows)
    expiry_rows = [row for row in rows if row.quote.maturity_date == nearest_expiry]
    puts = [row for row in expiry_rows if row.quote.call_put == "P" and row.quote.strike <= snapshot.underlying_price]
    calls = [row for row in expiry_rows if row.quote.call_put == "C" and row.quote.strike >= snapshot.underlying_price]
    if not puts or not calls:
        return None
    put = min(puts, key=lambda row: abs(row.quote.strike / snapshot.underlying_price - 0.97))
    call = min(calls, key=lambda row: abs(row.quote.strike / snapshot.underlying_price - 1.03))
    if put.implied_volatility is None or call.implied_volatility is None:
        return None
    return put.implied_volatility - call.implied_volatility


def _round(value: float | None, digits: int = 8) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _bucket_summary(rows: list[EnrichedOptionQuote], target_strike: float | None = None) -> dict[str, float | int | None]:
    values = [float(row.implied_volatility) for row in rows if row.implied_volatility is not None]
    if not values:
        return {"avg_iv": None, "representative_strike": None, "option_count": 0}
    if target_strike is None:
        representative = min(rows, key=lambda row: abs(float(row.quote.strike) - mean([r.quote.strike for r in rows])))
    else:
        representative = min(rows, key=lambda row: abs(float(row.quote.strike) - target_strike))
    return {
        "avg_iv": _round(mean(values)),
        "representative_strike": _round(representative.quote.strike, 4),
        "option_count": len(values),
    }


def _vol_surface(snapshot: OptionChainSnapshot, enriched: list[EnrichedOptionQuote], term_structure: dict[str, float], skew_25d: float | None) -> dict[str, object]:
    rows = [row for row in enriched if row.implied_volatility is not None]
    if not rows:
        return {
            "underlying_price": snapshot.underlying_price,
            "nearest_expiry": None,
            "moneyness_buckets": {},
            "skew": {"put_call_skew": None, "risk_reversal_proxy": None, "smile_curvature_proxy": None},
            "term_regime": {"shape": "no_iv", "front_expiry": None, "back_expiry": None, "front_iv": None, "back_iv": None, "slope": None},
        }

    expiries = sorted({row.quote.maturity_date for row in rows})
    buckets: dict[str, dict[str, dict[str, float | int | None]]] = {}
    for expiry in expiries:
        expiry_rows = [row for row in rows if row.quote.maturity_date == expiry]
        strikes = sorted({row.quote.strike for row in expiry_rows})
        atm_strike = min(strikes, key=lambda strike: (abs(strike - snapshot.underlying_price), strike))
        otm_puts = [row for row in expiry_rows if row.quote.call_put == "P" and row.quote.strike < snapshot.underlying_price]
        atm_rows = [row for row in expiry_rows if row.quote.strike == atm_strike]
        otm_calls = [row for row in expiry_rows if row.quote.call_put == "C" and row.quote.strike > snapshot.underlying_price]
        buckets[expiry] = {
            "otm_put": _bucket_summary(otm_puts, snapshot.underlying_price * 0.97),
            "atm": _bucket_summary(atm_rows, atm_strike),
            "otm_call": _bucket_summary(otm_calls, snapshot.underlying_price * 1.03),
        }

    nearest_expiry = expiries[0]
    nearest = buckets[nearest_expiry]
    put_iv = nearest["otm_put"].get("avg_iv")
    atm_iv = nearest["atm"].get("avg_iv")
    call_iv = nearest["otm_call"].get("avg_iv")
    risk_reversal = float(call_iv) - float(put_iv) if put_iv is not None and call_iv is not None else None
    curvature = ((float(put_iv) + float(call_iv)) / 2.0 - float(atm_iv)) if put_iv is not None and call_iv is not None and atm_iv is not None else None

    term_items = sorted(term_structure.items())
    if len(term_items) >= 2:
        front_expiry, front_iv = term_items[0]
        back_expiry, back_iv = term_items[-1]
        slope = back_iv - front_iv
        if abs(slope) < 0.0025:
            shape = "flat"
        elif slope > 0:
            shape = "contango"
        else:
            shape = "backwardation"
    else:
        front_expiry = term_items[0][0] if term_items else None
        front_iv = term_items[0][1] if term_items else None
        back_expiry = None
        back_iv = None
        slope = None
        shape = "single_expiry"

    return {
        "underlying_price": snapshot.underlying_price,
        "nearest_expiry": nearest_expiry,
        "moneyness_buckets": buckets,
        "skew": {
            "put_call_skew": _round(skew_25d),
            "risk_reversal_proxy": _round(risk_reversal),
            "smile_curvature_proxy": _round(curvature),
            "note": "put_call_skew is put IV minus call IV; risk_reversal_proxy is call IV minus put IV for nearest-expiry OTM buckets.",
        },
        "term_regime": {
            "front_expiry": front_expiry,
            "back_expiry": back_expiry,
            "front_iv": _round(front_iv),
            "back_iv": _round(back_iv),
            "slope": _round(slope),
            "shape": shape,
        },
    }


def _exposure(enriched: list[EnrichedOptionQuote]) -> ExposureSummary:
    total_gex = sum(row.gex_per_1pct or 0.0 for row in enriched)
    total_abs_gex = sum(abs(row.gex_per_1pct or 0.0) for row in enriched)
    total_dex = sum(row.dex or 0.0 for row in enriched)
    by_strike_map: dict[float, dict[str, float]] = defaultdict(lambda: {"strike": 0.0, "gex": 0.0, "abs_gex": 0.0, "dex": 0.0, "open_interest": 0.0})
    for row in enriched:
        bucket = by_strike_map[row.quote.strike]
        bucket["strike"] = row.quote.strike
        bucket["gex"] += row.gex_per_1pct or 0.0
        bucket["abs_gex"] += abs(row.gex_per_1pct or 0.0)
        bucket["dex"] += row.dex or 0.0
        bucket["open_interest"] += row.quote.open_interest
    by_strike = [by_strike_map[key] for key in sorted(by_strike_map)]
    return ExposureSummary(total_gex=total_gex, total_abs_gex=total_abs_gex, total_dex=total_dex, by_strike=by_strike)


def _signed_gex_at_price(snapshot: OptionChainSnapshot, enriched: list[EnrichedOptionQuote], futures_price: float, risk_free_rate: float) -> float:
    value = 0.0
    for row in enriched:
        if not row.implied_volatility:
            continue
        greeks = black76_greeks(
            futures_price,
            row.quote.strike,
            row.time_to_expiry,
            risk_free_rate,
            row.implied_volatility,
            row.quote.call_put,
        )
        signed = 1.0 if row.quote.call_put == "C" else -1.0
        value += signed * greeks.gamma * row.quote.open_interest * futures_price * futures_price * 0.01
    return value


def _gamma_flip(snapshot: OptionChainSnapshot, enriched: list[EnrichedOptionQuote], risk_free_rate: float) -> float | None:
    f0 = snapshot.underlying_price
    grid = [f0 * (0.85 + i * 0.01) for i in range(31)]
    values = [_signed_gex_at_price(snapshot, enriched, x, risk_free_rate) for x in grid]
    for idx in range(1, len(grid)):
        prev, cur = values[idx - 1], values[idx]
        if prev == 0:
            return grid[idx - 1]
        if prev * cur < 0:
            x0, x1 = grid[idx - 1], grid[idx]
            return x0 + (x1 - x0) * abs(prev) / (abs(prev) + abs(cur))
    return None


def analyze_option_chain(
    symbol: str,
    trade_date: str | None = None,
    expiry: str | None = None,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> OptionAnalyticsReport:
    """Load a SHFE option chain and compute Phase-1 core analytics."""
    snapshot = load_option_chain_snapshot(symbol, trade_date=trade_date, expiry=expiry)
    enriched = _enrich(snapshot, risk_free_rate)
    call_oi = sum(row.open_interest for row in snapshot.options if row.call_put == "C")
    put_oi = sum(row.open_interest for row in snapshot.options if row.call_put == "P")
    call_vol = sum(row.volume for row in snapshot.options if row.call_put == "C")
    put_vol = sum(row.volume for row in snapshot.options if row.call_put == "P")
    exposure = _exposure(enriched)
    term_structure = _term_structure(enriched)
    skew_25d = _skew(snapshot, enriched)
    return OptionAnalyticsReport(
        product=snapshot.product,
        trade_date=snapshot.trade_date,
        underlying_symbol=snapshot.underlying_symbol,
        underlying_price=snapshot.underlying_price,
        atm_iv=_atm_iv(snapshot, enriched),
        skew_25d=skew_25d,
        term_structure=term_structure,
        vol_surface=_vol_surface(snapshot, enriched, term_structure, skew_25d),
        pcr_open_interest=_safe_ratio(put_oi, call_oi),
        pcr_volume=_safe_ratio(put_vol, call_vol),
        call_wall=_wall(snapshot.options, "C"),
        put_wall=_wall(snapshot.options, "P"),
        gamma_flip=_gamma_flip(snapshot, enriched, risk_free_rate),
        exposure=exposure,
        options=enriched,
        assumptions=[
            "black76_futures_option_model",
            f"risk_free_rate={risk_free_rate:.4f}",
            "dealer_position_unknown",
            "GEX/DEX are scenario/concentration metrics inferred from exchange OI, not verified dealer inventory",
            "contract_multiplier_not_applied: Phase-1 exposure is relative unless multiplier enrichment is added",
        ],
    )
