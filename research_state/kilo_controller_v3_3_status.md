# Kilo controller v3.3 status — 2026-10-25

## Controller and prompt changes

- Added `.github/workflows/historical-coverage-probe.yml`, a schedule-only coverage workflow at minutes 13 and 43 each hour, with a separate concurrency group, 20-minute timeout, existing cooldown, bounded no-credential 120-day/four-underlying probe, unique artifact commits, bounded reconciliation, immediate remote blob verification, and a recovery artifact. It does not invoke Kilo or write the run-diagnostics ledger.
- Added/updated workflow-contract tests. Research CI [#40224632551](https://github.com/takenthatusernameis-collab/Cross-venue-funding-rate-dispersion/actions/runs/40224632551) passed on controller/test/docs commit `0c8df56627795c5b6ce994ed523d106995d35434`.
- New prompt v3.3 adds a guard against falsely diagnosing inactivity: workflow run metadata may be stale while commit history shows actual Kilo progress.

## Fresh research-progress evidence

- Despite stale run metadata, Kilo run `#40209613351` produced checkpoint commit `98e195a9632ed29f090fee5398ee0c31d6da3029` at 2026-10-25T19:08:55Z.
- That commit added `research_state/exploratory_run_manifest_2026-10-25.json` for `FVD-EXPLORATORY-002`, status `EXPLORATORY_ONLY`, preserved confirmatory status `BLOCKED_DATA_GATE`, and explicitly set `backtest_completed=false` and `performance_metrics_computed=false`. The handoff reports 97 days of daily-observation history against a 90-observation threshold-history requirement and lists the single frozen FVD053 anchor as the next task. The worker's validation summary reports 349 tests and the documented validators passing; this is a worker-reported result, not a separately-triggered CI run on that checkpoint SHA.
- This is meaningful progress, not proof of profitability. The short overlap, unverified symbol-only contract identity and survivorship uncertainty remain limitations.

## Live-workflow and source limitations

- The independent coverage workflow's first scheduled run has not yet been verified. A cooldown skip is valid and must not be reported as a new source probe.
- The old Kilo run remained in progress at the last check; do not infer it is stalled from its run metadata timestamp alone. Do not start a competing Kilo worker or overwrite a handoff that changed after it was fetched.
- Original confirmatory FVD001–FVD108/FVD053 remains frozen and `BLOCKED_DATA_GATE`. No performance metrics are claimed.

## Acceptance criteria

1. Research CI passes on the latest code/test revision; inspect any later code changes separately.
2. Inspect actual run/job steps, latest commit history, diffs and manifests before calling a worker stalled or claiming progress.
3. A scheduled probe logs its cooldown decision and, if due, JSON-validates, checkpoints and remotely verifies the exact artifact blob.
4. Keep coverage-only work separate from Kilo and diagnostics-ledger writing; retain free public sources and no-live/paper-trading limits.
