# Architecture and research gates

1. **Specification:** validate frozen protocol, grid, event timing, costs and status schema.
2. **Source:** use documented free public endpoints; record URL, request parameters, retrieval time, pagination state, schema and hashes.
3. **Historical universe:** require market-cap effective/as-of and publication timestamps no later than each ranking snapshot. Current ranks are discovery-only. Continue the descending rank frontier with no fixed top-N cutoff.
4. **Coverage:** quantify hourly price and funding coverage, missing intervals, settlement history, listing/delisting state, contract mapping and stale observations.
5. **Normalization:** convert timestamps to UTC and funding rates to a common 8-hour equivalent while preserving original units and source rows.
6. **Signal/execution:** closed-hour signals only; next tradable hourly open at earliest; equal-notional pair; total gross exposure <=1.0x equity.
7. **Accounting:** funding cash flows at actual settlement times remain separate from each leg's price/basis PnL, fees and slippage.
8. **Evaluation:** minimum three complete years; chronological 60/20/20 split; grid only on discovery/validation; final holdout only FVD053.
9. **Independent audit:** recompute event-ledger metrics and test leakage, multiple testing, costs, coverage, holdout isolation and reproducibility.

## Separation of concerns

- `configs/`: immutable parameters.
- `src/`: deterministic calculations and point-in-time ranking.
- `scripts/`: offline validation and bounded operational probes.
- `tests/`: offline known-answer/adversarial tests; synthetic fixtures never count as market evidence.
- `research_state/`: run status and resumable rank frontier.
- `reports/`: concise summaries and artifact links, not bulk raw data.
- `.github/workflows/main.yml`: sequential Kilo loop with checkpoint/recovery.
- `.github/workflows/research-ci.yml`: read-only offline checks.
- `.github/workflows/public-source-preflight.yml`: manual no-secret endpoint probe.

A passing test means code behavior matches the tested contract. An HTTP 200 does not prove usable history. A successful backtest run is not an independently audited economic result.
