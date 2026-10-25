#!/usr/bin/env python3
"""Offline conformance check for evaluation/split logic (standard library only)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.evaluation import (
    GRID_FAMILY_SIZE,
    assign_split,
    split_counts,
    wilson_ci_lower_bound,
)


def validate_evaluation() -> list[str]:
    errors = []
    try:
        if split_counts(108) != (65, 22, 21):
            errors.append("split counts wrong")
    except Exception as exc:
        errors.append(f"split counts raised: {exc}")
    try:
        if assign_split(0, 108) != "discovery":
            errors.append("split 0 wrong")
        if assign_split(64, 108) != "discovery":
            errors.append("split 64 wrong")
        if assign_split(65, 108) != "validation":
            errors.append("split 65 wrong")
        if assign_split(86, 108) != "validation":
            errors.append("split 86 wrong")
        if assign_split(87, 108) != "holdout":
            errors.append("split 87 wrong")
        if assign_split(107, 108) != "holdout":
            errors.append("split 107 wrong")
    except Exception as exc:
        errors.append(f"assign split raised: {exc}")
    try:
        if GRID_FAMILY_SIZE != 36:
            errors.append("grid family size wrong")
    except Exception as exc:
        errors.append(f"family size raised: {exc}")
    try:
        lo = wilson_ci_lower_bound(50, 100, 0.95)
        if not (0 < lo < 1):
            errors.append("wilson ci out of range")
    except Exception as exc:
        errors.append(f"wilson raised: {exc}")
    for bad in [(-1, 10), (5, 0), (5, 3), ("x", 10)]:
        try:
            assign_split(*bad)
            errors.append("assign split accepted bad input")
        except (TypeError, ValueError):
            pass
        except Exception as exc:
            errors.append(f"assign split bad input wrong type: {exc}")
    try:
        split_counts(10)
        errors.append("split_counts accepted wrong total")
    except ValueError:
        pass
    except Exception as exc:
        errors.append(f"split_counts wrong total wrong type: {exc}")
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
