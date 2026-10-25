import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import validate_research  # noqa: E402


class ValidateResearchTests(unittest.TestCase):
    def test_main_passes_on_committed_repo(self):
        rc = validate_research.main()
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
