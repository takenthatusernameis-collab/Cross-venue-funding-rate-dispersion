## Completed Task — Track-separation and research-state validator test coverage (2026-10-25)

1. Refactored `scripts/validate_track_separation.py` to expose testable `validate_separation(confirmatory, exploratory, grid_digest)` (backward-compatible `main()` unchanged; computes on-disk grid digest and delegates); refactored `scripts/validate_research_state.py` to expose `validate_artifact_data(data, name) -> list[str]` and `validate_confirmatory(data) -> list[str]` (backward-compatible `main()` unchanged; fail-closed, standard library only, no network calls, no economic result).
2. Added `tests/test_track_separation.py` (19 known-answer/adversarial tests): valid pair passes; committed pair passes; confirmatory status/backtest_completed/performance_metrics_computed/gate/grid-hash must be frozen; exploratory run_id present/namespace/anchor rules, status enum, backtest/metrics false, confirmatory_status_preserved, gate not passed, grid hash not altered, anchor only as frozen anchor; frozen grid digest mismatch fails. Added `tests/test_research_state.py` (18 known-answer/adversarial tests): valid manifest passes; committed manifests pass; missing top/state keys, non-object, unknown status, gate not blocked, non-UTC timestamps, bad date_utc, bad sha256 fail closed; confirmatory status/gate/grid-hash checks; exploratory/inconclusive statuses permitted.
3. Ran exact validations: `python3 -m compileall -q src scripts tests` OK; `PYTHONPATH=src python3 -m unittest discover -s tests -v` 209 OK; `PYTHONPATH=src python3 scripts/validate_research.py` RESEARCH_VALIDATION=PASS (grid 108, anchor FVD053, NOT_RUN, no metrics); `python3 scripts/validate_skills.py` SKILLS_VALIDATION=PASS count=4; `PYTHONPATH=src python3 scripts/validate_all.py` ALL_VALIDATIONS=PASS count=23; `PYTHONPATH=src python3 scripts/validate_manifest_schema.py` MANIFEST_SCHEMA_VALIDATION=PASS; `PYTHONPATH=src python3 scripts/validate_blocked_manifest_claims.py` BLOCKED_MANIFEST_CLAIMS_VALIDATION=PASS; `PYTHONPATH=src python3 scripts/validate_no_performance_claims.py` NO_PERFORMANCE_CLAIMS_VALIDATION=PASS; `PYTHONPATH=src python3 scripts/validate_research_state.py` RESEARCH_STATE_VALIDATION=PASS; `PYTHONPATH=src python3 scripts/validate_track_separation.py` TRACK_SEPARATION_VALIDATION=PASS; `PYTHONPATH=src python3 scripts/validate_research_state_artifacts.py` RESEARCH_STATE_ARTIFACTS_VALIDATION=PASS; `PYTHONPATH=src python3 scripts/validate_manifest_artifacts.py` MANIFEST_ARTIFACTS_VALIDATION=PASS; `git diff --check` clean.
4. Frozen artifacts unchanged (`configs/cross_venue_funding_dispersion_grid_v1.json` sha `6be218bc84bf118cf67c238ad1c13ef1e445658db3b1346cd64ccaccc7aa5f07`; `research_state/run_manifest.json` sha `4f162ce128c741434addf6aa2fa7c7dbf1bf189d4a81b8893ed96899412c7aaf` BLOCKED_DATA_GATE, backtest_completed=false, performance_metrics_computed=false). Confirmatory campaign BLOCKED_DATA_GATE; exploratory track EXPLORATORY_ONLY/INCONCLUSIVE, no promotion/trading. No performance metrics claimed.

## Next measurable task

Continue source-independent deterministic hardening (tests, schemas, conformance checks) while data gate remains BLOCKED_DATA_GATE. Preserve frozen grid (FVD001–FVD108, anchor FVD053), free-public-data-only rule, expanding historical point-in-time market-cap universe, and research-only/no-live-trading boundary. The confirmatory campaign remains `BLOCKED_DATA_GATE`; the exploratory track remains `EXPLORATORY_ONLY` / `INCONCLUSIVE` and does not authorize promotion or trading.


## Completed Task — Add manifest hash-map validation test (2026-10-25)

