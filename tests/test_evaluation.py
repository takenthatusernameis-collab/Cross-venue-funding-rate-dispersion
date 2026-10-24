import math
import unittest
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.evaluation import (
    GRID_FAMILY_SIZE,
    block_bootstrap_samples,
    bootstrap_confidence_interval,
    chronological_split_indices,
    holm_bonferroni,
)


class EvaluationPrimitiveTests(unittest.TestCase):
    def test_grid_family_size_is_108(self):
        self.assertEqual(GRID_FAMILY_SIZE, 108)

    def test_chronological_split_60_20_20(self):
        splits = chronological_split_indices(100)
        self.assertEqual(splits["discovery"].start, 0)
        self.assertEqual(splits["discovery"].stop, 60)
        self.assertEqual(splits["validation"].start, 60)
        self.assertEqual(splits["validation"].stop, 80)
        self.assertEqual(splits["holdout"].start, 80)
        self.assertEqual(splits["holdout"].stop, 100)
        self.assertEqual(splits["discovery"].stop, splits["validation"].start)
        self.assertEqual(splits["validation"].stop, splits["holdout"].start)

    def test_split_boundaries_frozen_and_contiguous(self):
        for total in (10, 50, 101, 1000):
            splits = chronological_split_indices(total)
            self.assertGreater(splits["discovery"].stop, splits["discovery"].start)
            self.assertGreater(splits["validation"].stop, splits["validation"].start)
            self.assertGreater(splits["holdout"].stop, splits["holdout"].start)
            self.assertEqual(splits["discovery"].stop, splits["validation"].start)
            self.assertEqual(splits["validation"].stop, splits["holdout"].start)

    def test_split_rejects_bad_fractions_and_total(self):
        with self.assertRaises(ValueError):
            chronological_split_indices(0)
        with self.assertRaises(ValueError):
            chronological_split_indices(10, discovery_fraction=0.6, validation_fraction=0.2, holdout_fraction=0.1)
        with self.assertRaises(ValueError):
            chronological_split_indices(10, discovery_fraction=1.5)
        with self.assertRaises(ValueError):
            chronological_split_indices(10, discovery_fraction=-0.1)

    def test_holm_known_answer_single_test(self):
        # One test: adjusted p equals raw p (no correction needed).
        self.assertAlmostEqual(holm_bonferroni([0.01])[0], 0.01)

    def test_holm_known_answer_two_tests(self):
        # Raw [0.01, 0.001]; sorted ascending -> 0.001*2=0.002, then 0.01*1=0.01.
        # Output order must match input order: index0=0.01 -> 0.01, index1=0.001 -> 0.002.
        adjusted = holm_bonferroni([0.01, 0.001])
        self.assertAlmostEqual(adjusted[0], 0.01)
        self.assertAlmostEqual(adjusted[1], 0.002)

    def test_holm_monotone_in_sorted_order(self):
        # Step-down enforcement: adjusted values must be non-decreasing when
        # the raw p-values are already ascending.
        raw = [0.001, 0.01, 0.05, 0.2]
        adjusted = holm_bonferroni(raw)
        for previous, current in zip(adjusted, adjusted[1:]):
            self.assertLessEqual(previous, current + 1e-12)

    def test_holm_caps_at_one(self):
        adjusted = holm_bonferroni([0.9, 0.95])
        for value in adjusted:
            self.assertLessEqual(value, 1.0)

    def test_holm_rejects_out_of_range_and_non_finite(self):
        with self.assertRaises(ValueError):
            holm_bonferroni([1.5])
        with self.assertRaises(ValueError):
            holm_bonferroni([-0.1])
        with self.assertRaises(ValueError):
            holm_bonferroni([float("nan")])
        with self.assertRaises(ValueError):
            holm_bonferroni([float("inf")])

    def test_holm_empty_family(self):
        self.assertEqual(holm_bonferroni([]), [])

    def test_bootstrap_is_seeded_and_reproducible(self):
        returns = [0.01, -0.02, 0.015, -0.005, 0.03, -0.01, 0.0, 0.02]
        first = block_bootstrap_samples(returns, block_size=3, n_bootstrap=200, seed=42)
        second = block_bootstrap_samples(returns, block_size=3, n_bootstrap=200, seed=42)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 200)
        for sample in first:
            self.assertTrue(math.isfinite(sample))

    def test_bootstrap_rejects_bad_inputs(self):
        with self.assertRaises(ValueError):
            block_bootstrap_samples([], block_size=2, n_bootstrap=10, seed=1)
        with self.assertRaises(ValueError):
            block_bootstrap_samples([0.1, 0.2], block_size=5, n_bootstrap=10, seed=1)
        with self.assertRaises(ValueError):
            block_bootstrap_samples([0.1, 0.2], block_size=0, n_bootstrap=10, seed=1)
        with self.assertRaises(ValueError):
            block_bootstrap_samples([0.1, 0.2], block_size=2, n_bootstrap=0, seed=1)
        with self.assertRaises(ValueError):
            block_bootstrap_samples([float("nan"), 0.1], block_size=2, n_bootstrap=10, seed=1)

    def test_bootstrap_block_size_one_samples_individual_returns(self):
        # With block_size=1 every block is exactly one element, so every
        # bootstrap draw equals some observed return (start index wraps via
        # randrange, so all indices are reachable).
        returns = [0.1, -0.05, 0.2, 0.0]
        samples = block_bootstrap_samples(returns, block_size=1, n_bootstrap=100, seed=3)
        self.assertEqual(set(samples), set(returns))

    def test_confidence_interval_bounds_ordered(self):
        returns = [0.01, -0.02, 0.015, -0.005, 0.03, -0.01, 0.0, 0.02]
        lower, upper = bootstrap_confidence_interval(returns, block_size=3, n_bootstrap=500, seed=11, alpha=0.05)
        self.assertLessEqual(lower, upper)
        self.assertTrue(math.isfinite(lower) and math.isfinite(upper))

    def test_confidence_interval_rejects_bad_alpha(self):
        with self.assertRaises(ValueError):
            bootstrap_confidence_interval([0.1, 0.2], block_size=1, n_bootstrap=10, seed=1, alpha=0.0)
        with self.assertRaises(ValueError):
            bootstrap_confidence_interval([0.1, 0.2], block_size=1, n_bootstrap=10, seed=1, alpha=1.0)


if __name__ == "__main__":
    unittest.main()