import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from verify_fvd053_series_digests import canonical_digest, _window  # noqa: E402


def _rows():
    return [
        {"time": 1_700_000_000_000, "open": 1.5, "close": 1.75},
        {"time": 1_700_003_600_000, "open": 1.75, "close": 1.6},
        {"time": 1_699_996_400_000, "open": 1.4, "close": 1.5},
    ]


class CanonicalDigestTests(unittest.TestCase):
    def test_digest_is_order_independent(self):
        forward = canonical_digest(_rows())
        reverse = canonical_digest(list(reversed(_rows())))
        self.assertEqual(forward, reverse)

    def test_digest_reports_count_and_bounds(self):
        digest = canonical_digest(_rows())
        self.assertEqual(digest["row_count"], 3)
        self.assertEqual(digest["first_time_utc"], "2023-11-14T21:13:20Z")
        self.assertEqual(digest["last_time_utc"], "2023-11-14T23:13:20Z")

    def test_digest_changes_when_a_close_changes(self):
        base = canonical_digest(_rows())
        tweaked = _rows()
        tweaked[1]["close"] = 1.6000001
        self.assertNotEqual(base["sha256"], canonical_digest(tweaked)["sha256"])

    def test_empty_series_digest_is_defined(self):
        digest = canonical_digest([])
        self.assertEqual(digest["row_count"], 0)
        self.assertIsNone(digest["first_time_utc"])
        self.assertIsNone(digest["last_time_utc"])

    def test_matches_producer_digest_for_same_rows(self):
        from run_fvd053_anchor import _series_digest

        rows = _rows()
        self.assertEqual(canonical_digest(rows)["sha256"], _series_digest(rows)["sha256"])


class FundingWindowTests(unittest.TestCase):
    def test_window_uses_min_and_max_time(self):
        self.assertEqual(
            _window([{"time": 2}, {"time": 1}, {"time": 3}]),
            {"first_time_utc": "1970-01-01T00:00:00.001000Z", "last_time_utc": "1970-01-01T00:00:00.003000Z"},
        )

    def test_empty_window_is_none(self):
        self.assertEqual(_window([]), {"first_time_utc": None, "last_time_utc": None})


if __name__ == "__main__":
    unittest.main()
