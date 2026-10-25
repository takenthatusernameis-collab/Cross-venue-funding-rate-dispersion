#!/usr/bin/env python3
"""Offline conformance check for recompute/determinism (standard library only)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.recompute import recompute_run


def validate_recompute() -> list[str]:
    errors = []
    try:
        r1 = recompute_run(config_id="FVD001", seed=123)
        r2 = recompute_run(config_id="FVD001", seed=123)
        if r1 != r2:
            errors.append("not deterministic")
    except Exception as exc:
        errors.append(f"recompute deterministic raised: {exc}")
    try:
        recompute_run(config_id="", seed=1)
        errors.append("empty config_id accepted")
    except ValueError:
        pass
    except Exception as exc:
        errors.append(f"empty config_id raised wrong type: {exc}")
    try:
        recompute_run(config_id="FVD001", seed="bad")
        errors.append("bad seed accepted")
    except (TypeError, ValueError):
        pass
    except Exception as exc:
        errors.append(f"bad seed raised wrong type: {exc}")
    return errors


def main() -> int:
    errors = validate_recompute()
    if errors:
        for e in errors:
            print("FAIL:", e)
        sys.exit(1)
    print("RECOMPUTE_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
