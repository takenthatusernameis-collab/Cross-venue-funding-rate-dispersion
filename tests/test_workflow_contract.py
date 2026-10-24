import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


class WorkflowContractTests(unittest.TestCase):
    def test_kilo_loop_has_safety_and_recovery_controls(self):
        text=(ROOT/".github/workflows/main.yml").read_text(encoding="utf-8")
        for item in ('cron: "*/5 * * * *"',"workflow_dispatch:","kilo/kilo-auto/free","timeout-minutes: 360","checkpoint_reserve_seconds=300","scripts/controller_progress.py","HANDOFF.md","cancel-in-progress: false","actions/upload-artifact@v7.0.2"):
            self.assertIn(item,text)
        self.assertNotIn("workflow: write",text.lower())
        self.assertNotIn("tests/test_controller_progress_accounting.py",text)

    def test_ci_is_read_only(self):
        text=(ROOT/".github/workflows/research-ci.yml").read_text(encoding="utf-8")
        self.assertIn("contents: read",text)
        self.assertNotIn("contents: write",text)
        self.assertIn("python3 scripts/validate_research.py",text)


if __name__=="__main__":
    unittest.main()
