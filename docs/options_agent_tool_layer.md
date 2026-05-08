# Options Agent Tool Layer

This document records the first bridge between Alan's deterministic SHFE options
analytics core and the original TradingAgents multi-agent workflow.

## Principle

Keep the original TradingAgents reasoning structure, but make options analysis
volatility-first:

- `market_analyst`: underlying futures trend, RV, technical context, and the futures anchor.
- `fundamentals_analyst`: inventories, macro anchors, term structure context, and volatility regime drivers.
- `news_analyst`: event risks that can reprice IV, skew, or tail demand.
- `bull_researcher`: bullish directional or bullish-volatility structures supported by data.
- `bear_researcher`: bearish directional or bearish-volatility structures supported by data.
- `research_manager`: adjudicate the bull/bear volatility debate and preserve a 5/20/40-day vol path handoff for the trader.
- `trader`: first state the volatility view, then convert it into structured option strategies with auditable legs/payoff/risk/execution fields.
- `risk_manager`: stress-test Greeks, gamma/theta, vega, liquidity, bid/ask feasibility, slippage, execution liquidity, expiry, margin/max loss, contract-multiplier cash risk, scenario PnL, breakeven proximity, and no-trade filters.
- `portfolio_manager`: decide trade/watch/no-trade with scenario PnL assessment, cash risk-budget utilization, options risk assessment, execution liquidity checks, no-trade conditions, and assumptions.

LLMs should interpret the structured results. They should not calculate IV,
Greeks, GEX, DEX, PCR, walls, or gamma flip from raw prices.

## Tool module

```text
tradingagents/agents/utils/options_tools.py
```

Public deterministic helpers:

- `build_option_trade_context(symbol, trade_date=None, expiry=None)` — compact JSON/dict for agent prompts.
- `build_option_analytics_payload(symbol, trade_date=None, expiry=None)` — full audit JSON/dict with option rows.
- `build_option_analytics_markdown(symbol, trade_date=None, expiry=None)` — human-readable Markdown.

LangChain tools:

- `get_option_trade_context`
- `get_option_analytics_json`
- `get_option_analytics_report`
- `get_option_strategy_candidate`
- `get_option_strategy_scenarios`

## Strategy structurer

Phase 5 adds a deterministic strategy structurer:

```text
tradingagents/options/strategies.py
```

It currently supports:

- `bull_call_spread`
- `bear_put_spread`
- `long_straddle`
- `long_strangle`

The structurer returns an auditable object with:

- `legs`: each leg has side, quantity, call/put, strike, expiry, option code, price, IV, Greeks, volume, OI, bid/ask when available, execution price (`BUY` at ask / `SELL` at bid), and per-leg slippage.
- `net_premium` and `premium_type` (`debit` / `credit`).
- `max_loss`, `max_profit`, and `breakevens`.
- net `greeks` snapshot.
- `liquidity` filter based on min volume/OI.
- `execution`: bid/ask completeness, net mid premium, net execution premium, slippage points/cash, spread metrics, and a 0-100 execution liquidity score.
- assumptions including `option close + futures close` and `contract_multiplier_applied=True`.
- `cash_risk`: contract multiplier, net premium cash, max loss cash, max profit cash, underlying notional per lot, and risk-budget utilization when provided.

`TraderProposal` can render this object under `Structured Option Strategy`, after the natural-language `Option Strategy` and before `Reasoning`.

## Scenario PnL / Payoff Engine

Phase 6 adds a deterministic scenario engine:

```text
tradingagents/options/scenarios.py
```

It takes a structured strategy candidate and reprices each leg with Black-76
across a configurable grid:

- underlying futures shocks, e.g. `F ±1% / ±3% / ±5%`;
- absolute IV shocks, e.g. `IV ±2 vol / ±5 vol`;
- time-forward scenarios, e.g. `T+0 / T+1 / T+5 / T+20`.

The output includes per-leg scenario values, total strategy value, PnL,
PnL as a fraction of max loss, best/worst scenario IDs, and breakeven proximity.
Phase 8 keeps option-price-point fields for auditability and adds cash fields
after applying the SHFE contract multiplier: `scenario_value_cash`, `pnl_cash`,
`worst_pnl_cash`, `best_pnl_cash`, and risk-budget utilization when provided.

`get_option_strategy_scenarios` exposes this as JSON to agents so risk and
portfolio managers can inspect path-dependent payoff behavior instead of only
reading static Greeks/max-loss fields.

## Analyst node integration

Phase 2B wires the tool layer into the existing analyst nodes without replacing
the original graph:

- `market_analyst` keeps `get_stock_data` and `get_indicators`, and adds `get_option_trade_context`, `get_option_analytics_report`, `get_option_analytics_json`, `get_option_strategy_candidate`, and `get_option_strategy_scenarios` for supported SHFE metals option symbols.
- `fundamentals_analyst` keeps the commodity/fundamental tools and adds `get_option_trade_context` so inventories, macro anchors, and term structure can be interpreted as volatility-regime drivers.
- `news_analyst` keeps local/global news tools and adds `get_option_trade_context` so events are framed as IV, skew, and tail-demand repricing risks.
- `bull_researcher` and `bear_researcher` keep the native debate loop but, in options mode, must discuss whether implied volatility is more likely to rise or fall over 5-day, 20-day, and 40-day horizons.
- `research_manager` carries a `Volatility Debate Summary` into the investment plan so the trader sees both bull and bear volatility path arguments.
- `trader` renders `Volatility View` before `Option Strategy`; this forces a view on future volatility direction before selecting structures.
- `aggressive/conservative/neutral risk` analysts keep the native debate loop but must evaluate Greeks, gamma/theta trade-off, vega exposure, liquidity, expiry, margin, max loss, cash risk budget, scenario PnL worst/best cases, T+5/T+20 decay, IV up/down sensitivity, breakeven proximity, and no-trade filters in options mode.
- `portfolio_manager` renders optional `Scenario PnL Assessment`, `Options Risk Assessment`, and `No-Trade Conditions`, forcing final approval to be tied to the deterministic stress matrix, cash risk budget, and executable liquidity.
- Phase 9 adds bid/ask-aware execution fields. When `vw_shfe_option_chain_latest` exposes `bid`/`ask`, or when `akshare_option_snapshot` can be joined by trade date, metal, contract month, strike, and call/put, strategy candidates use `BUY` at ask and `SELL` at bid to estimate execution premium and slippage. When bid/ask is missing, execution fields fall back to the analysis price and mark bid/ask completeness as false.

The activation check is symbol-based (`CU/AU/AG/AL/ZN/NI/PB/SN/AO` plus aliases such as `copper`, `铜`, `gold`, `黄金`). Non-options symbols keep the stock-style toolset and prompts.

## Conventions

- Model: Black-76 futures option model.
- Default risk-free rate: `0.015`.
- Default price basis: option `close` + futures `close`.
- Settlement basis is only for explicit settlement/risk-control requests.
- GEX/DEX are scenario/concentration metrics inferred from exchange OI; exchange OI does not reveal verified dealer inventory.
- Contract multipliers are applied from static SHFE futures contract specifications for cash premium, max loss, max profit, notional, and scenario PnL fields. Option-price-point fields remain available for audit.

## Verification

```bash
cd /mnt/e/cautious_twinkle/projects/TradingAgents
.venv/bin/python -m pytest tests/test_options_tools.py -q
.venv/bin/python -m pytest -q
```
