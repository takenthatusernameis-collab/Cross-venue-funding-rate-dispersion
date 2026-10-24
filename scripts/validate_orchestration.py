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

errors = []
# run_configuration basic
r = run_configuration(config_id="FVD001", equity=100.0, pairs=[{"asset_long": "A", "asset_short": "B", "entry_price_long": 100.0, "exit_price_long": 101.0, "entry_price_short": 100.0, "exit_price_short": 99.0, "funding_rate_long": 0.001, "funding_rate_short": 0.002, "position_open_at_settlement": True}],
                      signal_time="2024-01-01T00:00:00Z", next_open_time="2024-01-01T01:00:00Z",
                      fee_bps_per_side=1.0, slippage_bps_per_side=1.0)
assert r["config_id"] == "FVD001" and r["gross_exposure"] <= r["gross_exposure_cap"]
# split aggregation
records = [{"i": i} for i in range(108)]
agg = aggregate_split_records(records, total=108)
assert len(agg["discovery"]) == 65 and len(agg["validation"]) == 22 and len(agg["holdout"]) == 21
assert agg["discovery"][0]["i"] == 0 and agg["holdout"][-1]["i"] == 107
# family report
report = validation_family_report([0.01] * GRID_FAMILY_SIZE)
assert report["family_size"] == GRID_FAMILY_SIZE
assert report["n_rejected_at_0_05"] >= 0
# persistence round-trip
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "artifact.json")
    sha = persist_run_artifact(p, {"a": 1})
    assert sha and load_run_artifact(p) == {"a": 1}
# fail-closed checks
for bad in [None, [], "" ]:
    try:
        run_configuration(config_id=bad, equity=1.0, pairs=[], signal_time="2024-01-01T00:00:00Z",
                          next_open_time="2024-01-01T01:00:00Z", fee_bps_per_side=0.0, slippage_bps_per_side=0.0)
        errors.append("run_configuration accepted bad config_id")
    except ValueError:
        pass
try:
    aggregate_split_records(records, total=10)
    errors.append("aggregate accepted wrong total")
except ValueError:
    pass
try:
    validation_family_report("x")
    errors.append("family report accepted non-list")
except ValueError:
    pass
try:
    load_run_artifact("/nonexistent/path.json")
    errors.append("load accepted missing file")
except (FileNotFoundError, OSError, ValueError):
    pass

if errors:
    print("ORCHESTRATION_VALIDATION=FAIL")
    for e in errors: print(e)
    sys.exit(1)
print("ORCHESTRATION_VALIDATION=PASS")
