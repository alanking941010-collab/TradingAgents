"""Black-76 pricing helpers for futures options."""

from __future__ import annotations

import math

_EPS = 1e-12


def normal_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _cp(option_type: str) -> int:
    opt = (option_type or "").upper()[:1]
    if opt == "C":
        return 1
    if opt == "P":
        return -1
    raise ValueError(f"option_type must be C/call or P/put, got {option_type!r}")


def _d1_d2(futures_price: float, strike: float, time_to_expiry: float, volatility: float) -> tuple[float, float]:
    if futures_price <= 0 or strike <= 0:
        raise ValueError("futures_price and strike must be positive")
    if time_to_expiry <= 0 or volatility <= 0:
        raise ValueError("time_to_expiry and volatility must be positive")
    sigma_sqrt_t = volatility * math.sqrt(time_to_expiry)
    d1 = (math.log(futures_price / strike) + 0.5 * volatility * volatility * time_to_expiry) / sigma_sqrt_t
    return d1, d1 - sigma_sqrt_t


def black76_price(
    futures_price: float,
    strike: float,
    time_to_expiry: float,
    risk_free_rate: float,
    volatility: float,
    option_type: str,
) -> float:
    """Return the Black-76 price for an option on a futures contract."""
    sign = _cp(option_type)
    if time_to_expiry <= 0 or volatility <= 0:
        intrinsic = max(sign * (futures_price - strike), 0.0)
        return intrinsic
    d1, d2 = _d1_d2(futures_price, strike, time_to_expiry, volatility)
    discount = math.exp(-risk_free_rate * time_to_expiry)
    if sign == 1:
        return discount * (futures_price * normal_cdf(d1) - strike * normal_cdf(d2))
    return discount * (strike * normal_cdf(-d2) - futures_price * normal_cdf(-d1))


def black76_intrinsic(futures_price: float, strike: float, risk_free_rate: float, time_to_expiry: float, option_type: str) -> float:
    sign = _cp(option_type)
    return math.exp(-risk_free_rate * max(time_to_expiry, 0.0)) * max(sign * (futures_price - strike), 0.0)


def implied_volatility(
    option_price: float,
    futures_price: float,
    strike: float,
    time_to_expiry: float,
    risk_free_rate: float,
    option_type: str,
    *,
    lower: float = 1e-6,
    upper: float = 5.0,
    tolerance: float = 1e-7,
    max_iter: int = 120,
) -> float | None:
    """Invert Black-76 by bisection.

    Returns None for impossible or missing inputs instead of fabricating an IV.
    """
    if option_price is None or option_price <= 0 or futures_price <= 0 or strike <= 0 or time_to_expiry <= 0:
        return None
    intrinsic = black76_intrinsic(futures_price, strike, risk_free_rate, time_to_expiry, option_type)
    if option_price < intrinsic - 1e-8:
        return None

    lo, hi = lower, upper
    lo_price = black76_price(futures_price, strike, time_to_expiry, risk_free_rate, lo, option_type)
    hi_price = black76_price(futures_price, strike, time_to_expiry, risk_free_rate, hi, option_type)
    if option_price <= lo_price:
        return lo
    while hi_price < option_price and hi < 10.0:
        hi *= 2.0
        hi_price = black76_price(futures_price, strike, time_to_expiry, risk_free_rate, hi, option_type)
    if hi_price < option_price:
        return None

    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        mid_price = black76_price(futures_price, strike, time_to_expiry, risk_free_rate, mid, option_type)
        if abs(mid_price - option_price) <= tolerance:
            return mid
        if mid_price < option_price:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)
