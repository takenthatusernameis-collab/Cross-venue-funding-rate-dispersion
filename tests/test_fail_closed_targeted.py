import unittest
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cross_venue_funding_dispersion.signals import (
    dispersion_from_venue_histories,
    time_weighted_mean,
)
from cross_venue_funding_dispersion.backtest import run_backtest_skeleton


class FailClosedTargetedTests(unittest.TestCase):
    def test_time_weighted_mean_staleness_gap(self):
        rows = [
            {"timestamp": "2024-01-01T00:00:00Z", "rate_8h": 1.0},
            {"timestamp": "2024-01-01T05:00:00Z", "rate_8h": 3.0},
        ]
        self.assertIsNone(time_weighted_mean(rows, "2024-01-01T00:00:00Z", "2024-01-01T06:00:00Z", max_staleness_hours=3))

    def test_time_weighted_mean_first_observation_coverage(self):
        rows = [{"timestamp": "2024-01-01T01:00:00Z", "rate_8h": 1.0}]
        self.assertIsNone(time_weighted_mean(rows, "2024-01-01T00:00:00Z", "2024-01-01T02:00:00Z", max_staleness_hours=3))

    def test_time_weighted_mean_duplicate_timestamps(self):
        rows = [
            {"timestamp": "2024-01-01T00:00:00Z", "rate_8h": 1.0},
            {"timestamp": "2024-01-01T00:00:00Z", "rate_8h": 2.0},
        ]
        with self.assertRaises(ValueError):
            time_weighted_mean(rows, "2024-01-01T00:00:00Z", "2024-01-01T02:00:00Z", max_staleness_hours=3)

    def test_time_weighted_mean_non_positive_interval(self):
        rows = [{"timestamp": "2024-01-01T00:00:00Z", "rate_8h": 1.0}]
        with self.assertRaises(ValueError):
            time_weighted_mean(rows, "2024-01-01T02:00:00Z", "2024-01-01T00:00:00Z", max_staleness_hours=3)

    def test_dispersion_insufficient_venues(self):
        start = "2024-01-01T00:00:00Z"; end = "2024-01-01T02:00:00Z"
        histories = {"A": [{"timestamp": start, "rate_8h": 1.0}]}
        disp, means = dispersion_from_venue_histories(histories, start, end, minimum_venues=2, max_staleness_hours=3)
        self.assertIsNone(disp)
        self.assertEqual(means, {"A": 1.0})

    def test_backtest_settlement_before_next_open_missed(self):
        pairs = [{
            "asset_long": "A", "asset_short": "B",
            "entry_price_long": 100.0, "exit_price_long": 101.0,
            "entry_price_short": 100.0, "exit_price_short": 99.0,
            "funding_rate_long": 0.01, "funding_rate_short": 0.005,
            "settlement_time": "2024-01-01T00:30:00Z",
            "position_open_at_settlement": True,
        }]
        result = run_backtest_skeleton(
            equity=1000.0, pairs=pairs,
            signal_time="2024-01-01T00:00:00Z",
            next_open_time="2024-01-01T01:00:00Z",
            fee_bps_per_side=0.0, slippage_bps_per_side=0.0,
        )
        self.assertEqual(result["pairs"][0]["ledger"]["funding_cash_flow"], 0.0)


if __name__ == "__main__":
    unittest.main()
