"""Phase 20B tests for true 25-delta skew instead of moneyness proxies."""

from __future__ import annotations

import math
import sqlite3
from statistics import NormalDist

import pytest


def _strike_for_black76_delta(
    *,
    futures_price: float,
    time_to_expiry: float,
    risk_free_rate: float,
    volatility: float,
    option_type: str,
    abs_delta: float = 0.25,
) -> float:
    discount = math.exp(-risk_free_rate * time_to_expiry)
    if option_type == "C":
        nd1 = abs_delta / discount
    else:
        nd1 = 1.0 - abs_delta / discount
    d1 = NormalDist().inv_cdf(nd1)
    return futures_price / math.exp(d1 * volatility * math.sqrt(time_to_expiry) - 0.5 * volatility * volatility * time_to_expiry)


def _insert_exact_25_delta_quotes(db_path, *, put_iv: float = 0.31, call_iv: float = 0.22) -> tuple[float, float]:
    from tradingagents.options.pricing import black76_price

    futures_price = 80500.0
    risk_free_rate = 0.015
    time_to_expiry = 55 / 365
    put_strike = _strike_for_black76_delta(
        futures_price=futures_price,
        time_to_expiry=time_to_expiry,
        risk_free_rate=risk_free_rate,
        volatility=put_iv,
        option_type="P",
    )
    call_strike = _strike_for_black76_delta(
        futures_price=futures_price,
        time_to_expiry=time_to_expiry,
        risk_free_rate=risk_free_rate,
        volatility=call_iv,
        option_type="C",
    )
    put_price = black76_price(futures_price, put_strike, time_to_expiry, risk_free_rate, put_iv, "P")
    call_price = black76_price(futures_price, call_strike, time_to_expiry, risk_free_rate, call_iv, "C")

    with sqlite3.connect(db_path) as con:
        con.executemany(
            """
            insert into vw_shfe_option_chain_latest values
                (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    "20260501",
                    "CU2606P25DTRUE.SHF",
                    "铜真25Delta看跌",
                    "CU",
                    "P",
                    put_strike,
                    "20260625",
                    "OPCU2606.SHF",
                    "OPCU2606.SHF",
                    "CU2606",
                    put_price,
                    put_price,
                    put_price,
                    put_price,
                    put_price,
                    put_price,
                    put_price,
                    1000,
                    2000,
                    5000,
                ),
                (
                    "20260501",
                    "CU2606C25DTRUE.SHF",
                    "铜真25Delta看涨",
                    "CU",
                    "C",
                    call_strike,
                    "20260625",
                    "OPCU2606.SHF",
                    "OPCU2606.SHF",
                    "CU2606",
                    call_price,
                    call_price,
                    call_price,
                    call_price,
                    call_price,
                    call_price,
                    call_price,
                    1000,
                    2000,
                    5000,
                ),
            ],
        )
        con.commit()
    return put_strike, call_strike


def test_skew_25d_uses_true_option_delta_not_three_percent_moneyness_proxy(shfe_options_db):
    from tradingagents.options.analytics import analyze_option_chain

    put_strike, call_strike = _insert_exact_25_delta_quotes(shfe_options_db, put_iv=0.31, call_iv=0.22)

    report = analyze_option_chain("CU", trade_date="2026-05-01", risk_free_rate=0.015)
    skew = report.vol_surface["skew"]

    assert report.skew_25d == pytest.approx(0.31 - 0.22, abs=1e-4)
    assert skew["method"] == "delta_25"
    assert skew["put_25d_iv"] == pytest.approx(0.31, abs=1e-4)
    assert skew["call_25d_iv"] == pytest.approx(0.22, abs=1e-4)
    assert skew["put_25d_strike"] == pytest.approx(put_strike, rel=1e-4)
    assert skew["call_25d_strike"] == pytest.approx(call_strike, rel=1e-4)
    assert skew["put_25d_delta"] == pytest.approx(-0.25, abs=1e-4)
    assert skew["call_25d_delta"] == pytest.approx(0.25, abs=1e-4)


def test_true_25d_skew_metadata_is_exposed_in_tool_payload_and_markdown(shfe_options_db):
    import json

    from tradingagents.agents.utils.options_tools import get_option_analytics_json, get_option_analytics_report

    _insert_exact_25_delta_quotes(shfe_options_db, put_iv=0.30, call_iv=0.24)

    payload = json.loads(get_option_analytics_json.invoke({"symbol": "CU", "trade_date": "2026-05-01"}))
    skew = payload["vol_surface"]["skew"]
    assert skew["method"] == "delta_25"
    assert skew["put_call_skew"] == pytest.approx(0.06, abs=1e-4)
    assert "put_25d_delta" in skew
    assert "call_25d_delta" in skew

    markdown = get_option_analytics_report.invoke({"symbol": "CU", "trade_date": "2026-05-01"})
    assert "25Δ skew" in markdown
    assert "method delta_25" in markdown
