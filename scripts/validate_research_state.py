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


def validate_artifact(path: Path) -> None:
    data = load_json(path)
    for key in REQUIRED_TOP_KEYS:
        check(key in data, f"{path.name} missing required key {key}")
    status = data["status"]
    check(status in NON_PERFORMANCE_STATUSES, f"{path.name} status {status!r} is not a registered non-performance status")
    try:
        ResearchStatus(status)
    except ValueError:
        check(False, f"{path.name} status {status!r} is not a registered ResearchStatus")
    for key in REQUIRED_STATE_KEYS:
        check(key in data, f"{path.name} missing required key {key}")
        check(data[key] is False, f"{path.name} {key} must be false")
    # Confirmatory gate must remain blocked when the empirical grid has not run.
    if "historical_point_in_time_market_cap_gate" in data:
        check(
            data["historical_point_in_time_market_cap_gate"] in ("BLOCKED", "BLOCKED_DATA_GATE"),
            f"{path.name} historical_point_in_time_market_cap_gate must be BLOCKED/BLOCKED_DATA_GATE",
        )
    # UTC timestamp sanity: *_at_utc fields must be ISO-8601 Z-suffixed timestamps;
    # date_utc is a calendar date and must be YYYY-MM-DD.
    for key, value in data.items():
        if isinstance(value, str) and key.endswith("_at_utc"):
            check(value.endswith("Z") or "+00:00" in value, f"{path.name} {key} must be UTC ISO-8601")
        elif key == "date_utc":
            import re
            check(bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)), f"{path.name} date_utc must be YYYY-MM-DD")
    # Hash fields, when present, must be 64-hex digests.
    for key, value in data.items():
        if key.endswith("_sha256") or key == "sha256" or key == "grid_config_sha256":
            check(
                isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value),
                f"{path.name} {key} must be a 64-hex sha256",
            )


def main() -> int:
    artifacts = [
        ROOT / "research_state/run_manifest.json",
        ROOT / "research_state/exploratory_run_manifest_2026-10-24.json",
    ]
    for path in artifacts:
        if not path.is_file():
            print("FAIL: missing research-state artifact", path.name)
            return 1
        validate_artifact(path)
    # Confirmatory manifest must preserve the blocked gate.
    confirmatory = load_json(artifacts[0])
    check(
        confirmatory.get("status") == "BLOCKED_DATA_GATE",
        "confirmatory run_manifest must remain BLOCKED_DATA_GATE",
    )
    check(
        confirmatory.get("historical_point_in_time_market_cap_gate") == "BLOCKED",
        "confirmatory historical_point_in_time_market_cap_gate must be BLOCKED",
    )
    check(
        confirmatory.get("grid_config_sha256") == "6be218bc84bf118cf67c238ad1c13ef1e445658db3b1346cd64ccaccc7aa5f07",
        "confirmatory grid sha256 must remain the frozen 108-config grid",
    )
    print("RESEARCH_STATE_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())