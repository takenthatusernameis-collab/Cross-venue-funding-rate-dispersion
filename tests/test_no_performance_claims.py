import unittest
from scripts.validate_no_performance_claims import find_forbidden, FORBIDDEN


class TestNoPerformanceClaims(unittest.TestCase):
    def test_clean_text_passes(self):
        self.assertEqual(find_forbidden("hello world"), [])

    def test_each_forbidden_detected(self):
        for key in FORBIDDEN:
            self.assertIn(key, find_forbidden(f"contains {key} here"))

    def test_case_insensitive(self):
        self.assertIn("sharpe", find_forbidden("SHARPE ratio"))

    def test_multiple_offenders(self):
        res = find_forbidden("sharpe and win_rate")
        self.assertIn("sharpe", res)
        self.assertIn("win_rate", res)

    def test_empty_text(self):
        self.assertEqual(find_forbidden(""), [])


if __name__ == "__main__":
    unittest.main()
