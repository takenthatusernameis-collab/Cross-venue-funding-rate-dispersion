import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import validate_backtest as v


class ValidateBacktestScriptTests(unittest.TestCase):
    def test_validate_backtest_returns_empty(self):
        self.assertEqual(v.validate_backtest(), [])

    def test_main_returns_zero(self):
        rc = v.main()
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
