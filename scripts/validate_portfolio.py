#!/usr/bin/env python3
"""Offline conformance check for portfolio construction (standard library only)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.portfolio import build_portfolio


def validate_portfolio() -> list[str]:
    errors = []
    try:
        p = build_portfolio(signals=[{"asset": "A", "signal": 1.0}], max_positions=1, long_short=True)
        if "positions" not in p or "gross_exposure" not in p:
            errors.append("portfolio missing keys")
    except Exception as exc:
        errors.append(f"portfolio basic raised: {exc}")
    try:
        build_portfolio(signals=[], max_positions=0, long_short=True)
        errors.append("zero max_positions accepted")
    except ValueError:
        pass
    except Exception as exc:
        errors.append(f"zero max_positions raised wrong type: {exc}")
    try:
        build_portfolio(signals="bad", max_positions=1, long_short=True)
        errors.append("bad signals accepted")
    except (TypeError, ValueError):
        pass
    except Exception as exc:
        errors.append(f"bad signals raised wrong type: {exc}")
    return errors


def main() -> int:
    errors = validate_portfolio()
    if errors:
        for e in errors:
            print("FAIL:", e)
        sys.exit(1)
    print("PORTFOLIO_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
