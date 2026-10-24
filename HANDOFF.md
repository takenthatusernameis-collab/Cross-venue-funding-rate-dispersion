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

## Next task: prove or block historical source coverage

1. Read AGENTS.md, SKILLS.md, the historical-universe and research-orchestration skills, and docs/sources.md.
2. Run the four offline commands listed in AGENTS.md.
3. If useful, run the manual public-source preflight; store it as an artifact, not market evidence.
4. Investigate official free sources for historical point-in-time market-cap data with both effective and publication/availability time. Verify terms, history span, delisted coverage, pagination and reproducibility.
5. Produce a source coverage matrix: endpoint/request, response status, usable range, pagination exhaustion proof, missingness, units, terms/limits, retrieval time and response hashes.
6. If no source meets the gate, record BLOCKED_DATA_GATE in a new immutable run record and continue source-independent accounting/cohort tests. Do not run the empirical grid.
7. Before ending, run tests, inspect the full diff, verify remote persistence, append a dated Completed Task entry with evidence and set one next measurable task.
