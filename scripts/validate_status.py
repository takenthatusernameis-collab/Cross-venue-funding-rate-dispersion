"""Offline conformance check for research status / performance-claim gate (standard library only)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.status import ResearchStatus, performance_claim_allowed


def validate_status() -> list[str]:
    errors: list[str] = []
    # NOT_RUN can never claim performance, even with all gates set true
    if performance_claim_allowed(ResearchStatus.NOT_RUN, backtest_completed=True, independent_audit_passed=True, final_holdout_complete=True):
        errors.append("NOT_RUN claimed performance")
    # BLOCKED_DATA_GATE can never claim
    if performance_claim_allowed(ResearchStatus.BLOCKED_DATA_GATE, backtest_completed=True, independent_audit_passed=True, final_holdout_complete=True):
        errors.append("BLOCKED_DATA_GATE claimed performance")
    # Unknown status fails closed
    if performance_claim_allowed("UNKNOWN", backtest_completed=True, independent_audit_passed=True, final_holdout_complete=True):
        errors.append("unknown status claimed performance")
    # All gates required
    args = dict(backtest_completed=True, independent_audit_passed=True, final_holdout_complete=True)
    if not performance_claim_allowed(ResearchStatus.SUPPORTED_FOR_FURTHER_RESEARCH, **args):
        errors.append("all gates should allow claim")
    for field in args:
        changed = dict(args)
        changed[field] = False
        if performance_claim_allowed(ResearchStatus.SUPPORTED_FOR_FURTHER_RESEARCH, **changed):
            errors.append(f"missing {field} should block claim")
    # StrEnum values round-trip
    if ResearchStatus("BLOCKED_DATA_GATE") is not ResearchStatus.BLOCKED_DATA_GATE:
        errors.append("status round-trip failed")
    return errors


def main():
    errors = validate_status()
    if errors:
        for e in errors:
            print("FAIL:", e)
        sys.exit(1)
    print("STATUS_VALIDATION=PASS")


if __name__ == "__main__":
    main()
