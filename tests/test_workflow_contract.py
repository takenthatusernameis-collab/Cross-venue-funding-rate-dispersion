import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


class WorkflowContractTests(unittest.TestCase):
    def test_kilo_loop_has_safety_and_recovery_controls(self):
        text=(ROOT/".github/workflows/main.yml").read_text(encoding="utf-8")
        for item in (
            'cron: "*/5 * * * *"',
            "workflow_dispatch:",
            "scripts/kilo_free_model_fallback.py",
            "scripts/should_run_historical_probe.py",
            "scripts/probe_historical_overlap.py",
            "--lookback-days 120 --max-assets 4",
            'kilo run --model "kilo/$current_model" --auto',
            "session_models_tried",
            "free-model-routes-exhausted",
            "timeout-minutes: 360",
            "checkpoint_reserve_seconds=300",
            "scripts/controller_progress.py",
            "HANDOFF.md",
            "cancel-in-progress: false",
            "actions/upload-artifact@v7.0.2",
        ):
            self.assertIn(item,text)
        self.assertIn("only try models whose current catalog explicitly prices both input and output at zero",text)
        self.assertNotIn("kilo/kilo-auto/free",text)
        self.assertNotIn("workflow: write",text.lower())
        self.assertNotIn("tests/test_controller_progress_accounting.py",text)

    def test_ci_is_read_only(self):
        text=(ROOT/".github/workflows/research-ci.yml").read_text(encoding="utf-8")
        self.assertIn("contents: read",text)
        self.assertNotIn("contents: write",text)
        self.assertIn("python3 scripts/validate_research.py",text)


if __name__=="__main__":
    unittest.main()
