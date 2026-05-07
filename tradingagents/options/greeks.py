"""Black-76 Greeks for futures options."""

from __future__ import annotations

import math
from dataclasses import dataclass

from tradingagents.options.pricing import _cp, _d1_d2, normal_cdf, normal_pdf


@dataclass(frozen=True)
class Greeks:
    delta: float
    gamma: float
    vega: float
    theta: float


def black76_greeks(
    futures_price: float,
    strike: float,
    time_to_expiry: float,
    risk_free_rate: float,
    volatility: float,
    option_type: str,
) -> Greeks:
    """Return Black-76 delta/gamma/vega/theta for one option contract.

    Vega is per 1.00 volatility point, not per 1 vol point percentage.
    """
    sign = _cp(option_type)
    if time_to_expiry <= 0 or volatility <= 0 or futures_price <= 0 or strike <= 0:
        return Greeks(delta=0.0, gamma=0.0, vega=0.0, theta=0.0)
    d1, d2 = _d1_d2(futures_price, strike, time_to_expiry, volatility)
    discount = math.exp(-risk_free_rate * time_to_expiry)
    sqrt_t = math.sqrt(time_to_expiry)
    if sign == 1:
        delta = discount * normal_cdf(d1)
        theta = (
            -discount * futures_price * normal_pdf(d1) * volatility / (2.0 * sqrt_t)
            + risk_free_rate * discount * (futures_price * normal_cdf(d1) - strike * normal_cdf(d2))
        )
    else:
        delta = discount * (normal_cdf(d1) - 1.0)
        theta = (
            -discount * futures_price * normal_pdf(d1) * volatility / (2.0 * sqrt_t)
            + risk_free_rate * discount * (strike * normal_cdf(-d2) - futures_price * normal_cdf(-d1))
        )
    gamma = discount * normal_pdf(d1) / (futures_price * volatility * sqrt_t)
    vega = discount * futures_price * normal_pdf(d1) * sqrt_t
    return Greeks(delta=delta, gamma=gamma, vega=vega, theta=theta)
