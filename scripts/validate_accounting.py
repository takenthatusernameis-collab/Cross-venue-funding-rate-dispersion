#!/usr/bin/env python3
"""Offline conformance check for funding settlement accounting (standard library only)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.accounting import apply_funding_settlement


def validate_accounting() -> list[str]:
    errors = []
    try:
        res = apply_funding_settlement(notional=100.0, funding_rate=0.01, position_open_at_settlement=True)
        if res["funding_cash_flow"] != 1.0 or res["settled"] is not True:
            errors.append("long funding sign/cash flow wrong")
        res2 = apply_funding_settlement(notional=100.0, funding_rate=0.01, position_open_at_settlement=True, side="short")
        if res2["funding_cash_flow"] != -1.0:
            errors.append("short funding sign wrong")
    except Exception as exc:
        errors.append(f"accounting basic raised: {exc}")
    try:
        res3 = apply_funding_settlement(notional=100.0, funding_rate=0.01, position_open_at_settlement=False)
        if res3["funding_cash_flow"] != 0.0 or res3["settled"] is not False:
            errors.append("missed settlement should pay zero")
    except Exception as exc:
        errors.append(f"missed settlement raised: {exc}")
    for bad in [
        dict(notional=0.0, funding_rate=0.01, position_open_at_settlement=True),
        dict(notional=100.0, funding_rate=0.01, position_open_at_settlement=True, side="bad"),
        dict(notional=-1.0, funding_rate=0.01, position_open_at_settlement=True),
    ]:
        try:
            apply_funding_settlement(**bad)
            errors.append("invalid input accepted")
        except ValueError:
            pass
        except Exception as exc:
            errors.append(f"invalid input raised wrong type: {exc}")
    return errors


def main() -> int:
    errors = validate_accounting()
    if errors:
        for e in errors:
            print("FAIL:", e)
        sys.exit(1)
    print("ACCOUNTING_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
