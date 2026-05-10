"""Alan local business SQLite data vendor.

This vendor replaces the original network-first stock data channel with
read-only access to Alan's three local business warehouses:

- metals_data.db: cross-market metals prices, inventories, CFTC, macro overlays
- shfe_options.db: SHFE futures, options chain, warehouse stock
- tushare.db: Tushare futures/equities/news/fundamental raw tables

The public functions intentionally match the existing dataflow interface so the
LangChain tools can keep their original names while sourcing data locally.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

from tradingagents.dataflows import local_paths

METALS_DB_ENV = local_paths.METALS_DB_ENV
SHFE_OPTIONS_DB_ENV = local_paths.SHFE_OPTIONS_DB_ENV
TUSHARE_DB_ENV = local_paths.TUSHARE_DB_ENV

DEFAULT_METALS_DB = local_paths.DEFAULT_METALS_DB
DEFAULT_SHFE_OPTIONS_DB = local_paths.DEFAULT_SHFE_OPTIONS_DB
DEFAULT_TUSHARE_DB = local_paths.DEFAULT_TUSHARE_DB

_ALIASES = {
    "cu": ("copper", "CU"),
    "copper": ("copper", "CU"),
    "铜": ("copper", "CU"),
    "hg": ("copper", "CU"),
    "au": ("gold", "AU"),
    "gold": ("gold", "AU"),
    "黄金": ("gold", "AU"),
    "gc": ("gold", "AU"),
    "ag": ("silver", "AG"),
    "silver": ("silver", "AG"),
    "白银": ("silver", "AG"),
    "si": ("silver", "AG"),
    "al": ("aluminum", "AL"),
    "aluminum": ("aluminum", "AL"),
    "aluminium": ("aluminum", "AL"),
    "铝": ("aluminum", "AL"),
    "zn": ("zinc", "ZN"),
    "zinc": ("zinc", "ZN"),
    "锌": ("zinc", "ZN"),
    "ni": ("nickel", "NI"),
    "nickel": ("nickel", "NI"),
    "镍": ("nickel", "NI"),
    "pb": ("lead", "PB"),
    "lead": ("lead", "PB"),
    "铅": ("lead", "PB"),
    "sn": ("tin", "SN"),
    "tin": ("tin", "SN"),
    "锡": ("tin", "SN"),
    "ao": ("alumina", "AO"),
    "alumina": ("alumina", "AO"),
    "氧化铝": ("alumina", "AO"),
}


def _db_path(env_name: str, default: str) -> str:
    return local_paths.local_db_path(env_name, default)


def _metals_db() -> str:
    return local_paths.metals_db_path()


def _shfe_db() -> str:
    return local_paths.shfe_options_db_path()


def _tushare_db() -> str:
    return local_paths.tushare_db_path()


def _connect_ro(path: str) -> sqlite3.Connection:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Business database not found: {path}")
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    return con


def _table_exists(path: str, name: str) -> bool:
    try:
        with _connect_ro(path) as con:
            row = con.execute(
                "select 1 from sqlite_master where name=? and type in ('table','view')",
                (name,),
            ).fetchone()
            return row is not None
    except Exception:
        return False


def _read_sql(path: str, sql: str, params: Iterable = ()) -> pd.DataFrame:
    with _connect_ro(path) as con:
        return pd.read_sql_query(sql, con, params=tuple(params))


def _fmt_date_for_tushare(date_str: str) -> str:
    return date_str.replace("-", "")


def _fmt_date_iso(date_str: str) -> str:
    if not date_str:
        return date_str
    s = str(date_str)
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def _normalize_symbol(symbol: str) -> tuple[str, str, str]:
    raw = (symbol or "").strip()
    key = raw.lower().replace(".shf", "").replace(".sh", "").replace(".sz", "")
    key = "".join(ch for ch in key if not ch.isdigit()) or key
    product, metal_code = _ALIASES.get(key, (key, key.upper()))
    return raw.upper(), product, metal_code


def _format_df(title: str, df: pd.DataFrame, max_rows: int = 40) -> str:
    if df is None or df.empty:
        return f"## {title}\nNo rows found."
    shown = df.head(max_rows).copy()
    return f"## {title}\nRows: {len(df)} (showing {len(shown)})\n\n" + shown.to_csv(index=False)


def _safe_section(title: str, func) -> str:
    try:
        return func()
    except FileNotFoundError as exc:
        return f"## {title}\n{exc}"
    except Exception as exc:
        return f"## {title}\nError querying local DB: {type(exc).__name__}: {exc}"


def _local_ohlcv(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    raw, product, metal = _normalize_symbol(symbol)
    frames: list[pd.DataFrame] = []

    # Prefer SHFE options warehouse for domestic futures, because it is the
    # dedicated options/futures DB and includes latest underlying/option context.
    shfe_path = _shfe_db()
    if _table_exists(shfe_path, "futures_daily"):
        start_ymd, end_ymd = _fmt_date_for_tushare(start_date), _fmt_date_for_tushare(end_date)
        df = _read_sql(
            shfe_path,
            """
            select trade_date as date, ts_code as contract, open, high, low,
                   close, settle, vol as volume, amount, oi,
                   'shfe_options.db:futures_daily' as source
            from futures_daily
            where upper(ts_code) like ? and trade_date between ? and ?
            order by trade_date, ts_code
            limit 500
            """,
            (f"{metal}%", start_ymd, end_ymd),
        )
        if not df.empty:
            df["date"] = df["date"].map(_fmt_date_iso)
            frames.append(df)

    metals_path = _metals_db()
    if _table_exists(metals_path, "v_daily_prices_std"):
        df = _read_sql(
            metals_path,
            """
            select date, exchange, venue, product_group, product, contract,
                   open, high, low, close, settle, volume, oi, source,
                   source_symbol, contract_month, symbol, currency
            from v_daily_prices_std
            where date between ? and ?
              and (lower(product)=? or upper(symbol)=? or upper(contract) like ?)
            order by date, venue, contract
            limit 500
            """,
            (start_date, end_date, product, metal, f"%{metal}%"),
        )
        if not df.empty:
            frames.append(df)

    tushare_path = _tushare_db()
    if _table_exists(tushare_path, "raw_fut_daily"):
        start_ymd, end_ymd = _fmt_date_for_tushare(start_date), _fmt_date_for_tushare(end_date)
        df = _read_sql(
            tushare_path,
            """
            select trade_date as date, ts_code as contract, open, high, low,
                   close, settle, vol as volume, amount, oi,
                   'tushare.db:raw_fut_daily' as source
            from raw_fut_daily
            where upper(ts_code) like ? and trade_date between ? and ?
            order by trade_date, ts_code
            limit 500
            """,
            (f"{metal}%", start_ymd, end_ymd),
        )
        if not df.empty:
            df["date"] = df["date"].map(_fmt_date_iso)
            frames.append(df)

    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True, sort=False)
    for col in ["open", "high", "low", "close", "settle", "volume", "oi"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def get_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    """Return local OHLCV/futures data from Alan's business SQLite DBs."""
    df = _local_ohlcv(symbol, start_date, end_date)
    header = (
        f"# Alan business DB market data for {symbol.upper()} from {start_date} to {end_date}\n"
        f"# Sources: metals_data.db, shfe_options.db, tushare.db (read-only SQLite)\n\n"
    )
    if df.empty:
        return header + "No local market rows found for the requested instrument/date range."
    return header + _format_df("Local OHLCV / futures rows", df, max_rows=80)


