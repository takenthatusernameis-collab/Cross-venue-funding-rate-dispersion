import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import validate_evaluation as v


class ValidateEvaluationScriptTests(unittest.TestCase):
    def test_validate_evaluation_returns_empty(self):
        self.assertEqual(v.validate_evaluation(), [])

    def test_main_returns_zero(self):
        rc = v.main()
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
