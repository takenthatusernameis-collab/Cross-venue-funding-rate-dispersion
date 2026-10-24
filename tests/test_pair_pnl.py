import math
import unittest
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.pair_pnl import compute_pair_pnl


class PairPnLTests(unittest.TestCase):
    def test_attributed_ledger_known_answer(self):
        ledger = compute_pair_pnl(
            equity=10000.0,
            notional_per_leg=5000.0,
            entry_price_long=100.0,
            exit_price_long=110.0,
            entry_price_short=200.0,
            exit_price_short=190.0,
            funding_rate_long=0.0005,
            funding_rate_short=0.001,
            fee_bps_per_side=5.0,
            slippage_bps_per_side=5.0,
            gross_multiple=1.0,
            position_open_at_settlement=True,
            fills_per_leg=2,
        )
        self.assertAlmostEqual(ledger["long_price_pnl"], 500.0)
        self.assertAlmostEqual(ledger["short_price_pnl"], 250.0)
        self.assertAlmostEqual(ledger["net_price_basis_pnl"], 750.0)
        # long pays 2.5, short receives 5.0 -> net +2.5 carry
        self.assertAlmostEqual(ledger["funding_cash_flow"], 2.5)
        # 4 fills (2 legs x 2 fills), 5 bps each
        self.assertAlmostEqual(ledger["fees"], 10.0)
        self.assertAlmostEqual(ledger["slippage"], 10.0)
        self.assertAlmostEqual(ledger["total_net_pnl"], 732.5)
        self.assertAlmostEqual(ledger["gross_exposure"], 10000.0)
        self.assertAlmostEqual(ledger["gross_exposure_cap"], 10000.0)

    def test_gross_exposure_hard_cap_rejected(self):
        with self.assertRaises(ValueError):
            compute_pair_pnl(
                equity=10000.0,
                notional_per_leg=6000.0,
                entry_price_long=100.0,
                exit_price_long=110.0,
                entry_price_short=200.0,
                exit_price_short=190.0,
                funding_rate_long=0.0,
                funding_rate_short=0.0,
                fee_bps_per_side=0.0,
                slippage_bps_per_side=0.0,
                gross_multiple=1.0,
            )

    def test_gross_exposure_exact_cap_allowed(self):
        ledger = compute_pair_pnl(
            equity=10000.0,
            notional_per_leg=5000.0,
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
        self.assertAlmostEqual(ledger["total_net_pnl"], 0.0)
        self.assertAlmostEqual(ledger["gross_exposure"], 10000.0)

    def test_missed_settlement_pays_zero_funding(self):
        filled = compute_pair_pnl(
            equity=10000.0,
            notional_per_leg=5000.0,
            entry_price_long=100.0,
            exit_price_long=110.0,
            entry_price_short=200.0,
            exit_price_short=190.0,
            funding_rate_long=0.0005,
            funding_rate_short=0.001,
            fee_bps_per_side=5.0,
            slippage_bps_per_side=5.0,
            position_open_at_settlement=True,
        )
        missed = compute_pair_pnl(
            equity=10000.0,
            notional_per_leg=5000.0,
            entry_price_long=100.0,
            exit_price_long=110.0,
            entry_price_short=200.0,
            exit_price_short=190.0,
            funding_rate_long=0.0005,
            funding_rate_short=0.001,
            fee_bps_per_side=5.0,
            slippage_bps_per_side=5.0,
            position_open_at_settlement=False,
        )
        self.assertEqual(missed["funding_cash_flow"], 0.0)
        self.assertAlmostEqual(missed["total_net_pnl"], filled["total_net_pnl"] - filled["funding_cash_flow"])
        # Price and cost fields unchanged; only funding differs.
        self.assertEqual(missed["long_price_pnl"], filled["long_price_pnl"])
        self.assertEqual(missed["short_price_pnl"], filled["short_price_pnl"])
        self.assertEqual(missed["fees"], filled["fees"])
        self.assertEqual(missed["slippage"], filled["slippage"])

    def test_funding_sign_conventions(self):
        # Positive rate: long pays, short receives.
        ledger = compute_pair_pnl(
            equity=10000.0,
            notional_per_leg=1000.0,
            entry_price_long=100.0,
            exit_price_long=100.0,
            entry_price_short=100.0,
            exit_price_short=100.0,
            funding_rate_long=0.001,
            funding_rate_short=0.001,
            fee_bps_per_side=0.0,
            slippage_bps_per_side=0.0,
        )
        self.assertEqual(ledger["funding_cash_flow"], -1.0 + 1.0)
        # Negative rate: long receives, short pays.
        ledger = compute_pair_pnl(
            equity=10000.0,
            notional_per_leg=1000.0,
            entry_price_long=100.0,
            exit_price_long=100.0,
            entry_price_short=100.0,
            exit_price_short=100.0,
            funding_rate_long=-0.001,
            funding_rate_short=-0.001,
            fee_bps_per_side=0.0,
            slippage_bps_per_side=0.0,
        )
        self.assertEqual(ledger["funding_cash_flow"], 1.0 - 1.0)

    def test_price_basis_pnl_separated_from_funding(self):
        base = compute_pair_pnl(
            equity=10000.0,
            notional_per_leg=5000.0,
            entry_price_long=100.0,
            exit_price_long=110.0,
            entry_price_short=200.0,
            exit_price_short=190.0,
            funding_rate_long=0.0,
            funding_rate_short=0.0,
            fee_bps_per_side=0.0,
            slippage_bps_per_side=0.0,
        )
        shifted = compute_pair_pnl(
            equity=10000.0,
            notional_per_leg=5000.0,
            entry_price_long=100.0,
            exit_price_long=110.0,
            entry_price_short=200.0,
            exit_price_short=190.0,
            funding_rate_long=0.005,
            funding_rate_short=-0.005,
            fee_bps_per_side=0.0,
            slippage_bps_per_side=0.0,
        )
        # Price PnL fields are identical; only funding and total differ.
        self.assertEqual(base["long_price_pnl"], shifted["long_price_pnl"])
        self.assertEqual(base["short_price_pnl"], shifted["short_price_pnl"])
        self.assertEqual(base["net_price_basis_pnl"], shifted["net_price_basis_pnl"])
        self.assertNotEqual(base["funding_cash_flow"], shifted["funding_cash_flow"])
        self.assertNotEqual(base["total_net_pnl"], shifted["total_net_pnl"])

    def test_per_leg_per_fill_cost_scaling(self):
        default = compute_pair_pnl(
            equity=10000.0,
            notional_per_leg=5000.0,
            entry_price_long=100.0,
            exit_price_long=100.0,
            entry_price_short=100.0,
            exit_price_short=100.0,
            funding_rate_long=0.0,
            funding_rate_short=0.0,
            fee_bps_per_side=10.0,
            slippage_bps_per_side=10.0,
            fills_per_leg=2,
        )
        doubled = compute_pair_pnl(
            equity=10000.0,
            notional_per_leg=5000.0,
            entry_price_long=100.0,
            exit_price_long=100.0,
            entry_price_short=100.0,
            exit_price_short=100.0,
            funding_rate_long=0.0,
            funding_rate_short=0.0,
            fee_bps_per_side=10.0,
            slippage_bps_per_side=10.0,
            fills_per_leg=4,
        )
        self.assertAlmostEqual(doubled["fees"], 2 * default["fees"])
        self.assertAlmostEqual(doubled["slippage"], 2 * default["slippage"])

    def test_zero_notional_and_equity(self):
        ledger = compute_pair_pnl(
            equity=0.0,
            notional_per_leg=0.0,
            entry_price_long=100.0,
            exit_price_long=100.0,
            entry_price_short=100.0,
            exit_price_short=100.0,
            funding_rate_long=0.001,
            funding_rate_short=0.001,
            fee_bps_per_side=5.0,
            slippage_bps_per_side=5.0,
        )
        for value in ledger.values():
            self.assertAlmostEqual(value, 0.0)

    def test_sub_cap_gross_multiple_allowed(self):
        ledger = compute_pair_pnl(
            equity=10000.0,
            notional_per_leg=2000.0,
            entry_price_long=100.0,
            exit_price_long=100.0,
            entry_price_short=100.0,
            exit_price_short=100.0,
            funding_rate_long=0.0,
            funding_rate_short=0.0,
            fee_bps_per_side=0.0,
            slippage_bps_per_side=0.0,
            gross_multiple=0.5,
        )
        self.assertAlmostEqual(ledger["gross_exposure"], 4000.0)
        self.assertAlmostEqual(ledger["gross_exposure_cap"], 5000.0)

    def test_deterministic(self):
        kwargs = dict(
            equity=10000.0,
            notional_per_leg=5000.0,
            entry_price_long=100.0,
            exit_price_long=110.0,
            entry_price_short=200.0,
            exit_price_short=190.0,
            funding_rate_long=0.0005,
            funding_rate_short=0.001,
            fee_bps_per_side=5.0,
            slippage_bps_per_side=5.0,
        )
        self.assertEqual(compute_pair_pnl(**kwargs), compute_pair_pnl(**kwargs))

    def test_invalid_inputs_rejected(self):
        base = dict(
            equity=10000.0,
            notional_per_leg=5000.0,
            entry_price_long=100.0,
            exit_price_long=110.0,
            entry_price_short=200.0,
            exit_price_short=190.0,
            funding_rate_long=0.0005,
            funding_rate_short=0.001,
            fee_bps_per_side=5.0,
            slippage_bps_per_side=5.0,
        )
        invalid = [
            dict(base, equity=-1.0),
            dict(base, notional_per_leg=-1.0),
            dict(base, equity=float("nan")),
            dict(base, entry_price_long=0.0),
            dict(base, exit_price_short=float("inf")),
            dict(base, entry_price_short=float("nan")),
            dict(base, funding_rate_long=float("nan")),
            dict(base, funding_rate_short=float("inf")),
            dict(base, fee_bps_per_side=-1.0),
            dict(base, slippage_bps_per_side=float("nan")),
            dict(base, gross_multiple=1.1),
            dict(base, gross_multiple=-0.1),
            dict(base, gross_multiple=float("nan")),
            dict(base, fills_per_leg=0),
            dict(base, fills_per_leg=-1),
            dict(base, fills_per_leg=True),
            dict(base, fills_per_leg=2.5),
        ]
        for kwargs in invalid:
            with self.assertRaises(ValueError, msg=kwargs):
                compute_pair_pnl(**kwargs)


if __name__ == "__main__":
    unittest.main()