def _indicator_series(df: pd.DataFrame, indicator: str) -> pd.Series:
    price = pd.to_numeric(df.get("close"), errors="coerce").fillna(
        pd.to_numeric(df.get("settle"), errors="coerce")
    )
    high = pd.to_numeric(df.get("high"), errors="coerce")
    low = pd.to_numeric(df.get("low"), errors="coerce")
    volume = pd.to_numeric(df.get("volume"), errors="coerce")
    ind = indicator.lower()

    if ind.endswith("_sma"):
        window = int(ind.split("_")[1])
        return price.rolling(window=window, min_periods=1).mean()
    if ind.endswith("_ema"):
        window = int(ind.split("_")[1])
        return price.ewm(span=window, adjust=False, min_periods=1).mean()
    if ind == "rsi":
        delta = price.diff()
        gain = delta.clip(lower=0).rolling(14, min_periods=1).mean()
        loss = (-delta.clip(upper=0)).rolling(14, min_periods=1).mean()
        rs = gain / loss.replace(0, pd.NA)
        return 100 - (100 / (1 + rs))
    if ind == "macd":
        return price.ewm(span=12, adjust=False, min_periods=1).mean() - price.ewm(span=26, adjust=False, min_periods=1).mean()
    if ind == "macds":
        macd = price.ewm(span=12, adjust=False, min_periods=1).mean() - price.ewm(span=26, adjust=False, min_periods=1).mean()
        return macd.ewm(span=9, adjust=False, min_periods=1).mean()
    if ind == "macdh":
        macd = _indicator_series(df, "macd")
        sig = macd.ewm(span=9, adjust=False, min_periods=1).mean()
        return macd - sig
    if ind == "boll":
        return price.rolling(20, min_periods=1).mean()
    if ind == "boll_ub":
        mid = price.rolling(20, min_periods=1).mean()
        std = price.rolling(20, min_periods=1).std().fillna(0)
        return mid + 2 * std
    if ind == "boll_lb":
        mid = price.rolling(20, min_periods=1).mean()
        std = price.rolling(20, min_periods=1).std().fillna(0)
        return mid - 2 * std
    if ind == "atr":
        prev_close = price.shift(1)
        tr = pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
        return tr.rolling(14, min_periods=1).mean()
    if ind == "vwma":
        return (price * volume).rolling(20, min_periods=1).sum() / volume.rolling(20, min_periods=1).sum()
    if ind == "mfi":
        typical = (high + low + price) / 3
        raw_flow = typical * volume
        direction = typical.diff().fillna(0)
        positive = raw_flow.where(direction >= 0, 0).rolling(14, min_periods=1).sum()
        negative = raw_flow.where(direction < 0, 0).rolling(14, min_periods=1).sum()
        ratio = positive / negative.replace(0, pd.NA)
        return 100 - (100 / (1 + ratio))
    raise ValueError(
        "Indicator {indicator} is not supported by alan_db. Supported: "
        "close_<N>_sma, close_<N>_ema, rsi, macd, macds, macdh, boll, "
        "boll_ub, boll_lb, atr, vwma, mfi".format(indicator=indicator)
    )


