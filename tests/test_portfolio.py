import unittest
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from cross_venue_funding_dispersion.portfolio import allocate_equal_notional_pairs


class PortfolioTests(unittest.TestCase):
    def test_gross_exposure_never_exceeds_one_x(self):
        allocation=allocate_equal_notional_pairs(1000,["B","A","C"])
        self.assertEqual(list(allocation),["A","B","C"])
        self.assertAlmostEqual(sum(allocation.values())*2,1000)
        self.assertTrue(all(x==1000/6 for x in allocation.values()))

    def test_gross_multiple_one_x_hard_cap(self):
        allocation = allocate_equal_notional_pairs(5000, ["BTC", "ETH", "SOL"], gross_multiple=1.0)
        self.assertAlmostEqual(sum(allocation.values()) * 2.0, 5000.0)
        for v in allocation.values():
            self.assertAlmostEqual(v, 5000.0 / 6.0)

    def test_no_assets_and_invalid_inputs(self):
        self.assertEqual(allocate_equal_notional_pairs(1000,[]),{})
        self.assertEqual(allocate_equal_notional_pairs(0, ["A"]), {})
        self.assertEqual(allocate_equal_notional_pairs(1000, ["A"], gross_multiple=0.0), {})
        with self.assertRaises(ValueError): allocate_equal_notional_pairs(1000,["A","A"])
        with self.assertRaises(ValueError): allocate_equal_notional_pairs(1000,["A"],gross_multiple=1.1)
        with self.assertRaises(ValueError): allocate_equal_notional_pairs(1000,["A"],gross_multiple=-0.1)
        with self.assertRaises(ValueError): allocate_equal_notional_pairs(-1,["A"])


if __name__=="__main__":
    unittest.main()
