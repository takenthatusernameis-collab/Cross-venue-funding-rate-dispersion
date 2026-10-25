import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from validate_track_separation import (  # noqa: E402
    CONFIRMATORY_STATUS,
    EXPLORATORY_STATUSES,
    FROZEN_GRID_SHA,
    validate_separation,
)

FROZEN_DIGEST = "6be218bc84bf118cf67c238ad1c13ef1e445658db3b1346cd64ccaccc7aa5f07"

CONFIRMATORY = {
    "schema_version": "1.0",
    "experiment_id": "FVD-DISPERSION-V1",
    "run_id": "run-2026-01-01",
    "status": "BLOCKED_DATA_GATE",
    "backtest_completed": False,
    "performance_metrics_computed": False,
    "historical_point_in_time_market_cap_gate": "BLOCKED",
    "grid_config_sha256": FROZEN_DIGEST,
    "output_artifacts": [],
    "caveats": ["no performance claim"],
}

EXPLORATORY = {
    "schema_version": "1.0",
    "experiment_id": "FVD-EXPLORATORY-001",
    "run_id": "FVD-EXPLORATORY-001-run-2026-10-24",
    "status": "EXPLORATORY_ONLY",
    "confirmatory_status_preserved": "BLOCKED_DATA_GATE",
    "historical_point_in_time_market_cap_gate": "BLOCKED",
    "backtest_completed": False,
    "performance_metrics_computed": False,
    "output_artifacts": [],
    "caveats": ["no performance claim"],
}


class TrackSeparationTests(unittest.TestCase):
    def test_valid_pair_passes(self):
        validate_separation(dict(CONFIRMATORY), dict(EXPLORATORY), FROZEN_DIGEST)

    def test_committed_pair_passes(self):
        import json
        confirmatory = json.loads((ROOT / "research_state/run_manifest.json").read_text())
        exploratory = json.loads((ROOT / "research_state/exploratory_run_manifest_2026-10-24.json").read_text())
        validate_separation(confirmatory, exploratory, FROZEN_DIGEST)

    def test_confirmatory_status_must_be_blocked(self):
        bad = dict(CONFIRMATORY, status="NOT_RUN")
        with self.assertRaises(SystemExit):
            validate_separation(bad, dict(EXPLORATORY), FROZEN_DIGEST)

    def test_confirmatory_backtest_completed_must_be_false(self):
        bad = dict(CONFIRMATORY, backtest_completed=True)
        with self.assertRaises(SystemExit):
            validate_separation(bad, dict(EXPLORATORY), FROZEN_DIGEST)

    def test_confirmatory_performance_metrics_must_be_false(self):
        bad = dict(CONFIRMATORY, performance_metrics_computed=True)
        with self.assertRaises(SystemExit):
            validate_separation(bad, dict(EXPLORATORY), FROZEN_DIGEST)

    def test_confirmatory_gate_must_be_blocked(self):
        bad = dict(CONFIRMATORY, historical_point_in_time_market_cap_gate="PASS")
        with self.assertRaises(SystemExit):
            validate_separation(bad, dict(EXPLORATORY), FROZEN_DIGEST)

    def test_confirmatory_grid_hash_must_be_frozen(self):
        bad = dict(CONFIRMATORY, grid_config_sha256="0" * 64)
        with self.assertRaises(SystemExit):
            validate_separation(bad, dict(EXPLORATORY), FROZEN_DIGEST)

    def test_exploratory_run_id_must_be_present(self):
        bad = dict(EXPLORATORY)
        del bad["run_id"]
        with self.assertRaises(SystemExit):
            validate_separation(dict(CONFIRMATORY), bad, FROZEN_DIGEST)

    def test_exploratory_run_id_must_not_reuse_confirmatory_anchor(self):
        bad = dict(EXPLORATORY, run_id="FVD053")
        with self.assertRaises(SystemExit):
            validate_separation(dict(CONFIRMATORY), bad, FROZEN_DIGEST)

    def test_exploratory_run_id_namespace(self):
        bad = dict(EXPLORATORY, run_id="FVD-DISPERSION-V1")
        with self.assertRaises(SystemExit):
            validate_separation(dict(CONFIRMATORY), bad, FROZEN_DIGEST)

    def test_exploratory_status_must_be_exploratory_or_inconclusive(self):
        bad = dict(EXPLORATORY, status="BLOCKED_DATA_GATE")
        with self.assertRaises(SystemExit):
            validate_separation(dict(CONFIRMATORY), bad, FROZEN_DIGEST)

    def test_exploratory_status_must_be_registered(self):
        bad = dict(EXPLORATORY, status="PROFITABLE")
        with self.assertRaises(SystemExit):
            validate_separation(dict(CONFIRMATORY), bad, FROZEN_DIGEST)

    def test_exploratory_inconclusive_status_permitted(self):
        validate_separation(dict(CONFIRMATORY), dict(EXPLORATORY, status="INCONCLUSIVE"), FROZEN_DIGEST)

    def test_exploratory_backtest_completed_must_be_false(self):
        bad = dict(EXPLORATORY, backtest_completed=True)
        with self.assertRaises(SystemExit):
            validate_separation(dict(CONFIRMATORY), bad, FROZEN_DIGEST)

    def test_exploratory_performance_metrics_must_be_false(self):
        bad = dict(EXPLORATORY, performance_metrics_computed=True)
        with self.assertRaises(SystemExit):
            validate_separation(dict(CONFIRMATORY), bad, FROZEN_DIGEST)

    def test_exploratory_must_preserve_confirmatory_status(self):
        bad = dict(EXPLORATORY)
        bad["confirmatory_status_preserved"] = "NOT_RUN"
        with self.assertRaises(SystemExit):
            validate_separation(dict(CONFIRMATORY), bad, FROZEN_DIGEST)

    def test_exploratory_must_not_pass_confirmatory_gate(self):
        bad = dict(EXPLORATORY, historical_point_in_time_market_cap_gate="PASS")
        with self.assertRaises(SystemExit):
            validate_separation(dict(CONFIRMATORY), bad, FROZEN_DIGEST)

    def test_exploratory_must_not_introduce_different_grid_hash(self):
        bad = dict(EXPLORATORY, grid_config_sha256="0" * 64)
        with self.assertRaises(SystemExit):
            validate_separation(dict(CONFIRMATORY), bad, FROZEN_DIGEST)

    def test_exploratory_may_reference_anchor_only_as_frozen(self):
        bad = dict(EXPLORATORY, anchor="FVD108")
        with self.assertRaises(SystemExit):
            validate_separation(dict(CONFIRMATORY), bad, FROZEN_DIGEST)

    def test_exploratory_may_reference_fvd053_as_frozen_anchor(self):
        validate_separation(dict(CONFIRMATORY), dict(EXPLORATORY, anchor="FVD053"), FROZEN_DIGEST)

    def test_frozen_grid_digest_mismatch_fails(self):
        with self.assertRaises(SystemExit):
            validate_separation(dict(CONFIRMATORY), dict(EXPLORATORY), "0" * 64)


if __name__ == "__main__":
    unittest.main()