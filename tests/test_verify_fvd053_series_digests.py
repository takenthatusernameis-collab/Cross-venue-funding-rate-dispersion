import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from verify_fvd053_series_digests import canonical_digest, _window, execution_price_checks  # noqa: E402


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


class ExecutionPriceProvenanceTests(unittest.TestCase):
    ENTRY_MS = 1_700_000_000_000
    EXIT_MS = 1_700_003_600_000

    def _signals(self):
        return [{
            "underlying": "BTC",
            "long_venue": "OKX",
            "short_venue": "Hyperliquid",
            "entry_time_utc": "2023-11-14T22:13:20Z",
            "exit_time_utc": "2023-11-14T23:13:20Z",
            "entry_price_long": 100.0,
            "entry_price_short": 101.0,
            "exit_price_long": 102.0,
            "exit_price_short": 103.0,
            "candle_evidence": [
                {"venue": "OKX", "side": "long", "timestamp_utc": "2023-11-14T22:13:20Z", "open": 100.0, "close": 100.5},
                {"venue": "Hyperliquid", "side": "short", "timestamp_utc": "2023-11-14T22:13:20Z", "open": 101.0, "close": 101.5},
                {"venue": "OKX", "side": "long", "timestamp_utc": "2023-11-14T23:13:20Z", "open": 102.0, "close": 102.5},
                {"venue": "Hyperliquid", "side": "short", "timestamp_utc": "2023-11-14T23:13:20Z", "open": 103.0, "close": 103.5},
            ],
        }]

    def _candles(self, okx_exit_open=102.0):
        return {
            ("BTC", "OKX"): [
                {"time": self.ENTRY_MS, "open": 100.0, "close": 100.5},
                {"time": self.EXIT_MS, "open": okx_exit_open, "close": 102.5},
            ],
            ("BTC", "Hyperliquid"): [
                {"time": self.ENTRY_MS, "open": 101.0, "close": 101.5},
                {"time": self.EXIT_MS, "open": 103.0, "close": 103.5},
            ],
        }

    def test_all_rows_match_with_tolerance_zero(self):
        result = execution_price_checks(self._signals(), self._candles())
        self.assertTrue(result["all_matched"])
        self.assertEqual(result["rows_expected"], 4)
        self.assertEqual(result["rows_matched"], 4)
        self.assertEqual(result["internal_price_failed"], 0)

    def test_changed_refetched_open_fails(self):
        result = execution_price_checks(self._signals(), self._candles(okx_exit_open=102.0000001))
        self.assertFalse(result["all_matched"])
        self.assertEqual(result["rows_failed"], 1)
        failed = [r for r in result["rows"] if not r["passed"]][0]
        self.assertEqual((failed["underlying"], failed["venue"], failed["role"]), ("BTC", "OKX", "exit"))
        self.assertEqual(failed["recorded_open"], 102.0)
        self.assertEqual(failed["refetched_open"], 102.0000001)

    def test_missing_timestamp_is_failed_not_silently_skipped(self):
        candles = self._candles()
        candles[("BTC", "Hyperliquid")] = candles[("BTC", "Hyperliquid")][:1]
        result = execution_price_checks(self._signals(), candles)
        self.assertFalse(result["all_matched"])
        self.assertEqual(result["rows_not_found"], 1)
        self.assertEqual(result["rows_failed"], 1)

    def test_signal_price_inconsistent_with_its_own_candle_fails(self):
        signals = self._signals()
        signals[0]["entry_price_long"] = 99.99
        result = execution_price_checks(signals, self._candles())
        self.assertFalse(result["all_matched"])
        self.assertEqual(result["rows_failed"], 0)
        self.assertEqual(result["internal_price_failed"], 1)


if __name__ == "__main__":
    unittest.main()
