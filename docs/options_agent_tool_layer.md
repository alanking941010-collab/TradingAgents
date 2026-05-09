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
- `risk_manager`: stress-test Greeks, gamma/theta, vega, liquidity, bid/ask feasibility, slippage, execution liquidity, expiry, margin required, risk budget pass/fail, contract-multiplier cash risk, credit execution quality, scenario PnL, breakeven proximity, and no-trade filters.
- `portfolio_manager`: decide trade/watch/no-trade with scenario PnL assessment, cash risk-budget utilization, margin checks, options risk assessment, execution liquidity checks, credit/risk quality checks, no-trade conditions, and assumptions.

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

Phase 16 enriches the analytics payload with `vol_surface`:

- `moneyness_buckets`: per-expiry `otm_put`, `atm`, and `otm_call` IV buckets with representative strike and option count.
- `skew`: `put_call_skew`, `risk_reversal_proxy`, and `smile_curvature_proxy` for the nearest expiry.
- `term_regime`: front/back expiry IV, slope, and shape (`contango`, `backwardation`, `flat`, or `single_expiry`).

These are deterministic summaries of available chain rows. They are volatility-surface diagnostics for agent interpretation, not dealer-position or executable-vol quotes.

LangChain tools:

- `get_option_trade_context`
- `get_option_analytics_json`
- `get_option_analytics_report`
- `get_option_strategy_candidate`
- `get_option_strategy_selection`
- `get_option_strategy_scenarios`
- `get_option_strategy_replay`
- `get_option_strategy_report`
- `get_option_research_pack`
- `get_option_feishu_delivery_payload`
- `get_option_hermes_cron_delivery_spec`

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
- `long_call_butterfly`
- `long_put_butterfly`
- `short_iron_condor`

The structurer returns an auditable object with:

- `legs`: each leg has side, quantity, call/put, strike, expiry, option code, price, IV, Greeks, volume, OI, bid/ask when available, execution price (`BUY` at ask / `SELL` at bid), and per-leg slippage. Phase 14B adds `short_iron_condor`, a four-leg credit defined-risk structure that buys the outer put/call wings and sells the inner OTM put/call.
- `net_premium` and `premium_type` (`debit` / `credit`).
- `max_loss`, `max_profit`, and `breakevens`.
- net `greeks` snapshot.
- `liquidity` filter based on min volume/OI.
- `execution`: bid/ask completeness, net mid premium, net execution premium, slippage points/cash, spread metrics, and a 0-100 execution liquidity score.
- `credit_execution`: for supported credit structures such as `short_iron_condor`, executable credit (`SELL` legs at bid, `BUY` wings at ask), credit slippage, wing width, execution-adjusted max loss, credit/wing-width ratio, credit/max-loss ratio, optional quality-filter status, and no-trade reasons.
- `margin`: simplified defined-risk margin required, using execution-adjusted max loss when bid/ask execution premium or executable credit is available.
- `risk_budget`: pass/fail/not-provided status, margin/max-loss utilization, and no-trade reasons when the budget or optional execution-quality filters are breached.
- assumptions including `option close + futures close` and `contract_multiplier_applied=True`.
- `cash_risk`: contract multiplier, net premium cash, max loss cash, max profit cash, underlying notional per lot, and risk-budget utilization when provided.

`TraderProposal` can render this object under `Structured Option Strategy`, after the natural-language `Option Strategy` and before `Reasoning`.

## Strategy Selector / Ranking

Phase 17 adds a deterministic selector in:

```text
tradingagents/options/selector.py
```

`build_option_strategy_selection` ranks supported structures using the Phase 16
volatility surface diagnostics plus each strategy candidate's execution,
liquidity, simplified margin, risk-budget status, and credit-quality fields. The
selector returns:

- `surface_regime`: nearest expiry, term shape/slope, put-call skew, risk-reversal proxy, smile-curvature proxy, and ATM IV.
- `ranked_candidates`: strategy type, score, decision (`candidate`, `watch`, `low_priority`, or `no_trade`), ranking reasons, no-trade reasons, margin/max-loss cash, execution liquidity grade, and the full underlying candidate.
- `portfolio_summary`: Phase 18A portfolio-level comparison table with selected strategy risk-budget utilization, total tradable-candidate margin/max-loss, highest-margin and lowest-max-loss structures, watchlist, and explicit no-trade rows.
- `selected_strategy`: the highest-ranked non-`no_trade` structure.
- `markdown`: a human-readable `Strategy Ranking` and `Portfolio Risk Summary` section for reports or Feishu handoff.

