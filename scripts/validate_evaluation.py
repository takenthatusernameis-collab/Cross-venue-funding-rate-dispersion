#!/usr/bin/env python3
"""Offline conformance check for evaluation/split logic (standard library only)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.evaluation import (
    GRID_FAMILY_SIZE,
    bootstrap_confidence_interval,
    block_bootstrap_samples,
    chronological_split_indices,
    holm_bonferroni,
)


def validate_evaluation() -> list[str]:
    errors = []
    # Frozen grid family size is 108 (protocol section 7).
    if GRID_FAMILY_SIZE != 108:
        errors.append("grid family size wrong")
    # Chronological splits are contiguous, ordered, and sum to the total.
    splits = chronological_split_indices(108)
    if splits["discovery"] != slice(0, 65):
        errors.append("discovery slice wrong")
    if splits["validation"] != slice(65, 87):
        errors.append("validation slice wrong")
    if splits["holdout"] != slice(87, 108):
        errors.append("holdout slice wrong")
    # Holm-Bonferroni adjusted p-values are >= raw and capped at 1.0.
    raw = [0.01, 0.02, 0.03, 0.5, 1.0]
    adjusted = holm_bonferroni(raw)
    if len(adjusted) != len(raw):
        errors.append("holm length wrong")
    else:
        for adj, val in zip(adjusted, raw):
            if adj < val or adj > 1.0:
                errors.append("holm adjusted out of range")
                break
    # Deterministic block bootstrap with fixed seed produces identical output.
    returns = [0.01, -0.02, 0.03, -0.01, 0.02] * 10
    s1 = block_bootstrap_samples(returns, 3, 50, seed=7)
    s2 = block_bootstrap_samples(returns, 3, 50, seed=7)
    if s1 != s2:
        errors.append("bootstrap not deterministic")
    if len(s1) != 50:
        errors.append("bootstrap count wrong")
    # Confidence interval bounds are ordered.
    lo, hi = bootstrap_confidence_interval(returns, 3, 100, seed=7)
    if not (lo <= hi):
        errors.append("ci bounds unordered")
    # Fail-closed: split fractions must sum to 1.0.
    try:
        chronological_split_indices(10, discovery_fraction=0.5, validation_fraction=0.3, holdout_fraction=0.1)
        errors.append("split fractions not summing to 1 accepted")
    except ValueError:
        pass
    except Exception as exc:
        errors.append(f"split fractions raised wrong type: {exc}")
    # Fail-closed: negative total rejected.
    try:
        chronological_split_indices(-1)
        errors.append("negative total accepted")
    except ValueError:
        pass
    except Exception as exc:
        errors.append(f"negative total raised wrong type: {exc}")
    return errors


def main() -> int:
    errors = validate_evaluation()
    if errors:
        for e in errors:
            print("FAIL:", e)
        sys.exit(1)
    print("EVALUATION_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
