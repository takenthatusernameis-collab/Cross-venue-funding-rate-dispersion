import math
import unittest
from datetime import date, datetime, timezone

from cross_venue_funding_dispersion.backtest import run_backtest_skeleton
from cross_venue_funding_dispersion.signals import (
    dispersion_from_venue_histories,
    linear_quantile,
    normalize_funding_rate,
    prior_daily_threshold,
    select_top_dispersion,
    time_weighted_mean,
)


class AnchorFVD053SmokeTests(unittest.TestCase):
    def test_fvd053_anchor_end_to_end_known_answer(self):
        # 1) Causal normalize (linear 8h normalization)
        self.assertAlmostEqual(normalize_funding_rate(0.00025, 1.0), 0.002)
        self.assertAlmostEqual(normalize_funding_rate(0.0005, 8.0), 0.0005)

        # 2) Time-weighted mean over a 1h window with piecewise-constant rates
        obs = [
            {"timestamp": "2026-01-01T00:00:00Z", "rate_8h": 0.0001},
            {"timestamp": "2026-01-01T00:30:00Z", "rate_8h": 0.0003},
        ]
        mean = time_weighted_mean(obs, "2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z", max_staleness_hours=24)
        self.assertAlmostEqual(mean, 0.0002)

        # 3) Dispersion from venue histories (population std dev)
        histories = {
            "A": [{"timestamp": "2026-01-01T00:00:00Z", "rate_8h": 0.0001}],
            "B": [{"timestamp": "2026-01-01T00:00:00Z", "rate_8h": 0.0002}],
            "C": [{"timestamp": "2026-01-01T00:00:00Z", "rate_8h": 0.0003}],
        }
        disp, means = dispersion_from_venue_histories(
            histories, "2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z", minimum_venues=2, max_staleness_hours=24
        )
        self.assertAlmostEqual(disp, math.sqrt((( -0.0001)**2 + 0**2 + 0.0001**2)/3))
        self.assertEqual(set(means.keys()), {"A", "B", "C"})

        # 4) Prior-daily threshold (latest <=23:00 UTC per prior date)
        samples = [
            {"date": "2025-12-31", "snapshot_time_utc": "22:00:00", "dispersion": 0.0010},
            {"date": "2025-12-30", "snapshot_time_utc": "23:00:00", "dispersion": 0.0020},
            {"date": "2025-12-29", "snapshot_time_utc": "23:05:00", "dispersion": 0.0030},  # excluded (>23:00)
            {"date": "2026-01-01", "snapshot_time_utc": "12:00:00", "dispersion": 0.0099},  # excluded (current date)
        ]
        thr = prior_daily_threshold(samples, "2026-01-01", 50.0, lookback_days=90, minimum_observations=2)
        self.assertAlmostEqual(thr, 0.0015)

        # 5) Select top dispersion tail above threshold
        sel = select_top_dispersion({"BTC": 0.0025, "ETH": 0.0012, "SOL": 0.0010}, thr, 0.5)
        self.assertEqual(sel, ["BTC"])

        # 6) Backtest skeleton with closed-bar/next-open, settlement-timed funding,
        #    funding sign conventions, price/basis separation, 1.0x gross cap
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
                    "funding_rate_long": 0.0005,  # longs pay when positive
                    "funding_rate_short": 0.0010,  # shorts receive when positive
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
        self.assertAlmostEqual(res["gross_exposure"], 10000.0)
        self.assertAlmostEqual(res["gross_exposure_cap"], 10000.0)
        # net = price_basis_pnl + funding - fees - slippage = 375 + 1.25 - 5 - 5 = 366.25
        self.assertAlmostEqual(res["total_price_basis_pnl"], 375.0)
        self.assertAlmostEqual(res["total_funding_cash_flow"], 1.25)
        self.assertAlmostEqual(res["total_fees"], 5.0)
        self.assertAlmostEqual(res["total_slippage"], 5.0)
        self.assertAlmostEqual(res["total_net_pnl"], 366.25)

        # 7) Gross-exposure fail-closed cap
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
                signal_time="2026-01-01T14:00:00Z",
                next_open_time="2026-01-01T15:00:00Z",
                fee_bps_per_side=0.0,
                slippage_bps_per_side=0.0,
                gross_multiple=1.5,  # > 1.0 not allowed
            )