This is a deterministic pre-trade research layer. It does not execute orders and
should not override explicit risk-manager/portfolio-manager rejection when live
liquidity, margin, or market conditions invalidate the setup.

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
Phase 10 also carries `margin`, `risk_budget`, and summary PnL as a percentage
of margin required into the scenario matrix.

`get_option_strategy_scenarios` exposes this as JSON to agents so risk and
portfolio managers can inspect path-dependent payoff behavior instead of only
reading static Greeks/max-loss fields.

## Historical Replay / Post-Trade Review

Phase 12 adds deterministic replay in:

```text
tradingagents/options/replay.py
```

`build_option_strategy_replay` selects the entry structure on `entry_date`, then
marks the same entry legs by `ts_code` across review dates using option close +
futures close. It reports per-leg marks, strategy mark value, PnL in option
points and cash, PnL as a percentage of margin required, and a simple
post-trade review outcome (`profitable`, `loss_making`, or `flat`). Phase 18B
adds `performance_summary`: win/lose/flat counts, win rate, average/final PnL
cash, max drawdown cash, a date-by-date `pnl_path`, and IV-regime buckets based
on close-derived ATM IV diagnostics for each mark date.

`get_option_strategy_replay` exposes this as JSON to market/risk/portfolio
agents for historical replay, backtest-style sanity checks, and post-trade
review. It is a deterministic mark-to-market replay, not a fill simulator: fees,
post-entry slippage, and order-book queue effects are not modeled.

## Report Pipeline / Feishu Delivery

Phase 13 adds a Markdown-first report composer in:

```text
tradingagents/options/reports.py
```

`build_option_strategy_report` composes the deterministic volatility snapshot,
strategy candidate, scenario PnL summary, and optional historical replay into a
Feishu-renderable Markdown report. The report payload keeps the underlying JSON
sections under `payloads` so every headline number remains auditable.

`build_feishu_delivery_payload` wraps the report as a side-effect-free Feishu
message payload (`channel`, `target`, `title`, `message`, `dry_run`, and
`delivery_hint`). It deliberately does **not** send anything; an external Hermes
`send_message`/Gateway caller must explicitly publish the Markdown.

`get_option_strategy_report` and `get_option_feishu_delivery_payload` expose
these functions as tools for agents that need report generation or delivery
handoff.

## Unified Research Pack

Phase 19A adds a side-effect-free research pack orchestrator in:

```text
tradingagents/options/research_pack.py
```

`build_option_research_pack` stitches together the deterministic selector, Phase
18A `portfolio_summary`, selected strategy report, optional Phase 18B replay
performance summary, and a dry-run Feishu delivery payload. If `strategy_type` is
omitted it uses selector auto-pick; if supplied it keeps the full selector output
but marks `selection_mode="explicit_strategy_override"` for audit.

The pack returns:

- `pack_type="shfe_option_research_pack"`, product, trade date, expiry, selected strategy, and selection mode.
- `summary`: selected decision/score, risk budget cash/status/utilization, execution liquidity grade, worst scenario PnL cash, replay final PnL, replay max drawdown, replay win rate, and report title.
- `payloads.selection`: full selector/ranking JSON.
- `payloads.portfolio_summary`: Phase 18A candidate comparison for portfolio-manager review.
- `payloads.selected_strategy_report`: the complete Markdown-first strategy report, including scenario and optional replay sections.
- `payloads.feishu_delivery_payload`: dry-run Feishu Markdown payload; no message is sent by this code path.
- `markdown`: a single `Options Research Pack` handoff combining strategy selection and selected strategy report.

`get_option_research_pack` exposes the pack as an agent tool so market analysts
can request one auditable research bundle instead of separately calling selector,
report, replay, and Feishu-payload tools.

Phase 14A adds an explicit send boundary and Hermes cron-ready entrypoint:

