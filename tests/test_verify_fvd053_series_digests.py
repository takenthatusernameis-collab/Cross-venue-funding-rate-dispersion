import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import pstdev

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from verify_fvd053_series_digests import (  # noqa: E402
    canonical_digest,
    _window,
    _iso,
    execution_price_checks,
    funding_settlement_checks,
    dispersion_threshold_checks,
    selection_observation_checks,
    linear_quantile,
    prior_daily_threshold,
)


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


class FundingSettlementProvenanceTests(unittest.TestCase):
    OKX_MS = 1_700_000_000_000
    HL_MS = 1_700_003_600_000

    def _signals(self):
        okx_rate = 0.0002
        hl_rate = -0.00005
        return [{
            "underlying": "BTC",
            "funding_evidence": [
                {
                    "venue": "OKX", "side": 1, "settlement_time_utc": _iso(self.OKX_MS),
                    "original_rate": okx_rate, "interval_hours": 8.0,
                    "rate_8h": okx_rate, "notional": 5000.0,
                    "cash_flow": -1 * 5000.0 * okx_rate,
                },
                {
                    "venue": "Hyperliquid", "side": -1, "settlement_time_utc": _iso(self.HL_MS),
                    "original_rate": hl_rate, "interval_hours": 1.0,
                    "rate_8h": hl_rate * 8.0, "notional": 5000.0,
                    "cash_flow": 1 * 5000.0 * hl_rate,
                },
            ],
        }]

    def _funding(self, okx_rate=0.0002):
        return {
            ("BTC", "OKX"): [{"time": self.OKX_MS, "rate": okx_rate}],
            ("BTC", "Hyperliquid"): [{"time": self.HL_MS, "rate": -0.00005}],
        }

    def test_all_rows_match_with_tolerance_zero(self):
        result = funding_settlement_checks(self._signals(), self._funding())
        self.assertTrue(result["all_matched"])
        self.assertEqual(result["rows_expected"], 2)
        self.assertEqual(result["rows_matched"], 2)
        self.assertEqual(result["rows_failed"], 0)

    def test_changed_refetched_rate_fails(self):
        result = funding_settlement_checks(self._signals(), self._funding(okx_rate=0.00020001))
        self.assertFalse(result["all_matched"])
        self.assertEqual(result["rows_failed"], 1)
        failed = [r for r in result["rows"] if not r["passed"]][0]
        self.assertEqual((failed["underlying"], failed["venue"]), ("BTC", "OKX"))
        self.assertEqual(failed["recorded_rate"], 0.0002)
        self.assertEqual(failed["refetched_rate"], 0.00020001)

    def test_cash_flow_arithmetic_defect_fails(self):
        signals = self._signals()
        signals[0]["funding_evidence"][0]["cash_flow"] += 0.01
        result = funding_settlement_checks(signals, self._funding())
        self.assertFalse(result["all_matched"])
        self.assertEqual(result["rows_failed"], 1)

    def test_interval_not_matching_venue_fails(self):
        signals = self._signals()
        signals[0]["funding_evidence"][1]["interval_hours"] = 8.0
        result = funding_settlement_checks(signals, self._funding())
        self.assertFalse(result["all_matched"])
        self.assertEqual(result["rows_failed"], 1)

    def test_settlement_older_than_truncated_refetch_is_labelled_outside_retention(self):
        signals = self._signals()
        funding = {("BTC", "OKX"): [{"time": self.OKX_MS + 3_600_000, "rate": 0.0002}],
                   ("BTC", "Hyperliquid"): [{"time": self.HL_MS, "rate": -0.00005}]}
        result = funding_settlement_checks(
            signals, funding, {("BTC", "OKX"): True, ("BTC", "Hyperliquid"): False}
        )
        self.assertTrue(result["all_matched"])
        self.assertEqual(result["rows_outside_retention"], 1)
        self.assertEqual(result["rows_not_found"], 0)

    def test_missing_settlement_within_retention_is_a_failure(self):
        signals = self._signals()
        funding = {("BTC", "OKX"): [], ("BTC", "Hyperliquid"): [{"time": self.HL_MS, "rate": -0.00005}]}
        result = funding_settlement_checks(signals, funding)
        self.assertFalse(result["all_matched"])
        self.assertEqual(result["rows_not_found"], 1)
        self.assertEqual(result["rows_failed"], 1)


