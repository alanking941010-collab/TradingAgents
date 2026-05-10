from __future__ import annotations

from pathlib import Path


def test_alan_data_warehouse_defaults_are_centralized_and_shared(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_METALS_DB", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_SHFE_OPTIONS_DB", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_TUSHARE_DB", raising=False)

    from tradingagents.dataflows import alan_business_db, local_paths
    from tradingagents.options import data_loader

    assert alan_business_db.DEFAULT_METALS_DB == local_paths.DEFAULT_METALS_DB
    assert alan_business_db.DEFAULT_SHFE_OPTIONS_DB == local_paths.DEFAULT_SHFE_OPTIONS_DB
    assert alan_business_db.DEFAULT_TUSHARE_DB == local_paths.DEFAULT_TUSHARE_DB
    assert data_loader.DEFAULT_SHFE_OPTIONS_DB == local_paths.DEFAULT_SHFE_OPTIONS_DB

    assert alan_business_db._metals_db() == local_paths.metals_db_path()
    assert alan_business_db._shfe_db() == local_paths.shfe_options_db_path()
    assert alan_business_db._tushare_db() == local_paths.tushare_db_path()
    assert data_loader.shfe_db_path() == local_paths.shfe_options_db_path()


def test_alan_data_warehouse_env_overrides_remain_shared(monkeypatch, tmp_path):
    metals = tmp_path / "metals_data.db"
    shfe = tmp_path / "shfe_options.db"
    tushare = tmp_path / "tushare.db"
    monkeypatch.setenv("TRADINGAGENTS_METALS_DB", str(metals))
    monkeypatch.setenv("TRADINGAGENTS_SHFE_OPTIONS_DB", str(shfe))
    monkeypatch.setenv("TRADINGAGENTS_TUSHARE_DB", str(tushare))

    from tradingagents.dataflows import alan_business_db, local_paths
    from tradingagents.options import data_loader

    assert local_paths.metals_db_path() == str(metals)
    assert local_paths.shfe_options_db_path() == str(shfe)
    assert local_paths.tushare_db_path() == str(tushare)

    assert alan_business_db._metals_db() == str(metals)
    assert alan_business_db._shfe_db() == str(shfe)
    assert alan_business_db._tushare_db() == str(tushare)
    assert data_loader.shfe_db_path() == str(shfe)


def test_alan_absolute_db_defaults_only_live_in_local_paths_module():
    repo = Path(__file__).resolve().parents[1]
    legacy_defaults = [
        str(Path("/mnt") / "e" / "star" / "projects" / "free-cme-lme-data-v1" / "data" / "metals_data.db"),
        str(Path("/mnt") / "e" / "star" / "projects" / "shfe-options-db-v1" / "data" / "shfe_options.db"),
        str(Path("/mnt") / "e" / "star" / "data" / "tushare" / "tushare.db"),
    ]

    centralized = repo / "tradingagents" / "dataflows" / "local_paths.py"
    centralized_text = centralized.read_text(encoding="utf-8")
    for legacy_default in legacy_defaults:
        assert legacy_default in centralized_text

    duplicated_modules = [
        repo / "tradingagents" / "options" / "data_loader.py",
        repo / "tradingagents" / "dataflows" / "alan_business_db.py",
    ]
    for module_path in duplicated_modules:
        text = module_path.read_text(encoding="utf-8")
        for legacy_default in legacy_defaults:
            assert legacy_default not in text
