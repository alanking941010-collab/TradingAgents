"""Shared pytest fixtures that prevent CI hangs when API keys are absent."""

import os
import sqlite3
from unittest.mock import MagicMock, patch

import pytest


def pytest_configure(config):
    for marker in ("unit", "integration", "smoke"):
        config.addinivalue_line("markers", f"{marker}: {marker}-level tests")


_API_KEY_ENV_VARS = (
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "ZHIPU_API_KEY",
    "OPENROUTER_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "ALPHA_VANTAGE_API_KEY",
)


@pytest.fixture(autouse=True)
def _dummy_api_keys(monkeypatch):
    for env_var in _API_KEY_ENV_VARS:
        monkeypatch.setenv(env_var, os.environ.get(env_var, "placeholder"))


@pytest.fixture()
def mock_llm_client():
    client = MagicMock()
    client.get_llm.return_value = MagicMock()
    with patch(
        "tradingagents.llm_clients.factory.create_llm_client",
        return_value=client,
    ):
        yield client

@pytest.fixture()
def shfe_options_db(tmp_path, monkeypatch):
    """Create a compact SHFE options SQLite fixture shared by options tests."""
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
                ('20260501','CU2606P82000.SHF','铜看跌82000','CU','P',82000,'20260625','OPCU2606.SHF','OPCU2606.SHF','CU2606',1900,1880,1950,2150,1850,2100,2080,1100,2000,1500),
                ('20260501','CU2607C80000.SHF','铜看涨80000','CU','C',80000,'20260725','OPCU2607.SHF','OPCU2607.SHF','CU2607',3000,2950,3100,3300,2900,3150,3120,1000,2400,1800),
                ('20260501','CU2607P80000.SHF','铜看跌80000','CU','P',80000,'20260725','OPCU2607.SHF','OPCU2607.SHF','CU2607',2100,2050,2200,2400,2000,2300,2280,800,1900,1600);
            """
        )
        con.commit()
    finally:
        con.close()
    monkeypatch.setenv("TRADINGAGENTS_SHFE_OPTIONS_DB", str(db_path))
    return db_path
