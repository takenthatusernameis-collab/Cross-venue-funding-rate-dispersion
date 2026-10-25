#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCRIPTS = [
    "scripts/validate_research.py",
    "scripts/validate_skills.py",
    "scripts/validate_universe_frontier.py",
    "scripts/validate_orchestration.py",
    "scripts/validate_pair_pnl.py",
    "scripts/validate_evaluation.py",
    "scripts/validate_accounting.py",
    "scripts/validate_signals.py",
    "scripts/validate_backtest.py",
    "scripts/validate_universe.py",
    "scripts/validate_portfolio.py",
    "scripts/validate_recompute.py",
    "scripts/validate_status.py",
    "scripts/validate_research_state.py",
    "scripts/validate_research_state_artifacts.py",
    "scripts/validate_track_separation.py",
    "scripts/validate_grid.py",
    "scripts/validate_controller_progress.py",
    "scripts/validate_manifest_artifacts.py",
    "scripts/validate_manifest_schema.py",
    "scripts/validate_validation_coverage.py",
    "scripts/validate_blocked_manifest_claims.py",
    "scripts/validate_no_performance_claims.py",
]


def validate_all(script_names, repo_root, run_fn=None, env=None):
    """Return list of (script, code, tail) failures; empty means pass."""
    if env is None:
        env = dict(subprocess.os.environ)
        env["PYTHONPATH"] = str(repo_root / "src") + (":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    runner = run_fn if run_fn is not None else subprocess.run
    failures = []
    for s in script_names:
        p = repo_root / s
        try:
            res = runner([sys.executable, str(p)], cwd=str(repo_root), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
            out = res.stdout.decode("utf-8", errors="replace")
            if res.returncode != 0:
                failures.append((s, res.returncode, out[-400:]))
                continue
        except Exception as e:
            failures.append((s, -1, str(e)))
    return failures


def main() -> int:
    repo = ROOT
    failures = validate_all(SCRIPTS, repo)
    if failures:
        for name, code, tail in failures:
            print(f"FAIL: {name} rc={code}")
            print(tail)
        print("ALL_VALIDATIONS=FAIL")
        return 1
    print("ALL_VALIDATIONS=PASS count=%d" % len(SCRIPTS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
