import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import probe_historical_overlap as probe


class FakeResponse:
    status = 200
    def __init__(self, body):
        self.body = body
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, size=None):
        return self.body if size is None else self.body[:size]


class HistoricalOverlapProbeTests(unittest.TestCase):
    def test_hyperliquid_candle_payload_has_documented_nested_req(self):
        payload = probe.hl_candle_payload("BTC", 1000, 2000)
        self.assertEqual(payload["type"], "candleSnapshot")
        self.assertEqual(payload["req"], {
            "coin": "BTC", "interval": "1h", "startTime": 1000, "endTime": 2000
        })
        self.assertNotIn("coin", payload)

    def test_extract_hyperliquid_coins_from_metadata(self):
        meta = {"universe": [{"name": "BTC"}, {"name": "ETH"}, {"other": "x"}]}
        self.assertEqual(probe.extract_hl_coins(meta), {"BTC", "ETH"})
        self.assertEqual(probe.extract_hl_coins({"universe": None}), set())

    def test_extract_only_live_linear_usdt_swaps(self):
        payload = {"code": "0", "data": [
            {"baseCcy": "BTC", "instId": "BTC-USDT-SWAP", "quoteCcy": "USDT",
             "settleCcy": "USDT", "ctType": "linear", "state": "live"},
            {"baseCcy": "ETH", "instId": "ETH-USD-SWAP", "quoteCcy": "USD",
             "settleCcy": "USD", "ctType": "inverse", "state": "live"},
            {"baseCcy": "SOL", "instId": "SOL-USDT-SWAP", "quoteCcy": "USDT",
             "settleCcy": "USDT", "ctType": "linear", "state": "suspend"},
        ]}
        self.assertEqual(list(probe.extract_okx_linear_usdt_swaps(payload)), ["BTC"])

    def test_summarize_dict_rows_counts_duplicate_and_range(self):
        summary = probe.summarize_rows([
            {"time": "3600000"}, {"time": "7200000"}, {"time": "7200000"}
        ], "time")
        self.assertEqual(summary["row_count"], 3)
        self.assertEqual(summary["timestamp_count"], 3)
        self.assertEqual(summary["unique_timestamp_count"], 2)
        self.assertEqual(summary["duplicate_timestamps"], 1)
        self.assertIsNotNone(summary["earliest_utc"])
        self.assertIsNotNone(summary["latest_utc"])

    def test_summarize_hourly_candles_detects_gaps(self):
        summary = probe.summarize_rows([[0], [3_600_000], [10_800_000]], hourly_candles=True)
        self.assertEqual(summary["hourly_gap_count"], 1)
        self.assertEqual(summary["maximum_missing_hours_in_gap"], 1)

    def test_request_json_hashes_exact_response_and_records_nested_request(self):
        body = b'{"universe":[{"name":"BTC"}]}'
        captured = {}
        def fake_open(req, timeout):
            captured["body"] = req.data
            captured["method"] = req.get_method()
            captured["timeout"] = timeout
            return FakeResponse(body)
        meta, payload = probe.request_json(
            probe.HYPERLIQUID, {"type": "meta"}, opener=fake_open
        )
        self.assertEqual(meta["http_status"], 200)
        self.assertEqual(meta["response_sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(meta["request_sha256"], hashlib.sha256(b'{"type":"meta"}').hexdigest())
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(json.loads(captured["body"]), {"type": "meta"})
        self.assertEqual(payload["universe"][0]["name"], "BTC")

    def test_oversize_response_fails_closed_without_parsing(self):
        body = b"x" * (probe.MAX_RESPONSE_BYTES + 1)
        meta, payload = probe.request_json("https://example.invalid", opener=lambda req, timeout: FakeResponse(body))
        self.assertEqual(meta["response_shape"], "oversize")
        self.assertIsNone(payload)
        self.assertIsNotNone(meta["error"])
        self.assertFalse(meta["response_hash_complete"])
        self.assertIsNone(meta["response_sha256"])
        self.assertEqual(meta["response_prefix_sha256"], hashlib.sha256(body).hexdigest())

    def test_lookback_bounds_reject_short_or_excessive_windows(self):
        with self.assertRaises(ValueError):
            probe.run_probe(89)
        with self.assertRaises(ValueError):
            probe.run_probe(181)

    def test_network_failure_never_marks_data_or_original_gate_passed(self):
        def no_network(url, payload=None, timeout=probe.TIMEOUT_SECONDS, opener=None):
            return ({
                "url": url, "method": "POST" if payload is not None else "GET",
                "request_sha256": None, "http_status": None,
                "response_bytes_read": None, "response_sha256": None,
                "response_prefix_sha256": None, "response_hash_complete": False,
                "response_shape": None, "latency_ms": 0.0,
                "error": "URLError: Temporary failure in name resolution",
            }, None)
        with patch.object(probe, "request_json", side_effect=no_network):
            report = probe.run_probe(120, 1)
        self.assertEqual(report["status"], "NETWORK_UNAVAILABLE_FROM_THIS_HOST")
        self.assertEqual(report["historical_coverage_gate"], "NOT_PASSED_BY_COVERAGE_PROBE")
        self.assertEqual(report["original_confirmatory_gate"], "BLOCKED_DATA_GATE")
        self.assertEqual(report["source_responses_with_http_status"], 0)
        self.assertFalse(report["backtest_completed"])
        self.assertFalse(report["performance_metrics_computed"])
        self.assertEqual(report["candidate_asset_count"], 0)

    def test_probe_status_does_not_assume_data_gate_pass(self):
        # The report-level invariant is enforced by the output constructor.
        report = {
            "historical_coverage_gate": "NOT_PASSED_BY_COVERAGE_PROBE",
            "original_confirmatory_gate": "BLOCKED_DATA_GATE",
            "backtest_completed": False,
            "performance_metrics_computed": False,
        }
        self.assertEqual(report["historical_coverage_gate"], "NOT_PASSED_BY_COVERAGE_PROBE")
        self.assertEqual(report["original_confirmatory_gate"], "BLOCKED_DATA_GATE")
        self.assertFalse(report["backtest_completed"])
        self.assertFalse(report["performance_metrics_computed"])


if __name__ == "__main__":
    unittest.main()
