"""Offline conformance check for evaluation primitives (standard library only)."""
import math
import sys

from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.evaluation import (
    GRID_FAMILY_SIZE, chronological_split_indices, holm_bonferroni,
    block_bootstrap_samples, bootstrap_confidence_interval,
)


def check(cond, msg):
    if not cond:
        print("FAIL:", msg)
        sys.exit(1)


def main():
    check(GRID_FAMILY_SIZE == 108, "grid family size")

    splits = chronological_split_indices(108)
    check(splits["discovery"] == slice(0, 65), "discovery slice")
    check(splits["validation"] == slice(65, 87), "validation slice")
    check(splits["holdout"] == slice(87, 108), "holdout slice")

    # bad inputs fail-closed
    for args in [dict(total=0), dict(total=1.0), dict(total=True),
                 dict(total=5, discovery_fraction=0.5, validation_fraction=0.3, holdout_fraction=0.3)]:
        try:
            chronological_split_indices(**args)
            check(False, "bad split accepted")
        except ValueError:
            pass

    # holm known answer
    adj = holm_bonferroni([0.01, 0.02, 0.03])
    check(all(isinstance(x, float) for x in adj), "holm types")
    check(all(0 <= x <= 1 for x in adj), "holm range")
    for bad in [[1.1], [-0.1], [float("nan")], [float("inf")]]:
        try:
            holm_bonferroni(bad)
            check(False, "bad holm accepted")
        except ValueError:
            pass
    check(holm_bonferroni([]) == [], "holm empty")

    # bootstrap reproducibility
    returns = [0.01, -0.02, 0.015, -0.005, 0.02]
    a = block_bootstrap_samples(returns, block_size=2, n_bootstrap=3, seed=7)
    b = block_bootstrap_samples(returns, block_size=2, n_bootstrap=3, seed=7)
    check(a == b, "bootstrap reproducibility")
    for bad in [dict(block_size=0), dict(n_bootstrap=0), dict(block_size=1, returns=[float("nan")])]:
        try:
            block_bootstrap_samples(returns if "returns" not in bad else bad["returns"],
                                   block_size=bad.get("block_size", 2),
                                   n_bootstrap=bad.get("n_bootstrap", 3), seed=7)
            check(False, "bad bootstrap accepted")
        except ValueError:
            pass

    # confidence interval
    samples = [0.1, 0.2, 0.3, 0.4, 0.5]
    lo, hi = bootstrap_confidence_interval([0.1,0.2,0.3,0.4,0.5], 2, 5, seed=7, alpha=0.1)
    check(lo <= hi, "ci ordered")
    try:
        bootstrap_confidence_interval([0.1,0.2,0.3], 1, 2, seed=1, alpha=0.0)
        check(False, "bad alpha accepted")
    except ValueError:
        pass

    print("EVALUATION_VALIDATION=PASS")


if __name__ == "__main__":
    main()
