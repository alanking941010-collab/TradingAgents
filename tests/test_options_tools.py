"""Tests for option analytics tools exposed to TradingAgents agents."""

from __future__ import annotations

import json
import sqlite3

import pytest


@pytest.fixture()
def shfe_options_db(tmp_path, monkeypatch):
    db_path = tmp_path / "shfe_options.db"
    con = sqlite3.connect(db_path)
    try:
        con.executescript(
            """
            create table futures_daily (
                trade_date text, ts_code text, pre_close real, pre_settle real,
                open real, high real, low real, close real, settle real,
                change1 real, change2 real, vol real, amount real, oi real
            );
            insert into futures_daily values
                ('20260501','CU2606.SHF',79800,79750,80000,81200,79000,80500,80400,700,650,120000,500000,220000),
                ('20260501','CU.SHF',79800,79750,80000,81200,79000,80500,80400,700,650,120000,500000,220000);

            create table vw_shfe_option_chain_latest (
                trade_date text, ts_code text, name text, metal text, call_put text,
                strike real, maturity_date text, opt_code text, underlying_fut_code text,
                underlying_symbol text, pre_settle real, pre_close real, open real, high real,
                low real, close real, settle real, volume real, amount real, open_interest real
            );
            insert into vw_shfe_option_chain_latest values
                ('20260501','CU2606C78000.SHF','铜看涨78000','CU','C',78000,'20260625','OPCU2606.SHF','OPCU2606.SHF','CU2606',3200,3150,3300,3500,3100,3400,3380,900,2000,1200),
                ('20260501','CU2606C80000.SHF','铜看涨80000','CU','C',80000,'20260625','OPCU2606.SHF','OPCU2606.SHF','CU2606',2200,2150,2300,2500,2100,2450,2400,1200,2600,3000),
                ('20260501','CU2606C82000.SHF','铜看涨82000','CU','C',82000,'20260625','OPCU2606.SHF','OPCU2606.SHF','CU2606',1200,1180,1300,1500,1150,1450,1420,1800,3000,5000),
                ('20260501','CU2606P78000.SHF','铜看跌78000','CU','P',78000,'20260625','OPCU2606.SHF','OPCU2606.SHF','CU2606',900,880,950,1100,850,1000,980,1600,2200,7000),
                ('20260501','CU2606P80000.SHF','铜看跌80000','CU','P',80000,'20260625','OPCU2606.SHF','OPCU2606.SHF','CU2606',1300,1280,1350,1550,1250,1500,1480,1300,2100,2500),
                ('20260501','CU2606P82000.SHF','铜看跌82000','CU','P',82000,'20260625','OPCU2606.SHF','OPCU2606.SHF','CU2606',1900,1880,1950,2150,1850,2100,2080,1100,2000,1500);
            """
        )
        con.commit()
    finally:
        con.close()
    monkeypatch.setenv("TRADINGAGENTS_SHFE_OPTIONS_DB", str(db_path))
    return db_path


def test_build_option_trade_context_is_compact_and_volatility_first(shfe_options_db):
    from tradingagents.agents.utils.options_tools import build_option_trade_context

    context = build_option_trade_context("铜", trade_date="2026-05-01", expiry="20260625")

    assert context["product"] == "CU"
    assert context["underlying"]["price"] == pytest.approx(80500)
    assert context["underlying"]["price_basis"] == "close"
    assert context["volatility"]["atm_iv"] > 0
    assert context["positioning"]["pcr_oi"] > 0
    assert context["positioning"]["call_wall"]["strike"] == 82000
    assert context["risk_assumptions"]["risk_free_rate"] == 0.015
    assert context["risk_assumptions"]["dealer_position_unknown"] is True
    assert context["agent_lens"]["market_analyst"] == "underlying trend, RV, technical context, and futures anchor"
    assert "volatility" in context["agent_lens"]["fundamentals_analyst"]
    assert "options" not in json.dumps(context).lower() or len(json.dumps(context)) < 6000


def test_get_option_trade_context_tool_returns_parseable_json(shfe_options_db):
    from tradingagents.agents.utils.options_tools import get_option_trade_context

    raw = get_option_trade_context.invoke({"symbol": "CU", "trade_date": "2026-05-01", "expiry": "20260625"})
    payload = json.loads(raw)

    assert payload["product"] == "CU"
    assert payload["risk_assumptions"]["price_basis"] == "option close + futures close"
    assert payload["volatility"]["atm_iv"] > 0


def test_get_option_analytics_report_tool_returns_markdown(shfe_options_db):
    from tradingagents.agents.utils.options_tools import get_option_analytics_report

    report = get_option_analytics_report.invoke({"symbol": "CU", "trade_date": "2026-05-01", "expiry": "20260625"})

    assert report.startswith("# Options analytics core: CU")
    assert "Price basis: option close + futures close" in report
    assert "dealer_position_unknown" in report


def test_get_option_analytics_json_tool_keeps_full_chain_for_audit(shfe_options_db):
    from tradingagents.agents.utils.options_tools import get_option_analytics_json

    raw = get_option_analytics_json.invoke({"symbol": "CU", "trade_date": "2026-05-01", "expiry": "20260625"})
    payload = json.loads(raw)

    assert payload["assumptions"]["price_basis"] == "option close + futures close"
    assert len(payload["options"]) == 6
    assert payload["options"][0]["price_used"] == payload["options"][0]["close"]
