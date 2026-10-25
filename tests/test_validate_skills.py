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


    def test_validate_skills_empty_returns_error(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            skill_root = root / ".agents" / "skills"
            skill_root.mkdir(parents=True)
            errors = validate_skills.validate_skills(root=root, skill_root=skill_root)
            self.assertTrue(any("AGENTS.md missing" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
