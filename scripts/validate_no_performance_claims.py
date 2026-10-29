#!/usr/bin/env python3
"""Fail-closed scan: no performance/economic claims in research artifacts or HANDOFF."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = (
    "sharpe",
    "annualized_return",
    "max_drawdown",
    "pnl_total",
    "equity_curve",
    "edge_detected",
    "profit_factor",
    "sortino",
    "calmar",
    "cagr",
    "win_rate",
    "hit_rate",
    "information_ratio",
)


def find_forbidden(text: str) -> list[str]:
    lowered = text.lower()
    return [key for key in FORBIDDEN if key in lowered]


def scan_text(text: str, name: str) -> None:
    offenders = find_forbidden(text)
    if offenders:
        print(f"FAIL: forbidden claim token '{offenders[0]}' in {name}")
        sys.exit(1)


def scan_path(p: Path) -> None:
    if not p.is_file():
        return
    text = p.read_text(encoding="utf-8", errors="replace")
    scan_text(text, p.name)


def validate_no_performance_claims(targets=None) -> list[str]:
    if targets is None:
        targets = default_targets()
    errors: list[str] = []
    for p in targets:
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        offenders = find_forbidden(text)
        if offenders:
            errors.append(f"forbidden claim token '{offenders[0]}' in {p.name}")
    return errors


def main(targets=None) -> int:
    errors = validate_no_performance_claims(targets)
    if errors:
        for e in errors:
            print(f"FAIL: {e}")
        return 1
    print("NO_PERFORMANCE_CLAIMS_VALIDATION=PASS")
    return 0


def default_targets() -> list[Path]:
    targets = [ROOT / "HANDOFF.md", ROOT / "README.md", ROOT / "SKILLS.md"]
    targets += sorted((ROOT / "research_state").glob("*.json"))
    for p in sorted(ROOT.rglob("*.md")):
        if "docs" in p.relative_to(ROOT).parts:
            continue
        if p not in targets:
            targets.append(p)
    return targets


if __name__ == "__main__":
    raise SystemExit(main())
