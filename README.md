# Cross-Venue Funding-Rate Dispersion Research

**Current evidence status: NOT RUN.** This repository starts with a preregistered research design and engineering controls. No historical strategy backtest has been completed, and no performance metrics or economic edge are established.

## Hypothesis

At a given completed UTC hour, unusually high dispersion among normalized, recently settled perpetual-futures funding rates for the same underlying may identify a cross-venue, equal-notional long/short carry opportunity. The research must separate funding cash flows from venue-specific price/basis PnL and account for fees, slippage, missing data, funding schedules, and execution timing.

This is a falsifiable research hypothesis, not a trading recommendation.

## First checks

Requires Python 3.11+ and Git. The offline core and tests use the Python standard library.

```bash
python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 scripts/validate_research.py
python3 scripts/validate_skills.py
```

To inspect public endpoint reachability (manual, bounded, no credentials):

```bash
python3 scripts/preflight_public_sources.py --output /tmp/funding-source-preflight.json
```

A successful preflight means only that an endpoint responded at that time. It does **not** prove that sufficient historical funding, price, contract-mapping, delisted-asset, or point-in-time market-cap data is available.

## Research invariants

- Free, public data and no-cost tools only; no paid APIs, subscriptions, trials, or paid compute.
- Research and historical simulation only. Never submit orders, connect trading credentials, or deploy live/paper trading.
- Exactly **108** configurations, IDs **FVD001–FVD108**, in `configs/cross_venue_funding_dispersion_grid_v1.json`.
- Primary anchor **FVD053** is frozen. Do not tune it after inspecting the final holdout.
- The universe must expand through descending **historical point-in-time market-cap ranks**. There is no fixed top-N cutoff. Current ranks may discover candidates, but cannot stand in for historical ranks.
- If free historical point-in-time market-cap evidence cannot be established, block the affected backtest; do not fabricate ranks or silently weaken the design.
- No backtest or performance claim until data, causality, accounting, reproducibility, and independent audit gates pass.

## Repository map

- `AGENTS.md`: short always-on engineering rules and exact commands.
- `SKILLS.md` and `.agents/skills/*/SKILL.md`: progressive-disclosure agent procedures.
- `HANDOFF.md`: durable Kilo task, evidence ledger and next measurable deliverable.
- `configs/`: frozen parameter grid and research controls.
- `docs/research_protocol.md`: full hypothesis, timing, costs, splits, inference and gate definitions.
- `docs/exploratory_protocol_v1.md`: separate, explicitly non-confirmatory path for verified historical cross-venue overlap when the market-cap-rank gate blocks the original study.
- `prompts/`: iteratively refined self-contained research-agent prompt.
- `src/cross_venue_funding_dispersion/`: deterministic grid, signal/threshold, funding/price accounting, portfolio exposure and point-in-time universe primitives.
- `tests/`: offline known-answer and workflow-contract tests.
- `scripts/`: validation, progress accounting and bounded public-source preflight.
- `.github/workflows/main.yml`: sequential Kilo agent loop; scheduled/manual worker with checkpoint/recovery safeguards.
- `.github/workflows/research-ci.yml`: read-only offline validation.
- `.github/workflows/public-source-preflight.yml`: manually triggered public endpoint preflight.
- `research_state/`: explicit run status and expanding-universe frontier; not raw market-data storage.
- `schemas/`: machine-readable run manifest schema.

## Status vocabulary

Use `NOT_RUN`, `BLOCKED_DATA_GATE`, `BLOCKED_SPECIFICATION_GATE`, `IMPLEMENTATION_FAILED`, `EXPLORATORY_ONLY`, `INCONCLUSIVE`, `REJECTED`, or `SUPPORTED_FOR_FURTHER_RESEARCH` according to evidence. Worker success, a green CI run, synthetic fixtures, or a successful endpoint probe are not evidence of trading profitability.

## Agent workflow

Every Kilo session reads `AGENTS.md`, the relevant skill(s), and `HANDOFF.md`; completes one measurable task; runs the exact checks; inspects the diff; and updates the handoff with verified evidence and a specific next task. Research outputs must distinguish code correctness, data readiness, evaluation validity, and economic results.