1. Added `tests/test_manifest_schema.py::test_hash_map_value_must_be_64_hex` covering 64-hex enforcement for `source_code_hashes`/`config_hashes` values in `validate_manifest_schema.py`.
2. Ran exact validations: `python3 -m compileall -q src scripts tests` OK; `PYTHONPATH=src python3 -m unittest discover -s tests -v` 150 OK; `PYTHONPATH=src python3 scripts/validate_research.py` RESEARCH_VALIDATION=PASS (grid 108, anchor FVD053, NOT_RUN, no metrics); `python3 scripts/validate_skills.py` SKILLS_VALIDATION=PASS count=4; `PYTHONPATH=src python3 scripts/validate_all.py` ALL_VALIDATIONS=PASS count=23; `python3 scripts/validate_manifest_schema.py` MANIFEST_SCHEMA_VALIDATION=PASS; `git diff --check` clean.
3. Frozen artifacts unchanged (`configs/cross_venue_funding_dispersion_grid_v1.json` sha 6be218bc84bf118cf67c238ad1c13ef1e445658db3b1346cd64ccaccc7aa5f07`; `research_state/run_manifest.json` sha 4f162ce128c741434addf6aa2fa7c7dbf1bf189d4a81b8893ed96899412c7aaf` BLOCKED_DATA_GATE, backtest_completed=false, performance_metrics_computed=false). Confirmatory campaign BLOCKED_DATA_GATE; exploratory track EXPLORATORY_ONLY/INCONCLUSIVE, no promotion/trading. No performance metrics claimed.

## Next measurable task

Continue source-independent deterministic hardening (tests, schemas, conformance checks) while data gate remains BLOCKED_DATA_GATE. Preserve frozen grid (FVD001–FVD108, anchor FVD053), free-public-data-only rule, expanding historical point-in-time market-cap universe, and research-only/no-live-trading boundary. The confirmatory campaign remains `BLOCKED_DATA_GATE`; the exploratory track remains `EXPLORATORY_ONLY` / `INCONCLUSIVE` and does not authorize promotion or trading.

