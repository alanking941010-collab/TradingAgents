"""Tests for Alan's local business SQLite dataflow vendor.

The vendor should replace network-first yfinance/alpha_vantage data access with
read-only queries against Alan's three local warehouses:
- metals_data.db
- shfe_options.db
- tushare.db
"""

import sqlite3

import pytest

from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.interface import VENDOR_LIST, route_to_vendor
from tradingagents.default_config import DEFAULT_CONFIG


def _exec_many(db_path, statements):
    con = sqlite3.connect(db_path)
    try:
        for sql in statements:
            con.execute(sql)
        con.commit()
    finally:
        con.close()


@pytest.fixture()
def alan_business_dbs(tmp_path, monkeypatch):
    metals = tmp_path / "metals_data.db"
    shfe = tmp_path / "shfe_options.db"
    tushare = tmp_path / "tushare.db"

    _exec_many(
        metals,
        [
            """
            create table v_daily_prices_std (
                date text, exchange text, venue text, product_group text,
                product text, contract text, open real, high real, low real,
                close real, settle real, volume real, oi real, source text,
                source_symbol text, contract_month text, symbol text, currency text
            )
            """,
            "insert into v_daily_prices_std values ('2026-05-01','CME Group','COMEX','base_metals','copper','COMEX_HG_202605',5.1,5.3,5.0,5.2,5.21,1000,2000,'unit_test','HG','202605','MAY26','USD')",
            "insert into v_daily_prices_std values ('2026-05-02','SHFE','SHFE','base_metals','copper','SHFE_CU_202606',80000,81000,79500,80800,80600,3000,4000,'unit_test','CU','202606','CU2606','CNY')",
            """
            create table v_lme_inventory_std (
                date text, metal text, total_stock real, cancelled_warrant real,
                region text, warehouse text, location text, live_warrant real, source text
            )
            """,
            "insert into v_lme_inventory_std values ('2026-05-01','copper',12345,100,'Asia','LMEWH','Singapore',12245,'unit_test')",
            """
            create table v_cn_inventory_std (
                date text, exchange text, symbol text, product text, fut_name text,
                warehouse text, pre_vol real, vol real, vol_chg real, unit text, source text
            )
            """,
            "insert into v_cn_inventory_std values ('2026-05-01','SHFE','CU','铜','沪铜','仓库A',900,1000,100,'吨','unit_test')",
            """
            create table v_cftc_cot_std (
                date text, market text, commercial_long real, commercial_short real,
                noncommercial_long real, noncommercial_short real, net_position real,
                open_interest real, report_type text, source text
            )
            """,
            "insert into v_cftc_cot_std values ('2026-04-28','copper',10,20,30,15,15,100,'legacy','unit_test')",
            """
            create table v_macro_overlay_std (
                date text, usd_index real, rates_us2y real, rates_us10y real,
                crude_wti real, crude_brent real, gold real, silver real, cnh real,
                etf_xme real, etf_gdx real, source text
            )
            """,
            "insert into v_macro_overlay_std values ('2026-05-01',100,4.1,4.2,70,74,3300,35,7.2,60,40,'unit_test')",
        ],
    )

    _exec_many(
        shfe,
        [
            """
            create table futures_daily (
                trade_date text, ts_code text, pre_close real, pre_settle real,
                open real, high real, low real, close real, settle real,
                change1 real, change2 real, vol real, amount real, oi real
            )
            """,
            "insert into futures_daily values ('20260501','CU.SHF',79000,78900,80000,81000,79800,80888,80666,1888,1766,10000,200000,300000)",
            """
            create table vw_shfe_option_chain_latest (
                trade_date text, ts_code text, name text, metal text, call_put text,
                strike real, maturity_date text, opt_code text, underlying_fut_code text,
                underlying_symbol text, pre_settle real, pre_close real, open real, high real,
                low real, close real, settle real, vol real, amount real, oi real
            )
            """,
            "insert into vw_shfe_option_chain_latest values ('20260501','CU2606C80000.SHF','铜看涨','CU','C',80000,'20260625','CU2606C80000','CU2606','CU',100,101,102,110,99,105,106,1000,2000,3000)",
        ],
    )

    _exec_many(
        tushare,
        [
            """
            create table raw_fut_daily (
                ts_code text, trade_date text, pre_close real, pre_settle real,
                open real, high real, low real, close real, settle real,
                change1 real, change2 real, vol real, amount real, oi real
            )
            """,
            "insert into raw_fut_daily values ('CU.SHF','20260501',79000,78900,80000,81000,79800,80888,80666,1888,1766,10000,200000,300000)",
            """
            create table raw_news (
                datetime text, content text, title text, _partition_key text, _ingested_at text, channels text
            )
            """,
            "insert into raw_news values ('2026-05-01 09:00:00','Copper inventory fell in Asia','Copper test news','20260501','2026-05-01T09:01:00','metal')",
            """
            create table raw_major_news (
                title text, content text, pub_time text, src text, _partition_key text, _ingested_at text
            )
            """,
            "insert into raw_major_news values ('Global macro test','Dollar and copper moved','2026-05-01 08:00:00','unit','20260501','2026-05-01T08:01:00')",
        ],
    )

    monkeypatch.setenv("TRADINGAGENTS_METALS_DB", str(metals))
    monkeypatch.setenv("TRADINGAGENTS_SHFE_OPTIONS_DB", str(shfe))
    monkeypatch.setenv("TRADINGAGENTS_TUSHARE_DB", str(tushare))

    cfg = DEFAULT_CONFIG.copy()
    cfg["data_vendors"] = {
        "core_stock_apis": "alan_db",
        "technical_indicators": "alan_db",
        "fundamental_data": "alan_db",
        "news_data": "alan_db",
    }
    cfg["tool_vendors"] = {}
    set_config(cfg)
    yield {"metals": metals, "shfe": shfe, "tushare": tushare}
    set_config(DEFAULT_CONFIG.copy())


def test_alan_db_vendor_is_registered():
    assert "alan_db" in VENDOR_LIST


def test_route_stock_data_uses_local_business_dbs(alan_business_dbs):
    result = route_to_vendor("get_stock_data", "CU", "2026-05-01", "2026-05-03")
    assert "Alan business DB" in result
    assert "metals_data.db" in result
    assert "shfe_options.db" in result
    assert "COMEX_HG_202605" in result
    assert "CU.SHF" in result
    assert "unit_test" in result


def test_route_indicators_calculates_from_local_ohlcv(alan_business_dbs):
    result = route_to_vendor("get_indicators", "CU", "close_10_ema", "2026-05-03", 10)
    assert "close_10_ema" in result
    assert "Alan business DB" in result
    assert "2026-05-01" in result


def test_route_fundamentals_combines_three_business_dbs(alan_business_dbs):
    result = route_to_vendor("get_fundamentals", "CU", "2026-05-03")
    assert "Alan business DB fundamentals/context" in result
    assert "LME inventory" in result
    assert "CN inventory" in result
    assert "CFTC COT" in result
    assert "SHFE option chain" in result
    assert "Macro overlay" in result


def test_route_news_uses_tushare_local_news(alan_business_dbs):
    result = route_to_vendor("get_news", "CU", "2026-05-01", "2026-05-02")
    assert "Alan business DB news" in result
    assert "Copper test news" in result
    assert "Copper inventory fell" in result


def test_route_news_handles_empty_local_news_without_crashing(alan_business_dbs):
    result = route_to_vendor("get_news", "NI", "2026-06-01", "2026-06-02")
    assert "Alan business DB news" in result
    assert "No rows found" in result
