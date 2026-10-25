#!/usr/bin/env python3
"""Offline conformance check for funding-dispersion signal construction (standard library only)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.signals import compute_funding_dispersion


def validate_signals() -> list[str]:
    errors = []
    try:
        s = compute_funding_dispersion([0.01, 0.02, 0.03])
        if "mean" not in s or "spread" not in s or "zscore" not in s or "signal" not in s:
            errors.append("missing signal fields")
        if s["mean"] != 0.02:
            errors.append("mean wrong")
        if s["spread"] != 0.02:
            errors.append("spread wrong")
    except Exception as exc:
        errors.append(f"signals basic raised: {exc}")
    try:
        compute_funding_dispersion([])
        errors.append("empty list accepted")
    except ValueError:
        pass
    except Exception as exc:
        errors.append(f"empty list raised wrong type: {exc}")
    try:
        compute_funding_dispersion([0.01, float("nan")])
        errors.append("nan accepted")
    except ValueError:
        pass
    except Exception as exc:
        errors.append(f"nan raised wrong type: {exc}")
    try:
        compute_funding_dispersion("bad")
        errors.append("bad type accepted")
    except (TypeError, ValueError):
        pass
    except Exception as exc:
        errors.append(f"bad type raised wrong type: {exc}")
    return errors


def main() -> int:
    errors = validate_signals()
    if errors:
        for e in errors:
            print("FAIL:", e)
        sys.exit(1)
    print("SIGNALS_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
