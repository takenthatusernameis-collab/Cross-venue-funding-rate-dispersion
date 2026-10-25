import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from preflight_public_sources import (  # noqa: E402
    HTTPError,
    MAX_RESPONSE_BYTES,
    PROBES,
    URLError,
    is_json,
    main,
    probe,
)


class _FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, n=None):
        return self._body


class PreflightPublicSourcesTests(unittest.TestCase):
    def test_is_json_detects_json_and_non_json(self):
        self.assertTrue(is_json(b'{"ok": true}'))
        self.assertFalse(is_json(b"hello world"))
        self.assertFalse(is_json(b"{not json"))

    def _mock_urlopen(self, status, body):
        return patch("preflight_public_sources.urlopen", return_value=_FakeResponse(status, body))

    def test_probe_200_json_reachable(self):
        with self._mock_urlopen(200, b'{"time": "2026-01-01T00:00:00Z"}'):
            result = probe(PROBES[0])
        self.assertTrue(result["reachable"])
        self.assertEqual(result["http_status"], 200)
        self.assertEqual(result["response_shape"], "json")
        self.assertIsNone(result["error"])
        self.assertIsInstance(result["latency_ms"], float)
        self.assertFalse(result["historical_coverage_proven"])
        self.assertEqual(result["source_id"], PROBES[0]["id"])

    def test_probe_http_451_not_reachable(self):
        with patch("preflight_public_sources.urlopen", side_effect=HTTPError("http://x", 451, "unavailable", {}, None)):
            result = probe(PROBES[0])
        self.assertFalse(result["reachable"])
        self.assertEqual(result["http_status"], 451)
        self.assertIsNotNone(result["error"])
        self.assertFalse(result["historical_coverage_proven"])

    def test_probe_http_403_not_reachable(self):
        with patch("preflight_public_sources.urlopen", side_effect=HTTPError("http://x", 403, "forbidden", {}, None)):
            result = probe(PROBES[1])
        self.assertFalse(result["reachable"])
        self.assertEqual(result["http_status"], 403)
        self.assertIsNotNone(result["error"])

    def test_probe_urlerror_not_reachable(self):
        with patch("preflight_public_sources.urlopen", side_effect=URLError("DNS failure")):
            result = probe(PROBES[4])
        self.assertFalse(result["reachable"])
        self.assertIsNone(result["http_status"])
        self.assertIsNotNone(result["error"])

    def test_probe_timeout_not_reachable(self):
        with patch("preflight_public_sources.urlopen", side_effect=TimeoutError("timed out")):
            result = probe(PROBES[2])
        self.assertFalse(result["reachable"])
        self.assertIsNotNone(result["error"])

    def test_probe_200_non_json_body(self):
        with self._mock_urlopen(200, b"plain text body"):
            result = probe(PROBES[0])
        self.assertTrue(result["reachable"])
        self.assertEqual(result["response_shape"], "non-json")

    def test_probe_oversize_body(self):
        oversize = b"x" * (MAX_RESPONSE_BYTES + 1)
        with self._mock_urlopen(200, oversize):
            result = probe(PROBES[0])
        self.assertTrue(result["reachable"])
        self.assertEqual(result["response_shape"], "oversize")

    def test_historical_coverage_proven_never_true(self):
        with self._mock_urlopen(200, b'{"ok": true}'):
            for item in PROBES:
                self.assertFalse(probe(item)["historical_coverage_proven"])

    def test_main_writes_report_without_metrics(self):
        out = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        out.close()
        old_argv = sys.argv
        sys.argv = ["preflight_public_sources.py", "--output", out.name]
        try:
            with patch("preflight_public_sources.urlopen", return_value=_FakeResponse(200, b'{"ok": true}')):
                stdout = io.StringIO()
                with patch("sys.stdout", stdout):
                    rc = main()
        finally:
            sys.argv = old_argv
        self.assertEqual(rc, 0)
        report = json.loads(Path(out.name).read_text(encoding="utf-8"))
        self.assertEqual(report["run_type"], "public_endpoint_reachability_only")
        self.assertEqual(report["status"], "PREFLIGHT_ONLY")
        self.assertFalse(report["performance_metrics_computed"])
        self.assertEqual(report["historical_point_in_time_market_cap_gate"], "NOT_VERIFIED")
        self.assertEqual(len(report["probes"]), len(PROBES))
        self.assertTrue(all(not p["historical_coverage_proven"] for p in report["probes"]))
        summary = json.loads(stdout.getvalue())
        self.assertEqual(summary["status"], "PREFLIGHT_ONLY")
        self.assertEqual(summary["probes"], len(PROBES))
        Path(out.name).unlink(missing_ok=True)

    def test_main_respects_per_probe_outcome(self):
        def side_effect(request, timeout=None):
            if "binance" in request.get_full_url():
                raise HTTPError(request.get_full_url(), 451, "legal", {}, None)
            return _FakeResponse(200, b'{"ok": true}')
        out = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        out.close()
        old_argv = sys.argv
        sys.argv = ["preflight_public_sources.py", "--output", out.name]
        try:
            with patch("preflight_public_sources.urlopen", side_effect=side_effect):
                with patch("sys.stdout", new_callable=io.StringIO):
                    rc = main()
        finally:
            sys.argv = old_argv
        self.assertEqual(rc, 0)
        report = json.loads(Path(out.name).read_text(encoding="utf-8"))
        statuses = {p["source_id"]: p["reachable"] for p in report["probes"]}
        self.assertFalse(statuses["binance-usdm-time"])
        self.assertTrue(all(v for k, v in statuses.items() if k != "binance-usdm-time"))
        Path(out.name).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
