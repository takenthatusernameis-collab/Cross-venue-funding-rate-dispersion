# Durable Kilo Research Handoff

## Mission and evidence status

Investigate the cross-venue funding-rate dispersion hypothesis in `docs/research_protocol.md`.

**Current status: NOT_RUN. Data gate: BLOCKED_DATA_GATE (no free public source meets the >=3-year point-in-time market-cap gate). No historical backtest has been completed. No performance metrics or economic edge are established.** CI and synthetic tests verify engineering contracts only.

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

## Completed Task — Historical source coverage gate (2026-10-24)

1. Read AGENTS.md, SKILLS.md, .agents/skills/historical-universe/SKILL.md, .agents/skills/research-orchestration/SKILL.md, and docs/sources.md.
2. Ran the four AGENTS.md offline commands: `python3 -m compileall -q src scripts tests` = OK; `PYTHONPATH=src python3 -m unittest discover -s tests -v` = 28 tests OK; `PYTHONPATH=src python3 scripts/validate_research.py` = RESEARCH_VALIDATION=PASS, grid 108, anchor FVD053, status NOT_RUN, no metrics; `python3 scripts/validate_skills.py` = SKILLS_VALIDATION=PASS count=4.
3. Ran the bounded public-source preflight: `python3 scripts/preflight_public_sources.py --output research_state/preflight_2026-10-24_reverify.json` = 3/5 reachable (OKX 200, CoinGecko 200, Hyperliquid 200; Binance 451, Bybit 403); gate NOT_VERIFIED by reachability alone. Stored as artifact, not market evidence.
4. Investigated official free sources for historical point-in-time market-cap data (effective + publication/availability time): Binance USD-M (451), Bybit (403), OKX time (200, no cap ranks), CoinGecko ping (200, free plan limited to 365 days per support docs), Hyperliquid info meta (200, no cap rank history), CoinPaprika tickers (200, free tier 1 year daily, HTTP 402 for older), CoinCap (DNS failure), CoinMarketCap listings latest (401, key required), CryptoDataDownload (OHLCV since 2017, no cap ranks), Wayback Machine CMC snapshots (HTML scraping, not a structured reproducible API).
5. Produced research_state/source_coverage_matrix_2026-10-24.json: endpoint/request, response status, usable range, pagination, missingness, units, terms/limits, retrieval time and response sha256 for all candidates; artifact sha256 1339f9c3059030e275827e61d8e510348feb77218c579c9df44845e308290645 recorded in research_state/run_manifest.json output_artifacts (previously "pending").
6. No source meets the >=3-year historical point-in-time market-cap gate: run_manifest.json retains status BLOCKED_DATA_GATE, historical_point_in_time_market_cap_gate BLOCKED, backtest_completed false, performance_metrics_computed false; caveats appended, prior evidence preserved. The empirical grid was NOT run.
7. Re-ran tests and validators (all PASS), inspected `git diff --check` (clean) and full diff, verified remote persistence: `git ls-remote origin HEAD` = da797a82bed8efa36208b597934a88648c87d93b equals local HEAD; new artifacts are uncommitted working-tree files pending an explicit commit instruction.

## Next task: source-independent deterministic work while data gate is blocked

1. Add known-answer and adversarial tests for the source-independent primitives: funding cash-flow sign conventions, price/basis PnL separation, per-leg execution cost, time-weighted mean staleness gap fail-close, rank frontier gap rejection, type-7 quantile no-fallback, tail-selection determinism, and the 1.0x gross-exposure cap.
2. Run the four AGENTS.md validation commands and confirm all pass; keep run status BLOCKED_DATA_GATE.
3. Do not run the empirical grid until a free public source passes the historical point-in-time market-cap gate; do not claim any performance metric.

## Completed Task — Source-independent primitive test coverage (2026-10-24)

1. Verified existing known-answer/adversarial tests cover all eight listed primitives: funding cash-flow sign conventions, price/basis PnL separation, per-leg execution cost, time-weighted mean staleness gap fail-close, rank frontier gap rejection, type-7 quantile no-fallback, tail-selection determinism, and the 1.0x gross-exposure cap.
2. Ran the four AGENTS.md validation commands: compileall OK; 28 tests OK; RESEARCH_VALIDATION=PASS (grid 108, anchor FVD053, status NOT_RUN, no metrics); SKILLS_VALIDATION=PASS count=4.
3. `git diff --check` clean; status BLOCKED_DATA_GATE retained; no empirical grid run; no performance metric claimed.

## Completed Task — Historical point-in-time market-cap data gate verification (2026-10-24)

1. Re-verified the data gate using existing immutable evidence: research_state/source_coverage_matrix_2026-10-24.json (sha256 1339f9c3059030e275827e61d8e510348feb77218c579c9df44845e308290645) documents 10 candidate free sources; none meets the >=3-year point-in-time market-cap gate with both effective/as-of and publication/availability timestamps (CoinGecko 365 days, CoinPaprika 1 year daily, Binance USD-M 451, Bybit 403, CoinMarketCap 401/key, CoinCap DNS failure, OKX/Hyperliquid reachable without cap-rank history, CryptoDataDownload OHLCV-only, Wayback CMC HTML-scraping-only).
2. Did not re-probe the same sources (avoid looping on documented failure); no materially different free public source was found that meets the gate. Gate remains BLOCKED_DATA_GATE; all artifacts and prior evidence preserved, untouched.
3. Ran the four AGENTS.md validation commands: `python3 -m compileall -q src scripts tests` = OK; `PYTHONPATH=src python3 -m unittest discover -s tests -v` = 28 tests OK; `PYTHONPATH=src python3 scripts/validate_research.py` = RESEARCH_VALIDATION=PASS (grid 108, anchor FVD053, status NOT_RUN, no metrics); `python3 scripts/validate_skills.py` = SKILLS_VALIDATION=PASS count=4.
4. research_state/run_manifest.json retains status BLOCKED_DATA_GATE, historical_point_in_time_market_cap_gate BLOCKED, backtest_completed false, performance_metrics_computed false; grid sha 6be218bc84bf118cf67c238ad1c13ef1e445658db3b1346cd64ccaccc7aa5f07 unchanged (frozen 108-config grid FVD001-FVD108, anchor FVD053, preserved).
5. `git status --short` clean; `git diff --check` exit 0; remote HEAD da797a82bed8efa36208b597934a88648c87d93b equals local HEAD; no uncommitted changes from this read-only validation session.
6. No performance metric or economic edge claimed.

## Next task: source-independent universe-frontier readiness (data gate remains blocked)

Implement and test the source-independent universe-frontier persistence contract (snapshot ID, rank frontier sorted by market-cap descending with deterministic asset-ID tie-break, last completed rank, completed/pending asset IDs, explicit exclusions/reasons, source hashes, pagination cursors, resume state) per .agents/skills/historical-universe/SKILL.md, with known-answer tests; keep run status BLOCKED_DATA_GATE; re-run the four AGENTS.md validation commands and confirm all pass; do not run the empirical grid until a free public source passes the historical point-in-time market-cap gate; do not claim any performance metric.
