#!/usr/bin/env python3
"""Offline conformance check that every validate_*.py script is registered in validate_all.py."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def validate_coverage(registered_text: str, script_names: list[str]) -> list[str]:
    """Return list of unregistered validator names (empty means pass)."""
    return [name for name in sorted(script_names) if name not in registered_text]


def main() -> int:
    registered_text = (ROOT / "scripts/validate_all.py").read_text(encoding="utf-8")
    validate_scripts = sorted(p.name for p in (ROOT / "scripts").glob("validate_*.py") if p.name != "validate_all.py")
    missing = validate_coverage(registered_text, validate_scripts)
    if missing:
        print("VALIDATION_COVERAGE=FAIL")
        for name in missing:
            print(f"- unregistered validator: {name}")
        return 1
    print(f"VALIDATION_COVERAGE=PASS count={len(validate_scripts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
