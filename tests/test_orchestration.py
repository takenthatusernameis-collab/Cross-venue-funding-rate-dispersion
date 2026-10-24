"""Known-answer and adversarial tests for orchestration harness."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest

from cross_venue_funding_dispersion.orchestration import (
    GRID_FAMILY_SIZE,
    aggregate_split_records,
    load_run_artifact,
    persist_run_artifact,
    run_configuration,
    validation_family_report,
)


def _pair():
    return {
        "asset_long": "A",
        "asset_short": "B",
        "entry_price_long": 100.0,
        "exit_price_long": 110.0,
        "entry_price_short": 100.0,
        "exit_price_short": 95.0,
        "funding_rate_long": 0.01,
        "funding_rate_short": 0.005,
        "position_open_at_settlement": True,
    }


class TestOrchestration(unittest.TestCase):
    def test_run_configuration_known_answer(self):
        rec = run_configuration(
            config_id="FVD001",
            equity=1000.0,
            pairs=[_pair()],
            signal_time="2024-01-01T00:00:00Z",
            next_open_time="2024-01-01T01:00:00Z",
            fee_bps_per_side=5.0,
            slippage_bps_per_side=2.0,
        )
        self.assertEqual(rec["config_id"], "FVD001")
        self.assertEqual(rec["n_pairs"], 1)
        self.assertLessEqual(rec["gross_exposure"], rec["equity"] * 1.0 + 1e-9)

    def test_run_configuration_invalid(self):
        with self.assertRaises(ValueError):
            run_configuration(
                config_id="",
                equity=1000.0,
                pairs=[_pair()],
                signal_time="2024-01-01T00:00:00Z",
                next_open_time="2024-01-01T01:00:00Z",
                fee_bps_per_side=5.0,
                slippage_bps_per_side=2.0,
            )

    def test_aggregate_split_records(self):
        records = [{"i": i} for i in range(10)]
        out = aggregate_split_records(records, total=10)
        self.assertEqual(len(out["discovery"]), 6)
        self.assertEqual(len(out["validation"]), 2)
        self.assertEqual(len(out["holdout"]), 2)
        self.assertEqual(out["discovery"][0]["i"], 0)
        self.assertEqual(out["holdout"][-1]["i"], 9)

    def test_aggregate_length_mismatch(self):
        with self.assertRaises(ValueError):
            aggregate_split_records([{"i": 0}], total=2)

    def test_validation_family_report(self):
        pvals = [0.01] + [0.5] * (GRID_FAMILY_SIZE - 1)
        rep = validation_family_report(pvals)
        self.assertEqual(rep["family_size"], GRID_FAMILY_SIZE)
        self.assertEqual(len(rep["holm_adjusted_p_values"]), GRID_FAMILY_SIZE)
        self.assertGreaterEqual(rep["n_rejected_at_0_05"], 0)

    def test_validation_family_report_invalid(self):
        with self.assertRaises(ValueError):
            validation_family_report("not a list")

    def test_persist_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "artifact.json")
            payload = {"a": 1, "b": [2, 3]}
            sha = persist_run_artifact(path, payload)
            self.assertEqual(len(sha), 64)
            loaded = load_run_artifact(path)
            self.assertEqual(loaded, payload)
            # sha matches file
            with open(path, "rb") as f:
                self.assertEqual(hashlib.sha256(f.read()).hexdigest(), sha)

    def test_persist_invalid(self):
        with self.assertRaises(ValueError):
            persist_run_artifact("", {"a": 1})
        with self.assertRaises(ValueError):
            persist_run_artifact("/tmp/x.json", "bad")

    def test_load_invalid(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bad.json")
            with open(path, "w") as f:
                f.write("[]")
            with self.assertRaises(ValueError):
                load_run_artifact(path)


if __name__ == "__main__":
    unittest.main()
