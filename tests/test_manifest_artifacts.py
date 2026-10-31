import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from validate_manifest_artifacts import validate_manifest_artifacts


class TestManifestArtifacts(unittest.TestCase):
    def _make(self, tmp, artifacts, **extra):
        m = Path(tmp) / "m.json"
        m.write_text(json.dumps({"output_artifacts": artifacts, **extra}))
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

    def test_reference_probe_hash_matches_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "research_state" / "probe.json"
            p.parent.mkdir(parents=True)
            p.write_text("{}")
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            m = self._make(d, [], reference_probe="probe.json", reference_probe_sha256=digest)
            self.assertEqual(validate_manifest_artifacts([m], d), [])

    def test_reference_probe_missing_file_fails(self):
        with tempfile.TemporaryDirectory() as d:
            m = self._make(d, [], reference_probe="missing.json", reference_probe_sha256="a" * 64)
            errs = validate_manifest_artifacts([m], d)
            self.assertTrue(any("reference_probe file missing" in e for e in errs))

    def test_reference_probe_hash_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "research_state" / "probe.json"
            p.parent.mkdir(parents=True)
            p.write_text("{}")
            m = self._make(d, [], reference_probe="probe.json", reference_probe_sha256="0" * 64)
            errs = validate_manifest_artifacts([m], d)
            self.assertTrue(any("reference_probe_sha256 mismatch" in e for e in errs))

    def test_reference_probe_sha_without_probe_fails(self):
        with tempfile.TemporaryDirectory() as d:
            m = self._make(d, [], reference_probe_sha256="a" * 64)
            errs = validate_manifest_artifacts([m], d)
            self.assertTrue(any("reference_probe_sha256 present without reference_probe" in e for e in errs))

    def test_no_reference_probe_passes(self):
        with tempfile.TemporaryDirectory() as d:
            m = self._make(d, [])
            self.assertEqual(validate_manifest_artifacts([m], d), [])

    def test_committed_exploratory_003_reference_probe_validated(self):
        root = Path(__file__).resolve().parents[1]
        manifest = root / "research_state" / "exploratory_run_manifest_2026-10-27.json"
        errs = validate_manifest_artifacts([manifest], root)
        self.assertEqual(errs, [], f"reference_probe validation failed for FVD-EXPLORATORY-003: {errs}")

    def test_parent_manifest_hash_matches_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "research_state" / "parent.json"
            p.parent.mkdir(parents=True)
            p.write_text("{}")
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            m = self._make(d, [], parent_exploratory_manifest="parent.json", parent_exploratory_manifest_sha256=digest)
            self.assertEqual(validate_manifest_artifacts([m], d), [])

    def test_parent_manifest_missing_file_fails(self):
        with tempfile.TemporaryDirectory() as d:
            m = self._make(d, [], parent_exploratory_manifest="missing.json", parent_exploratory_manifest_sha256="a" * 64)
            errs = validate_manifest_artifacts([m], d)
            self.assertTrue(any("parent_exploratory_manifest file missing" in e for e in errs))

    def test_parent_manifest_hash_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "research_state" / "parent.json"
            p.parent.mkdir(parents=True)
            p.write_text("{}")
            m = self._make(d, [], parent_exploratory_manifest="parent.json", parent_exploratory_manifest_sha256="0" * 64)
            errs = validate_manifest_artifacts([m], d)
            self.assertTrue(any("parent_exploratory_manifest_sha256 mismatch" in e for e in errs))

    def test_parent_manifest_sha_without_path_fails(self):
        with tempfile.TemporaryDirectory() as d:
            m = self._make(d, [], parent_exploratory_manifest_sha256="a" * 64)
            errs = validate_manifest_artifacts([m], d)
            self.assertTrue(any("parent_exploratory_manifest_sha256 present without parent_exploratory_manifest" in e for e in errs))

    def test_committed_exploratory_003_parent_manifest_validated(self):
        root = Path(__file__).resolve().parents[1]
        manifest = root / "research_state" / "exploratory_run_manifest_2026-10-27.json"
        errs = validate_manifest_artifacts([manifest], root)
        self.assertEqual(errs, [], f"parent manifest validation failed for FVD-EXPLORATORY-003: {errs}")


if __name__ == "__main__":
    unittest.main()
