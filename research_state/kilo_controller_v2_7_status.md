# Kilo controller v2.7 execution status — 2026-10-25

## Changes committed

- `.github/workflows/main.yml`: scheduled activations are capped at 40 minutes and two sequential worker sessions, reserving the final five minutes for checkpoint/recovery. Manual dispatch retains its 355-minute budget.
- `.github/workflows/main.yml`: a dedicated bounded 120-day historical coverage step runs before Kilo CLI installation/model preflight, validates JSON, commits the probe artifact, and verifies the exact remote SHA with bounded retries. Runner-local evidence is uploaded if checkpointing fails.
- `prompts/autonomous_free_data_gate_unblocking_v2_7.md`: describes the new independent data-probe step, scheduling fix, acceptance checks, and limits.
- `AGENTS.md`: points agents to v2.7.

## Validation and limits

Research CI run [#40219700097](https://github.com/takenthatusernameis-collab/Cross-venue-funding-rate-dispersion/actions/runs/40219700097) passed on the 40-minute/two-session change. CI after the dedicated pre-Kilo probe step was still running at the time of this note; verify the latest CI run before treating that step as validated.

Scheduled run [#40209613351](https://github.com/takenthatusernameis-collab/Cross-venue-funding-rate-dispersion/actions/runs/40209613351) started at 16:00:33 UTC on an older workflow revision and remained in progress at the last check. New workflow changes cannot alter an already-running activation. The available GitHub integration cannot cancel it or dispatch a replacement. The new 40-minute cap and early probe take effect on a future scheduled activation after the old run releases the shared concurrency lock.

The last verified source evidence remains a six-hour Hyperliquid candle request for BTC/ETH/SOL/AVAX/LINK. No verified 120-day multi-venue overlap or strategy metrics are established. Confirmatory status remains `BLOCKED_DATA_GATE`; FVD001–FVD108 and FVD053 remain frozen.

## Acceptance checks

1. Latest Research CI passes.
2. A future scheduled run performs the probe before Kilo setup and commits/verifies the result or uploads recovery evidence.
3. Scheduled run exits within 40 minutes and no more than two worker sessions.
4. Report HTTP/network status separately from usable multi-venue historical coverage.
5. No paid data, credentials, live/paper trading, protocol/grid changes, or unsupported performance claims.
