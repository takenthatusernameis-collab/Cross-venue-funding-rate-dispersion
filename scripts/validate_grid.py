#!/usr/bin/env python3
"""Offline conformance check for the frozen research grid (standard library only)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cross_venue_funding_dispersion.grid import config_id, expand_grid, load_grid, validate_grid

GRID_PATH = ROOT / "configs" / "cross_venue_funding_dispersion_grid_v1.json"


def validate_grid_script() -> list[str]:
    errors = []
    try:
        config = load_grid(GRID_PATH)
        combos = expand_grid(config)
        errors.extend(validate_grid(config))
        if len(combos) != 108:
            errors.append(f"expected 108 combinations, found {len(combos)}")
        if config_id(1, config) != "FVD001" or config_id(108, config) != "FVD108":
            errors.append("config id range not FVD001..FVD108")
        # fail-closed checks
        for bad in (None, {}, {"axes": []}, {"axes": [{"name": "a", "values": []}]}):
            try:
                expand_grid(bad)  # type: ignore[arg-type]
                errors.append("expand_grid accepted invalid input")
            except (TypeError, ValueError, AttributeError):
                pass
    except Exception as exc:
        errors.append(f"grid validation raised: {exc}")
    return errors


# backward compatible name
validate_grid_check = validate_grid_script


def main() -> int:
    errors = validate_grid_script()
    if errors:
        for e in errors:
            print("GRID_VALIDATION_FAIL:", e)
        print("GRID_VALIDATION=FAIL")
        return 1
    print("GRID_VALIDATION=PASS combinations=108 anchor=FVD053")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
