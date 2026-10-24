#!/usr/bin/env python3
"""Offline conformance check that every validate_*.py script is registered in validate_all.py."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    registered_text = (ROOT / "scripts/validate_all.py").read_text(encoding="utf-8")
    validate_scripts = sorted(p.name for p in (ROOT / "scripts").glob("validate_*.py") if p.name != "validate_all.py")
    missing = [name for name in validate_scripts if name not in registered_text]
    if missing:
        print("VALIDATION_COVERAGE=FAIL")
        for name in missing:
            print(f"- unregistered validator: {name}")
        return 1
    print(f"VALIDATION_COVERAGE=PASS count={len(validate_scripts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
