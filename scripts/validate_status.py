"""Offline conformance check for research status / performance-claim gate (standard library only)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.status import ResearchStatus, performance_claim_allowed


def check(cond, msg):
    if not cond:
        print("FAIL:", msg)
        sys.exit(1)


def main():
    # NOT_RUN can never claim performance, even with all gates set true
    check(
        not performance_claim_allowed(ResearchStatus.NOT_RUN, backtest_completed=True, independent_audit_passed=True, final_holdout_complete=True),
        "NOT_RUN claimed performance",
    )
    # BLOCKED_DATA_GATE can never claim
    check(
        not performance_claim_allowed(ResearchStatus.BLOCKED_DATA_GATE, backtest_completed=True, independent_audit_passed=True, final_holdout_complete=True),
        "BLOCKED_DATA_GATE claimed performance",
    )
    # Unknown status fails closed
    check(
        not performance_claim_allowed("UNKNOWN", backtest_completed=True, independent_audit_passed=True, final_holdout_complete=True),
        "unknown status claimed performance",
    )
    # All gates required
    args = dict(backtest_completed=True, independent_audit_passed=True, final_holdout_complete=True)
    check(
        performance_claim_allowed(ResearchStatus.SUPPORTED_FOR_FURTHER_RESEARCH, **args),
        "all gates should allow claim",
    )
    for field in args:
        changed = dict(args)
        changed[field] = False
        check(
            not performance_claim_allowed(ResearchStatus.SUPPORTED_FOR_FURTHER_RESEARCH, **changed),
            f"missing {field} should block claim",
        )
    # StrEnum values round-trip
    check(ResearchStatus("BLOCKED_DATA_GATE") is ResearchStatus.BLOCKED_DATA_GATE, "status round-trip failed")

    print("STATUS_VALIDATION=PASS")


if __name__ == "__main__":
    main()
