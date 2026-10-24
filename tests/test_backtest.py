import math
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.backtest import run_backtest_skeleton, allocate_portfolio_pairs


class BacktestSkeletonTests(unittest.TestCase):
    def test_known_answer_single_pair_closed_bar_next_open(self):
        res = run_backtest_skeleton(
            equity=10000.0,
            pairs=[
                {
                    "asset_long": "BTC",
                    "asset_short": "ETH",
                    "entry_price_long": 100.0,
                    "exit_price_long": 110.0,
                    "entry_price_short": 200.0,
                    "exit_price_short": 190.0,
                    "funding_rate_long": 0.0005,
                    "funding_rate_short": 0.001,
                    "position_open_at_settlement": True,
                    "settlement_time": "2026-01-01T16:00:00Z",
                }
            ],
            signal_time="2026-01-01T14:00:00Z",
            next_open_time="2026-01-01T15:00:00Z",
            fee_bps_per_side=5.0,
            slippage_bps_per_side=5.0,
            gross_multiple=1.0,
        )
        # 2 assets total -> notional_per_leg = 10000*1.0/(2*2)=2500
        self.assertAlmostEqual(res["gross_exposure"], 10000.0)
        self.assertAlmostEqual(res["gross_exposure_cap"], 10000.0)
        self.assertAlmostEqual(res["total_price_basis_pnl"], 375.0)
        self.assertAlmostEqual(res["total_funding_cash_flow"], 1.25)
        self.assertAlmostEqual(res["total_fees"], 5.0)
        self.assertAlmostEqual(res["total_slippage"], 5.0)
        self.assertAlmostEqual(res["total_net_pnl"], 366.25)

    def test_two_pairs_cross_pair_gross_cap_enforced(self):
        # Cross-pair gross exposure <= 1.0x equity enforced
        with self.assertRaises(ValueError):
            pairs = []
            for i in range(200):
                pairs.append({
                    "asset_long": f"L{i}",
                    "asset_short": f"S{i}",
                    "entry_price_long": 100.0,
                    "exit_price_long": 100.0,
                    "entry_price_short": 100.0,
                    "exit_price_short": 100.0,
                    "funding_rate_long": 0.0,
                    "funding_rate_short": 0.0,
                })
            run_backtest_skeleton(
                equity=0.01,
                pairs=pairs,
                signal_time="2026-01-01T14:00:00Z",
                next_open_time="2026-01-01T15:00:00Z",
                fee_bps_per_side=0.0,
                slippage_bps_per_side=0.0,
                gross_multiple=1.0,
            )

    def test_sub_cap_allocation_allowed(self):
        res = run_backtest_skeleton(
            equity=10000.0,
            pairs=[
                {
                    "asset_long": "BTC",
                    "asset_short": "ETH",
                    "entry_price_long": 100.0,
                    "exit_price_long": 100.0,
                    "entry_price_short": 100.0,
                    "exit_price_short": 100.0,
                    "funding_rate_long": 0.0,
                    "funding_rate_short": 0.0,
                }
            ],
            signal_time="2026-01-01T14:00:00Z",
            next_open_time="2026-01-01T15:00:00Z",
            fee_bps_per_side=0.0,
            slippage_bps_per_side=0.0,
            gross_multiple=0.5,
        )
        self.assertAlmostEqual(res["gross_exposure"], 5000.0)

    def test_closed_bar_next_open_enforced(self):
        with self.assertRaises(ValueError):
            run_backtest_skeleton(
                equity=10000.0,
                pairs=[
                    {
                        "asset_long": "BTC",
                        "asset_short": "ETH",
                        "entry_price_long": 100.0,
                        "exit_price_long": 100.0,
                        "entry_price_short": 100.0,
                        "exit_price_short": 100.0,
                        "funding_rate_long": 0.0,
                        "funding_rate_short": 0.0,
                    }
                ],
                signal_time="2026-01-01T15:00:00Z",
                next_open_time="2026-01-01T14:00:00Z",
                fee_bps_per_side=0.0,
                slippage_bps_per_side=0.0,
            )

    def test_settlement_before_open_treated_as_missed_funding(self):
        res = run_backtest_skeleton(
            equity=10000.0,
            pairs=[
                {
                    "asset_long": "BTC",
                    "asset_short": "ETH",
                    "entry_price_long": 100.0,
                    "exit_price_long": 110.0,
                    "entry_price_short": 200.0,
                    "exit_price_short": 190.0,
                    "funding_rate_long": 0.001,
                    "funding_rate_short": 0.001,
                    "settlement_time": "2026-01-01T14:30:00Z",  # before next_open
                }
            ],
            signal_time="2026-01-01T14:00:00Z",
            next_open_time="2026-01-01T15:00:00Z",
            fee_bps_per_side=0.0,
            slippage_bps_per_side=0.0,
        )
        self.assertAlmostEqual(res["total_funding_cash_flow"], 0.0)
        self.assertAlmostEqual(res["total_price_basis_pnl"], 375.0)

    def test_funding_separated_from_price(self):
        res = run_backtest_skeleton(
            equity=10000.0,
            pairs=[
                {
                    "asset_long": "BTC",
                    "asset_short": "ETH",
                    "entry_price_long": 100.0,
                    "exit_price_long": 110.0,
                    "entry_price_short": 200.0,
                    "exit_price_short": 190.0,
                    "funding_rate_long": 0.01,
                    "funding_rate_short": -0.01,
                }
            ],
            signal_time="2026-01-01T14:00:00Z",
            next_open_time="2026-01-01T15:00:00Z",
            fee_bps_per_side=0.0,
            slippage_bps_per_side=0.0,
        )
        self.assertAlmostEqual(res["total_price_basis_pnl"], 375.0)
        # funding different from zero
        self.assertNotEqual(res["total_funding_cash_flow"], 0.0)

    def test_duplicate_assets_rejected(self):
        with self.assertRaises(ValueError):
            run_backtest_skeleton(
                equity=10000.0,
                pairs=[
                    {"asset_long": "BTC", "asset_short": "ETH", "entry_price_long": 100, "exit_price_long": 100, "entry_price_short": 100, "exit_price_short": 100, "funding_rate_long": 0, "funding_rate_short": 0},
                    {"asset_long": "BTC", "asset_short": "SOL", "entry_price_long": 100, "exit_price_long": 100, "entry_price_short": 100, "exit_price_short": 100, "funding_rate_long": 0, "funding_rate_short": 0},
                ],
                signal_time="2026-01-01T14:00:00Z",
                next_open_time="2026-01-01T15:00:00Z",
                fee_bps_per_side=0.0,
                slippage_bps_per_side=0.0,
            )

    def test_missing_data_fails_closed(self):
        with self.assertRaises(ValueError):
            run_backtest_skeleton(
                equity=10000.0,
                pairs=[
                    {"asset_long": "BTC", "asset_short": "ETH", "entry_price_long": 100, "exit_price_long": 100, "entry_price_short": 100, "exit_price_short": 100, "funding_rate_long": float("nan"), "funding_rate_short": 0},
                ],
                signal_time="2026-01-01T14:00:00Z",
                next_open_time="2026-01-01T15:00:00Z",
                fee_bps_per_side=0.0,
                slippage_bps_per_side=0.0,
            )
        with self.assertRaises(ValueError):
            run_backtest_skeleton(
                equity=10000.0,
                pairs=[
                    {"asset_long": "BTC", "asset_short": "ETH", "entry_price_long": 0, "exit_price_long": 100, "entry_price_short": 100, "exit_price_short": 100, "funding_rate_long": 0, "funding_rate_short": 0},
                ],
                signal_time="2026-01-01T14:00:00Z",
                next_open_time="2026-01-01T15:00:00Z",
                fee_bps_per_side=0.0,
                slippage_bps_per_side=0.0,
            )

    def test_deterministic(self):
        kwargs = dict(
            equity=10000.0,
            pairs=[
                {
                    "asset_long": "BTC",
                    "asset_short": "ETH",
                    "entry_price_long": 100.0,
                    "exit_price_long": 110.0,
                    "entry_price_short": 200.0,
                    "exit_price_short": 190.0,
                    "funding_rate_long": 0.0005,
                    "funding_rate_short": 0.001,
                }
            ],
            signal_time="2026-01-01T14:00:00Z",
            next_open_time="2026-01-01T15:00:00Z",
            fee_bps_per_side=5.0,
            slippage_bps_per_side=5.0,
        )
        self.assertEqual(run_backtest_skeleton(**kwargs), run_backtest_skeleton(**kwargs))

    def test_allocate_portfolio_pairs(self):
        alloc = allocate_portfolio_pairs(10000.0, ["ETH", "BTC"], gross_multiple=1.0)
        self.assertEqual(sorted(alloc.keys()), ["BTC", "ETH"])


if __name__ == "__main__":
    unittest.main()