def get_indicator(symbol: str, indicator: str, curr_date: str, look_back_days: int = 30) -> str:
    curr = datetime.strptime(curr_date, "%Y-%m-%d")
    start = (curr - timedelta(days=int(look_back_days))).strftime("%Y-%m-%d")
    df = _local_ohlcv(symbol, start, curr_date)
    title = f"Alan business DB {indicator} values for {symbol.upper()} from {start} to {curr_date}"
    if df.empty:
        return f"## {title}\nNo local OHLCV rows available."
    # Use one row per date/source-contract combination. For multi-contract rows,
    # keep the first per date after source ordering so the output remains compact.
    df = df.sort_values(["date", "contract" if "contract" in df.columns else "source"]).drop_duplicates("date")
    df[indicator] = _indicator_series(df, indicator).round(6)
    return _format_df(title, df[["date", indicator, "close", "settle", "source"]], max_rows=80)


def _latest_by_date(path: str, table: str, date_col: str, where: str = "", params: Iterable = (), limit: int = 20) -> pd.DataFrame:
    if not _table_exists(path, table):
        return pd.DataFrame()
    sql = f'select * from "{table}"'
    if where:
        sql += f" where {where}"
    sql += f' order by "{date_col}" desc limit {int(limit)}'
    return _read_sql(path, sql, params)


def get_fundamentals(ticker: str, curr_date: Optional[str] = None) -> str:
    """Return commodity/futures context from Alan's local warehouses."""
    raw, product, metal = _normalize_symbol(ticker)
    sections = [
        f"# Alan business DB fundamentals/context for {ticker.upper()}\n"
        f"# Instrument mapping: product={product}, SHFE metal={metal}\n"
        f"# Sources: metals_data.db, shfe_options.db, tushare.db (read-only SQLite)"
    ]

    metals_path = _metals_db()
    shfe_path = _shfe_db()

    sections.append(_safe_section(
        "LME inventory",
        lambda: _format_df(
            "LME inventory",
            _latest_by_date(metals_path, "v_lme_inventory_std", "date", "lower(metal)=?", (product,), 20),
        ),
    ))
    sections.append(_safe_section(
        "CN inventory",
        lambda: _format_df(
            "CN inventory",
            _latest_by_date(metals_path, "v_cn_inventory_std", "date", "upper(symbol)=? or lower(product) like ?", (metal, f"%{product}%"), 20),
        ),
    ))
    sections.append(_safe_section(
        "CFTC COT",
        lambda: _format_df(
            "CFTC COT",
            _latest_by_date(metals_path, "v_cftc_cot_std", "date", "lower(market) like ?", (f"%{product}%",), 12),
        ),
    ))
    sections.append(_safe_section(
        "Macro overlay",
        lambda: _format_df(
            "Macro overlay",
            _latest_by_date(metals_path, "v_macro_overlay_std", "date", limit=10),
        ),
    ))
    sections.append(_safe_section(
        "SHFE option chain",
        lambda: _format_df(
            "SHFE option chain",
            _latest_by_date(shfe_path, "vw_shfe_option_chain_latest", "trade_date", "upper(metal)=?", (metal,), 40),
        ),
    ))
    return "\n\n".join(sections)


