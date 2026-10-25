import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import validate_universe_frontier as v  # noqa: E402


class TestUniverseFrontierValidator(unittest.TestCase):
    def test_committed_passes(self):
        self.assertEqual(v.validate_frontier(), [])

    def test_committed_frontier_passes(self):
        self.assertEqual(v.validate_committed_frontier(), [])

    def test_committed_frontier_missing_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = v.FRONTIER_PATH
            v.FRONTIER_PATH = Path(tmp) / "missing.json"
            try:
                errs = v.validate_committed_frontier()
            finally:
                v.FRONTIER_PATH = original
            self.assertTrue(any("missing" in e for e in errs))

    def test_committed_frontier_unreadable_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = v.FRONTIER_PATH
            bad = Path(tmp) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            v.FRONTIER_PATH = bad
            try:
                errs = v.validate_committed_frontier()
            finally:
                v.FRONTIER_PATH = original
            self.assertTrue(any("unreadable" in e for e in errs))

    def test_committed_frontier_non_object_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = v.FRONTIER_PATH
            bad = Path(tmp) / "bad.json"
            bad.write_text("[]", encoding="utf-8")
            v.FRONTIER_PATH = bad
            try:
                errs = v.validate_committed_frontier()
            finally:
                v.FRONTIER_PATH = original
            self.assertTrue(any("JSON object" in e for e in errs))

    def _stub(self, **overrides):
        stub = {
            "schema_version": "1.0",
            "experiment_id": "FVD-DISPERSION-V1",
            "status": "NOT_STARTED",
            "snapshot_id": None,
            "snapshot_at": None,
            "previous_snapshot_id": None,
            "rank_frontier": [],
            "last_completed_rank": 0,
            "completed_asset_ids": [],
            "pending_asset_ids": [],
            "excluded_assets": [],
            "current_cohort": [],
            "next_action": "x",
            "source": {"id": None, "hash": None, "retrieved_at_utc": None},
            "pagination": {"cursor": None, "batch_size": 0, "has_more": False},
            "resume": {
                "next_rank": 1,
                "next_asset": None,
                "batch_window": None,
                "has_more": False,
                "frontier_size": 0,
                "snapshot_id": None,
            },
            "updated_at_utc": None,
        }
        stub.update(overrides)
        return stub

    def test_committed_frontier_rejects_snapshot_id(self):
        stub = self._stub(snapshot_id="FVD-SNAP-0000000000000000")
        with tempfile.TemporaryDirectory() as tmp:
            original = v.FRONTIER_PATH
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps(stub), encoding="utf-8")
            v.FRONTIER_PATH = bad
            try:
                errs = v.validate_committed_frontier()
            finally:
                v.FRONTIER_PATH = original
            self.assertTrue(any("snapshot_id" in e for e in errs))

    def test_committed_frontier_rejects_rank_frontier(self):
        stub = self._stub(rank_frontier=[{"rank": 1, "asset": "X"}])
        with tempfile.TemporaryDirectory() as tmp:
            original = v.FRONTIER_PATH
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps(stub), encoding="utf-8")
            v.FRONTIER_PATH = bad
            try:
                errs = v.validate_committed_frontier()
            finally:
                v.FRONTIER_PATH = original
            self.assertTrue(any("rank_frontier" in e for e in errs))

    def test_committed_frontier_rejects_completed_rank(self):
        stub = self._stub(last_completed_rank=1, completed_asset_ids=["X"])
        with tempfile.TemporaryDirectory() as tmp:
            original = v.FRONTIER_PATH
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps(stub), encoding="utf-8")
            v.FRONTIER_PATH = bad
            try:
                errs = v.validate_committed_frontier()
            finally:
                v.FRONTIER_PATH = original
            self.assertTrue(any("last_completed_rank" in e for e in errs))

    def test_committed_frontier_rejects_wrong_status(self):
        stub = self._stub(status="OPEN")
        with tempfile.TemporaryDirectory() as tmp:
            original = v.FRONTIER_PATH
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps(stub), encoding="utf-8")
            v.FRONTIER_PATH = bad
            try:
                errs = v.validate_committed_frontier()
            finally:
                v.FRONTIER_PATH = original
            self.assertTrue(any("status" in e for e in errs))

    def test_committed_frontier_rejects_non_utc_timestamp(self):
        stub = self._stub(updated_at_utc="2024-01-01T00:00:00")
        with tempfile.TemporaryDirectory() as tmp:
            original = v.FRONTIER_PATH
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps(stub), encoding="utf-8")
            v.FRONTIER_PATH = bad
            try:
                errs = v.validate_committed_frontier()
            finally:
                v.FRONTIER_PATH = original
            self.assertTrue(any("updated_at_utc" in e for e in errs))

    def test_committed_frontier_rejects_source_id(self):
        stub = self._stub(source={"id": "coingecko", "hash": "x", "retrieved_at_utc": None})
        with tempfile.TemporaryDirectory() as tmp:
            original = v.FRONTIER_PATH
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps(stub), encoding="utf-8")
            v.FRONTIER_PATH = bad
            try:
                errs = v.validate_committed_frontier()
            finally:
                v.FRONTIER_PATH = original
            self.assertTrue(any("source" in e for e in errs))

    def test_committed_frontier_rejects_pagination_cursor(self):
        stub = self._stub(pagination={"cursor": "page-1", "batch_size": 0, "has_more": False})
        with tempfile.TemporaryDirectory() as tmp:
            original = v.FRONTIER_PATH
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps(stub), encoding="utf-8")
            v.FRONTIER_PATH = bad
            try:
                errs = v.validate_committed_frontier()
            finally:
                v.FRONTIER_PATH = original
            self.assertTrue(any("pagination" in e for e in errs))

    def test_committed_frontier_rejects_resume_snapshot_id(self):
        stub = self._stub(resume={
            "next_rank": 1,
            "next_asset": None,
            "batch_window": None,
            "has_more": False,
            "frontier_size": 0,
            "snapshot_id": "FVD-SNAP-0000000000000000",
        })
        with tempfile.TemporaryDirectory() as tmp:
            original = v.FRONTIER_PATH
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps(stub), encoding="utf-8")
            v.FRONTIER_PATH = bad
            try:
                errs = v.validate_committed_frontier()
            finally:
                v.FRONTIER_PATH = original
            self.assertTrue(any("resume" in e for e in errs))


if __name__ == "__main__":
    unittest.main()