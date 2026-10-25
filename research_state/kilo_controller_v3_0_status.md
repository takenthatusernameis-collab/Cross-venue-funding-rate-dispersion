# Kilo controller v3.0 status — 2026-10-25

## New evidence and design change

The stale Kilo activation `#40209613351` remained in progress on workflow revision `6b5e16819c4b3de281ef908b333a55dee1a4c09f`, despite later commits improving the controller. It held the shared `kilo-repository` concurrency group; the main workflow's new early probe cannot retroactively execute in that run. This integration exposes no supported cancel-run or workflow-dispatch operation.

To make coverage evidence independent of Kilo's shared lock, this revision adds `.github/workflows/historical-coverage-probe.yml`, a scheduled coverage-only workflow:
- Runs at minute 13 and 43 each hour, with its own `historical-coverage-probe` concurrency group and 20-minute job timeout.
- Uses the existing six-hour normal / fifteen-minute network-failure cooldown helper.
- Calls the existing 120-day/four-underlying probe and validates its JSON.
- Writes only a unique `research_state/historical_overlap_probe_*.json` artifact, with bounded fetch/rebase/push retries and exact remote file-blob verification.
- Emits a step summary and uploads a short-lived recovery artifact when the probe runs or is skipped.
- Starts no Kilo worker and does not write `research_state/workflow_run_diagnostics.jsonl`. No push or manual-dispatch trigger was added.

The full Research CI must be checked on this revision. A scheduled run must then be inspected to prove the workflow is active; if it skips due to cooldown, that is not a new source test. The last known probe artifact was observed at 2026-10-25T18:07:05Z, so under its existing six-hour cooldown the next full probe is expected after about 2026-10-26T00:07Z, at the next scheduled slot (subject to GitHub schedule latency).

## Research status unchanged

The last evidenced common price window across Hyperliquid and OKX for BTC, ETH, SOL and XRP was 2026-06-27 through 2026-10-25; the common funding overlap was approximately 97 days because the OKX funding endpoint was limiting. The prior report explicitly says historical coverage gate NOT_PASSED_BY_COVERAGE_PROBE and contract identity is not independently verified.

The original confirmatory manifest remains `BLOCKED_DATA_GATE`; FVD001–FVD108 and anchor FVD053 remain frozen. This probe is only a source-coverage tool: no backtest has been run in this change, no performance metrics are claimed, and no claim of profitability is justified.

## Acceptance checks

1. Research CI passes, including the new workflow contract and Bash syntax checks.
2. A real scheduled run reaches the cooldown decision; if eligible, it runs the probe and records an artifact, while if not eligible it clearly records the skip reason.
3. For a completed probe, the report is JSON-valid, only the bounded source coverage probe ran, and the exact probe file blob is present on the remote default branch.
4. The independent workflow does not invoke Kilo, does not write the central diagnostics ledger, and never changes the frozen protocol/grid/manifest.