def get_balance_sheet(ticker: str, freq: str = "quarterly", curr_date: Optional[str] = None) -> str:
    return get_fundamentals(ticker, curr_date) + "\n\n# Note\nBalance-sheet-style context is mapped to warehouse inventory / market structure for commodity instruments."


def get_cashflow(ticker: str, freq: str = "quarterly", curr_date: Optional[str] = None) -> str:
    return get_fundamentals(ticker, curr_date) + "\n\n# Note\nCashflow-style context is mapped to positioning, inventories, and local market flow proxies for commodity instruments."


def get_income_statement(ticker: str, freq: str = "quarterly", curr_date: Optional[str] = None) -> str:
    return get_fundamentals(ticker, curr_date) + "\n\n# Note\nIncome-statement-style context is mapped to macro/price/inventory drivers for commodity instruments."


def get_news(ticker: str, start_date: str, end_date: str) -> str:
    raw, product, metal = _normalize_symbol(ticker)
    path = _tushare_db()
    start, end = f"{start_date} 00:00:00", f"{end_date} 23:59:59"
    frames: list[pd.DataFrame] = []
    if _table_exists(path, "raw_news"):
        frames.append(_read_sql(
            path,
            """
            select datetime as pub_time, title, content, channels, 'tushare.db:raw_news' as source
            from raw_news
            where datetime between ? and ?
              and (lower(title) like ? or lower(content) like ? or upper(title) like ? or upper(content) like ?)
            order by datetime desc
            limit 80
            """,
            (start, end, f"%{product}%", f"%{product}%", f"%{metal}%", f"%{metal}%"),
        ))
    if _table_exists(path, "raw_major_news"):
        frames.append(_read_sql(
            path,
            """
            select pub_time, title, content, src, 'tushare.db:raw_major_news' as source
            from raw_major_news
            where pub_time between ? and ?
            order by pub_time desc
            limit 80
            """,
            (start, end),
        ))
    nonempty = [f for f in frames if not f.empty]
    df = pd.concat(nonempty, ignore_index=True, sort=False) if nonempty else pd.DataFrame()
    return f"# Alan business DB news for {ticker.upper()} from {start_date} to {end_date}\n\n" + _format_df("Tushare local news", df, max_rows=40)


def get_global_news(curr_date: str, look_back_days: int = 7, limit: int = 5) -> str:
    curr = datetime.strptime(curr_date, "%Y-%m-%d")
    start = (curr - timedelta(days=int(look_back_days))).strftime("%Y-%m-%d")
    path = _tushare_db()
    frames: list[pd.DataFrame] = []
    if _table_exists(path, "raw_major_news"):
        frames.append(_read_sql(
            path,
            """
            select pub_time, title, content, src, 'tushare.db:raw_major_news' as source
            from raw_major_news
            where pub_time between ? and ?
            order by pub_time desc
            limit ?
            """,
            (f"{start} 00:00:00", f"{curr_date} 23:59:59", int(limit)),
        ))
    nonempty = [f for f in frames if not f.empty]
    df = pd.concat(nonempty, ignore_index=True, sort=False) if nonempty else pd.DataFrame()
    return f"# Alan business DB global news from {start} to {curr_date}\n\n" + _format_df("Tushare global/major news", df, max_rows=limit)


def get_insider_transactions(ticker: str) -> str:
    return (
        f"# Alan business DB insider transactions for {ticker.upper()}\n"
        "Insider transactions are not a primary commodity-market concept in Alan's three local business databases. "
        "Use get_fundamentals for inventories, SHFE option chain, CFTC positioning, and macro overlays."
    )
