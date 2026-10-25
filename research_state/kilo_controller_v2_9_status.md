# Kilo controller v2.9 status — 2026-10-25

## Changes committed

- Workflow deadline/controller commit: `82c3a0cff4cbdc215fc1e4a393271786dd2ae67a`; follow-up reporting/test-contract commit: `913874dd4fe41785741daad2b5ca559f002ebdc3`.
- The 120-day public-source coverage probe now runs immediately after checkout, before diagnostic backfill, ledger persistence, npm installation and Kilo.
- Scheduled activations record their start before the probe and use a 40-minute job-wide deadline. The workflow job timeout is 45 minutes for scheduled, push-diagnostics and diagnostics-only activations, leaving five minutes for checkpoint/recovery.
- A normal manual research dispatch retains its 355-minute Kilo budget and 360-minute job timeout.
- If preflight consumes the scheduled budget, the Kilo loop exits instead of resetting the clock or starting a new session.
- Prompt v2.9 is immutable at `prompts/autonomous_free_data_gate_unblocking_v2_9.md`; `AGENTS.md` points to it.

## Verification status

- Research CI [#40222908322](https://github.com/takenthatusernameis-collab/Cross-venue-funding-rate-dispersion/actions/runs/40222908322) passed on commit `913874dd4fe41785741daad2b5ca559f002ebdc3`. The first run against the deadline change exposed one stale test that expected a literal `timeout-minutes: 360`; the workflow contract test was updated to assert the conditional 360/45-minute policy and the probe-before-diagnostics ordering. The corrected full CI passed.
- Older scheduled run `#40209613351` was still in progress at the latest inspection, on a pre-fix workflow SHA. The available GitHub integration exposes no supported cancel or workflow-dispatch action. New code cannot affect that existing process.
- Live acceptance is still outstanding: a future scheduled/manual run must prove the early probe ran or was properly skipped by cooldown, record real source coverage, verify the probe artifact commit SHA remotely, and exit within the intended deadline.
- Historical coverage is not equivalent to the three-year point-in-time market-cap gate. The original manifest remains `BLOCKED_DATA_GATE`; FVD001–FVD108 and FVD053 remain frozen. No new backtest or performance metrics are claimed.

## Next measurable acceptance test

Inspect the next eligible scheduled activation's timestamps and step outcomes. Verify: probe precedes diagnostics; scheduled elapsed time stays within 45 minutes; a probe checkpoint is remotely verified or recovery evidence is retained; and any Kilo session uses only free, unauthenticated routes. Do not count CI green status as evidence of live data coverage.