class QuantileAndThresholdTests(unittest.TestCase):
    def test_type7_linear_quantile(self):
        self.assertAlmostEqual(linear_quantile([1.0, 2.0, 3.0, 4.0], 80, minimum_observations=4), 3.4)

    def test_insufficient_observations_returns_none(self):
        self.assertIsNone(linear_quantile([1.0, 2.0], 80, minimum_observations=3))

    def test_current_date_is_excluded_and_lookback_respected(self):
        samples = [
            {"date": "2023-11-10", "snapshot_time_utc": "23:00:00", "dispersion": 1.0},
            {"date": "2023-11-11", "snapshot_time_utc": "23:00:00", "dispersion": 2.0},
            {"date": "2023-11-12", "snapshot_time_utc": "23:00:00", "dispersion": 100.0},
            {"date": "2023-08-01", "snapshot_time_utc": "23:00:00", "dispersion": 500.0},
        ]
        self.assertEqual(
            prior_daily_threshold(
                samples, "2023-11-12", 80, lookback_days=90, minimum_observations=2
            ),
            1.8,
        )

    def test_snapshot_after_cutoff_is_ignored(self):
        samples = [
            {"date": "2023-11-10", "snapshot_time_utc": "23:00:00", "dispersion": 1.0},
            {"date": "2023-11-10", "snapshot_time_utc": "23:30:00", "dispersion": 99.0},
        ]
        self.assertEqual(
            prior_daily_threshold(
                samples, "2023-11-12", 80, lookback_days=90, minimum_observations=1
            ),
            1.0,
        )


class _SyntheticMarket:
    """Constant per-venue funding so every covered date has one known dispersion."""

    HL_RATE = 0.0001
    OKX_RATE = 0.0003
    DISPERSION = pstdev([0.0008, 0.0003])

    @staticmethod
    def _ms(text):
        return int(datetime.fromisoformat(text + "+00:00").timestamp() * 1000)

    def hl_rows(self, start="2023-11-06T00:00:00", end="2023-11-12T23:00:00"):
        rows, cursor = [], datetime.fromisoformat(start + "+00:00")
        stop = datetime.fromisoformat(end + "+00:00")
        while cursor <= stop:
            rows.append({"time": int(cursor.timestamp() * 1000), "rate": self.HL_RATE})
            cursor += timedelta(hours=1)
        return rows

    def okx_rows(self, start="2023-11-06T00:00:00", end="2023-11-12T16:00:00"):
        rows, cursor = [], datetime.fromisoformat(start + "+00:00")
        stop = datetime.fromisoformat(end + "+00:00")
        while cursor <= stop:
            rows.append({"time": int(cursor.timestamp() * 1000), "rate": self.OKX_RATE})
            cursor += timedelta(hours=8)
        return rows

    def observations(self, rows, interval_hours, start, end):
        begin = self._ms(start)
        finish = self._ms(end)
        return [
            {
                "timestamp": _iso(row["time"]),
                "interval_hours": interval_hours,
                "original_rate": row["rate"],
                "rate_8h": row["rate"] * 8.0 / interval_hours,
            }
            for row in rows
            if begin <= row["time"] <= finish
        ]


class DispersionAndThresholdWiringTests(unittest.TestCase):
    DATES = ["2023-11-07", "2023-11-08", "2023-11-09", "2023-11-10", "2023-11-11", "2023-11-12"]

    def setUp(self):
        self.market = _SyntheticMarket()
        self.funding = {
            ("BTC", "Hyperliquid"): self.market.hl_rows(),
            ("BTC", "OKX"): self.market.okx_rows(),
        }

    def _artifact(self):
        evidence = []
        for index, day in enumerate(self.DATES):
            prior_samples = index
            threshold = self.market.DISPERSION if prior_samples >= 4 else None
            evidence.append({
                "date_utc": day,
                "underlyings": {
                    "BTC": {
                        "dispersion": self.market.DISPERSION,
                        "prior_threshold": threshold,
                        "threshold_eligible": threshold is not None,
                        "selected": threshold is not None,
                    }
                },
            })
        return {
            "window_start_utc": "2023-11-06T00:00:00Z",
            "window_end_utc": "2023-11-12T23:00:00Z",
            "underlyings": ["BTC"],
            "anchor_params": {
                "dispersion_lookback_hours": 24,
                "entry_percentile": 80,
                "threshold_lookback_days": 90,
                "threshold_minimum_observations": 4,
                "portfolio_tail_fraction": 0.1,
            },
            "dispersion_evidence": evidence,
            "selection_evidence": [],
        }

    def test_every_dispersion_threshold_and_selection_row_matches(self):
        result = dispersion_threshold_checks(self._artifact(), self.funding)
        self.assertTrue(result["all_matched"])
        self.assertEqual(result["dispersion_rows_matched"], len(self.DATES))
        self.assertEqual(result["threshold_rows_failed"], 0)
        self.assertEqual(result["selection_rows_failed"], 0)

    def test_changed_refetched_rate_breaks_dispersion(self):
        funding = dict(self.funding)
        funding[("BTC", "OKX")] = [
            {"time": row["time"], "rate": row["rate"] * 1.01} for row in self.market.okx_rows()
        ]
        result = dispersion_threshold_checks(self._artifact(), funding)
        self.assertFalse(result["all_matched"])
        self.assertGreater(result["dispersion_rows_failed"], 0)

    def test_changed_recorded_threshold_fails(self):
        artifact = self._artifact()
        artifact["dispersion_evidence"][-1]["underlyings"]["BTC"]["prior_threshold"] *= 1.000001
        result = dispersion_threshold_checks(artifact, self.funding)
        self.assertFalse(result["all_matched"])
        self.assertEqual(result["threshold_rows_failed"], 1)

    def test_changed_selection_flag_fails(self):
        artifact = self._artifact()
        artifact["dispersion_evidence"][-1]["underlyings"]["BTC"]["selected"] = False
        result = dispersion_threshold_checks(artifact, self.funding)
        self.assertFalse(result["all_matched"])
        self.assertEqual(result["selection_rows_failed"], 1)

    def test_null_dispersion_matches_when_both_venues_absent(self):
        artifact = self._artifact()
        artifact["dispersion_evidence"] = [{
            "date_utc": "2023-11-07",
            "underlyings": {"BTC": {"dispersion": None, "prior_threshold": None,
                                    "threshold_eligible": False, "selected": False}},
        }]
        funding = {("BTC", "Hyperliquid"): [], ("BTC", "OKX"): []}
        result = dispersion_threshold_checks(artifact, funding)
        self.assertTrue(result["all_matched"])
        self.assertEqual(result["dispersion_rows_matched"], 1)

    def test_okx_retention_gap_is_labelled_not_matched(self):
        artifact = self._artifact()
        funding = {
            ("BTC", "Hyperliquid"): self.market.hl_rows(),
            ("BTC", "OKX"): self.market.okx_rows(start="2023-11-12T00:00:00"),
        }
        result = dispersion_threshold_checks(
            artifact, funding, {("BTC", "OKX"): True}
        )
        self.assertTrue(result["all_matched"])
        self.assertGreater(result["dispersion_rows_outside_retention"], 0)


