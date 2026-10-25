# Kilo controller v3.1 status — 2026-10-25

## Controller changes

- Added the scheduled coverage-only workflow `.github/workflows/historical-coverage-probe.yml` on v3.0. It operates outside the stale Kilo concurrency lock, uses the existing cooldown helper, runs the bounded no-credential 120-day/four-asset probe only when due, and writes unique probe artifacts. It does not invoke Kilo and does not write the workflow-run diagnostics ledger.
- The first CI for commit `14b7f292b19c7056125896f9d7612a9cbca15ea4` failed because the test expected lowercase `performance metrics computed: false` while the workflow summary uses `Performance metrics computed: false`. That was a real CI failure and was not treated as pass.
- This follow-up fixes the case-sensitive regression test, checks that the script passed to bash syntax validation is joined with real line breaks, and adds immediate remote blob verification after every successful artifact push. The last allowed retry can no longer push and then exit without attempting verification.

## Validation status and live limits

- CI must be re-queried on this follow-up commit before calling this revision valid. If it fails, inspect the actual failure log and fix it before reporting success.
- The old Kilo run `#40209613351` remained in progress on an older workflow revision at last inspection. This interface does not expose a supported cancel or dispatch operation.
- The independent coverage workflow will next run on its schedule (13 and 43 minutes past each hour, subject to GitHub scheduling latency). Due to the existing six-hour normal cooldown, a recent successful source probe should produce a recorded skip, not a false claim of fresh coverage. The prior probe timestamp was `2026-10-25T18:07:05Z`; the next full probe should be due after roughly `2026-10-26T00:07Z`, at the next eligible scheduled run.
- The prior coverage evidence spans only about 97 days of funding-plus-price overlap for BTC, ETH, SOL and XRP; contract mapping is not independently verified. The original confirmatory manifest is still `BLOCKED_DATA_GATE`. FVD001–FVD108 and FVD053 remain unchanged; no backtest or performance metrics are claimed.

## Acceptance criteria

1. Research CI passes on the latest commit, including workflow contract and Bash syntax tests.
2. A scheduled coverage run produces either an accurate cooldown skip or an auditable live probe.
3. If the probe ran, remote branch ancestry and the exact artifact blob are verified before success is reported.
4. No paid sources, user credentials, live/paper trading, parallel Kilo workers, secondary diagnostics-ledger writers, or changes to the frozen research protocol/grid.
