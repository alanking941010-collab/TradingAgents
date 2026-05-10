# Alan Business DB Dataflow

This local fork replaces TradingAgents' default network-first data vendors (`yfinance` / `alpha_vantage`) with Alan's read-only SQLite business warehouses.

## Default vendor

`tradingagents/default_config.py` now sets every data category to:

```python
"alan_db"
```

Affected categories:

- `core_stock_apis`
- `technical_indicators`
- `fundamental_data`
- `news_data`

The original vendors remain registered as fallback-capable implementations, but they are no longer the default.

## Database paths

Default WSL paths are centralized in:

```text
tradingagents/dataflows/local_paths.py
```

| Alias | Path |
|---|---|
| `metals` | `/mnt/e/star/projects/free-cme-lme-data-v1/data/metals_data.db` |
| `shfe_options` | `/mnt/e/star/projects/shfe-options-db-v1/data/shfe_options.db` |
| `tushare` | `/mnt/e/star/data/tushare/tushare.db` |

Override with environment variables:

```bash
TRADINGAGENTS_METALS_DB=/path/to/metals_data.db
TRADINGAGENTS_SHFE_OPTIONS_DB=/path/to/shfe_options.db
TRADINGAGENTS_TUSHARE_DB=/path/to/tushare.db
```

All SQLite connections use `mode=ro`.

## Supported tool mapping

The public tool names are unchanged so the LangGraph agents can keep their existing wiring:

| TradingAgents tool | Alan local source behavior |
|---|---|
| `get_stock_data` | Local OHLCV/futures rows from `shfe_options.futures_daily`, `metals.v_daily_prices_std`, and `tushare.raw_fut_daily` |
| `get_indicators` | Technical indicators computed locally from local OHLCV rows |
| `get_fundamentals` | Commodity context: LME/CN inventories, CFTC COT, macro overlay, SHFE option chain |
| `get_balance_sheet` / `get_cashflow` / `get_income_statement` | Commodity-context aliases over the same inventory/positioning/macro/option-chain report |
| `get_news` / `get_global_news` | Local Tushare news tables (`raw_news`, `raw_major_news`) |
| `get_insider_transactions` | Explicitly reports that this is not a primary commodity concept and points to local context tools |

## Instrument aliases

The adapter recognizes common metals aliases, including:

- `CU`, `copper`, `铜`, `HG`
- `AU`, `gold`, `黄金`, `GC`
- `AG`, `silver`, `白银`, `SI`
- `AL`, `aluminum`, `铝`
- `ZN`, `zinc`, `锌`
- `NI`, `nickel`, `镍`
- `PB`, `lead`, `铅`
- `SN`, `tin`, `锡`
- `AO`, `alumina`, `氧化铝`

## Verification

```bash
cd /mnt/e/cautious_twinkle/projects/TradingAgents
source .venv/bin/activate
python3 -m pytest tests/test_alan_business_db_dataflow.py -q
python3 -m pytest tests/ -q
```
