import json
import math
import tempfile
import unittest
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.frontier import (
    build_frontier,
    build_not_started_frontier,
    compute_snapshot_id,
    load_frontier,
    persist_frontier,
    rank_universe,
    save_frontier,
    validate_ranked_assets,
    FrontierError,
)


class FrontierTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"asset": "BTC", "market_cap_usd": 1_000_000_000.0, "as_of": "2024-01-01T00:00:00Z", "published_at": "2024-01-01T01:00:00Z"},
            {"asset": "ETH", "market_cap_usd": 400_000_000.0, "as_of": "2024-01-01T00:00:00Z", "published_at": "2024-01-01T01:00:00Z"},
            {"asset": "SOL", "market_cap_usd": 400_000_000.0, "as_of": "2024-01-01T00:00:00Z", "published_at": "2024-01-01T01:00:00Z"},
            {"asset": "BTC", "market_cap_usd": 1_100_000_000.0, "as_of": "2024-02-01T00:00:00Z", "published_at": "2024-02-01T01:00:00Z"},
            {"asset": "FUTURE", "market_cap_usd": 999_000_000.0, "as_of": "2025-01-01T00:00:00Z", "published_at": "2025-01-01T01:00:00Z"},
            {"asset": "LATE", "market_cap_usd": 888_000_000.0, "as_of": "2024-02-01T00:00:00Z", "published_at": "2024-03-01T00:00:00Z"},
            {"asset": "BAD", "market_cap_usd": float("nan"), "as_of": "2024-01-01T00:00:00Z", "published_at": "2024-01-01T01:00:00Z"},
            {"asset": "NEG", "market_cap_usd": -50.0, "as_of": "2024-01-01T00:00:00Z", "published_at": "2024-01-01T01:00:00Z"},
            {"asset": "", "market_cap_usd": 100.0, "as_of": "2024-01-01T00:00:00Z", "published_at": "2024-01-01T01:00:00Z"},
        ]
        self.snapshot = "2024-02-15T00:00:00Z"

    def test_rank_universe_descending_with_asset_id_tie_break(self):
        ranked, excluded = rank_universe(self.records, self.snapshot)
        self.assertEqual([item["asset"] for item in ranked], ["BTC", "ETH", "SOL"])
        self.assertEqual([item["rank"] for item in ranked], [1, 2, 3])
        self.assertEqual(ranked[0]["market_cap_usd"], 1_100_000_000.0)
        self.assertEqual(ranked[0]["as_of"], "2024-02-01T00:00:00Z")
        self.assertEqual(ranked[0]["published_at"], "2024-02-01T01:00:00Z")

    def test_rank_universe_excludes_stale_and_invalid_with_reasons(self):
        ranked, excluded = rank_universe(self.records, self.snapshot)
        ranked_assets = {item["asset"] for item in ranked}
        self.assertNotIn("FUTURE", ranked_assets)
        self.assertNotIn("LATE", ranked_assets)
        self.assertNotIn("BAD", ranked_assets)
        self.assertNotIn("NEG", ranked_assets)
        reasons = {entry["reason"] for entry in excluded}
        self.assertTrue(any("effective" in reason for reason in reasons))
        self.assertTrue(any("published" in reason for reason in reasons))
        self.assertTrue(any("market cap" in reason for reason in reasons))
        for entry in excluded:
            self.assertIn("asset", entry)
            self.assertIn("reason", entry)
            self.assertIn("excluded_at_utc", entry)

    def test_rank_universe_record_order_is_immaterial(self):
        ranked_first, _ = rank_universe(list(self.records), self.snapshot)
        ranked_second, _ = rank_universe(list(reversed(self.records)), self.snapshot)
        self.assertEqual(ranked_first, ranked_second)

    def test_snapshot_id_is_deterministic_and_source_bound(self):
        first = compute_snapshot_id("coingecko", "sha256:abc", self.snapshot, self.records)
        self.assertEqual(first, compute_snapshot_id("coingecko", "sha256:abc", self.snapshot, self.records))
        self.assertTrue(first.startswith("FVD-SNAP-"))
        self.assertEqual(first, compute_snapshot_id("coingecko", "sha256:abc", self.snapshot, list(reversed(self.records))))
        self.assertNotEqual(compute_snapshot_id("coingecko", "sha256:abd", self.snapshot, self.records), first)
        self.assertNotEqual(compute_snapshot_id("coingecko", "sha256:abc", "2024-02-16T00:00:00Z", self.records), first)
        different = [dict(record) for record in self.records]
        different[0]["market_cap_usd"] = 2_000_000_000.0
        self.assertNotEqual(compute_snapshot_id("coingecko", "sha256:abc", self.snapshot, different), first)
        self.assertIsInstance(compute_snapshot_id("coingecko", "sha256:abc", self.snapshot, []), str)

    def test_persist_frontier_persists_full_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frontier.json"
            ranked, _ = rank_universe(self.records, self.snapshot)
            state = persist_frontier(path, self.snapshot, "coingecko", "sha256:abc123", records=self.records, batch_size=2)
            self.assertEqual(state["status"], "OPEN")
            self.assertEqual(state["snapshot_id"], compute_snapshot_id("coingecko", "sha256:abc123", self.snapshot, ranked))
            self.assertEqual(state["snapshot_at"], "2024-02-15T00:00:00Z")
            self.assertEqual(state["last_completed_rank"], 0)
            self.assertEqual(state["completed_asset_ids"], [])
            self.assertEqual(state["pending_asset_ids"], ["SOL"])
            self.assertEqual(state["rank_frontier"][0]["asset"], "BTC")
            self.assertEqual(state["rank_frontier"][1]["asset"], "ETH")
            self.assertEqual(state["rank_frontier"][2]["asset"], "SOL")
            self.assertEqual(state["resume"]["next_rank"], 1)
            self.assertEqual(state["resume"]["next_asset"], "BTC")
            self.assertEqual(state["resume"]["batch_window"], [1, 2])
            self.assertTrue(state["resume"]["has_more"])
            self.assertEqual(state["resume"]["frontier_size"], 3)
            self.assertTrue(state["pagination"]["has_more"])
            self.assertEqual(state["pagination"]["batch_size"], 2)
            self.assertIsNone(state["pagination"]["cursor"])
            self.assertEqual(state["source"]["id"], "coingecko")
            self.assertEqual(state["source"]["hash"], "sha256:abc123")
            excluded_assets = {entry["asset"] for entry in state["excluded_assets"]}
            self.assertEqual(excluded_assets, {"FUTURE", "LATE", "BAD", "NEG", "<missing>"})
            for entry in state["excluded_assets"]:
                self.assertIsInstance(entry["reason"], str)
                self.assertTrue(len(entry["reason"]) > 0)
                self.assertTrue(entry["excluded_at_utc"].endswith("Z"))
            loaded = load_frontier(path)
            self.assertEqual(loaded, state)
            self.assertTrue(loaded["updated_at_utc"].endswith("Z"))
            self.assertEqual([entry.name for entry in Path(tmp).iterdir()], ["frontier.json"])

    def test_persist_frontier_batch_cursor_has_no_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frontier.json"
            first = persist_frontier(path, self.snapshot, "coingecko", "sha256:abc", records=self.records, batch_size=2, last_completed_rank=0)
            second = persist_frontier(
                path, self.snapshot, "coingecko", "sha256:abc", records=self.records, batch_size=50, last_completed_rank=2,
                completed_asset_ids=["BTC", "ETH"],
            )
            self.assertEqual(first["last_completed_rank"], 0)
            self.assertEqual(second["last_completed_rank"], 2)
            self.assertEqual(second["completed_asset_ids"], ["BTC", "ETH"])
            self.assertEqual(second["pending_asset_ids"], [])
            self.assertEqual(second["resume"]["next_rank"], 3)
            self.assertEqual(second["resume"]["next_asset"], "SOL")
            self.assertEqual(second["resume"]["batch_window"], [3, 3])
            self.assertFalse(second["resume"]["has_more"])
            self.assertFalse(second["pagination"]["has_more"])
            self.assertEqual(second["status"], "COMPLETED")

    def test_persist_frontier_accepts_pre_ranked_frontier(self):
        ranked = [
            {"rank": 1, "asset": "BTC", "market_cap_usd": 1_100_000_000.0, "as_of": "2024-02-01T00:00:00Z", "published_at": "2024-02-01T01:00:00Z"},
            {"rank": 2, "asset": "ETH", "market_cap_usd": 400_000_000.0, "as_of": "2024-01-01T00:00:00Z", "published_at": "2024-01-01T01:00:00Z"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frontier.json"
            state = persist_frontier(path, self.snapshot, "external", "hash", records=self.records, ranked_assets=ranked, batch_size=1)
            self.assertEqual([item["asset"] for item in state["rank_frontier"]], ["BTC", "ETH"])
            self.assertEqual(state["snapshot_id"], compute_snapshot_id("external", "hash", self.snapshot, ranked))
            self.assertEqual(state["pending_asset_ids"], ["ETH"])

    def test_rank_frontier_gap_fails_closed(self):
        with self.assertRaisesRegex(FrontierError, "rank frontier gap"):
            build_frontier(
                self.snapshot, "source", "hash",
                ranked_assets=[
                    {"rank": 1, "asset": "A", "market_cap_usd": 100.0, "as_of": "2024-01-01T00:00:00Z", "published_at": "2024-01-01T01:00:00Z"},
                    {"rank": 3, "asset": "C", "market_cap_usd": 50.0, "as_of": "2024-01-01T00:00:00Z", "published_at": "2024-01-01T01:00:00Z"},
                ],
                last_completed_rank=1,
            )

    def test_duplicate_asset_in_frontier_fails_closed(self):
        with self.assertRaisesRegex(FrontierError, "duplicate asset"):
            build_frontier(
                self.snapshot, "source", "hash",
                ranked_assets=[
                    {"rank": 1, "asset": "A", "market_cap_usd": 100.0, "as_of": "2024-01-01T00:00:00Z", "published_at": "2024-01-01T01:00:00Z"},
                    {"rank": 2, "asset": "A", "market_cap_usd": 50.0, "as_of": "2024-01-01T00:00:00Z", "published_at": "2024-01-01T01:00:00Z"},
                ],
            )

    def test_duplicate_rank_fails_closed(self):
        with self.assertRaisesRegex(FrontierError, "duplicate ranks"):
            build_frontier(
                self.snapshot, "source", "hash",
                ranked_assets=[
                    {"rank": 1, "asset": "A", "market_cap_usd": 100.0, "as_of": "2024-01-01T00:00:00Z", "published_at": "2024-01-01T01:00:00Z"},
                    {"rank": 1, "asset": "B", "market_cap_usd": 50.0, "as_of": "2024-01-01T00:00:00Z", "published_at": "2024-01-01T01:00:00Z"},
                ],
            )

    def test_invalid_cursor_and_batch_fail(self):
        with self.assertRaises(FrontierError):
            build_frontier(self.snapshot, "s", "h", records=[], last_completed_rank=-1)
        with self.assertRaises(FrontierError):
            build_frontier(self.snapshot, "s", "h", records=[], batch_size=0)
        with self.assertRaises(FrontierError):
            build_frontier(self.snapshot, "s", "h")

    def test_missing_inputs_fail_closed(self):
        with self.assertRaises(FrontierError):
            build_frontier(self.snapshot, "s", "h")
        with self.assertRaises(FrontierError):
            rank_universe([], "not-a-timestamp")
        with self.assertRaises(FrontierError):
            compute_snapshot_id("s", "h", "not-a-timestamp", [])

    def test_save_frontier_rejects_incomplete_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frontier.json"
            with self.assertRaises(FrontierError):
                save_frontier(path, {"snapshot_id": "x"})

    def test_load_frontier_missing_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FrontierError):
                load_frontier(Path(tmp) / "missing.json")

    def test_load_frontier_corrupt_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frontier.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(FrontierError):
                load_frontier(path)

    def test_utc_timestamps_are_timezone_aware(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frontier.json"
            persist_frontier(path, self.snapshot, "coingecko", "sha256:abc", records=self.records)
            loaded = load_frontier(path)
            self.assertTrue(loaded["snapshot_at"].endswith("Z"))
            self.assertTrue(loaded["updated_at_utc"].endswith("Z"))
            self.assertTrue(loaded["source"]["retrieved_at_utc"].endswith("Z"))
            for entry in loaded["excluded_assets"]:
                self.assertTrue(entry["excluded_at_utc"].endswith("Z"))

    def test_validate_ranked_assets_accepts_and_rejects(self):
        good = [
            {"rank": 1, "asset": "A", "market_cap_usd": 100.0, "as_of": "2024-01-01T00:00:00Z", "published_at": "2024-01-01T01:00:00Z"},
            {"rank": 2, "asset": "B", "market_cap_usd": 50.0, "as_of": "2024-01-01T00:00:00Z", "published_at": "2024-01-01T01:00:00Z"},
        ]
        validate_ranked_assets(good)
        bad_cap = [dict(good[0], market_cap_usd=float("nan"))]
        with self.assertRaises(FrontierError):
            validate_ranked_assets(bad_cap)
        bad_order = [dict(good[0], rank=2), dict(good[1], rank=1)]
        with self.assertRaises(FrontierError):
            validate_ranked_assets(bad_order)

    def test_build_not_started_frontier_is_canonical_stub(self):
        stub = build_not_started_frontier()
        self.assertEqual(stub["schema_version"], "1.0")
        self.assertEqual(stub["experiment_id"], "FVD-DISPERSION-V1")
        self.assertEqual(stub["status"], "NOT_STARTED")
        self.assertIsNone(stub["snapshot_id"])
        self.assertIsNone(stub["snapshot_at"])
        self.assertEqual(stub["rank_frontier"], [])
        self.assertEqual(stub["last_completed_rank"], 0)
        self.assertEqual(stub["completed_asset_ids"], [])
        self.assertEqual(stub["pending_asset_ids"], [])
        self.assertEqual(stub["excluded_assets"], [])
        self.assertEqual(stub["current_cohort"], [])
        self.assertIsNone(stub["next_action"])
        self.assertEqual(stub["source"], {"id": None, "hash": None, "retrieved_at_utc": None})
        self.assertEqual(stub["pagination"], {"cursor": None, "batch_size": 0, "has_more": False})
        self.assertEqual(stub["resume"]["next_rank"], 1)
        self.assertIsNone(stub["resume"]["next_asset"])
        self.assertIsNone(stub["resume"]["batch_window"])
        self.assertFalse(stub["resume"]["has_more"])
        self.assertEqual(stub["resume"]["frontier_size"], 0)
        self.assertIsNone(stub["resume"]["snapshot_id"])
        self.assertIsNone(stub["updated_at_utc"])

    def test_build_not_started_frontier_round_trips_through_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frontier.json"
            stub = build_not_started_frontier(next_action="verify a free source")
            save_frontier(path, stub)
            loaded = load_frontier(path)
            self.assertEqual(loaded, stub)

    def test_build_frontier_carries_current_cohort_and_next_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frontier.json"
            state = persist_frontier(
                path, self.snapshot, "coingecko", "sha256:abc",
                records=self.records, batch_size=2,
                next_action="fetch next cohort",
            )
            self.assertEqual(state["current_cohort"], ["BTC", "ETH"])
            self.assertEqual(state["next_action"], "fetch next cohort")
            loaded = load_frontier(path)
            self.assertEqual(loaded["current_cohort"], ["BTC", "ETH"])
            self.assertEqual(loaded["next_action"], "fetch next cohort")

    def test_build_frontier_current_cohort_is_empty_when_unranked(self):
        state = build_frontier(self.snapshot, "s", "h", records=[], next_action="done")
        self.assertEqual(state["current_cohort"], [])
        self.assertEqual(state["next_action"], "done")

    def test_build_frontier_rejects_non_list_current_cohort(self):
        with self.assertRaises(FrontierError):
            build_frontier(self.snapshot, "s", "h", records=[], current_cohort="BTC")

    def test_build_frontier_rejects_non_string_next_action(self):
        with self.assertRaises(FrontierError):
            build_frontier(self.snapshot, "s", "h", records=[], next_action=123)

    def test_build_frontier_rejects_extra_unknown_field(self):
        with self.assertRaises(FrontierError):
            build_frontier(self.snapshot, "s", "h", records=[], mystery_field=1)


if __name__ == "__main__":
    unittest.main()
