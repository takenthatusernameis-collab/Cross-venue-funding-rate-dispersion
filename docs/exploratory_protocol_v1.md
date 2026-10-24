# Cross-Venue Funding Dispersion — Exploratory Protocol v1

**Status:** Design-only protocol; no backtest result is implied.  
**Scope:** A separately versioned feasibility and exploratory study that may proceed when the original point-in-time market-cap gate is structurally unavailable from permitted free sources.  
**Relationship to the frozen confirmatory study:** This document does not modify `docs/research_protocol.md`, `configs/cross_venue_funding_dispersion_grid_v1.json`, FVD001–FVD108, FVD053, or the original `research_state/run_manifest.json`. The confirmatory campaign remains `BLOCKED_DATA_GATE` until its original requirements are satisfied.

## 1. Question and allowed inference

Determine whether the frozen funding-dispersion signal can be calculated and evaluated at all on a real, verified historical overlap of perpetual contracts available on at least two venues, and describe its cost-adjusted behavior on that sample.

This is **not** a test of the original market-cap-ranked-universe claim. It is a narrower exploratory estimand on an availability-selected universe. It can identify implementation defects, data coverage and candidate mechanisms, but cannot establish a durable edge or authorize trading.

## 2. Identifier and preregistration

Before any outcome calculation, inspect existing run records and allocate a unique identifier (suggested family label: `FVD-EXPLORATORY-001`; verify uniqueness before use). Write a dated run manifest and freeze the data cutoff, instrument list, venue set, cost assumptions, code/config hashes, sample construction and exclusion rules first. Never reuse an inspected holdout or silently attach this version to the original FVD IDs.

Use the FVD053 values as a **frozen anchor only**:
- 24-hour lookback;
- 80th-percentile threshold;
- 24-hour holding period;
- top 10% cross-sectional tail;
- at least two eligible venues.

Do not run or optimize the full 108-cell grid in this exploratory protocol. Any parameter search is a later, separately registered family.

## 3. Eligible historical sample

The exploratory universe is the set of perpetual-futures underlyings for which, at each historical signal time, the evidence establishes:
1. at least two genuinely distinct eligible venues and compatible contract identities;
2. observed funding events with the actual funding interval, settlement time and rate units;
3. observed prices sufficient to execute both legs at the next tradable open and exit after the holding period;
4. timestamps, listing/delisting/lifecycle details and missingness sufficient to avoid backfilling unavailable contracts;
5. terms-compliant, free public source provenance, retrieval parameters, response hashes and coverage dates.

Do not require a market-cap rank for this distinct exploratory estimand if the rank is not essential to the funding-distribution mechanism. Do **not** replace that rank with a current snapshot or claim the sample is market-cap representative. Report the availability-based selection bias and venue-specific coverage. If only one venue remains, no cross-venue pair can be tested; mark it blocked and continue with source-independent work.

Use the actual historical intersection that can be verified. A shorter available window is allowed for this exploratory version; record its start/end, usable hours, settled funding events, unique instruments, venue-pairs, missingness and independent event structure. Do not describe it as satisfying the original >=3-year confirmatory requirement. If the window is too short to estimate uncertainty meaningfully, report descriptive output and `EXPLORATORY_ONLY` or `INCONCLUSIVE`, not a pass.

## 4. Signal timing, execution and accounting

Keep the original causal timing and accounting invariants:
- calculate signals from completed UTC-hour observations and only funding information settled/available by that timestamp;
- enter no earlier than the next tradable hourly open;
- long the eligible venue with the lowest normalized funding rate and short the venue with the highest, using deterministic tie-breaking;
- normalize funding to the same interval only using the documented actual settlement cadence;
- record funding cash flow separately from each leg's price PnL/basis movement, fees, slippage and combined net PnL;
- apply funding only at actual settlement times while each position is open;
- do not forward-fill missing funding/prices, fabricate fills, silently discard a pair after signal formation, or allow aggregate gross exposure above 1.0x;
- preserve adverse fill handling and show base plus stress costs. State clearly that modeled slippage is an assumption unless measured spread/execution data support it.

A deterministically reproducible known-answer test and an independent accounting recomputation are required before interpreting historical metrics.

## 5. Evaluation

First perform data/eligibility coverage and anchor signal-accounting checks; then run the single frozen anchor if the real-data requirements of this exploratory sample pass.

Report at minimum: net and gross return, volatility, Sharpe only when estimable, maximum drawdown, exposure, turnover, number of independent signal episodes, number of funding settlements, venue-pair counts, funding-versus-price/basis attribution, fees/slippage, cost sensitivity, missingness, sample-window dates and uncertainty limitations. Use dependence-aware resampling only if enough independent episodes exist; otherwise say uncertainty is not estimable. Avoid interpreting repeated hourly observations as independent trades.

Any output from this version must be marked `EXPLORATORY_ONLY` or `INCONCLUSIVE`. No multiple-testing-adjusted confirmatory claim is available from one anchor; if later variants are tried, list them all and treat them as one disclosed exploratory family.

## 6. Explicit stop and next-step rule

If public free data cannot establish the required two-venue historical overlap or contract mapping, do not fabricate or substitute data. Record the exact field, source, dates and failure; preserve the confirmatory gate; and proceed to a different bounded source-independent task. Do not loop on a source or route that has already failed without new evidence that its conditions changed.

## 7. Promotion boundary

Only the original confirmatory protocol, with its full point-in-time market-cap universe, >=3-year usable history, chronological splits, multiplicity correction, frozen anchor-only final holdout and independent audit, can support a confirmatory conclusion for the original hypothesis. Exploratory success does not automatically change that status, and neither result authorizes live or paper trading.
