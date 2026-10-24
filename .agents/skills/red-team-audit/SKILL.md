---
name: red-team-audit
description: Independently test whether funding-dispersion evidence is causal, complete, reproducible, cost-robust, statistically defensible and free of holdout leakage.
---
# Red-team audit

Before accepting an empirical result, verify:

1. Exact grid, anchor, protocol version, split boundaries, and code/config/data hashes.
2. UTC event alignment, publication-time availability, closed-bar signals, next-bar entry, settlement timing, and no future-data leakage.
3. Historical point-in-time market-cap ranks, expanding cohort completion, delisted assets and explicit exclusions.
4. Pagination exhaustion, rate limits, missingness, stale observations, units, contract mapping and venue settlement intervals.
5. Funding signs, separate price/basis PnL, fee/slippage per leg/fill, equal notionals and the 1.0x gross cap.
6. All 108 configurations reported; Holm correction covers the validation family; final holdout was not used for selection.
7. Dependence-aware uncertainty, event counts, concentration by asset/venue/time, drawdown, turnover and adverse costs.
8. Independent recomputation from immutable event-ledger rows matches published metrics within registered tolerances.
9. Run manifest, artifact checksums, logs, exclusion/failure records and reproduction commands exist.
10. Status matches evidence. Synthetic data, endpoint probes, worker success and green workflows are not proof of profitability.
