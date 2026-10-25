import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import validate_skills  # noqa: E402


class ValidateSkillsTests(unittest.TestCase):
    def test_main_passes_on_committed_repo(self):
        rc = validate_skills.main()
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
