# Kilo controller v2.8 status — 2026-10-25

## Change made

- Commit: `df06eae0544174f32bce46d6ed270dfb5d4ce8d2`
- Moved `Run and checkpoint bounded historical coverage before Kilo setup` to immediately after checkout in `.github/workflows/main.yml`.
- The probe now precedes offline diagnostics, completed-run log scanning, diagnostics-ledger persistence, npm installation, Kilo setup and model preflight. This reduces the chance that diagnostic backfill or a dependency/model outage consumes the activation before new source evidence is collected.
- The existing schedule/manual condition, cooldown, 120-day/four-asset bounded probe, JSON validation, checkpoint retry, remote-SHA verification, free-only model selection, scheduled 40-minute cap, and two-session limit are unchanged.
- Added immutable `prompts/autonomous_free_data_gate_unblocking_v2_8.md`; `AGENTS.md` now points to v2.8.

## Verification status

- The workflow-file commit triggers diagnostics-only workflow validation and Research CI. Check the latest Research CI result before calling this revision validated.
- No live scheduled/manual run has yet verified this new ordering. The older scheduled run `#40209613351` was reported still in progress on a pre-fix workflow revision at the last inspection. This interface does not expose a supported cancel or workflow-dispatch action; do not claim the new step has executed until a later run proves it.
- The probe only measures public-source coverage. HTTP 200 or a successful JSON artifact does not establish 120-day complete overlap, instrument identity, the three-year historical point-in-time market-cap gate, or strategy profitability.
- Original manifest remains `BLOCKED_DATA_GATE`; FVD001–FVD108 and FVD053 remain frozen. No backtest or performance metrics are claimed.

## Next measurable acceptance test

A future scheduled/manual activation must show, in its run log, that the early probe ran or was correctly skipped by cooldown; if it ran, inspect the persisted JSON for per-source status, timestamps, gaps, pagination stop reasons and contract-identity limits; verify the artifact's commit SHA against the remote branch; and confirm that Kilo remains bounded and uses only free, unauthenticated routes.
