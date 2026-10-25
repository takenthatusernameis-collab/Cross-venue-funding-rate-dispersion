import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_validation_coverage import validate_coverage  # noqa: E402


class ValidationCoverageTests(unittest.TestCase):
    def test_all_registered_passes(self):
        registered = "validate_foo.py\nvalidate_bar.py"
        self.assertEqual(validate_coverage(registered, ["validate_foo.py", "validate_bar.py"]), [])

    def test_missing_registered_fails(self):
        registered = "validate_foo.py"
        self.assertEqual(validate_coverage(registered, ["validate_foo.py", "validate_bar.py"]), ["validate_bar.py"])

    def test_empty_script_list_passes(self):
        self.assertEqual(validate_coverage("anything", []), [])

    def test_sorted_output(self):
        registered = ""
        self.assertEqual(validate_coverage(registered, ["z.py", "a.py"]), ["a.py", "z.py"])

    def test_committed_repo_passes(self):
        registered_text = (ROOT / "scripts" / "validate_all.py").read_text(encoding="utf-8")
        import glob as _g
        names = sorted(
            Path(p).name for p in _g.glob(str(ROOT / "scripts" / "validate_*.py"))
            if Path(p).name != "validate_all.py"
        )
        self.assertEqual(validate_coverage(registered_text, names), [])


if __name__ == "__main__":
    unittest.main()
