#!/usr/bin/env python3
"""Offline conformance check for backtest harness (standard library only)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.backtest import run_backtest


def validate_backtest() -> list[str]:
    errors = []
    try:
        res = run_backtest(config_id="FVD001", equity=100.0, pairs=[], fees_bps=1.0, slippage_bps=1.0)
        if not isinstance(res, dict):
            errors.append("backtest result not dict")
        elif "config_id" not in res or "total_net_pnl" not in res or "net_pnl_series" not in res:
            errors.append("backtest missing keys")
    except Exception as exc:
        errors.append(f"backtest basic raised: {exc}")
    try:
        run_backtest(config_id="", equity=100.0, pairs=[], fees_bps=0.0, slippage_bps=0.0)
        errors.append("empty config_id accepted")
    except ValueError:
        pass
    except Exception as exc:
        errors.append(f"empty config_id raised wrong type: {exc}")
    try:
        run_backtest(config_id="FVD001", equity=0.0, pairs=[], fees_bps=0.0, slippage_bps=0.0)
        errors.append("zero equity accepted")
    except ValueError:
        pass
    except Exception as exc:
        errors.append(f"zero equity raised wrong type: {exc}")
    try:
        run_backtest(config_id="FVD001", equity=100.0, pairs="bad", fees_bps=0.0, slippage_bps=0.0)
        errors.append("bad pairs accepted")
    except (TypeError, ValueError):
        pass
    except Exception as exc:
        errors.append(f"bad pairs raised wrong type: {exc}")
    return errors


def main() -> int:
    errors = validate_backtest()
    if errors:
        for e in errors:
            print("FAIL:", e)
        sys.exit(1)
    print("BACKTEST_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
