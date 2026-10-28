import math
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.accounting import execution_cost, funding_cash_flow, price_pnl
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

    def test_cross_pair_gross_cap_satisfied_by_construction(self):
        # Allocation normalizes by pair count, so gross exposure is exactly
        # equity*gross_multiple by construction and never exceeds the cap,
        # regardless of how many equal-notional pairs are requested.
        for pair_count in (1, 2, 5, 50, 500):
            pairs = [
                {
                    "asset_long": f"L{i}",
                    "asset_short": f"S{i}",
                    "entry_price_long": 100.0,
                    "exit_price_long": 100.0,
                    "entry_price_short": 100.0,
                    "exit_price_short": 100.0,
                    "funding_rate_long": 0.0,
                    "funding_rate_short": 0.0,
                }
                for i in range(pair_count)
            ]
            res = run_backtest_skeleton(
                equity=10000.0,
                pairs=pairs,
                signal_time="2026-01-01T14:00:00Z",
                next_open_time="2026-01-01T15:00:00Z",
                fee_bps_per_side=0.0,
                slippage_bps_per_side=0.0,
                gross_multiple=0.7,
            )
            self.assertAlmostEqual(res["gross_exposure"], 10000.0 * 0.7, places=9)
            self.assertAlmostEqual(res["gross_exposure_cap"], 10000.0 * 0.7, places=9)
            self.assertLessEqual(res["gross_exposure"], res["gross_exposure_cap"] + 1e-12)

    def test_cross_pair_gross_cap_violation_fails_closed(self):
        # If a caller bypasses the allocation and supplies notionals that would
        # exceed the 1.0x hard cap, the pair ledger must reject it fail-closed.
        from cross_venue_funding_dispersion.pair_pnl import compute_pair_pnl

        with self.assertRaises(ValueError):
            compute_pair_pnl(
                equity=1000.0,
                notional_per_leg=1000.0,  # 2x notional on one leg => 2.0x gross exposure
                entry_price_long=100.0,
                exit_price_long=100.0,
                entry_price_short=100.0,
                exit_price_short=100.0,
                funding_rate_long=0.0,
                funding_rate_short=0.0,
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


class BacktestAggregationRecomputeTests(unittest.TestCase):
    """Source-independent red-team tests (red-team audit #8).

    Independently recompute the cross-pair aggregate totals and each pair
    ledger from the RAW pair inputs via the accounting primitives
    (price_pnl / funding_cash_flow / execution_cost), using the documented
    allocation formula, then compare against run_backtest_skeleton's totals.
    This cross-checks the engine's total_* rollup and per-pair ledger so a
    sign/indexing/aggregation bug cannot hide behind compute_pair_pnl.
    """

    @staticmethod
    def _pairs():
        return [
            {
                "asset_long": "BTC",
                "asset_short": "ETH",
                "entry_price_long": 100.0,
                "exit_price_long": 110.0,
                "entry_price_short": 200.0,
                "exit_price_short": 190.0,
                "funding_rate_long": 0.0005,
                "funding_rate_short": 0.001,
            },
            {
                "asset_long": "SOL",
                "asset_short": "AVAX",
                "entry_price_long": 50.0,
                "exit_price_long": 45.0,
                "entry_price_short": 70.0,
                "exit_price_short": 75.0,
                "funding_rate_long": -0.001,
                "funding_rate_short": 0.0002,
            },
            {
                "asset_long": "LINK",
                "asset_short": "XRP",
                "entry_price_long": 5.0,
                "exit_price_long": 8.0,
                "entry_price_short": 0.4,
                "exit_price_short": 0.35,
                "funding_rate_long": 0.002,
                "funding_rate_short": -0.0015,
                "position_open_at_settlement": False,
            },
        ]

    def setUp(self):
        self.equity = 10000.0
        self.fee = 5.0
        self.slip = 5.0
        self.gross_multiple = 1.0
        self.fills_per_leg = 2
        self.res = run_backtest_skeleton(
            equity=self.equity,
            pairs=self._pairs(),
            signal_time="2026-01-01T14:00:00Z",
            next_open_time="2026-01-01T15:00:00Z",
            fee_bps_per_side=self.fee,
            slippage_bps_per_side=self.slip,
            gross_multiple=self.gross_multiple,
        )
        self.n_assets = len(self.res["pairs"]) * 2
        self.notional = self.equity * self.gross_multiple / (2.0 * self.n_assets)

    def _independent_pair_ledger(self, pair, open_at_settlement):
        notional = self.notional
        gross_fills = 2 * self.fills_per_leg
        long_price_pnl = price_pnl(1, notional, pair["entry_price_long"], pair["exit_price_long"])
        short_price_pnl = price_pnl(-1, notional, pair["entry_price_short"], pair["exit_price_short"])
        net_price_basis_pnl = long_price_pnl + short_price_pnl
        if open_at_settlement:
            funding = (
                funding_cash_flow(1, notional, pair["funding_rate_long"])
                + funding_cash_flow(-1, notional, pair["funding_rate_short"])
            )
        else:
            funding = 0.0
        fees = execution_cost(notional, self.fee, 0.0) * gross_fills
        slippage = execution_cost(notional, 0.0, self.slip) * gross_fills
        total_net_pnl = net_price_basis_pnl + funding - fees - slippage
        return {
            "long_price_pnl": long_price_pnl,
            "short_price_pnl": short_price_pnl,
            "net_price_basis_pnl": net_price_basis_pnl,
            "funding_cash_flow": funding,
            "fees": fees,
            "slippage": slippage,
            "total_net_pnl": total_net_pnl,
        }

    def test_cross_pair_totals_match_independent_recompute(self):
        independent = {
            "total_net_pnl": 0.0,
            "total_price_basis_pnl": 0.0,
            "total_funding_cash_flow": 0.0,
            "total_fees": 0.0,
            "total_slippage": 0.0,
        }
        for pair, item in zip(self._pairs(), self.res["pairs"]):
            open_at_settlement = bool(pair.get("position_open_at_settlement", True))
            ledger = self._independent_pair_ledger(pair, open_at_settlement)
            independent["total_net_pnl"] += ledger["total_net_pnl"]
            independent["total_price_basis_pnl"] += ledger["net_price_basis_pnl"]
            independent["total_funding_cash_flow"] += ledger["funding_cash_flow"]
            independent["total_fees"] += ledger["fees"]
            independent["total_slippage"] += ledger["slippage"]
            for key in ("net_price_basis_pnl", "funding_cash_flow", "fees", "slippage", "total_net_pnl"):
                self.assertAlmostEqual(
                    item["ledger"][key], ledger[key], places=9,
                    msg=f"{pair['asset_long']}/{pair['asset_short']} {key}",
                )
            self.assertAlmostEqual(item["ledger"]["gross_exposure"], 2 * self.notional, places=9)
            self.assertAlmostEqual(item["ledger"]["gross_exposure_cap"], self.equity * self.gross_multiple, places=9)
        for key in independent:
            self.assertAlmostEqual(independent[key], self.res[key], places=9, msg=f"cross-pair {key} mismatch")

    def test_additive_identity_holds_across_pairs(self):
        expected = (
            self.res["total_price_basis_pnl"]
            + self.res["total_funding_cash_flow"]
            - self.res["total_fees"]
            - self.res["total_slippage"]
        )
        self.assertAlmostEqual(expected, self.res["total_net_pnl"], places=9)

    def test_cross_pair_gross_exposure_cap_and_allocation(self):
        self.assertEqual(len(self.res["pairs"]), 3)
        for item in self.res["pairs"]:
            self.assertAlmostEqual(item["notional_per_leg"], self.notional, places=9)
        self.assertAlmostEqual(self.res["gross_exposure"], self.equity * self.gross_multiple, places=9)
        self.assertAlmostEqual(self.res["gross_exposure_cap"], self.equity * self.gross_multiple, places=9)
        self.assertLessEqual(self.res["gross_exposure"], self.res["gross_exposure_cap"] + 1e-12)
        self.assertAlmostEqual(self.notional, self.equity * self.gross_multiple / (2 * self.n_assets), places=9)

    def test_missed_settlement_zero_funding_independent_of_nonzero_rates(self):
        closed = self.res["pairs"][2]
        self.assertEqual(closed["asset_long"], "LINK")
        self.assertEqual(closed["asset_short"], "XRP")
        self.assertAlmostEqual(closed["ledger"]["funding_cash_flow"], 0.0, places=12)
        pair = self._pairs()[2]
        self.assertNotAlmostEqual(pair["funding_rate_long"], 0.0, places=12)
        self.assertNotAlmostEqual(pair["funding_rate_short"], 0.0, places=12)
        raw_funding = (
            funding_cash_flow(1, self.notional, pair["funding_rate_long"])
            + funding_cash_flow(-1, self.notional, pair["funding_rate_short"])
        )
        self.assertNotAlmostEqual(raw_funding, 0.0, places=12)


if __name__ == "__main__":
    unittest.main()
