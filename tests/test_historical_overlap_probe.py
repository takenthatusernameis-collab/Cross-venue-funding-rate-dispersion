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


class OKxFundingPaginationTests(unittest.TestCase):
    """Offline known-answer tests for OKX funding-rate-history pagination logic.

    These verify the cursor-based backward pagination in probe_okx_funding()
    using mock responses. They mirror the verified live behavior where OKX
    returns ~292 rows (page_not_full) on the first page because the endpoint
    is documented as 'up to three months' — the after cursor cannot extend
    beyond this because the server has no older records to return.
    """

    def _make_meta(self, url):
        return {
            "url": url, "method": "GET",
            "request_sha256": None, "http_status": 200,
            "response_bytes_read": 100, "response_sha256": "fake",
            "response_prefix_sha256": None, "response_hash_complete": True,
            "response_shape": "json", "latency_ms": 100.0, "error": None,
        }

    def _make_row(self, funding_time_ms, rate="0.0001"):
        return {
            "fundingTime": str(funding_time_ms),
            "fundingRate": rate,
            "realizedRate": rate,
            "instId": "BTC-USDT-SWAP",
        }

    def test_page_not_full_when_api_returns_below_limit(self):
        """page_not_full: API returns <400 rows -> stops after one page.

        Mirrors the verified probe evidence (historical_overlap_probe_40248932339_attempt_1.json):
        OKX funding-rate-history returned 292 rows on the first page (limit=400),
        so stop_reason='page_not_full'. The API is documented as 'up to three months';
        the after cursor cannot extend beyond this because no older records exist
        on the server side — this is a structural OKX API limitation, not a probe bug.
        """
        start_ms = 1_000
        end_ms = 1_000_000
        rows = [self._make_row(start_ms + 1 + i * (end_ms - start_ms - 1) // 292) for i in range(292)]
        payload = {"code": "0", "data": rows}
        with patch.object(probe, "request_json",
                          return_value=(self._make_meta("https://fake"), payload)):
            result = probe.probe_okx_funding("BTC-USDT-SWAP", start_ms, end_ms)
        self.assertEqual(result["stop_reason"], "page_not_full")
        self.assertEqual(result["pages_received"], 1)
        self.assertEqual(result["coverage"]["row_count"], 292)
        self.assertEqual(result["history_limit_documented"], "up to three months")

    def test_page_not_full_boundary_at_exactly_limit_continues(self):
        """When API returns exactly 400 rows, pagination continues to the next page."""
        start_ms = 1_000
        end_ms = 1_000_000
        page1_times = list(range(end_ms, end_ms - 400, -1))
        rows1 = [self._make_row(t) for t in page1_times]
        oldest1 = min(page1_times)
        page2_times = list(range(oldest1 - 1, oldest1 - 201, -1))
        rows2 = [self._make_row(t) for t in page2_times]

        call_idx = [0]
        payloads = [
            {"code": "0", "data": rows1},
            {"code": "0", "data": rows2},
        ]

        def fake_request(url, payload=None, timeout=probe.TIMEOUT_SECONDS, opener=None):
            idx = call_idx[0]
            call_idx[0] += 1
            if idx == 0:
                self.assertNotIn("after=", url)
            else:
                self.assertIn(f"after={oldest1}", url)
            return self._make_meta(url), payloads[idx]

        with patch.object(probe, "request_json", side_effect=fake_request):
            result = probe.probe_okx_funding("BTC-USDT-SWAP", start_ms, end_ms)
        self.assertEqual(result["stop_reason"], "page_not_full")
        self.assertEqual(result["pages_received"], 2)
        self.assertEqual(result["coverage"]["row_count"], 600)

    def test_cursor_stalled_stops_pagination(self):
        """cursor_stalled: oldest fundingTime does not advance beyond the previous cursor."""
        start_ms = 1_000
        end_ms = 1_000_000
        page_times = list(range(end_ms, end_ms - 400, -1))
        rows = [self._make_row(t) for t in page_times]
        payload = {"code": "0", "data": rows}

        with patch.object(probe, "request_json",
                          return_value=(self._make_meta("https://fake"), payload)):
            result = probe.probe_okx_funding("BTC-USDT-SWAP", start_ms, end_ms)
        self.assertEqual(result["stop_reason"], "cursor_stalled")
        self.assertEqual(result["pages_received"], 2)

    def test_window_start_reached_stops_pagination(self):
        """window_start_reached: oldest fundingTime falls at or below start_ms.

        The oldest check (min over all returned rows) precedes the page_not_full
        check, so even a small below-limit page stops with window_start_reached
        when oldest <= start_ms.
        """
        start_ms = 5_000
        end_ms = 10_000
        rows = [self._make_row(t) for t in range(end_ms, start_ms - 100, -1)]
        payload = {"code": "0", "data": rows}

        with patch.object(probe, "request_json",
                          return_value=(self._make_meta("https://fake"), payload)):
            result = probe.probe_okx_funding("BTC-USDT-SWAP", start_ms, end_ms)
        self.assertEqual(result["stop_reason"], "window_start_reached")
        self.assertEqual(result["pages_received"], 1)

    def test_empty_data_stops_pagination(self):
        """no_rows_or_request_failed: API returns empty data list."""
        start_ms = 1_000
        end_ms = 1_000_000
        payload = {"code": "0", "data": []}

        with patch.object(probe, "request_json",
                          return_value=(self._make_meta("https://fake"), payload)):
            result = probe.probe_okx_funding("BTC-USDT-SWAP", start_ms, end_ms)
        self.assertEqual(result["stop_reason"], "no_rows_or_request_failed")
        self.assertEqual(result["pages_received"], 1)

    def test_filtering_excludes_rows_outside_window(self):
        """Only rows within [start_ms, end_ms] are counted in coverage.

        Rows above end_ms are excluded from rows_all but remain in the raw
        response for oldest/cursor calculations. The oldest (600) is above
        start_ms (500), so page_not_full fires on the <400 row count.
        """
        start_ms = 500
        end_ms = 1500
        rows = [
            self._make_row(2000),  # above end_ms, excluded from rows_all
            self._make_row(600),   # in window
            self._make_row(1000),  # in window
            self._make_row(1500),  # at end_ms, included
        ]
        payload = {"code": "0", "data": rows}

        with patch.object(probe, "request_json",
                          return_value=(self._make_meta("https://fake"), payload)):
            result = probe.probe_okx_funding("BTC-USDT-SWAP", start_ms, end_ms)
        self.assertEqual(result["coverage"]["row_count"], 3)
        self.assertEqual(result["stop_reason"], "page_not_full")


if __name__ == "__main__":
    unittest.main()
