#!/usr/bin/env python3
"""Offline conformance check for the orchestration harness."""
import json, os, sys, tempfile
ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.orchestration import (
    run_configuration, aggregate_split_records, validation_family_report,
    persist_run_artifact, load_run_artifact,
)
from cross_venue_funding_dispersion.evaluation import GRID_FAMILY_SIZE


def validate_orchestration() -> list[str]:
    errors = []
    # run_configuration basic
    try:
        r = run_configuration(config_id="FVD001", equity=100.0, pairs=[{"asset_long": "A", "asset_short": "B", "entry_price_long": 100.0, "exit_price_long": 101.0, "entry_price_short": 100.0, "exit_price_short": 99.0, "funding_rate_long": 0.001, "funding_rate_short": 0.002, "position_open_at_settlement": True}],
                              signal_time="2024-01-01T00:00:00Z", next_open_time="2024-01-01T01:00:00Z",
                              fee_bps_per_side=1.0, slippage_bps_per_side=1.0)
        if not (r["config_id"] == "FVD001" and r["gross_exposure"] <= r["gross_exposure_cap"]):
            errors.append("run_configuration basic invariant failed")
    except Exception as exc:
        errors.append(f"run_configuration basic raised: {exc}")
    # split aggregation
    try:
        records = [{"i": i} for i in range(108)]
        agg = aggregate_split_records(records, total=108)
        if not (len(agg["discovery"]) == 65 and len(agg["validation"]) == 22 and len(agg["holdout"]) == 21):
            errors.append("split aggregation sizes wrong")
        if not (agg["discovery"][0]["i"] == 0 and agg["holdout"][-1]["i"] == 107):
            errors.append("split aggregation ordering wrong")
    except Exception as exc:
        errors.append(f"split aggregation raised: {exc}")
    # family report
    try:
        report = validation_family_report([0.01] * GRID_FAMILY_SIZE)
        if report["family_size"] != GRID_FAMILY_SIZE:
            errors.append("family report family_size wrong")
        if report["n_rejected_at_0_05"] < 0:
            errors.append("family report n_rejected negative")
    except Exception as exc:
        errors.append(f"family report raised: {exc}")
    # persistence round-trip
    try:
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "artifact.json")
            sha = persist_run_artifact(p, {"a": 1})
            if not sha or load_run_artifact(p) != {"a": 1}:
                errors.append("persistence round-trip failed")
    except Exception as exc:
        errors.append(f"persistence round-trip raised: {exc}")
    # fail-closed checks
    for bad in [None, [], ""]:
        try:
            run_configuration(config_id=bad, equity=1.0, pairs=[], signal_time="2024-01-01T00:00:00Z",
                              next_open_time="2024-01-01T01:00:00Z", fee_bps_per_side=0.0, slippage_bps_per_side=0.0)
            errors.append("run_configuration accepted bad config_id")
        except ValueError:
            pass
        except Exception as exc:
            errors.append(f"run_configuration bad config_id raised wrong type: {exc}")
    try:
        aggregate_split_records(records, total=10)
        errors.append("aggregate accepted wrong total")
    except ValueError:
        pass
    except Exception as exc:
        errors.append(f"aggregate wrong total raised wrong type: {exc}")
    try:
        validation_family_report("x")
        errors.append("family report accepted non-list")
    except ValueError:
        pass
    except Exception as exc:
        errors.append(f"family report non-list raised wrong type: {exc}")
    try:
        load_run_artifact("/nonexistent/path.json")
        errors.append("load accepted missing file")
    except (FileNotFoundError, OSError, ValueError):
        pass
    except Exception as exc:
        errors.append(f"load missing raised wrong type: {exc}")
    return errors


def main() -> int:
    errors = validate_orchestration()
    if errors:
        print("ORCHESTRATION_VALIDATION=FAIL")
        for e in errors:
            print(e)
        return 1
    print("ORCHESTRATION_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
