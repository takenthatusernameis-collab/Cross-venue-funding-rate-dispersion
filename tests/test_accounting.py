import math
import unittest
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from cross_venue_funding_dispersion.accounting import execution_cost,funding_cash_flow,pair_funding_cash_flow,price_pnl


class AccountingTests(unittest.TestCase):
    def test_positive_funding_long_pays_short_receives(self):
        self.assertEqual(funding_cash_flow(1,1000,0.001),-1.0)
        self.assertEqual(funding_cash_flow(-1,1000,0.001),1.0)

    def test_negative_funding_long_receives_short_pays(self):
        self.assertAlmostEqual(funding_cash_flow(1,1000,-0.001),1.0)
        self.assertAlmostEqual(funding_cash_flow(-1,1000,-0.001),-1.0)

    def test_long_low_rate_short_high_rate_collects_carry(self):
        self.assertAlmostEqual(pair_funding_cash_flow(1000,-0.0005,0.001),1.5)

    def test_pair_funding_symmetric_cases(self):
        self.assertAlmostEqual(pair_funding_cash_flow(500,0.002,-0.001),-1.5)
        self.assertAlmostEqual(pair_funding_cash_flow(100,0.0003,0.0003),0.0)

    def test_price_pnl_is_separate(self):
        self.assertAlmostEqual(price_pnl(1,1000,100,110),100)
        self.assertAlmostEqual(price_pnl(-1,1000,100,110),-100)
        self.assertAlmostEqual(price_pnl(1,2000,50,25),-1000)
        self.assertAlmostEqual(price_pnl(-1,2000,50,25),1000)

    def test_invalid_values_rejected(self):
        for fn,args in [(funding_cash_flow,(0,100,0.001)),(funding_cash_flow,(1,100,math.nan)),(funding_cash_flow,(2,100,0.001)),(execution_cost,(1000,-1,2)),(execution_cost,(1000,0,-0.1)),(price_pnl,(1,100,0,100)),(price_pnl,(1,-1,100,110)),(price_pnl,(1,100,math.inf,110))]:
            with self.assertRaises(ValueError):
                fn(*args)

    def test_cost_applies_per_side_and_fill(self):
        self.assertAlmostEqual(execution_cost(1000,5,5),1.0)
        self.assertAlmostEqual(execution_cost(0,10,10),0.0)
        self.assertAlmostEqual(execution_cost(500,2,3),0.25)


if __name__=="__main__":
    unittest.main()
