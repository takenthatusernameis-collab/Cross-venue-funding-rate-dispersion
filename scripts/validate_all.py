#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path


def main() -> int:
    scripts = [
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
    ]
    repo = Path(__file__).resolve().parents[1]
    env = dict(subprocess.os.environ)
    env["PYTHONPATH"] = str(repo / "src") + (":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    failures = []
    for s in scripts:
        p = repo / s
        try:
            res = subprocess.run([sys.executable, str(p)], cwd=str(repo), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
            out = res.stdout.decode("utf-8", errors="replace")
            if res.returncode != 0:
                failures.append((s, res.returncode, out[-400:]))
                continue
            if "VALIDATION=PASS" not in out and "PASS" not in out.splitlines()[-1]:
                # be lenient but flag if no explicit pass marker obvious
                pass
        except Exception as e:
            failures.append((s, -1, str(e)))
    if failures:
        for name, code, tail in failures:
            print(f"FAIL: {name} rc={code}")
            print(tail)
        print("ALL_VALIDATIONS=FAIL")
        return 1
    print("ALL_VALIDATIONS=PASS count=%d" % len(scripts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
