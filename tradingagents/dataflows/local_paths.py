"""Centralized Alan local data warehouse path configuration.

The defaults describe Alan's WSL-mounted local SQLite warehouses. They are
intentional local-environment defaults and every path remains overrideable via
its corresponding ``TRADINGAGENTS_*_DB`` environment variable.
"""

from __future__ import annotations

import os

METALS_DB_ENV = "TRADINGAGENTS_METALS_DB"
SHFE_OPTIONS_DB_ENV = "TRADINGAGENTS_SHFE_OPTIONS_DB"
TUSHARE_DB_ENV = "TRADINGAGENTS_TUSHARE_DB"

DEFAULT_METALS_DB = "/mnt/e/star/projects/free-cme-lme-data-v1/data/metals_data.db"
DEFAULT_SHFE_OPTIONS_DB = "/mnt/e/star/projects/shfe-options-db-v1/data/shfe_options.db"
DEFAULT_TUSHARE_DB = "/mnt/e/star/data/tushare/tushare.db"


def local_db_path(env_name: str, default: str) -> str:
    """Resolve a local DB path from env override, falling back to its default."""
    return os.getenv(env_name, default)


def metals_db_path() -> str:
    """Resolve the cross-market metals SQLite warehouse path."""
    return local_db_path(METALS_DB_ENV, DEFAULT_METALS_DB)


def shfe_options_db_path() -> str:
    """Resolve the SHFE options/futures SQLite warehouse path."""
    return local_db_path(SHFE_OPTIONS_DB_ENV, DEFAULT_SHFE_OPTIONS_DB)


def tushare_db_path() -> str:
    """Resolve the local Tushare SQLite warehouse path."""
    return local_db_path(TUSHARE_DB_ENV, DEFAULT_TUSHARE_DB)


__all__ = [
    "DEFAULT_METALS_DB",
    "DEFAULT_SHFE_OPTIONS_DB",
    "DEFAULT_TUSHARE_DB",
    "METALS_DB_ENV",
    "SHFE_OPTIONS_DB_ENV",
    "TUSHARE_DB_ENV",
    "local_db_path",
    "metals_db_path",
    "shfe_options_db_path",
    "tushare_db_path",
]
