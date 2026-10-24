#!/usr/bin/env python3
"""Offline conformance check for the confirmatory/exploratory track separation.

Enforces AGENTS.md section 1 (two separate tracks) and the repository-specific
default in AGENTS.md:

  * The confirmatory manifest (research_state/run_manifest.json) must remain
    BLOCKED_DATA_GATE with the frozen 108-config grid sha256 and
    backtest_completed=false / performance_metrics_computed=false.
  * The exploratory manifest must carry a distinct run_id, status
    EXPLORATORY_ONLY or INCONCLUSIVE, must not reference the frozen confirmatory
    grid anchor as a result, and must not claim any performance metric.
  * The exploratory manifest must never flip the confirmatory gate or alter the
    confirmatory grid hash recorded in the confirmatory manifest.

Standard library only; no network calls; no economic result.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.status import ResearchStatus  # noqa: E402

FROZEN_GRID_SHA = "6be218bc84bf118cf67c238ad1c13ef1e445658db3b1346cd64ccaccc7aa5f07"
EXPLORATORY_STATUSES = {"EXPLORATORY_ONLY", "INCONCLUSIVE"}
CONFIRMATORY_STATUS = "BLOCKED_DATA_GATE"


def check(cond, msg):
    if not cond:
        print("FAIL:", msg)
        sys.exit(1)


def load_json(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: unreadable JSON {path.name}: {exc}")
        sys.exit(1)


def main() -> int:
    confirm_path = ROOT / "research_state/run_manifest.json"
    expl_path = ROOT / "research_state/exploratory_run_manifest_2026-10-24.json"
    grid_path = ROOT / "configs/cross_venue_funding_dispersion_grid_v1.json"

    for path in (confirm_path, expl_path, grid_path):
        check(path.is_file(), f"missing required artifact {path.name}")

    confirmatory = load_json(confirm_path)
    exploratory = load_json(expl_path)

    # --- Confirmatory track must remain frozen and blocked -------------------
    check(confirmatory.get("status") == CONFIRMATORY_STATUS,
          "confirmatory run_manifest status must remain BLOCKED_DATA_GATE")
    check(confirmatory.get("backtest_completed") is False,
          "confirmatory backtest_completed must be false")
    check(confirmatory.get("performance_metrics_computed") is False,
          "confirmatory performance_metrics_computed must be false")
    check(confirmatory.get("grid_config_sha256") == FROZEN_GRID_SHA,
          "confirmatory grid sha256 must remain the frozen 108-config grid")
    check(confirmatory.get("historical_point_in_time_market_cap_gate") == "BLOCKED",
          "confirmatory historical_point_in_time_market_cap_gate must remain BLOCKED")

    # --- Exploratory track must be separately versioned and non-confirmatory --
    run_id = exploratory.get("run_id")
    check(isinstance(run_id, str) and run_id, "exploratory manifest must carry a run_id")
    check(run_id != "FVD053", "exploratory run_id must not reuse the frozen confirmatory anchor id")
    check(run_id.startswith("FVD-EXPLORATORY"), "exploratory run_id must be under FVD-EXPLORATORY namespace")
    status = exploratory.get("status")
    check(status in EXPLORATORY_STATUSES,
          f"exploratory status must be EXPLORATORY_ONLY or INCONCLUSIVE, got {status!r}")
    try:
        ResearchStatus(status)
    except ValueError:
        check(False, f"exploratory status {status!r} is not a registered ResearchStatus")
    check(exploratory.get("backtest_completed") is False,
          "exploratory backtest_completed must be false")
    check(exploratory.get("performance_metrics_computed") is False,
          "exploratory performance_metrics_computed must be false")

    # --- Track separation: exploratory must not alter the confirmatory gate ---
    check(exploratory.get("historical_point_in_time_market_cap_gate") in (None, "BLOCKED", "BLOCKED_DATA_GATE", "N/A"),
          "exploratory manifest must not report a passed confirmatory gate")
    check(exploratory.get("confirmatory_status_preserved") == "BLOCKED_DATA_GATE",
          "exploratory manifest must preserve confirmatory_status_preserved=BLOCKED_DATA_GATE")
    check("grid_config_sha256" not in exploratory
          or exploratory.get("grid_config_sha256") == FROZEN_GRID_SHA,
          "exploratory manifest must not introduce a different confirmatory grid hash")
    check("anchor" not in exploratory or exploratory.get("anchor") in (None, "FVD053"),
          "exploratory manifest may only reference FVD053 as a frozen anchor, never as a result")

    # --- Frozen grid file on disk is untouched --------------------------------
    import hashlib
    digest = hashlib.sha256(grid_path.read_bytes()).hexdigest()
    check(digest == FROZEN_GRID_SHA, "frozen grid file on disk must match the recorded sha256")

    print("TRACK_SEPARATION_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())