import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from validate_manifest_artifacts import validate_manifest_artifacts


class TestManifestArtifacts(unittest.TestCase):
    def _make(self, tmp, artifacts):
        m = Path(tmp) / "m.json"
        m.write_text(json.dumps({"output_artifacts": artifacts}))
        return m

    def test_empty_artifacts_pass(self):
        with tempfile.TemporaryDirectory() as d:
            m = self._make(d, [])
            self.assertEqual(validate_manifest_artifacts([m], d), [])

    def test_missing_manifest_fails(self):
        with tempfile.TemporaryDirectory() as d:
            missing = Path(d) / "nope.json"
            errs = validate_manifest_artifacts([missing], d)
            self.assertTrue(any("manifest missing" in e for e in errs))

    def test_valid_artifact_passes(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.txt"
            p.write_text("hello")
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            m = self._make(d, [{"path": "a.txt", "sha256": digest}])
            self.assertEqual(validate_manifest_artifacts([m], d), [])

    def test_missing_file_fails(self):
        with tempfile.TemporaryDirectory() as d:
            m = self._make(d, [{"path": "missing.txt", "sha256": "a" * 64}])
            errs = validate_manifest_artifacts([m], d)
            self.assertTrue(any("artifact file missing" in e for e in errs))

    def test_sha_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.txt"
            p.write_text("hello")
            m = self._make(d, [{"path": "a.txt", "sha256": "0" * 64}])
            errs = validate_manifest_artifacts([m], d)
            self.assertTrue(any("sha256 mismatch" in e for e in errs))

    def test_bad_digest_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.txt"
            p.write_text("hello")
            m = self._make(d, [{"path": "a.txt", "sha256": "short"}])
            errs = validate_manifest_artifacts([m], d)
            self.assertTrue(any("bad sha256" in e for e in errs))

    def test_artifact_not_object_fails(self):
        with tempfile.TemporaryDirectory() as d:
            m = self._make(d, ["x"])
            errs = validate_manifest_artifacts([m], d)
            self.assertTrue(any("artifact not an object" in e for e in errs))

    def test_artifacts_not_list_fails(self):
        with tempfile.TemporaryDirectory() as d:
            m = Path(d) / "m.json"
            m.write_text(json.dumps({"output_artifacts": "x"}))
            errs = validate_manifest_artifacts([m], d)
            self.assertTrue(any("not a list" in e for e in errs))

    def test_committed_manifests_pass(self):
        root = Path(__file__).resolve().parents[1]
        manifests = [
            root / "research_state" / "run_manifest.json",
            root / "research_state" / "exploratory_run_manifest_2026-10-24.json",
            root / "research_state" / "exploratory_run_manifest_2026-10-25.json",
            root / "research_state" / "exploratory_run_manifest_2026-10-27.json",
        ]
        self.assertEqual(validate_manifest_artifacts(manifests, root), [])

    def test_missing_path_fails(self):
        with tempfile.TemporaryDirectory() as d:
            m = self._make(d, [{"sha256": "a" * 64}])
            errs = validate_manifest_artifacts([m], d)
            self.assertTrue(any("artifact missing path" in e for e in errs))

    def test_bad_json_fails(self):
        with tempfile.TemporaryDirectory() as d:
            m = Path(d) / "m.json"
            m.write_text("{bad")
            errs = validate_manifest_artifacts([m], d)
            self.assertTrue(len(errs) > 0)


if __name__ == "__main__":
    unittest.main()