class SelectionObservationTests(unittest.TestCase):
    def setUp(self):
        self.market = _SyntheticMarket()

    def _artifact(self, okx_rate=None):
        hl = self.market.hl_rows()
        okx = self.market.okx_rows()
        if okx_rate is not None:
            okx = [{"time": row["time"], "rate": okx_rate} for row in okx]
        entry = {
            "date_utc": "2023-11-12",
            "signal_time_utc": "2023-11-12T23:00:00Z",
            "window_start_utc": "2023-11-11T23:00:00Z",
            "underlyings": {
                "BTC": {
                    "dispersion": self.market.DISPERSION,
                    "observations": {
                        "Hyperliquid": self.market.observations(
                            hl, 1.0, "2023-11-10T23:00:00", "2023-11-12T23:00:00"),
                        "OKX": self.market.observations(
                            okx, 8.0, "2023-11-10T23:00:00", "2023-11-12T23:00:00"),
                    },
                }
            },
        }
        return {
            "underlyings": ["BTC"],
            "anchor_params": {"dispersion_lookback_hours": 24},
            "dispersion_evidence": [{
                "date_utc": "2023-11-12",
                "underlyings": {"BTC": {"dispersion": self.market.DISPERSION}},
            }],
            "selection_evidence": [entry],
        }

    def test_selection_observations_and_dispersion_reproduce(self):
        funding = {
            ("BTC", "Hyperliquid"): self.market.hl_rows(),
            ("BTC", "OKX"): self.market.okx_rows(),
        }
        result = selection_observation_checks(self._artifact(), funding)
        self.assertTrue(result["all_matched"])
        self.assertEqual(result["observation_rows_failed"], 0)
        self.assertEqual(result["underlying_windows_matched"], 1)

    def test_changed_refetched_observation_rate_fails(self):
        artifact = self._artifact()
        funding = {
            ("BTC", "Hyperliquid"): self.market.hl_rows(),
            ("BTC", "OKX"): self.market.okx_rows(),
        }
        funding[("BTC", "OKX")] = [
            {"time": row["time"], "rate": row["rate"] + 1e-9}
            for row in self.market.okx_rows()
        ]
        result = selection_observation_checks(artifact, funding)
        self.assertFalse(result["all_matched"])
        self.assertGreater(result["observation_rows_failed"], 0)

    def test_selection_dispersion_must_match_evidence_series(self):
        artifact = self._artifact()
        artifact["dispersion_evidence"][0]["underlyings"]["BTC"]["dispersion"] *= 2
        funding = {
            ("BTC", "Hyperliquid"): self.market.hl_rows(),
            ("BTC", "OKX"): self.market.okx_rows(),
        }
        result = selection_observation_checks(artifact, funding)
        self.assertFalse(result["all_matched"])
        self.assertEqual(result["underlying_windows_failed"], 1)


if __name__ == "__main__":
    unittest.main()
