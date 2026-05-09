"""Read-only loader for Alan's local SHFE options warehouse."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterable

from tradingagents.options.models import OptionChainSnapshot, OptionQuote

SHFE_OPTIONS_DB_ENV = "TRADINGAGENTS_SHFE_OPTIONS_DB"
DEFAULT_SHFE_OPTIONS_DB = "/mnt/e/star/projects/shfe-options-db-v1/data/shfe_options.db"

_ALIASES = {
    "cu": "CU",
    "copper": "CU",
    "铜": "CU",
    "hg": "CU",
    "au": "AU",
    "gold": "AU",
    "黄金": "AU",
    "gc": "AU",
    "ag": "AG",
    "silver": "AG",
    "白银": "AG",
    "si": "AG",
    "al": "AL",
    "aluminum": "AL",
    "aluminium": "AL",
    "铝": "AL",
    "zn": "ZN",
    "zinc": "ZN",
    "锌": "ZN",
    "ni": "NI",
    "nickel": "NI",
    "镍": "NI",
    "pb": "PB",
    "lead": "PB",
    "铅": "PB",
    "sn": "SN",
    "tin": "SN",
    "锡": "SN",
    "ao": "AO",
    "alumina": "AO",
    "氧化铝": "AO",
}


def normalize_product(symbol: str) -> str:
    raw = (symbol or "").strip()
    key = raw.lower().replace(".shf", "")
    key_no_digits = "".join(ch for ch in key if not ch.isdigit()) or key
    return _ALIASES.get(key_no_digits, key_no_digits.upper())


def format_ymd(date_str: str | None) -> str | None:
    if not date_str:
        return None
    s = str(date_str).strip().replace("-", "")
    return s if len(s) == 8 and s.isdigit() else str(date_str)


def format_iso(date_str: str | None) -> str | None:
    if not date_str:
        return None
    s = str(date_str)
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def shfe_db_path() -> str:
    return os.getenv(SHFE_OPTIONS_DB_ENV, DEFAULT_SHFE_OPTIONS_DB)


def connect_shfe_ro(path: str | None = None) -> sqlite3.Connection:
    db_path = Path(path or shfe_db_path())
    if not db_path.exists():
        raise FileNotFoundError(f"SHFE options database not found: {db_path}")
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    return con


def _columns(con: sqlite3.Connection, table_or_view: str) -> set[str]:
    return {row[1] for row in con.execute(f"PRAGMA table_info({table_or_view})").fetchall()}


def _table_exists(con: sqlite3.Connection, table_or_view: str) -> bool:
    row = con.execute(
        "select 1 from sqlite_master where name=? and type in ('table','view') limit 1",
        (table_or_view,),
    ).fetchone()
    return row is not None


def _latest_trade_date(
    con: sqlite3.Connection,
    product: str,
    trade_date: str | None,
    date_mode: str,
) -> tuple[str, bool]:
    if trade_date:
        ymd = format_ymd(trade_date)
        if date_mode == "exact":
            row = con.execute(
                """
                select trade_date
                from vw_shfe_option_chain_latest
                where upper(metal)=? and trade_date=?
                limit 1
                """,
                (product, ymd),
            ).fetchone()
        elif date_mode == "asof":
            row = con.execute(
                """
                select max(trade_date) as trade_date
                from vw_shfe_option_chain_latest
                where upper(metal)=? and trade_date<=?
                """,
                (product, ymd),
            ).fetchone()
        else:
            raise ValueError("date_mode must be 'exact' or 'asof' when trade_date is provided")
    else:
        row = con.execute(
            """
            select max(trade_date) as trade_date
            from vw_shfe_option_chain_latest
            where upper(metal)=?
            """,
            (product,),
        ).fetchone()
        ymd = None
    if not row or not row["trade_date"]:
        if trade_date and date_mode == "exact":
            raise ValueError(f"No exact trade_date match found for {product} trade_date={trade_date!r}")
        raise ValueError(f"No SHFE option chain rows found for {product} trade_date={trade_date!r}")
    resolved = row["trade_date"]
    return resolved, bool(ymd and resolved != ymd)


def _query_options(
    con: sqlite3.Connection,
    product: str,
    trade_ymd: str,
    expiry: str | None,
) -> list[sqlite3.Row]:
    cols = _columns(con, "vw_shfe_option_chain_latest")
    volume_col = "volume" if "volume" in cols else "vol"
    oi_col = "open_interest" if "open_interest" in cols else "oi"
    has_view_bid_ask = "bid" in cols and "ask" in cols
    has_snapshot_bid_ask = _table_exists(con, "akshare_option_snapshot") and {
        "bid",
        "ask",
        "metal",
        "strike",
        "call_put",
        "contract_month",
    }.issubset(_columns(con, "akshare_option_snapshot"))
    filters = ["upper(o.metal)=?", "o.trade_date=?"]
    params: list[object] = [product, trade_ymd]
    if expiry:
        filters.append("o.maturity_date=?")
        params.append(format_ymd(expiry))
    if has_view_bid_ask:
        bid_select = "o.bid as bid"
        ask_select = "o.ask as ask"
        join_clause = ""
    elif has_snapshot_bid_ask:
        bid_select = "q.bid as bid"
        ask_select = "q.ask as ask"
        join_clause = """
        left join akshare_option_snapshot q
          on upper(q.metal)=upper(o.metal)
         and q.trade_date=o.trade_date
         and q.contract_month=substr(replace(upper(o.ts_code), '.SHF', ''), length(upper(o.metal)) + 1, 4)
         and abs(q.strike - o.strike) < 1e-9
         and upper(q.call_put)=upper(o.call_put)
        """
    else:
        bid_select = "null as bid"
        ask_select = "null as ask"
        join_clause = ""
    sql = f"""
        select o.trade_date, o.ts_code, o.metal, o.call_put, o.strike, o.maturity_date,
               o.underlying_symbol, o.close, o.settle,
               coalesce(o.{volume_col}, 0) as volume,
               coalesce(o.{oi_col}, 0) as open_interest,
               {bid_select},
               {ask_select}
        from vw_shfe_option_chain_latest o
        {join_clause}
        where {' and '.join(filters)}
        order by o.maturity_date, o.strike, o.call_put
    """
    return con.execute(sql, params).fetchall()


def _pick_underlying_symbol(rows: Iterable[sqlite3.Row], product: str) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        symbol = row["underlying_symbol"] or product
        counts[symbol] = counts.get(symbol, 0) + 1
    if not counts:
        return f"{product}.SHF"
    return max(counts.items(), key=lambda item: item[1])[0]


def _load_underlying_price(con: sqlite3.Connection, product: str, trade_ymd: str, underlying_symbol: str) -> tuple[str, float, str, str]:
    candidates = []
    if underlying_symbol:
        u = underlying_symbol.upper().replace(".SHF", "")
        candidates.extend([f"{u}.SHF", u])
    candidates.extend([f"{product}.SHF", product])
    seen = []
    for item in candidates:
        if item not in seen:
            seen.append(item)
    placeholders = ",".join("?" for _ in seen)
    row = con.execute(
        f"""
        select trade_date, ts_code, close, settle
        from futures_daily
        where upper(ts_code) in ({placeholders}) and trade_date<=?
        order by trade_date desc,
                 case when upper(ts_code)=? then 0 when upper(ts_code)=? then 1 else 2 end
        limit 1
        """,
        [s.upper() for s in seen] + [trade_ymd, seen[0].upper(), f"{product}.SHF"],
    ).fetchone()
    if not row:
        raise ValueError(f"No underlying futures row found for {product}/{underlying_symbol} on or before {trade_ymd}")
    price = row["close"] if row["close"] is not None and row["close"] > 0 else row["settle"]
    basis = "close" if row["close"] is not None and row["close"] > 0 else "settle_fallback"
    if price is None or price <= 0:
        raise ValueError(f"Invalid underlying futures price for {row['ts_code']} on {row['trade_date']}")
    return row["ts_code"], float(price), format_iso(row["trade_date"]), basis


def load_option_chain_snapshot(
    symbol: str,
    trade_date: str | None = None,
    expiry: str | None = None,
    date_mode: str | None = None,
) -> OptionChainSnapshot:
    """Load a normalized SHFE option chain snapshot in read-only mode."""
    product = normalize_product(symbol)
    requested_trade_date = format_iso(trade_date)
    resolved_mode = date_mode or ("exact" if trade_date else "latest")
    lookup_mode = "asof" if resolved_mode == "latest" else resolved_mode
    with connect_shfe_ro() as con:
        trade_ymd, fallback_used = _latest_trade_date(con, product, trade_date, lookup_mode)
        rows = _query_options(con, product, trade_ymd, expiry)
        if not rows:
            raise ValueError(f"No SHFE option chain rows found for {product} trade_date={trade_date!r} expiry={expiry!r}")
        underlying_hint = _pick_underlying_symbol(rows, product)
        underlying_symbol, underlying_price, underlying_price_trade_date, underlying_price_basis = _load_underlying_price(
            con,
            product,
            trade_ymd,
            underlying_hint,
        )
        options = [
            OptionQuote(
                trade_date=format_iso(row["trade_date"]),
                ts_code=row["ts_code"],
                product=product,
                call_put=(row["call_put"] or "").upper()[:1],
                strike=float(row["strike"]),
                maturity_date=format_iso(row["maturity_date"]),
                underlying_symbol=row["underlying_symbol"] or underlying_symbol,
                close=None if row["close"] is None else float(row["close"]),
                settle=None if row["settle"] is None else float(row["settle"]),
                volume=float(row["volume"] or 0.0),
                open_interest=float(row["open_interest"] or 0.0),
                source="shfe_options.db:vw_shfe_option_chain_latest",
                bid=None if row["bid"] is None else float(row["bid"]),
                ask=None if row["ask"] is None else float(row["ask"]),
            )
            for row in rows
        ]
    return OptionChainSnapshot(
        product=product,
        trade_date=format_iso(trade_ymd),
        underlying_symbol=underlying_symbol,
        underlying_price=underlying_price,
        options=options,
        source="shfe_options.db:futures_daily+vw_shfe_option_chain_latest",
        requested_trade_date=requested_trade_date,
        trade_date_mode=resolved_mode,
        trade_date_fallback_used=fallback_used,
        underlying_price_trade_date=underlying_price_trade_date,
        underlying_price_basis=underlying_price_basis,
    )
