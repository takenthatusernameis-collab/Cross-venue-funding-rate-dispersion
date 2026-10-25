import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import should_run_historical_probe as policy


class ProbeScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.now = datetime(2026, 10, 25, 18, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.temp.cleanup()

    def write_probe(self, run_id, observed, status):
        path = self.root / f"historical_overlap_probe_{run_id}.json"
        path.write_text(json.dumps({
            "observed_at_utc": observed.isoformat().replace("+00:00", "Z"),
            "status": status,
        }), encoding="utf-8")
        return path

    def test_first_probe_runs_when_no_previous_record_exists(self):
        result = policy.decide(self.root, self.now)
        self.assertTrue(result["should_run"])
        self.assertEqual(result["reason"], "no_prior_parseable_probe")

    def test_recent_successful_probe_is_skipped_for_six_hours(self):
        self.write_probe("one", self.now - timedelta(hours=2), "SOURCE_PROBE_COMPLETED")
        result = policy.decide(self.root, self.now)
        self.assertFalse(result["should_run"])
        self.assertEqual(result["cooldown_seconds"], 21600)

    def test_successful_probe_becomes_eligible_after_six_hours(self):
        self.write_probe("one", self.now - timedelta(hours=7), "SOURCE_PROBE_COMPLETED")
        result = policy.decide(self.root, self.now)
        self.assertTrue(result["should_run"])
        self.assertEqual(result["reason"], "cooldown_elapsed")

    def test_network_failure_retries_after_fifteen_minutes_not_every_five_minutes(self):
        self.write_probe("one", self.now - timedelta(minutes=5), "NETWORK_UNAVAILABLE_FROM_THIS_HOST")
        result = policy.decide(self.root, self.now)
        self.assertFalse(result["should_run"])
        self.assertEqual(result["cooldown_seconds"], 900)

    def test_network_failure_retries_after_fifteen_minute_cooldown(self):
        self.write_probe("one", self.now - timedelta(minutes=16), "NETWORK_UNAVAILABLE_FROM_THIS_HOST")
        result = policy.decide(self.root, self.now)
        self.assertTrue(result["should_run"])

    def test_malformed_artifacts_are_not_rewritten_or_treated_as_success(self):
        malformed = self.root / "historical_overlap_probe_bad.json"
        malformed.write_text("{bad json", encoding="utf-8")
        result = policy.decide(self.root, self.now)
        self.assertTrue(result["should_run"])
        self.assertTrue(malformed.exists())

    def test_latest_timestamp_wins_not_lexicographic_filename(self):
        older = self.write_probe("999", self.now - timedelta(hours=8), "SOURCE_PROBE_COMPLETED")
        newer = self.write_probe("001", self.now - timedelta(hours=1), "SOURCE_PROBE_COMPLETED")
        result = policy.decide(self.root, self.now)
        self.assertFalse(result["should_run"])
        self.assertEqual(result["latest_probe"]["path"], str(newer))


if __name__ == "__main__":
    unittest.main()
