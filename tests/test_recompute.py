"""Known-answer and adversarial tests for the independent recomputation verifier."""
import unittest

from cross_venue_funding_dispersion.recompute import (
    attribution_check,
    recompute_ledger_totals,
    verify_artifact_consistency,
)


def _record(net=1.0, funding=0.1, fees=0.05, slippage=0.02, basis=0.9, gross=100.0, n_pairs=1):
    return {
        "total_net_pnl": net,
        "total_funding_cash_flow": funding,
        "total_fees": fees,
        "total_slippage": slippage,
        "total_price_basis_pnl": basis,
        "gross_exposure": gross,
        "n_pairs": n_pairs,
    }


class RecomputeTests(unittest.TestCase):
    def test_sums_constituent_parts(self):
        totals = recompute_ledger_totals([_record(), _record(net=2.0, n_pairs=2)])
        self.assertEqual(totals["n_configs"], 2)
        self.assertEqual(totals["n_pairs"], 3)
        self.assertAlmostEqual(totals["total_net_pnl"], 3.0)
        self.assertAlmostEqual(totals["total_funding_cash_flow"], 0.2)
        self.assertAlmostEqual(totals["total_fees"], 0.1)
        self.assertAlmostEqual(totals["total_slippage"], 0.04)
        self.assertAlmostEqual(totals["total_price_basis_pnl"], 1.8)
        self.assertAlmostEqual(totals["gross_exposure"], 200.0)

    def test_empty_and_non_list_fail_closed(self):
        for bad in ([], "not-a-list", None):
            with self.assertRaises(ValueError):
                recompute_ledger_totals(bad)

    def test_missing_field_and_non_dict_fail_closed(self):
        rec = _record()
        del rec["total_fees"]
        with self.assertRaises(ValueError):
            recompute_ledger_totals([rec])
        with self.assertRaises(ValueError):
            recompute_ledger_totals([{"n_pairs": 1}])
        with self.assertRaises(ValueError):
            recompute_ledger_totals(["not-a-dict"])

    def test_non_integer_n_pairs_fail_closed(self):
        base = {k: v for k, v in _record().items() if k != "n_pairs"}
        for bad_n in (1.5, -1, True, 0.5):
            with self.assertRaises(ValueError):
                recompute_ledger_totals([{**base, "n_pairs": bad_n}])

    def test_non_finite_record_value_fail_closed(self):
        rec = _record()
        rec["total_net_pnl"] = float("nan")
        with self.assertRaises(ValueError):
            recompute_ledger_totals([rec])

    def test_verify_consistent(self):
        records = [_record(net=1.0, basis=0.9, n_pairs=1)]
        published = recompute_ledger_totals(records)
        artifact = {"records": records, "published": published}
        result = verify_artifact_consistency(artifact)
        self.assertTrue(result["consistent"])
        self.assertEqual(result["mismatches"], [])
        for delta in result["deltas"].values():
            self.assertEqual(delta, 0.0)

    def test_verify_detects_mismatch(self):
        records = [_record(net=1.0)]
        published = recompute_ledger_totals(records)
        published["total_net_pnl"] = 2.0
        artifact = {"records": records, "published": published}
        result = verify_artifact_consistency(artifact)
        self.assertFalse(result["consistent"])
        self.assertIn("total_net_pnl", result["mismatches"])

    def test_verify_tolerance_window(self):
        records = [_record(net=1.0)]
        published = recompute_ledger_totals(records)
        published["total_fees"] += 1e-12
        artifact = {"records": records, "published": published}
        result = verify_artifact_consistency(artifact, tolerance=1e-9)
        self.assertTrue(result["consistent"])
        result_strict = verify_artifact_consistency(artifact, tolerance=1e-13)
        self.assertFalse(result_strict["consistent"])

    def test_verify_missing_fields_fail_closed(self):
        records = [_record()]
        published = recompute_ledger_totals(records)
        for bad in [
            {},
            {"records": records},
            {"published": published},
            {"records": "not-a-list", "published": published},
            {"records": [], "published": published},
            {"records": records, "published": "not-a-dict"},
            {"records": records, "published": {}}:
        ]:
            with self.assertRaises(ValueError):
                verify_artifact_consistency(bad)

    def test_verify_bad_tolerance_fail_closed(self):
        records = [_record()]
        published = recompute_ledger_totals(records)
        artifact = {"records": records, "published": published}
        for bad_tol in (float("nan"), -1.0, "x"):
            with self.assertRaises(ValueError):
                verify_artifact_consistency(artifact, tolerance=bad_tol)

    def test_attribution_known_answer(self):
        # net = basis + funding - fees - slippage
        records = [_record(net=1.03, funding=0.1, fees=0.05, slippage=0.02, basis=0.95)]
        published = recompute_ledger_totals(records)
        artifact = {"records": records, "published": published}
        result = attribution_check(artifact)
        self.assertTrue(result["consistent"])
        self.assertAlmostEqual(result["derived_total_net_pnl"], 1.03)

    def test_attribution_detects_mismatch(self):
        records = [_record(net=1.0, funding=0.1, fees=0.05, slippage=0.02, basis=0.95)]
        published = recompute_ledger_totals(records)
        published["total_net_pnl"] = 99.0  # inconsistent decomposition
        artifact = {"records": records, "published": published}
        result = attribution_check(artifact)
        self.assertFalse(result["consistent"])

    def test_attribution_missing_fields_fail_closed(self):
        records = [_record()]
        published = recompute_ledger_totals(records)
        del published["total_fees"]
        with self.assertRaises(ValueError):
            attribution_check({"records": records, "published": published})
        with self.assertRaises(ValueError):
            attribution_check("not-a-dict")
        with self.assertRaises(ValueError):
            attribution_check({"records": records})  # missing published
        with self.assertRaises(ValueError):
            attribution_check({"published": {}})  # missing records not required here but bad shape


if __name__ == "__main__":
    unittest.main()