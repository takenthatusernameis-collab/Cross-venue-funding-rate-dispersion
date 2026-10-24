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

def main() -> int:
    targets = [ROOT / "HANDOFF.md", ROOT / "README.md", ROOT / "SKILLS.md"]
    targets += sorted((ROOT / "research_state").glob("*.json"))
    # Close remaining documentation surfaces (exclude docs/ protocol specs that legitimately define metrics).
    for p in sorted(ROOT.rglob("*.md")):
        if "docs" in p.relative_to(ROOT).parts:
            continue
        if p not in targets:
            targets.append(p)
    for p in targets:
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace").lower()
        for key in FORBIDDEN:
            if key in text:
                print(f"FAIL: forbidden claim token '{key}' in {p.name}")
                sys.exit(1)
    print("NO_PERFORMANCE_CLAIMS_VALIDATION=PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
