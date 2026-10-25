import subprocess
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
            "timeout-minutes: ${{ github.event_name ==",
            "&& 360 || 45",
            "KILO_JOB_START_EPOCH=$(date +%s)",
            "job_start_epoch + activation_minutes * 60",
            "checkpoint_reserve_seconds=300",
            "scripts/controller_progress.py",
            "HANDOFF.md",
            "cancel-in-progress: false",
            "actions/upload-artifact@v7.0.2",
        ):
            self.assertIn(item,text)
        self.assertLess(
            text.index("Run and checkpoint bounded historical coverage before Kilo setup"),
            text.index("Inspect completed runs and update the diagnostics ledger"),
        )
        self.assertLess(
            text.index("Run and checkpoint bounded historical coverage before Kilo setup"),
            text.index("Run general-purpose Kilo agent loop"),
        )
        self.assertIn("catalog explicitly prices both input and",text)
        self.assertIn("output at zero.",text)
        self.assertNotIn("kilo/kilo-auto/free",text)
        self.assertNotIn("workflow: write",text.lower())
        self.assertNotIn("tests/test_controller_progress_accounting.py",text)

    def test_kilo_controller_shell_script_parses_with_bash(self):
        lines=(ROOT/".github/workflows/main.yml").read_text(encoding="utf-8").splitlines()
        step=next(i for i,line in enumerate(lines) if "- name: Run general-purpose Kilo agent loop" in line)
        run=next(i for i in range(step, len(lines)) if lines[i].strip()=="run: |")
        base_indent=len(lines[run])-len(lines[run].lstrip())+2
        script=[]
        for line in lines[run+1:]:
            if line.strip():
                indent=len(line)-len(line.lstrip())
                if indent < base_indent:
                    break
                script.append(line[base_indent:] if indent >= base_indent else "")
            else:
                script.append("")
        result=subprocess.run(["bash","-n"],input="\n".join(script),text=True,capture_output=True,check=False)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_independent_coverage_probe_is_bounded_and_separate_from_kilo(self):
        path=ROOT/".github/workflows/historical-coverage-probe.yml"
        text=path.read_text(encoding="utf-8")
        for item in (
            'cron: "13,43 * * * *"',
            "group: historical-coverage-probe",
            "cancel-in-progress: false",
            "timeout-minutes: 20",
            "contents: write",
            "scripts/should_run_historical_probe.py",
            "scripts/probe_historical_overlap.py",
            "--lookback-days 120 --max-assets 4",
            "git diff --cached --check",
            "git rebase",
            "probe_artifact_blob_sha",
            "actions/upload-artifact@v7.0.2",
            "GITHUB_STEP_SUMMARY",
            "performance metrics computed: false",
        ):
            self.assertIn(item,text)
        self.assertNotIn("\\n  push:", text)
        self.assertNotIn("workflow_dispatch:",text)
        self.assertNotIn("kilo run --model",text)
        self.assertNotIn("workflow_run_diagnostics.jsonl",text)
        self.assertLess(
            text.index("Check historical-probe cooldown"),
            text.index("Run bounded public historical coverage probe"),
        )
        lines=text.splitlines()
        step=next(i for i,line in enumerate(lines) if "- name: Run bounded public historical coverage probe" in line)
        run=next(i for i in range(step,len(lines)) if lines[i].strip()=="run: |")
        base_indent=len(lines[run])-len(lines[run].lstrip())+2
        script=[]
        for line in lines[run+1:]:
            if line.strip():
                indent=len(line)-len(line.lstrip())
                if indent<base_indent:
                    break
                script.append(line[base_indent:] if indent>=base_indent else "")
            else:
                script.append("")
        result=subprocess.run(["bash","-n"],input="\\n".join(script),text=True,capture_output=True,check=False)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_ci_is_read_only(self):
        text=(ROOT/".github/workflows/research-ci.yml").read_text(encoding="utf-8")
        self.assertIn("contents: read",text)
        self.assertNotIn("contents: write",text)
        self.assertIn("python3 scripts/validate_research.py",text)


if __name__=="__main__":
    unittest.main()
