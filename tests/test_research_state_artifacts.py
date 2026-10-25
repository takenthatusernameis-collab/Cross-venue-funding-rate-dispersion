import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import validate_research_state_artifacts as v  # noqa: E402


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class ResearchStateArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "repo"
        self.root.mkdir()
        (self.root / "research_state").mkdir()
        (self.root / "scripts").mkdir()
        (self.root / "src").mkdir()
        # Save module globals and point the module at the temporary root.
        self._saved_root = v.ROOT
        self._saved_state_dir = v.STATE_DIR
        self._saved_corrections_path = v.CORRECTIONS_PATH
        self._saved_manifests = v.MANIFESTS
        v.ROOT = self.root
        v.STATE_DIR = self.root / "research_state"
        v.CORRECTIONS_PATH = v.STATE_DIR / "artifact_hash_corrections_2026-10-25.json"
        v.MANIFESTS = [v.STATE_DIR / "run_manifest.json", v.STATE_DIR / "exploratory_run_manifest_2026-10-24.json", v.STATE_DIR / "exploratory_run_manifest_2026-10-25.json"]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        # Restore module globals so later tests that import this module see
        # the real repository root, not the deleted temp directory.
        v.ROOT = self._saved_root
        v.STATE_DIR = self._saved_state_dir
        v.CORRECTIONS_PATH = self._saved_corrections_path
        v.MANIFESTS = self._saved_manifests

    def _state(self, name, data):
        path = v.STATE_DIR / name
        _write(path, data)
        return path

    def test_passes_when_all_hashes_match(self):
        a = {"k": "v"}
        b = {"k": "v"}
        a_path = self._state("a.json", a)
        b_path = self._state("b.json", b)
        a_digest = v.sha256_file(a_path)
        b_digest = v.sha256_file(b_path)
        _write(
            v.STATE_DIR / "run_manifest.json",
            {
                "output_artifacts": [
                    {"path": "research_state/a.json", "sha256": a_digest},
                    {"path": "research_state/b.json", "sha256": b_digest},
                ]
            },
        )
        # Run the real entrypoint against the temporary root.
        rc = v.main()
        self.assertEqual(rc, 0)

    def test_malformed_json_fails_closed(self):
        bad = v.STATE_DIR / "broken.json"
        bad.write_text("{not json", encoding="utf-8")
        _write(v.STATE_DIR / "run_manifest.json", {"output_artifacts": []})
        rc = v.main()
        self.assertNotEqual(rc, 0)

    def test_missing_referenced_artifact_fails_closed(self):
        _write(
            v.STATE_DIR / "run_manifest.json",
            {"output_artifacts": [{"path": "research_state/missing.json", "sha256": "a" * 64}]},
        )
        rc = v.main()
        self.assertNotEqual(rc, 0)

    def test_bad_sha256_format_fails_closed(self):
        a_path = self._state("a.json", {"k": "v"})
        _write(
            v.STATE_DIR / "run_manifest.json",
            {"output_artifacts": [{"path": "research_state/a.json", "sha256": "nothex"}]},
        )
        rc = v.main()
        self.assertNotEqual(rc, 0)

    def test_unacknowledged_mismatch_fails_closed(self):
        a_path = self._state("a.json", {"k": "v"})
        _write(
            v.STATE_DIR / "run_manifest.json",
            {"output_artifacts": [{"path": "research_state/a.json", "sha256": "0" * 64}]},
        )
        rc = v.main()
        self.assertNotEqual(rc, 0)

    def test_acknowledged_mismatch_passes_with_warning(self):
        a_path = self._state("a.json", {"k": "v"})
        actual = v.sha256_file(a_path)
        _write(
            v.STATE_DIR / "run_manifest.json",
            {"output_artifacts": [{"path": "research_state/a.json", "sha256": "0" * 64}]},
        )
        _write(
            v.CORRECTIONS_PATH,
            {
                "corrections": [
                    {
                        "artifact": "research_state/a.json",
                        "recorded_sha256": "0" * 64,
                        "actual_sha256": actual,
                    }
                ]
            },
        )
        rc = v.main()
        self.assertEqual(rc, 0)

    def test_self_reference_wrong_hash_fails_closed(self):
        manifest_path = v.STATE_DIR / "run_manifest.json"
        actual = v.sha256_file(manifest_path) if manifest_path.exists() else None
        _write(
            manifest_path,
            {"output_artifacts": [{"path": "research_state/run_manifest.json", "sha256": "0" * 64}]},
        )
        rc = v.main()
        self.assertNotEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()