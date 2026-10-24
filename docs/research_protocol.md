# Research Protocol: Cross-Venue Funding-Rate Dispersion v1

**Protocol status:** frozen for FVD-DISPERSION-V1. **Evidence status:** NOT_RUN; no empirical performance result exists.

## 1. Hypothesis and falsification

Unusually high dispersion among normalized, recently settled funding rates for the same underlying across eligible perpetual venues may predict positive net returns for an equal-notional long/short pair after actual funding settlements, venue-specific price/basis movement, fees, slippage, and execution constraints. Reject or remain inconclusive if costs erase the effect, gains are driven by price/basis exposure, results depend on a few events/assets, or required historical data cannot be established.

## 2. Frozen parameter grid

The only registered grid is `configs/cross_venue_funding_dispersion_grid_v1.json`: lookbacks [8,24,72] hours; entry percentiles [70,80,90]; holds [8,24,72] hours; selected cross-sectional tails [10%,20%]; minimum eligible venues [2,3]. Exactly 108 unique configurations FVD001–FVD108. Primary anchor **FVD053** = 24-hour lookback, 80th-percentile threshold, 24-hour hold, top 10%, at least 2 venues. Do not add/drop/reorder/retune axes after outcomes are visible. A premise change requires a new experiment ID and preservation of prior evidence.

## 3. Historical point-in-time universe

At every historical ranking snapshot, order eligible underlyings by market capitalization descending. Retain rank, cap value, effective/as-of timestamp, publication/availability timestamp, source, retrieval metadata and hash. A record is admissible only if its information was available by the ranking snapshot. Current ranks are candidate discovery only, never historical ranks.

There is **no fixed top-N cutoff**. Process a practical batch, persist the rank frontier and completed/excluded candidates, then continue to the next lower-ranked cohort. Batch size is operational only. Track delisted assets and symbol/contract migrations. Never silently skip a rank, asset, venue, date or configuration. If no credible free historical point-in-time cap source exists, mark BLOCKED_DATA_GATE and do not run the empirical grid.

## 4. Funding dispersion signal

Normalize each venue's funding rate to an eight-hour equivalent using its documented actual interval: `r_8h = r_event * 8 / interval_hours`. Preserve original rate, units, interval, settlement time and normalized value. Do not assume all venues settle every eight hours.

At each completed hourly signal time, construct a piecewise-constant series from funding information actually settled/available at that time. For each venue, calculate a time-weighted mean normalized rate over the configured lookback. Dispersion is the population standard deviation across eligible venue-level means. Exclude stale/invalid observations and incompatible contracts.

The threshold is the configured percentile of the previous 90 completed UTC dates, with at most one daily observation per UTC date: the last completed hourly dispersion snapshot at or before **23:00 UTC**. Require at least 30 valid prior-date observations; exclude the current signal date; use linear/type-7 quantile. **No fallback threshold**. Insufficient history means no signal.

At each completed hourly signal timestamp, require the configured minimum eligible venues, rank all eligible underlyings by current dispersion, and select the configured top cross-sectional tail fraction. Then keep only selected assets whose dispersion is greater than or equal to that asset's historical threshold; a threshold failure does not cause replacement by a lower-ranked asset. Resolve ties deterministically by asset identifier. Long the venue with the lowest normalized funding rate and short the venue with the highest for the same underlying. Resolve venue ties by stable venue ID.

## 5. Execution and accounting

- Use only fully closed hourly data for signals. Entry occurs no earlier than the next tradable hourly open.
- Equal-notional long and short legs. Total gross exposure across both legs and all open pairs must never exceed 1.0x portfolio equity; no hidden leverage.
- Exit at the first tradable hourly open at or after the fixed holding period. Do not forward-fill missing prices or invent fills.
- Apply funding at actual venue settlement timestamps only when the position is open under that venue's documented settlement convention.
- Keep funding cash flow, each leg's price PnL, net price/basis PnL, fees, slippage and total net PnL as separate ledger fields. For side `s` (+1 long, -1 short), notional `N`, and funding rate `r`, funding cash flow is `-s*N*r`; positive funding means longs pay shorts.
- Use the frozen optimistic/base/stress cost assumptions. They are sensitivity assumptions, not claims about actual venue fee schedules. Never select a cheaper scenario after seeing results.
- Model missing data, stale rates, venue outages, contract changes, delistings, partial hours and funding interval changes explicitly.

## 6. Data gate

Require at least three years of usable hourly history after warmup and demonstrate coverage for prices, funding settlements, contract mapping, listing/delisting status and historical point-in-time ranks. Record missingness and exclusions by asset, venue, date and reason. Record source URLs, retrieval times, request parameters, pagination cursors, schemas, hashes and code/config hashes. An HTTP success does not prove historical completeness.

Use only free public endpoints and no-cost tools. No paid APIs, subscriptions, trials, private endpoints, paid compute or exchange credentials. Never trade or submit paper/live orders.

## 7. Evaluation and inference

Split the common chronological period into discovery 60%, validation 20%, final holdout 20%; freeze boundaries before viewing results. Run the grid on discovery and validation only. The validation primary endpoint is mean daily net portfolio return at <=1.0x gross exposure. Apply Holm correction across all 108 validation tests. Use a dependence-aware block bootstrap and disclose block choice/sensitivity.

Only FVD053 may be evaluated on the final holdout, after the discovery/validation decision is frozen. Never use holdout outcomes to choose parameters, costs, assets, venues, thresholds or execution rules. Report every tested configuration, not just winners. Secondary metrics include geometric annualized return, volatility, Sharpe, drawdown, turnover, funding/price attribution, fees, slippage, exposure, active days and independent event count.

## 8. Reproducibility and status

Each run needs a manifest with experiment/run ID, grid/code/data hashes, source coverage, split boundaries, cost/execution assumptions, start/end UTC, tests, outputs and status. Finalized evidence is immutable; corrections create a new run linked to the old. Independently recompute key metrics from the event ledger and verify no leakage or double counting.

Allowed statuses: NOT_RUN, BLOCKED_DATA_GATE, BLOCKED_SPECIFICATION_GATE, IMPLEMENTATION_FAILED, EXPLORATORY_ONLY, INCONCLUSIVE, REJECTED, SUPPORTED_FOR_FURTHER_RESEARCH. A green workflow, synthetic test, successful endpoint probe, or worker exit is not evidence of profitability. Even SUPPORTED_FOR_FURTHER_RESEARCH is not authorization to trade.