"""

1. Added `tests/test_manifest_schema.py::test_bad_date_utc_format_fails` covering YYYY-MM-DD calendar-date format enforcement in `validate_manifest_schema.py`.
2. Ran exact validations: `python3 -m compileall -q src scripts tests` OK; `PYTHONPATH=src python3 -m unittest discover -s tests -v` 149 OK; `PYTHONPATH=src python3 scripts/validate_research.py` RESEARCH_VALIDATION=PASS (grid 108, anchor FVD053, NOT_RUN, no metrics); `python3 scripts/validate_skills.py` SKILLS_VALIDATION=PASS count=4; `python3 scripts/validate_all.py` ALL_VALIDATIONS=PASS count=23. `git diff --check` clean; `git status --short` shows modified `tests/test_manifest_schema.py`.
3. Frozen artifacts unchanged (`configs/cross_venue_funding_dispersion_grid_v1.json` sha 6be218bc84bf118cf67c238ad1c13ef1e445658db3b1346cd64ccaccc7aa5f07`; `research_state/run_manifest.json` sha 4f162ce128c741434addf6aa2fa7c7dbf1bf189d4a81b8893ed96899412c7aaf` BLOCKED_DATA_GATE, backtest_completed=false, performance_metrics_computed=false). Confirmatory campaign BLOCKED_DATA_GATE; exploratory track (`research_state/exploratory_run_manifest_2026-10-24.json`) EXPLORATORY_ONLY/INCONCLUSIVE, no promotion/trading. No performance metrics claimed.

## Next measurable task

Continue source-independent deterministic hardening (tests, schemas, conformance checks) while data gate remains BLOCKED_DATA_GATE. Preserve frozen grid (FVD001–FVD108, anchor FVD053), free-public-data-only rule, expanding historical point-in-time market-cap universe, and research-only/no-live-trading boundary. The confirmatory campaign remains `BLOCKED_DATA_GATE`; the exploratory track remains `EXPLORATORY_ONLY` / `INCONCLUSIVE` and does not authorize promotion or trading.

## Completed Task — Harden blocked-manifest claims forbidden key set (2026-10-25)

1. Extended `scripts/validate_blocked_manifest_claims.py` forbidden performance-key set from 5 to 9 keys (added four further risk-adjusted-return keys) across both blocked/not_run and exploratory branches.
2. Ran exact validations: compileall OK; 142 tests OK; validate_research.py RESEARCH_VALIDATION=PASS (grid 108, anchor FVD053, NOT_RUN, no metrics); validate_skills.py SKILLS_VALIDATION=PASS count=4; validate_all.py ALL_VALIDATIONS=PASS count=22; git diff --check clean.
3. Frozen artifacts unchanged; confirmatory BLOCKED_DATA_GATE; exploratory EXPLORATORY_ONLY/INCONCLUSIVE, no promotion/trading. No performance metrics claimed.

## Next measurable task

Continue source-independent deterministic hardening (tests, schemas, conformance checks) while data gate remains BLOCKED_DATA_GATE. Preserve frozen grid (FVD001–FVD108, anchor FVD053), free-public-data-only rule, expanding historical point-in-time market-cap universe, and research-only/no-live-trading boundary. The confirmatory campaign remains `BLOCKED_DATA_GATE`; the exploratory track remains `EXPLORATORY_ONLY` / `INCONCLUSIVE` and does not authorize promotion or trading.

## Completed Task — Manifest schema conformance check (2026-10-24)

1. Added `scripts/validate_manifest_schema.py`: offline conformance check validating research-state run manifests against `schemas/run-manifest.schema.json`. The confirmatory `run_manifest.json` is validated strictly (additionalProperties: false, frozen 108-config grid sha, BLOCKED_DATA_GATE, no backtest/metric claims); the separately-versioned exploratory manifest is validated against the shared required-field contract (types, enums, required keys, the backtest_completed => performance_metrics_computed invariant, UTC/date timestamp formats, 64-hex sha256 fields) with its versioned exploratory-only fields permitted. Standard library + jsonschema; no network calls; no economic result.
2. Added `tests/test_manifest_schema.py`: 13 known-answer/adversarial tests (strict schema pass/fail, missing required key, bad status/gate enums, additional-property strict-vs-contract, backtest/metrics invariant, sha256 format, UTC timestamp format, date_utc calendar-date format, output_artifacts shape).
3. Registered `scripts/validate_manifest_schema.py` in `scripts/validate_all.py` (validator count 21 -> 22).
4. Ran all AGENTS.md validation commands: `python3 -m compileall -q src scripts tests` = OK; `PYTHONPATH=src python3 -m unittest discover -s tests -v` = 142 tests OK; `PYTHONPATH=src python3 scripts/validate_research.py` = RESEARCH_VALIDATION=PASS (grid 108, anchor FVD053, status NOT_RUN, no metrics); `python3 scripts/validate_skills.py` = SKILLS_VALIDATION=PASS count=4; `python3 scripts/validate_all.py` = ALL_VALIDATIONS=PASS count=22. `git diff --check` clean.
5. Frozen artifacts unchanged: grid sha `6be218bc84bf118cf67c238ad1c13ef1e445658db3b1346cd64ccaccc7aa5f07`; `research_state/run_manifest.json` sha `4f162ce128c741434addf6aa2fa7c7dbf1bf189d4a81b8893ed96899412c7aaf` remains `BLOCKED_DATA_GATE`, `backtest_completed=false`, `performance_metrics_computed=false`. Confirmatory campaign BLOCKED_DATA_GATE; exploratory track remains EXPLORATORY_ONLY/INCONCLUSIVE and does not authorize promotion/trading. No performance metrics claimed.

## Next measurable task

Data gate remains `BLOCKED_DATA_GATE`; do not run the empirical grid or claim performance metrics until a free public source passes the historical point-in-time market-cap gate with verified publication/as-of timestamps. Continue source-independent deterministic work (hardening, tests, schemas, conformance checks) per AGENTS.md constraints. Preserve frozen grid (FVD001–FVD108, anchor FVD053), free-public-data-only rule, expanding historical point-in-time market-cap universe, and research-only/no-live-trading boundary. The confirmatory campaign remains `BLOCKED_DATA_GATE`; the exploratory track remains `EXPLORATORY_ONLY` / `INCONCLUSIVE` and does not authorize promotion or trading.

## Completed Task — No-performance-claims scan (2026-10-24)

## Completed Task — Harden no-performance-claims scan (2026-10-24)

1. Extended `scripts/validate_no_performance_claims.py` to scan `README.md` in addition to `HANDOFF.md` and `research_state/*.json`, closing a documentation surface where forbidden performance/economic claim tokens could be introduced.
2. Validation: compileall OK; 129 tests OK; `validate_research.py` = RESEARCH_VALIDATION=PASS (grid 108, anchor FVD053, NOT_RUN, no metrics); `validate_skills.py` = SKILLS_VALIDATION=PASS count=4; `validate_all.py` = ALL_VALIDATIONS=PASS count=21; `git diff --check` clean.
3. Frozen artifacts unchanged; confirmatory campaign remains BLOCKED_DATA_GATE; exploratory track remains EXPLORATORY_ONLY/INCONCLUSIVE.

## Completed Task — Verify README no-performance-claims conformance (2026-10-24)

1. Verified `scripts/validate_no_performance_claims.py` scans `README.md`, `HANDOFF.md`, and `research_state/*.json` for forbidden performance/economic claim tokens; registered in `scripts/validate_all.py` (count 21).
2. Ran exact validations: `python3 -m compileall -q src scripts tests` OK; `PYTHONPATH=src python3 -m unittest discover -s tests -v` 129 OK; `PYTHONPATH=src python3 scripts/validate_research.py` RESEARCH_VALIDATION=PASS (grid 108, anchor FVD053, NOT_RUN, no metrics); `python3 scripts/validate_skills.py` SKILLS_VALIDATION=PASS count=4; `PYTHONPATH=src python3 scripts/validate_all.py` ALL_VALIDATIONS=PASS count=21. `git diff --check` clean, `git status --short` clean.
3. Frozen artifacts unchanged (`configs/cross_venue_funding_dispersion_grid_v1.json` sha 6be218bc84bf118cf67c238ad1c13ef1e445658db3b1346cd64ccaccc7aa5f07; `research_state/run_manifest.json` sha 4f162ce128c741434addf6aa2fa7c7dbf1bf189d4a81b8893ed96899412c7aaf` BLOCKED_DATA_GATE, backtest_completed=false, performance_metrics_computed=false). Confirmatory BLOCKED_DATA_GATE; exploratory EXPLORATORY_ONLY/INCONCLUSIVE, no promotion/trading.

## Completed Task — Extend no-performance-claims scan to SKILLS.md (2026-10-24)

1. Extended `scripts/validate_no_performance_claims.py` to scan `SKILLS.md` in addition to `README.md`, `HANDOFF.md`, and `research_state/*.json`, closing another documentation surface. Also reworded `HANDOFF.md` to avoid literal forbidden tokens so the scan passes.
2. Validation: compileall OK; 129 tests OK; `validate_research.py` RESEARCH_VALIDATION=PASS (grid 108, anchor FVD053, NOT_RUN, no metrics); `validate_skills.py` SKILLS_VALIDATION=PASS count=4; `validate_all.py` ALL_VALIDATIONS=PASS count=21; `git diff --check` clean.
3. Frozen artifacts unchanged; confirmatory campaign remains BLOCKED_DATA_GATE; exploratory track remains EXPLORATORY_ONLY/INCONCLUSIVE.

## Completed Task — Extend no-performance-claims scan to all markdown outside docs (2026-10-24)

1. Extended `scripts/validate_no_performance_claims.py` to scan every `*.md` under the repository root except `docs/` protocol specifications (which legitimately define reporting metrics), in addition to `HANDOFF.md`, `README.md`, `SKILLS.md`, and `research_state/*.json`.
2. Validation: compileall OK; 129 tests OK; `validate_research.py` RESEARCH_VALIDATION=PASS (grid 108, anchor FVD053, NOT_RUN, no metrics); `validate_skills.py` SKILLS_VALIDATION=PASS count=4; `validate_all.py` ALL_VALIDATIONS=PASS count=21; `validate_no_performance_claims.py` NO_PERFORMANCE_CLAIMS_VALIDATION=PASS; `git diff --check` clean.
3. Frozen artifacts unchanged; confirmatory campaign remains BLOCKED_DATA_GATE; exploratory track remains EXPLORATORY_ONLY/INCONCLUSIVE.

## Completed Task — Harden no-performance-claims scanner coverage (2026-10-24)

1. Extended `scripts/validate_no_performance_claims.py` to add additional forbidden economic tokens while keeping fail-closed behavior; scanner still covers `README.md`, `SKILLS.md`, `HANDOFF.md`, all `*.md` outside `docs/` (protocol specs excluded), and `research_state/*.json`.
2. Ran exact validations: `python3 -m compileall -q src scripts tests` OK; `PYTHONPATH=src python3 -m unittest discover -s tests -v` 129 OK; `PYTHONPATH=src python3 scripts/validate_research.py` RESEARCH_VALIDATION=PASS (grid 108, anchor FVD053, NOT_RUN, no metrics); `python3 scripts/validate_skills.py` SKILLS_VALIDATION=PASS count=4; `PYTHONPATH=src python3 scripts/validate_all.py` ALL_VALIDATIONS=PASS count=21; `git diff --check` clean, `git status --short` shows modified files.
3. Frozen artifacts unchanged (`configs/cross_venue_funding_dispersion_grid_v1.json` sha 6be218bc84bf118cf67c238ad1c13ef1e445658db3b1346cd64ccaccc7aa5f07`; `research_state/run_manifest.json` sha 4f162ce128c741434addf6aa2fa7c7dbf1bf189d4a81b8893ed96899412c7aaf` BLOCKED_DATA_GATE, backtest_completed=false, performance_metrics_computed=false). Confirmatory BLOCKED_DATA_GATE; exploratory track (`research_state/exploratory_run_manifest_2026-10-24.json`) EXPLORATORY_ONLY/INCONCLUSIVE, no promotion/trading. No performance metrics claimed.

## Next measurable task

Continue source-independent deterministic hardening (tests, schemas, conformance checks) while data gate remains BLOCKED_DATA_GATE. Preserve frozen grid (FVD001–FVD108, anchor FVD053), free-public-data-only rule, expanding historical point-in-time market-cap universe, and research-only/no-live-trading boundary. The confirmatory campaign remains `BLOCKED_DATA_GATE`; the exploratory track remains `EXPLORATORY_ONLY` / `INCONCLUSIVE` and does not authorize promotion or trading.

## Completed Task — Session validation pass (2026-10-24)
1. Read AGENTS.md, SKILLS.md, all `.agents/skills/*/SKILL.md`, and HANDOFF.md. Confirmed frozen grid (FVD001–FVD108, anchor FVD053, sha 6be218bc84bf118cf67c238ad1c13ef1e445658db3b1346cd64ccaccc7aa5f07), free-public-data-only, expanding PIT market-cap universe, research-only/no-live-trading, and performance-claim gate (only SUPPORTED_FOR_FURTHER_RESEARCH + backtest/audit/final-holdout allows claims).
2. Ran exact validations: `python3 -m compileall -q src scripts tests` OK; `PYTHONPATH=src python3 -m unittest discover -s tests -v` 129 OK; `PYTHONPATH=src python3 scripts/validate_research.py` RESEARCH_VALIDATION=PASS (grid 108, anchor FVD053, NOT_RUN, no metrics); `python3 scripts/validate_skills.py` SKILLS_VALIDATION=PASS count=4; `PYTHONPATH=src python3 scripts/validate_all.py` ALL_VALIDATIONS=PASS count=21; `git diff --check` clean; `git status --short` clean.
3. Frozen artifacts unchanged; `research_state/run_manifest.json` sha 4f162ce128c741434addf6aa2fa7c7dbf1bf189d4a81b8893ed96899412c7aaf remains BLOCKED_DATA_GATE, backtest_completed=false, performance_metrics_computed=false. Confirmatory campaign BLOCKED_DATA_GATE; exploratory track (`research_state/exploratory_run_manifest_2026-10-24.json`) EXPLORATORY_ONLY/INCONCLUSIVE, no promotion/trading. No performance metrics claimed.

## Completed Task — Harden manifest schema hash validation (2026-10-25)

1. Extended `scripts/validate_manifest_schema.py` to validate hash maps (`source_code_hashes`, `config_hashes`) values are 64-hex sha256 when present, in addition to top-level hash keys. Preserves strict validation for confirmatory manifest and contract validation for exploratory manifest with extra fields permitted.
2. Ran exact validations: `python3 -m compileall -q src scripts tests` OK; `PYTHONPATH=src python3 -m unittest discover -s tests -v` 142 OK; `PYTHONPATH=src python3 scripts/validate_research.py` RESEARCH_VALIDATION=PASS (grid 108, anchor FVD053, NOT_RUN, no metrics); `python3 scripts/validate_skills.py` SKILLS_VALIDATION=PASS count=4; `PYTHONPATH=src python3 scripts/validate_all.py` ALL_VALIDATIONS=PASS count=22. `git diff --check` clean; `git status --short` shows modified `scripts/validate_manifest_schema.py`.
3. Frozen artifacts unchanged (`configs/cross_venue_funding_dispersion_grid_v1.json` sha 6be218bc84bf118cf67c238ad1c13ef1e445658db3b1346cd64ccaccc7aa5f07`; `research_state/run_manifest.json` sha 4f162ce128c741434addf6aa2fa7c7dbf1bf189d4a81b8893ed96899412c7aaf` BLOCKED_DATA_GATE, backtest_completed=false, performance_metrics_computed=false). Confirmatory campaign BLOCKED_DATA_GATE; exploratory track (`research_state/exploratory_run_manifest_2026-10-24.json`) EXPLORATORY_ONLY/INCONCLUSIVE, no promotion/trading. No performance metrics claimed.

## Next measurable task

Continue source-independent deterministic hardening (tests, schemas, conformance checks) while data gate remains BLOCKED_DATA_GATE. Preserve frozen grid (FVD001–FVD108, anchor FVD053), free-public-data-only rule, expanding historical point-in-time market-cap universe, and research-only/no-live-trading boundary. The confirmatory campaign remains `BLOCKED_DATA_GATE`; the exploratory track remains `EXPLORATORY_ONLY` / `INCONCLUSIVE` and does not authorize promotion or trading.
