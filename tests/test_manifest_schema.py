import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import jsonschema  # noqa: E402
from validate_manifest_schema import (  # noqa: E402
    CONFIRMATORY, EXPLORATORY, FROZEN_GRID_SHA, load_schema, validate_contract,
)

BASE_MANIFEST = {
    "schema_version": "1.0",
    "experiment_id": "FVD-DISPERSION-V1",
    "run_id": "run-2026-01-01",
    "status": "BLOCKED_DATA_GATE",
    "backtest_completed": False,
    "performance_metrics_computed": False,
    "historical_point_in_time_market_cap_gate": "BLOCKED",
    "output_artifacts": [{"path": "research_state/art.json", "sha256": "a" * 64}],
    "caveats": ["no performance claim"],
    "started_at_utc": "2026-01-01T00:00:00Z",
    "grid_config_sha256": FROZEN_GRID_SHA,
}


class ManifestSchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema()

    def test_valid_confirmatory_manifest_passes_strict_schema(self):
        jsonschema.validate(BASE_MANIFEST, self.schema)
        validate_contract(dict(BASE_MANIFEST), CONFIRMATORY, allow_extra=False)

    def test_committed_confirmatory_manifest_passes_strict_schema(self):
        committed = json.loads(CONFIRMATORY.read_text(encoding="utf-8"))
        jsonschema.validate(committed, self.schema)
        validate_contract(committed, CONFIRMATORY, allow_extra=False)
        self.assertEqual(committed["status"], "BLOCKED_DATA_GATE")
        self.assertEqual(committed["grid_config_sha256"], FROZEN_GRID_SHA)

    def test_committed_exploratory_manifest_passes_contract_with_extra_fields(self):
        committed = json.loads(EXPLORATORY.read_text(encoding="utf-8"))
        self.assertTrue(set(committed) - set(self.schema["properties"]), "exploratory carries versioned extra fields")
        validate_contract(committed, EXPLORATORY, allow_extra=True)
        self.assertFalse(committed["backtest_completed"])
        self.assertFalse(committed["performance_metrics_computed"])

    def test_missing_required_key_fails(self):
        bad = dict(BASE_MANIFEST)
        del bad["caveats"]
        with self.assertRaises(SystemExit):
            validate_contract(bad, CONFIRMATORY, allow_extra=False)

    def test_bad_status_enum_fails(self):
        bad = dict(BASE_MANIFEST, status="PROFITABLE")
        with self.assertRaises(SystemExit):
            validate_contract(bad, CONFIRMATORY, allow_extra=False)

    def test_bad_gate_enum_fails(self):
        bad = dict(BASE_MANIFEST, historical_point_in_time_market_cap_gate="VERIFIED")
        with self.assertRaises(SystemExit):
            validate_contract(bad, CONFIRMATORY, allow_extra=False)

    def test_additional_property_rejected_strict_but_permitted_exploratory(self):
        bad = dict(BASE_MANIFEST, extra_field="x")
        with self.assertRaises(SystemExit):
            validate_contract(bad, CONFIRMATORY, allow_extra=False)
        validate_contract(bad, EXPLORATORY, allow_extra=True)

    def test_backtest_false_metrics_true_violates_invariant(self):
        bad = dict(BASE_MANIFEST, backtest_completed=False, performance_metrics_computed=True)
        with self.assertRaises(SystemExit):
            validate_contract(bad, CONFIRMATORY, allow_extra=False)

    def test_output_artifact_missing_sha256_fails(self):
        bad = dict(BASE_MANIFEST, output_artifacts=[{"path": "research_state/art.json"}])
        with self.assertRaises(SystemExit):
            validate_contract(bad, CONFIRMATORY, allow_extra=False)

    def test_sha256_must_be_64_hex(self):
        bad = dict(BASE_MANIFEST, grid_config_sha256="not-a-sha256")
        with self.assertRaises(SystemExit):
            validate_contract(bad, CONFIRMATORY, allow_extra=False)

    def test_non_utc_timestamp_fails(self):
        bad = dict(BASE_MANIFEST, started_at_utc="2026-01-01T00:00:00")
        with self.assertRaises(SystemExit):
            validate_contract(bad, CONFIRMATORY, allow_extra=False)

    def test_caveats_must_be_array_of_strings(self):
        bad = dict(BASE_MANIFEST, caveats="no performance claim")
        with self.assertRaises(SystemExit):
            validate_contract(bad, CONFIRMATORY, allow_extra=False)

    def test_strict_schema_rejects_additional_properties(self):
        bad = dict(BASE_MANIFEST, extra_field="x")
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)


if __name__ == "__main__":
    unittest.main()
