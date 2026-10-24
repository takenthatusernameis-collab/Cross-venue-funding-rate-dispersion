# Durable Kilo Research Handoff

## Mission and evidence status

Investigate the cross-venue funding-rate dispersion hypothesis in `docs/research_protocol.md`.

**Current status: NOT_RUN. No historical backtest has been completed. No performance metrics or economic edge are established.** CI and synthetic tests verify engineering contracts only.

## Non-negotiable constraints

- Free public data and no-cost tools only; no paid APIs/services/trials/compute.
- Research only; no live or paper orders, trading credentials, or bot deployment.
- Frozen 108-config grid, FVD001–FVD108; FVD053 primary anchor.
- Expanding descending historical point-in-time market-cap universe, no fixed top-N cutoff, durable rank frontier and explicit exclusion reasons.
- Current cap snapshots are discovery-only. If a free historical point-in-time source is unavailable, preserve BLOCKED_DATA_GATE.
- At least three years of usable history; causal hourly timing; actual funding settlement accounting; separate price/basis PnL; gross exposure <=1.0x.
- Chronological 60/20/20 split; grid on discovery/validation; final holdout only FVD053 after selection is frozen.
- No performance claim without a completed run and independent audit.

## Initial baseline

Repository baseline includes the frozen grid, protocol, deterministic grid/accounting/universe/status primitives, offline tests, bounded source preflight, Agent Skills, and Kilo/CI workflow scaffolding. No live source probe or historical backtest has been run as part of setup.

## Completed Task — Repository quality baseline (2026-10-24)

- Established the repository from an empty remote state with 70 tree entries, a concise AGENTS.md, CLAUDE.md shim, skill index, four Agent Skills, architecture/protocol/source documentation, ADRs, frozen config, run manifest, universe frontier, Python package, validators, bounded no-secret source preflight, CI and the full Kilo controller workflow.
- Kilo push-validation run **#40049658390** completed successfully: offline validation step passed, **28 unit/adversarial tests passed**, research validator reported `RESEARCH_VALIDATION=PASS`, grid count 108, anchor FVD053, initial status NOT_RUN, and skills validator passed for four skills. JSON syntax checks for grid, manifest and schema also passed.
- The push-triggered run correctly skipped the Kilo worker; this was a validation activation, not a completed research session. Do not report a backtest or strategy metrics.
- The separate Research CI workflow has an older run that remains in progress and a newer run queued. Its final status is not claimed here; the same test and validation commands did pass in the Kilo push-validation run. Check the workflow queue before claiming separate CI completion.
- Latest known Kilo validation commit: `08941d64284ec9b5d99f74b31a9ab2a8a0da8d19`. The main branch subsequently received the workflow diagnostics ledger and CI path-ignore refinement. Research status remains NOT_RUN.

## Next task: prove or block historical source coverage

1. Read AGENTS.md, SKILLS.md, the historical-universe and research-orchestration skills, and docs/sources.md.
2. Run the four offline commands listed in AGENTS.md.
3. If useful, run the manual public-source preflight; store it as an artifact, not market evidence.
4. Investigate official free sources for historical point-in-time market-cap data with both effective and publication/availability time. Verify terms, history span, delisted coverage, pagination and reproducibility.
5. Produce a source coverage matrix: endpoint/request, response status, usable range, pagination exhaustion proof, missingness, units, terms/limits, retrieval time and response hashes.
6. If no source meets the gate, record BLOCKED_DATA_GATE in a new immutable run record and continue source-independent accounting/cohort tests. Do not run the empirical grid.
7. Before ending, run tests, inspect the full diff, verify remote persistence, append a dated Completed Task entry with evidence and set one next measurable task.
