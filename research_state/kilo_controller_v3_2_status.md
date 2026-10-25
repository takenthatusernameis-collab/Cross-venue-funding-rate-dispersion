# Kilo controller v3.2 status — 2026-10-25

## Controller changes

- Added `.github/workflows/historical-coverage-probe.yml`: a schedule-only (minutes 13 and 43 each hour), coverage-only workflow using its own concurrency group and a 20-minute timeout. It calls the existing cooldown helper, runs the bounded no-credential 120-day/four-underlying probe only when due, and persists a uniquely named probe artifact. It invokes no Kilo model and does not write the workflow-run diagnostics ledger.
- Added contract tests that check schedule isolation, bounded execution, no Kilo or second ledger writer, and Bash syntax of the extracted probe step.
- The first CI exposed a case-sensitive assertion mismatch; the next exposed a test harness issue where shell lines were joined with a literal backslash-n instead of actual newlines. Both were corrected through observed CI failures, not assumed away.
- The remote artifact verifier is now defined before the retry loop. Every successful push is followed immediately by a bounded fetch and remote ancestry/blob check, including the last permitted retry.

## Validation

- Research CI [#40224573727](https://github.com/takenthatusernameis-collab/Cross-venue-funding-rate-dispersion/actions/runs/40224573727) passed on the then-latest repository head `ce9381652b21622c440a70d22cab56e7b24419b4`, including the v3.2 prompt pointer, status and handoff edits.
- Live execution remains unverified: the independent scheduled workflow has not yet been observed completing a run. A cooldown skip is not fresh source evidence.

## Remaining limits

- The old Kilo run `#40209613351` was still in progress on its old workflow revision at the latest check. This interface provides no supported cancel-run or workflow-dispatch operation.
- The last committed public-source probe had a common funding-plus-price window of about 97 days for BTC, ETH, SOL and XRP across Hyperliquid and OKX; contract identity was not independently verified. The original confirmatory manifest remains `BLOCKED_DATA_GATE`, and the three-year point-in-time market-cap requirement remains unmet.
- FVD001–FVD108 and FVD053 are unchanged. No backtest or performance metrics were computed in this controller task.

## Acceptance criteria

1. Research CI passes on the latest commit.
2. The scheduled coverage workflow's actual event, cooldown decision, probe JSON, step result and remote artifact blob are inspected.
3. No paid data, user credentials, unapproved runners, parallel Kilo worker, secondary diagnostics-ledger writer, or changes to frozen research protocol/grid are introduced.
