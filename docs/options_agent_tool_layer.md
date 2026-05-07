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
- `trader`: first state the volatility view, then convert it into structured option strategies with auditable legs/payoff/risk fields.
- `risk_manager`: stress-test Greeks, gamma/theta, vega, liquidity, expiry, margin/max loss, and no-trade filters.
- `portfolio_manager`: decide trade/watch/no-trade with options risk assessment, no-trade conditions, risk budget, and assumptions.

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

- `legs`: each leg has side, quantity, call/put, strike, expiry, option code, price, IV, Greeks, volume, and OI.
- `net_premium` and `premium_type` (`debit` / `credit`).
- `max_loss`, `max_profit`, and `breakevens`.
- net `greeks` snapshot.
- `liquidity` filter based on min volume/OI.
- assumptions including `option close + futures close` and `contract_multiplier_applied=False`.

`TraderProposal` can render this object under `Structured Option Strategy`, after the natural-language `Option Strategy` and before `Reasoning`.

## Analyst node integration

Phase 2B wires the tool layer into the existing analyst nodes without replacing
the original graph:

- `market_analyst` keeps `get_stock_data` and `get_indicators`, and adds `get_option_trade_context`, `get_option_analytics_report`, `get_option_analytics_json`, and `get_option_strategy_candidate` for supported SHFE metals option symbols.
- `fundamentals_analyst` keeps the commodity/fundamental tools and adds `get_option_trade_context` so inventories, macro anchors, and term structure can be interpreted as volatility-regime drivers.
- `news_analyst` keeps local/global news tools and adds `get_option_trade_context` so events are framed as IV, skew, and tail-demand repricing risks.
- `bull_researcher` and `bear_researcher` keep the native debate loop but, in options mode, must discuss whether implied volatility is more likely to rise or fall over 5-day, 20-day, and 40-day horizons.
- `research_manager` carries a `Volatility Debate Summary` into the investment plan so the trader sees both bull and bear volatility path arguments.
- `trader` renders `Volatility View` before `Option Strategy`; this forces a view on future volatility direction before selecting structures.
- `aggressive/conservative/neutral risk` analysts keep the native debate loop but must evaluate Greeks, gamma/theta trade-off, vega exposure, liquidity, expiry, margin, max loss, risk budget, and no-trade filters in options mode.
- `portfolio_manager` renders optional `Options Risk Assessment` and `No-Trade Conditions`, forcing final approval to be tied to risk budget and executable liquidity.

The activation check is symbol-based (`CU/AU/AG/AL/ZN/NI/PB/SN/AO` plus aliases such as `copper`, `铜`, `gold`, `黄金`). Non-options symbols keep the stock-style toolset and prompts.

## Conventions

- Model: Black-76 futures option model.
- Default risk-free rate: `0.015`.
- Default price basis: option `close` + futures `close`.
- Settlement basis is only for explicit settlement/risk-control requests.
- GEX/DEX are scenario/concentration metrics inferred from exchange OI; exchange OI does not reveal verified dealer inventory.
- Phase-1 TradingAgents exposure is relative unless contract multiplier enrichment is explicitly added.

## Verification

```bash
cd /mnt/e/cautious_twinkle/projects/TradingAgents
.venv/bin/python -m pytest tests/test_options_tools.py -q
.venv/bin/python -m pytest -q
```
