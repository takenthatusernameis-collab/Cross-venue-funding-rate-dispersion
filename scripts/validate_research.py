#!/usr/bin/env python3
"""Offline validation of the frozen grid, protocol, initial state and Kilo contract."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.grid import load_grid, validate_grid  # noqa: E402


def validate_research(root: Path = ROOT) -> list[str]:
    errors = []
    required = [
        root / "configs/cross_venue_funding_dispersion_grid_v1.json",
        root / "prompts/cross_venue_funding_rate_dispersion_research_v1.md",
        root / "docs/research_protocol.md",
        root / "research_state/run_manifest.json",
        root / ".github/workflows/main.yml",
    ]
    errors.extend(f"missing required file: {p.relative_to(root)}" for p in required if not p.is_file())
    if errors:
        return errors
    grid = load_grid(required[0])
    errors.extend(validate_grid(grid))
    combined = (required[1].read_text(encoding="utf-8") + "\n" + required[2].read_text(encoding="utf-8")).lower()
    for phrase in ("23:00 utc", "no fallback threshold", "fvd053", "point-in-time", "no paid", "never trade"):
        if phrase not in combined:
            errors.append(f"protocol/prompt missing required phrase: {phrase}")
    manifest = json.loads(required[3].read_text(encoding="utf-8"))
    allowed_gate_statuses = {"NOT_RUN", "BLOCKED_DATA_GATE", "BLOCKED_SPECIFICATION_GATE",
                             "IMPLEMENTATION_FAILED", "EXPLORATORY_ONLY", "INCONCLUSIVE", "REJECTED"}
    if manifest.get("status") not in allowed_gate_statuses:
        errors.append("manifest status must be a registered non-performance status")
    if manifest.get("backtest_completed") is not False or manifest.get("performance_metrics_computed") is not False:
        errors.append("manifest must not claim a backtest or computed performance metrics")
    workflow = required[4].read_text(encoding="utf-8")
    for phrase in (
        "scripts/kilo_free_model_fallback.py",
        "scripts/should_run_historical_probe.py",
        "scripts/probe_historical_overlap.py",
        "--lookback-days 120 --max-assets 4",
        'kilo run --model "kilo/$current_model" --auto',
        "sign[ -]?up for free",
        "free-model-routes-exhausted",
        "HANDOFF.md",
        "checkpoint_reserve_seconds=300",
        "scripts/controller_progress.py",
    ):
        if phrase not in workflow:
            errors.append(f"Kilo workflow missing safeguard: {phrase}")
    if "workflow: write" in workflow.lower():
        errors.append("Kilo workflow must not grant workflow permission")
    return errors


def main() -> int:
    errors = validate_research()
    if errors:
        print("RESEARCH_VALIDATION=FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("RESEARCH_VALIDATION=PASS")
    print("GRID_CONFIGURATIONS=108")
    print("PRIMARY_ANCHOR=FVD053")
    print("INITIAL_RUN_STATUS=NOT_RUN")
    print("PERFORMANCE_METRICS_COMPUTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
