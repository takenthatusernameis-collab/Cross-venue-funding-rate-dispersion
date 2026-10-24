import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from cross_venue_funding_dispersion.signals import (
    dispersion_from_venue_histories,linear_quantile,normalize_funding_rate,
    prior_daily_threshold,select_top_dispersion,time_weighted_mean
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


if __name__=="__main__":
    unittest.main()
