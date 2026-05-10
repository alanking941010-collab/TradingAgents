"""CLI tests for scripts/analyze_options.py."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from scripts.options_cli_common import run_subprocess_checked


def _create_shfe_options_fixture(db_path: Path) -> None:
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


def test_analyze_options_cli_writes_json_and_markdown(tmp_path):
    db_path = tmp_path / "shfe_options.db"
    outdir = tmp_path / "out"
    _create_shfe_options_fixture(db_path)

    proc = run_subprocess_checked(
        [
            sys.executable,
            "scripts/analyze_options.py",
            "CU",
            "--date",
            "2026-05-01",
            "--expiry",
            "20260625",
            "--output-dir",
            str(outdir),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env_extra={"TRADINGAGENTS_SHFE_OPTIONS_DB": str(db_path)},
        timeout=30,
    )

    payload = json.loads(proc.stdout)
    assert payload["product"] == "CU"
    assert payload["trade_date"] == "2026-05-01"
    assert payload["price_basis"] == "close"
    assert payload["risk_free_rate"] == 0.015
    assert payload["atm_iv"] > 0

    json_path = Path(payload["output_json"])
    md_path = Path(payload["output_markdown"])
    assert json_path.exists()
    assert md_path.exists()

    saved = json.loads(json_path.read_text(encoding="utf-8"))
    assert saved["underlying_price"] == 80500
    assert saved["assumptions"]["price_basis"] == "option_close + futures_close"
    assert saved["options"][0]["price_used"] == saved["options"][0]["close"]

    markdown = md_path.read_text(encoding="utf-8")
    assert "# Options analytics core: CU" in markdown
    assert "Price basis: option close + futures close" in markdown
    assert "Output JSON" not in markdown


def test_analyze_options_cli_can_print_markdown(tmp_path):
    db_path = tmp_path / "shfe_options.db"
    _create_shfe_options_fixture(db_path)
    proc = run_subprocess_checked(
        [
            sys.executable,
            "scripts/analyze_options.py",
            "CU",
            "--date",
            "2026-05-01",
            "--expiry",
            "20260625",
            "--stdout",
            "markdown",
            "--output-dir",
            str(tmp_path / "out"),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env_extra={"TRADINGAGENTS_SHFE_OPTIONS_DB": str(db_path)},
        timeout=30,
    )

    assert proc.stdout.startswith("# Options analytics core: CU")
    assert "Price basis: option close + futures close" in proc.stdout
