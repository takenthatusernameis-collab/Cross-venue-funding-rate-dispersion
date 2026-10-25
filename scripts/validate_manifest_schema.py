#!/usr/bin/env python3
"""Offline conformance check: research-state run manifests against schemas/run-manifest.schema.json.

The confirmatory run_manifest.json is validated strictly (additionalProperties: false,
frozen 108-config grid hash, BLOCKED_DATA_GATE). The exploratory manifest is validated
against the shared required-field contract (types, enums, required keys, the
backtest_completed => performance_metrics_computed invariant); its versioned
exploratory-only fields are expected and permitted.

Standard library + jsonschema; no network calls; no economic result; makes no
performance claim.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "run-manifest.schema.json"
CONFIRMATORY = ROOT / "research_state" / "run_manifest.json"
EXPLORATORY = ROOT / "research_state" / "exploratory_run_manifest_2026-10-24.json"
FROZEN_GRID_SHA = "6be218bc84bf118cf67c238ad1c13ef1e445658db3b1346cd64ccaccc7aa5f07"

STATUS_ENUM = {
    "NOT_RUN", "BLOCKED_DATA_GATE", "BLOCKED_SPECIFICATION_GATE", "IMPLEMENTATION_FAILED",
    "EXPLORATORY_ONLY", "INCONCLUSIVE", "REJECTED", "SUPPORTED_FOR_FURTHER_RESEARCH",
}
GATE_ENUM = {"NOT_VERIFIED", "PASS", "BLOCKED"}
REQUIRED_KEYS = (
    "schema_version", "experiment_id", "run_id", "status",
    "backtest_completed", "performance_metrics_computed",
    "historical_point_in_time_market_cap_gate", "output_artifacts", "caveats",
)
SHA256_KEYS = ("grid_config_sha256", "source_manifest_sha256", "sha256")
HASH_MAP_KEYS = ("source_code_hashes", "config_hashes")


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


def load_schema() -> dict:
    return load_json(SCHEMA_PATH)


def is_64_hex(value) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def is_utc_string(value) -> bool:
    return isinstance(value, str) and (value.endswith("Z") or "+00:00" in value)


def validate_contract(data: dict, path: Path, allow_extra: bool) -> None:
    for key in REQUIRED_KEYS:
        check(key in data, f"{path.name} missing required key {key}")
    check(isinstance(data["schema_version"], str) and data["schema_version"], f"{path.name} schema_version must be non-empty string")
    check(isinstance(data["experiment_id"], str) and data["experiment_id"], f"{path.name} experiment_id must be non-empty string")
    check(isinstance(data["run_id"], str) and data["run_id"], f"{path.name} run_id must be non-empty string")
    check(data["status"] in STATUS_ENUM, f"{path.name} status {data.get('status')!r} not a registered status")
    check(data["historical_point_in_time_market_cap_gate"] in GATE_ENUM,
          f"{path.name} historical_point_in_time_market_cap_gate {data.get('historical_point_in_time_market_cap_gate')!r} not in {sorted(GATE_ENUM)}")
    check(isinstance(data["backtest_completed"], bool), f"{path.name} backtest_completed must be boolean")
    check(isinstance(data["performance_metrics_computed"], bool), f"{path.name} performance_metrics_computed must be boolean")
    if data["backtest_completed"] is False:
        check(data["performance_metrics_computed"] is False,
              f"{path.name} backtest_completed=false requires performance_metrics_computed=false")
    check(isinstance(data["output_artifacts"], list), f"{path.name} output_artifacts must be a list")
    for item in data["output_artifacts"]:
        check(isinstance(item, dict) and "path" in item and "sha256" in item,
              f"{path.name} output_artifacts entry must carry path and sha256")
        check(is_64_hex(item["sha256"]), f"{path.name} output_artifacts sha256 must be 64-hex")
    check(isinstance(data["caveats"], list) and all(isinstance(item, str) for item in data["caveats"]),
          f"{path.name} caveats must be an array of strings")
    for key, value in data.items():
        if isinstance(value, str):
            if key == "date_utc":
                check(bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)), f"{path.name} date_utc must be YYYY-MM-DD")
            elif key.endswith("_at_utc") or key.endswith("_utc"):
                check(is_utc_string(value), f"{path.name} {key} must be UTC ISO-8601")
    for key in SHA256_KEYS:
        if key in data:
            check(is_64_hex(data[key]), f"{path.name} {key} must be 64-hex sha256")
    for key in HASH_MAP_KEYS:
        if key in data and data[key] is not None:
            check(isinstance(data[key], dict), f"{path.name} {key} must be an object if present")
            for subkey, subval in data[key].items():
                check(is_64_hex(subval), f"{path.name} {key}.{subkey} must be 64-hex sha256")
    if not allow_extra:
        schema_keys = set(load_schema()["properties"])
        extra = set(data) - schema_keys
        check(not extra, f"{path.name} unexpected additional properties: {sorted(extra)}")


def main() -> int:
    schema = load_schema()
    confirm = load_json(CONFIRMATORY)
    expl = load_json(EXPLORATORY)

    import jsonschema

    # Confirmatory: strict schema conformance (additionalProperties: false).
    try:
        jsonschema.validate(confirm, schema)
    except jsonschema.ValidationError as exc:
        print(f"FAIL: confirmatory manifest violates schema: {exc.message}")
        sys.exit(1)
    validate_contract(confirm, CONFIRMATORY, allow_extra=False)
    check(confirm.get("status") == "BLOCKED_DATA_GATE",
          "confirmatory run_manifest status must remain BLOCKED_DATA_GATE")
    check(confirm.get("historical_point_in_time_market_cap_gate") == "BLOCKED",
          "confirmatory historical_point_in_time_market_cap_gate must be BLOCKED")
    check(confirm.get("grid_config_sha256") == FROZEN_GRID_SHA,
          "confirmatory grid_config_sha256 must remain the frozen 108-config grid")
    check(confirm.get("backtest_completed") is False and confirm.get("performance_metrics_computed") is False,
          "confirmatory manifest must not claim a completed backtest or metrics")

    # Exploratory: contract conformance; versioned extra fields are permitted.
    validate_contract(expl, EXPLORATORY, allow_extra=True)
    check(expl.get("backtest_completed") is False and expl.get("performance_metrics_computed") is False,
          "exploratory manifest must not claim a completed backtest or metrics")
    if "grid_config_sha256" in expl and expl["grid_config_sha256"] is not None:
        check(expl["grid_config_sha256"] == FROZEN_GRID_SHA,
              "exploratory manifest must not introduce a different confirmatory grid hash")

    print("MANIFEST_SCHEMA_VALIDATION=PASS confirmatory=strict exploratory=contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
