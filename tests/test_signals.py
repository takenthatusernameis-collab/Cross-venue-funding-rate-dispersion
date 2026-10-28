import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.signals import (
    dispersion_from_venue_histories,
    linear_quantile,
    normalize_funding_rate,
    prior_daily_threshold,
    select_top_dispersion,
    time_weighted_mean,
)


class SignalTests(unittest.TestCase):
    def test_normalization_uses_actual_interval(self):
        self.assertAlmostEqual(normalize_funding_rate(0.001,4),0.002)
        with self.assertRaises(ValueError): normalize_funding_rate(0.001,0)

    def test_time_weighted_mean_and_gap_fail_closed(self):
        rows=[
            {"timestamp":"2024-01-01T00:00:00Z","rate_8h":1.0},
            {"timestamp":"2024-01-01T02:00:00Z","rate_8h":3.0},
        ]
        self.assertAlmostEqual(time_weighted_mean(rows,"2024-01-01T00:00:00Z","2024-01-01T04:00:00Z",max_staleness_hours=3),2.0)
        self.assertIsNone(time_weighted_mean(rows[1:],"2024-01-01T00:00:00Z","2024-01-01T04:00:00Z",max_staleness_hours=3))
        self.assertIsNone(time_weighted_mean(rows,"2024-01-01T00:00:00Z","2024-01-01T08:00:00Z",max_staleness_hours=3))

    def test_dispersion_requires_minimum_venues(self):
        start="2024-01-01T00:00:00Z"; end="2024-01-01T02:00:00Z"
        histories={
            "A":[{"timestamp":start,"rate_8h":1.0}],
            "B":[{"timestamp":start,"rate_8h":3.0}],
        }
        disp,means=dispersion_from_venue_histories(histories,start,end,minimum_venues=2,max_staleness_hours=3)
        self.assertAlmostEqual(disp,1.0)
        self.assertEqual(means,{"A":1.0,"B":3.0})
        disp,_=dispersion_from_venue_histories({"A":histories["A"]},start,end,minimum_venues=2,max_staleness_hours=3)
        self.assertIsNone(disp)

    def test_multi_venue_dispersion_normalization_known_answer(self):
        """A 1h venue rate r and an 8h venue rate 8r normalize to the same
        8h-equivalent value => zero dispersion. Equal raw rates r normalize
        to different 8h values (8r vs r) => nonzero dispersion. Normalization
        is essential to the cross-venue signal.
        """
        start = "2024-01-01T00:00:00Z"
        end = "2024-01-01T08:00:00Z"
        r = 0.0001
        # Case 1: HL hourly r (-> 8r) vs OKX 8h 8r (-> 8r): both 8h-equal => 0 dispersion.
        histories_same = {
            "Hyperliquid": [{"timestamp": start, "rate_8h": normalize_funding_rate(r, 1.0)}],
            "OKX": [{"timestamp": start, "rate_8h": normalize_funding_rate(8 * r, 8.0)}],
        }
        disp, means = dispersion_from_venue_histories(
            histories_same, start, end, minimum_venues=2, max_staleness_hours=24,
        )
        self.assertAlmostEqual(disp, 0.0)
        self.assertAlmostEqual(means["Hyperliquid"], 8 * r)
        self.assertAlmostEqual(means["OKX"], 8 * r)
        # Case 2: equal raw rates r on both venues: HL normalizes to 8r, OKX stays r => nonzero.
        histories_diff = {
            "Hyperliquid": [{"timestamp": start, "rate_8h": normalize_funding_rate(r, 1.0)}],
            "OKX": [{"timestamp": start, "rate_8h": normalize_funding_rate(r, 8.0)}],
        }
        disp2, means2 = dispersion_from_venue_histories(
            histories_diff, start, end, minimum_venues=2, max_staleness_hours=24,
        )
        self.assertAlmostEqual(disp2, 3.5 * r)
        self.assertAlmostEqual(means2["Hyperliquid"], 8 * r)
        self.assertAlmostEqual(means2["OKX"], r)

    def test_type7_quantile_and_no_fallback(self):
        self.assertAlmostEqual(linear_quantile([0,10,20,30],50),15)
        self.assertIsNone(linear_quantile([1,2],80,minimum_observations=3))

    def test_threshold_uses_prior_dates_only_and_one_sample_per_day(self):
        samples=[]
        for day in range(1,36):
            d=f"2024-01-{day:02d}"
            samples.append({"date":d,"snapshot_time_utc":"22:00","dispersion":float(day)})
            samples.append({"date":d,"snapshot_time_utc":"23:00","dispersion":float(day+100)})
            samples.append({"date":d,"snapshot_time_utc":"23:30","dispersion":9999.0})
        samples.append({"date":"2024-02-05","snapshot_time_utc":"23:00","dispersion":99999.0})
        result=prior_daily_threshold(samples,"2024-02-06",80,lookback_days=90,minimum_observations=30)
        self.assertIsNotNone(result)
        self.assertLess(result,1000)
        self.assertIsNone(prior_daily_threshold(samples,"2024-02-06",80,lookback_days=90,minimum_observations=40))

    def test_top_tail_is_deterministic_and_threshold_none_means_no_signal(self):
        self.assertEqual(select_top_dispersion({"B":4,"A":4,"C":2},3,0.5),["A","B"])
        self.assertEqual(select_top_dispersion({"A":10},None,0.5),[])

    def test_normalize_rejects_non_finite_and_zero_interval(self):
        with self.assertRaises(ValueError):
            normalize_funding_rate(float("nan"), 8)
        with self.assertRaises(ValueError):
            normalize_funding_rate(float("inf"), 8)
        with self.assertRaises(ValueError):
            normalize_funding_rate(0.001, -1)

    def test_time_weighted_mean_rejects_naive_and_bad_inputs(self):
        with self.assertRaises(ValueError):
            time_weighted_mean([{"timestamp": "2024-01-01T00:00:00", "rate_8h": 1.0}], "2024-01-01T00:00:00Z", "2024-01-01T04:00:00Z", max_staleness_hours=3)
        with self.assertRaises(ValueError):
            time_weighted_mean([{"timestamp": "2024-01-01T00:00:00Z", "rate_8h": 1.0}], "2024-01-01T00:00:00", "2024-01-01T04:00:00Z", max_staleness_hours=3)
        with self.assertRaises(ValueError):
            time_weighted_mean([{"timestamp": "2024-01-01T00:00:00Z", "rate_8h": 1.0}], "2024-01-01T04:00:00Z", "2024-01-01T00:00:00Z", max_staleness_hours=3)
        with self.assertRaises(ValueError):
            time_weighted_mean([{"timestamp": "2024-01-01T00:00:00Z", "rate_8h": 1.0}], "2024-01-01T00:00:00Z", "2024-01-01T04:00:00Z", max_staleness_hours=0)
        with self.assertRaises(ValueError):
            time_weighted_mean([{"timestamp": "2024-01-01T00:00:00Z", "rate_8h": float("nan")}], "2024-01-01T00:00:00Z", "2024-01-01T04:00:00Z", max_staleness_hours=3)
        with self.assertRaises(ValueError):
            time_weighted_mean([{"timestamp": "2024-01-01T00:00:00Z", "rate_8h": 1.0}, {"timestamp": "2024-01-01T00:00:00Z", "rate_8h": 2.0}], "2024-01-01T00:00:00Z", "2024-01-01T04:00:00Z", max_staleness_hours=3)

    def test_time_weighted_mean_rejects_gap_at_boundary_and_stale_change(self):
        rows = [{"timestamp": "2024-01-01T00:00:00Z", "rate_8h": 1.0}]
        # If a change would occur but is stale relative to boundary
        rows2 = [
            {"timestamp": "2024-01-01T00:00:00Z", "rate_8h": 1.0},
            {"timestamp": "2024-01-01T03:30:00Z", "rate_8h": 2.0},
        ]
        # max staleness 2h means change at +3.5h from previous is stale? previous is 00:00, next is at 03:30; gap from current_time (00:00) to next_time (03:30) is 3.5h > 2h -> fail closed
        self.assertIsNone(time_weighted_mean(rows2, "2024-01-01T00:00:00Z", "2024-01-01T04:00:00Z", max_staleness_hours=2))

    def test_time_weighted_mean_hourly_1h_boundary_strict_staleness(self):
        hourly = [
            {"timestamp": "2026-01-01T00:00:00Z", "rate_8h": 1.0},
            {"timestamp": "2026-01-01T01:00:00Z", "rate_8h": 2.0},
        ]
        self.assertAlmostEqual(
            time_weighted_mean(hourly, "2026-01-01T00:00:00Z", "2026-01-01T02:00:00Z", max_staleness_hours=1.0),
            1.5,
        )
        single = [{"timestamp": "2026-01-01T00:00:00Z", "rate_8h": 1.0}]
        # gap from 00:00 to finish 01:00 is exactly max_staleness (1.0h): strict `>` => accepted.
        self.assertAlmostEqual(
            time_weighted_mean(single, "2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z", max_staleness_hours=1.0),
            1.0,
        )
        # gap from 00:00 to finish 02:00 is 2.0h > 1.0h => fail closed.
        self.assertIsNone(
            time_weighted_mean(single, "2026-01-01T00:00:00Z", "2026-01-01T02:00:00Z", max_staleness_hours=1.0)
        )

    def test_dispersion_requires_minimum_venues_strict(self):
        start = "2024-01-01T00:00:00Z"
        end = "2024-01-01T02:00:00Z"
        with self.assertRaises(ValueError):
            dispersion_from_venue_histories({"A": [], "B": []}, start, end, minimum_venues=1, max_staleness_hours=3)
        disp, means = dispersion_from_venue_histories({}, start, end, minimum_venues=2, max_staleness_hours=3)
        self.assertIsNone(disp)
        self.assertEqual(means, {})

    def test_quantile_rejects_bad_args_and_no_fallback(self):
        with self.assertRaises(ValueError):
            linear_quantile([1, 2], 50, minimum_observations=0)
        with self.assertRaises(ValueError):
            linear_quantile([1, 2], -1)
        with self.assertRaises(ValueError):
            linear_quantile([1, 2], 101)
        with self.assertRaises(ValueError):
            linear_quantile([float("nan")], 50)
        self.assertIsNone(linear_quantile([], 50, minimum_observations=1))

    def test_prior_daily_threshold_excludes_current_and_after_cutoff_and_uses_latest_per_day(self):
        samples = []
        # prior days with samples after 23:00 excluded, keep latest <=23:00
        samples.append({"date": "2024-01-01", "snapshot_time_utc": "22:00", "dispersion": 1.0})
        samples.append({"date": "2024-01-01", "snapshot_time_utc": "23:00", "dispersion": 2.0})
        samples.append({"date": "2024-01-01", "snapshot_time_utc": "23:30", "dispersion": 3.0})
        # current day excluded
        samples.append({"date": "2024-01-02", "snapshot_time_utc": "22:00", "dispersion": 100.0})
        # malformed skipped
        samples.append({"date": "bad", "snapshot_time_utc": "22:00", "dispersion": 1.0})
        samples.append({"date": "2024-01-03", "snapshot_time_utc": "22:00", "dispersion": float("inf")})
        with self.assertRaises(ValueError):
            prior_daily_threshold(samples, "2024-01-02", 50, lookback_days=0, minimum_observations=1)
        res = prior_daily_threshold(samples, "2024-01-02", 50, lookback_days=90, minimum_observations=1)
        self.assertAlmostEqual(res, 2.0)

    def test_select_top_dispersion_deterministic_tie_and_fraction(self):
        # tie broken by asset id
        self.assertEqual(select_top_dispersion({"B": 5, "A": 5}, 1.0, 1.0), ["A", "B"])
        # fraction rounds up
        self.assertEqual(select_top_dispersion({"A": 10, "B": 1}, 0.5, 0.5), ["A"])
        # threshold filters
        self.assertEqual(select_top_dispersion({"A": 10, "B": 1}, 5.0, 1.0), ["A"])
        with self.assertRaises(ValueError):
            select_top_dispersion({"A": 1}, 1.0, 0)
        with self.assertRaises(ValueError):
            select_top_dispersion({"A": 1}, 1.0, 1.5)
        with self.assertRaises(ValueError):
            select_top_dispersion({"A": float("nan")}, 1.0, 0.5)


if __name__=="__main__":
    unittest.main()
