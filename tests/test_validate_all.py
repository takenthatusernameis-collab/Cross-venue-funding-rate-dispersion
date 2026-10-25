import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class FakeResult:
    def __init__(self, returncode=0, stdout=b"PASS\n"):
        self.returncode = returncode
        self.stdout = stdout


class TestValidateAll(unittest.TestCase):
    def test_empty_list_passes(self):
        from validate_all import validate_all
        self.assertEqual(validate_all([], ROOT, run_fn=lambda *a, **k: FakeResult()), [])

    def test_failing_script_reported(self):
        from validate_all import validate_all
        def runner(cmd, **kw):
            return FakeResult(returncode=1, stdout=b"boom")
        fails = validate_all(["scripts/x.py"], ROOT, run_fn=runner)
        self.assertEqual(len(fails), 1)
        self.assertEqual(fails[0][0], "scripts/x.py")

    def test_exception_reported(self):
        from validate_all import validate_all
        def runner(cmd, **kw):
            raise RuntimeError("oops")
        fails = validate_all(["scripts/x.py"], ROOT, run_fn=runner)
        self.assertEqual(len(fails), 1)
        self.assertEqual(fails[0][1], -1)

    def test_committed_repo_passes(self):
        from validate_all import validate_all, SCRIPTS
        fails = validate_all(SCRIPTS, ROOT)
        self.assertEqual(fails, [], fails)


if __name__ == "__main__":
    unittest.main()
