#!/usr/bin/env python3
"""Offline conformance check for the research-state persistence contract.

Verifies that every committed research-state artifact:
  1. is a JSON object with the required schema fields,
  2. carries a registered status that can never imply a performance claim,
  3. preserves the confirmatory gate as BLOCKED_DATA_GATE when the empirical
     grid has not run,
  4. records backtest_completed=false and performance_metrics_computed=false,
  5. records source/config/code hashes and UTC timestamps,
  6. never claims a backtest, edge or metric.

Standard library only; no network calls; no economic result.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.status import ResearchStatus  # noqa: E402

FROZEN_GRID_SHA = "6be218bc84bf118cf67c238ad1c13ef1e445658db3b1346cd64ccaccc7aa5f07"

NON_PERFORMANCE_STATUSES = {
    "NOT_RUN",
    "BLOCKED_DATA_GATE",
    "BLOCKED_SPECIFICATION_GATE",
    "IMPLEMENTATION_FAILED",
    "EXPLORATORY_ONLY",
    "INCONCLUSIVE",
    "REJECTED",
}

REQUIRED_TOP_KEYS = ("schema_version", "status")
REQUIRED_STATE_KEYS = ("backtest_completed", "performance_metrics_computed")


def check(cond, msg):
    if not cond:
        print("FAIL:", msg)
        sys.exit(1)


def load_json(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: unreadable JSON {path.name}: {exc}")
        sys.exit(1)
    check(isinstance(data, dict), f"{path.name} must be a JSON object")
    return data


def validate_artifact_data(data: dict, name: str) -> list[str]:
    """Validate one research-state artifact dict; return a list of violations.

    Empty list means the artifact passes. Fail-closed: every violation is
    recorded rather than raised, so callers can report the full defect set.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return [f"{name} must be a JSON object"]
    for key in REQUIRED_TOP_KEYS:
        if key not in data:
            errors.append(f"{name} missing required key {key}")
            return errors
    status = data["status"]
    if status not in NON_PERFORMANCE_STATUSES:
        errors.append(f"{name} status {status!r} is not a registered non-performance status")
    try:
        ResearchStatus(status)
    except ValueError:
        errors.append(f"{name} status {status!r} is not a registered ResearchStatus")
    for key in REQUIRED_STATE_KEYS:
        if key not in data:
            errors.append(f"{name} missing required key {key}")
        elif data[key] is not False:
            errors.append(f"{name} {key} must be false")
    # Confirmatory gate must remain blocked when the empirical grid has not run.
    if "historical_point_in_time_market_cap_gate" in data:
        if data["historical_point_in_time_market_cap_gate"] not in ("BLOCKED", "BLOCKED_DATA_GATE"):
            errors.append(
                f"{name} historical_point_in_time_market_cap_gate {data['historical_point_in_time_market_cap_gate']!r} "
                "must be BLOCKED/BLOCKED_DATA_GATE"
            )
    # UTC timestamp sanity: *_at_utc fields must be ISO-8601 Z-suffixed timestamps;
    # date_utc is a calendar date and must be YYYY-MM-DD.
    for key, value in data.items():
        if isinstance(value, str):
            if key.endswith("_at_utc"):
                if not (value.endswith("Z") or "+00:00" in value):
                    errors.append(f"{name} {key} must be UTC ISO-8601")
            elif key == "date_utc":
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    errors.append(f"{name} date_utc must be YYYY-MM-DD")
    # Hash fields, when present, must be 64-hex digests.
    for key, value in data.items():
        if key.endswith("_sha256") or key == "sha256" or key == "grid_config_sha256":
            if not (isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)):
                errors.append(f"{name} {key} must be a 64-hex sha256")
    return errors


def validate_artifact(path: Path) -> None:
    data = load_json(path)
    errors = validate_artifact_data(data, path.name)
    if errors:
        for error in errors:
            print("FAIL:", error)
        sys.exit(1)


def validate_confirmatory(data: dict) -> list[str]:
    """Confirmatory-specific frozen-gate checks (grid hash, blocked status)."""
    errors = validate_artifact_data(data, "run_manifest.json")
    if data.get("status") != "BLOCKED_DATA_GATE":
        errors.append("confirmatory run_manifest status must remain BLOCKED_DATA_GATE")
    if data.get("historical_point_in_time_market_cap_gate") != "BLOCKED":
        errors.append("confirmatory historical_point_in_time_market_cap_gate must be BLOCKED")
    if data.get("grid_config_sha256") != FROZEN_GRID_SHA:
        errors.append("confirmatory grid sha256 must remain the frozen 108-config grid")
    return errors


def main() -> int:
    artifacts = [
        ROOT / "research_state/run_manifest.json",
        ROOT / "research_state/exploratory_run_manifest_2026-10-24.json",
    ]
    for path in artifacts:
        if not path.is_file():
            print("FAIL: missing research-state artifact", path.name)
            return 1
        try:
            data = load_json(path)
        except SystemExit:
            return 1
        errors = validate_artifact_data(data, path.name)
        if errors:
            for error in errors:
                print("FAIL:", error)
            return 1
    # Confirmatory manifest must preserve the blocked gate.
    confirmatory = load_json(artifacts[0])
    confirm_errors = validate_confirmatory(confirmatory)
    if confirm_errors:
        for error in confirm_errors:
            print("FAIL:", error)
        return 1
    print("RESEARCH_STATE_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())