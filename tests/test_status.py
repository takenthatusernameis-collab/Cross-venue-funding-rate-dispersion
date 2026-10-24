import unittest
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from cross_venue_funding_dispersion.status import ResearchStatus,performance_claim_allowed


class StatusTests(unittest.TestCase):
    def test_not_run_never_claims_performance(self):
        self.assertFalse(performance_claim_allowed(ResearchStatus.NOT_RUN,backtest_completed=True,independent_audit_passed=True,final_holdout_complete=True))

    def test_every_gate_is_required(self):
        args=dict(backtest_completed=True,independent_audit_passed=True,final_holdout_complete=True)
        self.assertTrue(performance_claim_allowed(ResearchStatus.SUPPORTED_FOR_FURTHER_RESEARCH,**args))
        for field in args:
            changed=dict(args); changed[field]=False
            self.assertFalse(performance_claim_allowed(ResearchStatus.SUPPORTED_FOR_FURTHER_RESEARCH,**changed))

    def test_unknown_status_fails_closed(self):
        self.assertFalse(performance_claim_allowed("UNKNOWN",backtest_completed=True,independent_audit_passed=True,final_holdout_complete=True))


if __name__=="__main__":
    unittest.main()
