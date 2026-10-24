"""Research statuses and fail-closed performance-claim gate."""
from enum import StrEnum


class ResearchStatus(StrEnum):
    NOT_RUN = "NOT_RUN"
    BLOCKED_DATA_GATE = "BLOCKED_DATA_GATE"
    BLOCKED_SPECIFICATION_GATE = "BLOCKED_SPECIFICATION_GATE"
    IMPLEMENTATION_FAILED = "IMPLEMENTATION_FAILED"
    EXPLORATORY_ONLY = "EXPLORATORY_ONLY"
    INCONCLUSIVE = "INCONCLUSIVE"
    REJECTED = "REJECTED"
    SUPPORTED_FOR_FURTHER_RESEARCH = "SUPPORTED_FOR_FURTHER_RESEARCH"


def performance_claim_allowed(status: ResearchStatus | str, *, backtest_completed: bool, independent_audit_passed: bool, final_holdout_complete: bool) -> bool:
    """Only allow a claim when the registered empirical and audit gates all pass."""
    try:
        normalized = ResearchStatus(status)
    except ValueError:
        return False
    return normalized is ResearchStatus.SUPPORTED_FOR_FURTHER_RESEARCH and backtest_completed and independent_audit_passed and final_holdout_complete
