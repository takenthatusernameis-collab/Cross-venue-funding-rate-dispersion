import unittest
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from cross_venue_funding_dispersion.universe import next_ranked_cohort,rank_point_in_time


class UniverseTests(unittest.TestCase):
    def setUp(self):
        self.records=[
            {"asset":"AAA","market_cap_usd":100,"as_of":"2024-01-01T00:00:00Z","published_at":"2024-01-01T01:00:00Z"},
            {"asset":"BBB","market_cap_usd":200,"as_of":"2024-01-01T00:00:00Z","published_at":"2024-01-01T01:00:00Z"},
            {"asset":"AAA","market_cap_usd":150,"as_of":"2024-02-01T00:00:00Z","published_at":"2024-02-01T01:00:00Z"},
            {"asset":"FUTURE","market_cap_usd":999,"as_of":"2025-01-01T00:00:00Z","published_at":"2025-01-01T01:00:00Z"},
            {"asset":"LATE","market_cap_usd":888,"as_of":"2024-02-01T00:00:00Z","published_at":"2024-03-01T00:00:00Z"},
            {"asset":"BAD","market_cap_usd":float("nan"),"as_of":"2024-01-01T00:00:00Z","published_at":"2024-01-01T00:00:00Z"},
        ]

    def test_descending_point_in_time_rank(self):
        ranked=rank_point_in_time(self.records,"2024-02-15T00:00:00Z")
        self.assertEqual([x["asset"] for x in ranked],["BBB","AAA"])
        self.assertEqual([x["rank"] for x in ranked],[1,2])
        self.assertEqual(ranked[1]["market_cap_usd"],150)

    def test_future_and_late_published_data_excluded(self):
        ranked=rank_point_in_time(self.records,"2024-02-15T00:00:00Z")
        self.assertNotIn("FUTURE",[x["asset"] for x in ranked])
        self.assertNotIn("LATE",[x["asset"] for x in ranked])

    def test_cursor_batches_have_no_gaps(self):
        ranked=[{"rank":i,"asset":f"A{i}"} for i in range(1,8)]
        a=next_ranked_cohort(ranked,0,3)
        b=next_ranked_cohort(ranked,a[-1]["rank"],3)
        c=next_ranked_cohort(ranked,b[-1]["rank"],3)
        self.assertEqual([x["asset"] for x in a+b+c],[f"A{i}" for i in range(1,8)])

    def test_rank_frontier_gap_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "rank frontier gap"):
            next_ranked_cohort([{"rank":1,"asset":"A1"},{"rank":3,"asset":"A3"}], 1, 2)

    def test_bad_cursor_and_batch_fail(self):
        with self.assertRaises(ValueError): next_ranked_cohort([], -1, 2)
        with self.assertRaises(ValueError): next_ranked_cohort([], 0, 0)


if __name__=="__main__":
    unittest.main()