```text
tradingagents/options/delivery.py
scripts/deliver_option_strategy_report.py
```

`send_feishu_delivery_payload` performs live delivery only through an injected
sender callable (`target`, `message`) and returns a verified send result. If
`dry_run=False` and no sender is supplied, it raises instead of pretending a
message was sent.

`build_hermes_cron_delivery_spec` and `get_option_hermes_cron_delivery_spec`
document the no-agent cron path: run `scripts/deliver_option_strategy_report.py`
with `--stdout message`; Hermes no-agent cron delivers non-empty stdout to the
configured Feishu target. The script also writes the full report JSON, Markdown,
and Feishu payload JSON artifacts for audit.

## Analyst node integration

Phase 2B wires the tool layer into the existing analyst nodes without replacing
the original graph:

- `market_analyst` keeps `get_stock_data` and `get_indicators`, and adds `get_option_trade_context`, `get_option_analytics_report`, `get_option_analytics_json`, `get_option_strategy_candidate`, `get_option_strategy_selection`, `get_option_strategy_scenarios`, `get_option_strategy_replay`, `get_option_strategy_report`, `get_option_research_pack`, `get_option_feishu_delivery_payload`, and `get_option_hermes_cron_delivery_spec` for supported SHFE metals option symbols.
- `fundamentals_analyst` keeps the commodity/fundamental tools and adds `get_option_trade_context` so inventories, macro anchors, and term structure can be interpreted as volatility-regime drivers.
- `news_analyst` keeps local/global news tools and adds `get_option_trade_context` so events are framed as IV, skew, and tail-demand repricing risks.
- `bull_researcher` and `bear_researcher` keep the native debate loop but, in options mode, must discuss whether implied volatility is more likely to rise or fall over 5-day, 20-day, and 40-day horizons.
- `research_manager` carries a `Volatility Debate Summary` into the investment plan so the trader sees both bull and bear volatility path arguments.
- `trader` renders `Volatility View` before `Option Strategy`; this forces a view on future volatility direction before selecting structures.
- `aggressive/conservative/neutral risk` analysts keep the native debate loop but must evaluate Greeks, gamma/theta trade-off, vega exposure, liquidity, expiry, margin, max loss, cash risk budget, scenario PnL worst/best cases, T+5/T+20 decay, IV up/down sensitivity, breakeven proximity, and no-trade filters in options mode.
- `portfolio_manager` renders optional `Scenario PnL Assessment`, `Options Risk Assessment`, and `No-Trade Conditions`, forcing final approval to be tied to the deterministic stress matrix, cash risk budget, and executable liquidity.
- Phase 9 adds bid/ask-aware execution fields. When `vw_shfe_option_chain_latest` exposes `bid`/`ask`, or when `akshare_option_snapshot` can be joined by trade date, metal, contract month, strike, and call/put, strategy candidates use `BUY` at ask and `SELL` at bid to estimate execution premium and slippage. When bid/ask is missing, execution fields fall back to the analysis price and mark bid/ask completeness as false.
- Phase 10 adds simplified margin/risk-budget checks for the currently supported defined-risk structures. It reports `margin_required_cash`, `margin_required_pct_of_notional`, `margin_pct_of_risk_budget`, risk budget pass/fail, and explicit no-trade reasons. This is a pre-trade feasibility check, not an exchange/SPAN margin engine.
- Phase 11 begins the complex strategy expansion with long call/put butterflies: three-leg structures with 1x long lower strike, 2x short middle strike, and 1x long upper strike, including deterministic payoff, margin, scenario PnL, and tool-schema support.
- Phase 12 adds historical replay/post-trade review for structured strategies, including a market analyst tool node so agents can mark the same entry legs over review dates.
- Phase 13 adds a report pipeline and Feishu delivery handoff: agents can build a Markdown strategy report plus a side-effect-free Feishu payload, but the code does not publish messages by itself.
- Phase 14A adds a live-delivery boundary and Hermes cron-ready script: injected sender callables can perform verified sends, and no-agent cron can deliver report Markdown stdout to Feishu targets while saving audit artifacts.
- Phase 14B expands the complex strategy library with `short_iron_condor`: a credit, defined-risk, four-leg structure with simplified max-profit/max-loss, breakevens, cash-risk, margin, scenario PnL, report, and tool support.
- Phase 15 improves credit strategy execution realism: `short_iron_condor` now reports executable credit from bid/ask, credit slippage, execution-adjusted max loss/margin, credit/wing-width and credit/max-loss ratios, and optional no-trade filters (`min_credit_pct_of_wing_width`, `max_bid_ask_spread_pct`).
- Phase 16 adds volatility-surface diagnostics: moneyness IV buckets, risk-reversal/smile-curvature proxies, term-regime shape, and report/tool/prompt exposure so agents can tie structures to skew and term structure instead of only ATM IV.
- Phase 17 adds a deterministic strategy selector/ranking layer that maps volatility-surface regime, directional/volatility view, execution quality, simplified margin, risk-budget pass/fail, and credit filters into ranked candidate/watch/no-trade structures.
- Phase 18A adds portfolio-level candidate comparison and risk summary inside the selector output: selected-strategy risk-budget utilization, all-tradable candidate margin/max-loss totals, highest-margin/lowest-max-loss structures, watchlist/no-trade rows, and a Markdown `Portfolio Risk Summary` table.
- Phase 18B enhances replay/backtest output with `performance_summary`: win/lose/flat distribution, win rate, average/final PnL cash, max drawdown cash, per-date PnL path, close-based IV-regime buckets, and report payload/Markdown exposure.
- Phase 19A adds a unified side-effect-free research pack: selector auto-pick or explicit strategy override, Phase 18A portfolio summary, selected strategy report, optional Phase 18B replay performance, dry-run Feishu payload, and one Markdown handoff.

