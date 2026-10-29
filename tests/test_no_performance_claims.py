import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from scripts.validate_no_performance_claims import (  # noqa: E402
    find_forbidden,
    FORBIDDEN,
    main,
    default_targets,
    scan_path,
    validate_no_performance_claims,
)


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


class NoPerformanceClaimsValidationTests(unittest.TestCase):
    """Fail-closed tests for the full validate_no_performance_claims pipeline."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _write(self, name, text):
        p = self.root / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_empty_targets_returns_no_errors(self):
        self.assertEqual(validate_no_performance_claims([]), [])

    def test_clean_file_returns_no_errors(self):
        p = self._write("clean.json", json.dumps({"status": "BLOCKED_DATA_GATE"}))
        self.assertEqual(validate_no_performance_claims([p]), [])

    def test_forbidden_token_returns_error(self):
        p = self._write("claim.json", json.dumps({"sharpe": 1.5}))
        errors = validate_no_performance_claims([p])
        self.assertEqual(len(errors), 1)
        self.assertIn("sharpe", errors[0])

    def test_multiple_forbidden_tokens_all_reported(self):
        p = self._write("multi.json", json.dumps({"sharpe": 1.0, "win_rate": 0.5}))
        errors = validate_no_performance_claims([p])
        self.assertEqual(len(errors), 1)
        self.assertIn("sharpe", errors[0])

    def test_nonexistent_file_skipped(self):
        missing = self.root / "does_not_exist.json"
        self.assertEqual(validate_no_performance_claims([missing]), [])

    def test_main_returns_zero_when_clean(self):
        clean = self._write("clean.json", json.dumps({"status": "BLOCKED"}))
        self.assertEqual(main([clean]), 0)

    def test_main_returns_one_when_forbidden(self):
        bad = self._write("bad.json", json.dumps({"pnl_total": 100}))
        self.assertEqual(main([bad]), 1)

    def test_main_empty_targets_passes(self):
        self.assertEqual(main([]), 0)

    def test_scan_path_skips_nonexistent(self):
        scan_path(self.root / "nope.json")

    def test_scan_path_clean_file_no_exit(self):
        p = self._write("ok.md", "# Research\nblocked data gate\n")
        scan_path(p)

    def test_scan_path_forbidden_raises_systemexit(self):
        p = self._write("bad.md", "the sharpe ratio is positive")
        with self.assertRaises(SystemExit):
            scan_path(p)

    def test_committed_default_targets_pass(self):
        targets = default_targets()
        errors = validate_no_performance_claims(targets)
        self.assertEqual(errors, [], f"forbidden tokens in committed targets: {errors}")


class DefaultTargetsTests(unittest.TestCase):
    def test_default_targets_includes_key_files(self):
        names = {p.name for p in default_targets()}
        self.assertIn("HANDOFF.md", names)
        self.assertIn("SKILLS.md", names)

    def test_default_targets_includes_research_state_json(self):
        targets = default_targets()
        state_jsons = [
            p for p in targets
            if p.suffix == ".json" and p.parent.name == "research_state"
        ]
        self.assertGreater(len(state_jsons), 0)

    def test_default_targets_excludes_docs_markdown(self):
        targets = default_targets()
        docs_md = [
            p for p in targets
            if p.suffix == ".md" and "docs" in p.relative_to(ROOT).parts
        ]
        self.assertEqual(docs_md, [])


if __name__ == "__main__":
    unittest.main()
