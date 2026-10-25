import subprocess
import tempfile
import unittest
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from controller_progress import has_meaningful_committed_progress
import validate_controller_progress as vcp


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


class ControllerProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "initial")
        git(self.repo, "config", "user.email", "initial@example.invalid")
        (self.repo / "baseline.txt").write_text("baseline\n")
        git(self.repo, "add", "baseline.txt")
        git(self.repo, "commit", "-m", "initial")
        self.base = git(self.repo, "rev-parse", "HEAD")

    def tearDown(self):
        self.temp.cleanup()

    def commit_kilo(self, path, content):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        git(self.repo, "add", path)
        git(self.repo, "-c", "user.name=kilo-autonomous", "-c", "user.email=kilo-autonomous@users.noreply.github.com", "commit", "-m", "agent checkpoint")
        return git(self.repo, "rev-parse", "HEAD")

    def commit_other(self, path, content):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        git(self.repo, "add", path)
        git(self.repo, "commit", "-m", "other commit")
        return git(self.repo, "rev-parse", "HEAD")

    def test_progress_requires_matching_remote_sha_for_credit(self):
        head = self.commit_kilo("src/new.py", "value=1\n")
        self.assertTrue(has_meaningful_committed_progress(self.repo, self.base, head))
        self.assertFalse(has_meaningful_committed_progress(self.repo, self.base, head, "wrong"))
        self.assertTrue(has_meaningful_committed_progress(self.repo, self.base, head, head))

    def test_workflow_only_change_is_not_project_progress(self):
        head = self.commit_kilo(".github/workflows/main.yml", "name: test\n")
        self.assertFalse(has_meaningful_committed_progress(self.repo, self.base, head, head))

    def test_non_kilo_author_does_not_count(self):
        head = self.commit_other("docs/x.md", "# x\n")
        self.assertFalse(has_meaningful_committed_progress(self.repo, self.base, head, head))

    def test_base_equals_head_is_not_progress(self):
        self.assertFalse(has_meaningful_committed_progress(self.repo, self.base, self.base, self.base))

    def test_remote_mismatch_fails_closed(self):
        head = self.commit_kilo("src/new.py", "value=1\n")
        self.assertFalse(has_meaningful_committed_progress(self.repo, self.base, head, "wrong"))

    def test_empty_remote_sha_fails_closed(self):
        head = self.commit_kilo("src/new.py", "value=1\n")
        self.assertFalse(has_meaningful_committed_progress(self.repo, self.base, head, ""))

    def test_non_ancestor_base_fails_closed(self):
        head = self.commit_other("docs/x.md", "# x\n")
        other_base = git(self.repo, "rev-parse", f"{head}~1")
        self.assertFalse(has_meaningful_committed_progress(self.repo, head, other_base, other_base))

    def test_bad_repo_path_raises_fail_closed(self):
        head = self.commit_kilo("src/new.py", "value=1\n")
        raised = False
        try:
            has_meaningful_committed_progress("/nonexistent/repo/zzz", self.base, head, head)
        except (OSError, RuntimeError, ValueError):
            raised = True
        self.assertTrue(raised)

    def test_kilo_tests_commit_counts(self):
        head = self.commit_kilo("tests/test_x.py", "import unittest\n")
        self.assertTrue(has_meaningful_committed_progress(self.repo, self.base, head, head))

    def test_kilo_scripts_commit_counts(self):
        head = self.commit_kilo("scripts/x.py", "x=1\n")
        self.assertTrue(has_meaningful_committed_progress(self.repo, self.base, head, head))

    def test_kilo_configs_commit_counts(self):
        head = self.commit_kilo("configs/x.json", "{}\n")
        self.assertTrue(has_meaningful_committed_progress(self.repo, self.base, head, head))

    def test_kilo_research_state_commit_counts(self):
        head = self.commit_kilo("research_state/x.json", "{}\n")
        self.assertTrue(has_meaningful_committed_progress(self.repo, self.base, head, head))

    def test_kilo_src_commit_without_remote_sha_is_fail_open_by_default(self):
        # Documented contract: verified_remote_sha defaults to None, which skips
        # the remote-verification gate entirely. The controller workflow always
        # passes an explicit --verified-remote-sha, so the default is only
        # reachable from direct API use; it is fail-open, not fail-closed.
        head = self.commit_kilo("src/new.py", "value=1\n")
        self.assertTrue(has_meaningful_committed_progress(self.repo, self.base, head))

    def test_kilo_src_commit_with_explicit_matching_remote_sha_counts(self):
        head = self.commit_kilo("src/new.py", "value=1\n")
        self.assertTrue(has_meaningful_committed_progress(self.repo, self.base, head, head))

    def test_kilo_commit_touching_only_dotgithub_workflows_directory_does_not_count(self):
        head = self.commit_kilo(".github/workflows/main.yml", "name: test\n")
        self.assertFalse(has_meaningful_committed_progress(self.repo, self.base, head, head))

    def test_kilo_commit_touching_dotgithub_non_workflow_file_counts(self):
        # Only .github/workflows/ is excluded; other dotgithub paths are project files.
        head = self.commit_kilo(".github/main.yml", "name: test\n")
        self.assertTrue(has_meaningful_committed_progress(self.repo, self.base, head, head))

    def test_mixed_kilo_and_non_kilo_commits_only_kilo_paths_count(self):
        self.commit_other("docs/y.md", "# y\n")
        head = self.commit_kilo("src/z.py", "z=1\n")
        self.assertTrue(has_meaningful_committed_progress(self.repo, self.base, head, head))

    def test_validate_controller_progress_contract_passes(self):
        # Adversarial: the extracted validator must return no errors on the
        # committed contract cases (it is the same code path main() uses).
        self.assertEqual(vcp.validate_controller_progress(), [])


if __name__ == "__main__":
    unittest.main()