The activation check is symbol-based (`CU/AU/AG/AL/ZN/NI/PB/SN/AO` plus aliases such as `copper`, `铜`, `gold`, `黄金`). Non-options symbols keep the stock-style toolset and prompts.

## Conventions

- Model: Black-76 futures option model.
- Default risk-free rate: `0.015`.
- Default price basis: option `close` + futures `close`.
- Settlement basis is only for explicit settlement/risk-control requests.
- GEX/DEX are scenario/concentration metrics inferred from exchange OI; exchange OI does not reveal verified dealer inventory.
- Contract multipliers are applied from static SHFE futures contract specifications for cash premium, max loss, max profit, notional, and scenario PnL fields. Option-price-point fields remain available for audit.
- Volatility-surface model: `vol_surface` buckets are computed from available option close-based IV rows by expiry/moneyness; risk-reversal and smile-curvature proxies are diagnostics, not executable volatility quotes.
- Margin model: simplified defined-risk. Margin required equals execution-adjusted max loss for supported debit structures and, for `short_iron_condor`, execution-adjusted max loss based on executable credit when bid/ask are available; exchange/SPAN margin, fees, broker add-ons, and margin offsets are not modeled.
- Credit execution model: supported credit structures use bid/ask feasibility (`SELL` at bid, `BUY` at ask) to report executable credit, credit slippage, credit/wing-width ratio, and optional no-trade filters. This is still an indicative pre-trade proxy, not a guaranteed live fill.
- Replay model: mark the same entry legs by option `ts_code` with option close + futures close on each review date; post-entry fees/slippage and order-book execution are not modeled. Phase 18B performance summaries group replay marks by close-derived ATM-IV regime for diagnostics only, not executable volatility quotes.
- Report/delivery model: reports are Markdown + audit payloads; Feishu payloads are side-effect-free handoffs and require an external sender to publish. Research packs are also side-effect-free orchestration outputs; their embedded Feishu payload is dry-run by default and should not be interpreted as a sent message. Phase 14A live sends require an injected sender callable, while scheduled Hermes delivery should use no-agent cron with `scripts/deliver_option_strategy_report.py --stdout message`.

## Verification

```bash
cd /mnt/e/cautious_twinkle/projects/TradingAgents
.venv/bin/python -m pytest tests/test_options_phase19a_research_pack.py tests/test_options_analyst_integration.py -q
.venv/bin/python -m pytest tests/test_options_tools.py -q
.venv/bin/python -m pytest -q
```
