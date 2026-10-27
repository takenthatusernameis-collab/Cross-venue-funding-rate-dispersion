import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import validate_binance_archive as v


class ValidateBinanceArchiveScriptTests(unittest.TestCase):
    def test_validate_binance_archive_returns_empty(self):
        self.assertEqual(v.validate_binance_archive(), [])

    def test_main_returns_zero(self):
        rc = v.main()
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
