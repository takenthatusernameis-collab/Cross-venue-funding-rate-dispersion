#!/usr/bin/env python3
"""Fail-closed validation: blocked runs must not claim performance or completed backtests.

Standard library only; no network calls; no economic result.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: unreadable JSON {path.name}: {exc}")
        sys.exit(1)


def check(cond, msg):
    if not cond:
        print("FAIL:", msg)
        sys.exit(1)


BLOCKED_STATUSES = {
    "BLOCKED_DATA_GATE",
    "BLOCKED_SPECIFICATION_GATE",
}


def main() -> int:
    paths = [
        ROOT / "research_state/run_manifest.json",
        ROOT / "research_state/exploratory_run_manifest_2026-10-24.json",
    ]
    for p in paths:
        check(p.is_file(), f"missing required artifact {p.name}")

    for p in paths:
        m = load_json(p)
        status = m.get("status")
        if status in BLOCKED_STATUSES or status == "NOT_RUN":
            check(m.get("backtest_completed") is False,
                  f"{p.name}: blocked/not_run must have backtest_completed=false")
            check(m.get("performance_metrics_computed") is False,
                  f"{p.name}: blocked/not_run must have performance_metrics_computed=false")
            # Also ensure no performance metric keys present
            for key in ("sharpe", "annualized_return", "max_drawdown", "pnl_total", "equity_curve"):
                check(key not in m, f"{p.name}: must not contain performance key {key}")
        elif status in {"EXPLORATORY_ONLY", "INCONCLUSIVE"}:
            check(m.get("backtest_completed") is False,
                  f"{p.name}: exploratory must have backtest_completed=false")
            check(m.get("performance_metrics_computed") is False,
                  f"{p.name}: exploratory must have performance_metrics_computed=false")
            for key in ("sharpe", "annualized_return", "max_drawdown", "pnl_total", "equity_curve"):
                check(key not in m, f"{p.name}: must not contain performance key {key}")

    print("BLOCKED_MANIFEST_CLAIMS_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
