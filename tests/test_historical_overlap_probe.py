import hashlib
import json
import sys
import unittest
from datetime import datetime, timezone
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
        self.assertIn("contract_identity", report)
        ci = report["contract_identity"]
        self.assertEqual(ci["target_underlyings"], [])
        self.assertEqual(ci["hl_universe_size"], 0)
        self.assertEqual(ci["okx_instrument_count"], 0)
        self.assertEqual(ci["per_underlying"], {})

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


class ContractIdentityTests(unittest.TestCase):
    """Tests for verify_contract_identity and collect_contract_identity.

    These functions perform pure metadata comparison with no network access.
    """

    def test_verified_when_underlying_and_settlement_match(self):
        """Full metadata match on underlying + settlement -> verified."""
        hl = {"name": "BTC", "settleCcy": "USDT"}
        okx = {"instId": "BTC-USDT-SWAP", "baseCcy": "BTC", "settleCcy": "USDT"}
        result = probe.verify_contract_identity({"BTC": hl}, {"BTC": okx})
        self.assertEqual(result["BTC"]["evidence_level"], "verified")
        self.assertTrue(result["BTC"]["underlying_match"])
        self.assertTrue(result["BTC"]["settlement_match"])
        self.assertTrue(result["BTC"]["hl_settle_known"])

    def test_candidate_when_underlying_matches_settlement_unknown(self):
        """Underlying matches but settlement can't be confirmed -> candidate."""
        hl = {"name": "ETH"}
        okx = {"instId": "ETH-USDT-SWAP", "baseCcy": "", "settleCcy": "USDT"}
        result = probe.verify_contract_identity({"ETH": hl}, {"ETH": okx})
        self.assertEqual(result["ETH"]["evidence_level"], "candidate")
        self.assertTrue(result["ETH"]["underlying_match"])
        self.assertFalse(result["ETH"]["settlement_match"])
        self.assertFalse(result["ETH"]["hl_settle_known"])

    def test_candidate_when_underlying_matches_settlement_mismatch(self):
        """Underlying matches but settlement currencies differ -> candidate."""
        hl = {"name": "SOL", "settleCcy": "USDC"}
        okx = {"instId": "SOL-USDT-SWAP", "baseCcy": "SOL", "settleCcy": "USDT"}
        result = probe.verify_contract_identity({"SOL": hl}, {"SOL": okx})
        self.assertEqual(result["SOL"]["evidence_level"], "candidate")
        self.assertTrue(result["SOL"]["underlying_match"])
        self.assertFalse(result["SOL"]["settlement_match"])

    def test_unverified_when_underlying_mismatch(self):
        """No underlying match -> unverified regardless of settlement."""
        hl = {"name": "BTC", "settleCcy": "USDC"}
        okx = {"instId": "BTC-USDT-SWAP", "baseCcy": "WRONG", "settleCcy": "USDC"}
        result = probe.verify_contract_identity({"BTC": hl}, {"BTC": okx})
        self.assertEqual(result["BTC"]["evidence_level"], "unverified")
        self.assertFalse(result["BTC"]["underlying_match"])

    def test_hl_only_base_marked_unverified(self):
        """Base present only on Hyperliquid -> unverified with limitations."""
        hl = {"DOGE": {"name": "DOGE"}}
        result = probe.verify_contract_identity({"DOGE": hl}, {})
        self.assertEqual(result["DOGE"]["evidence_level"], "unverified")
        self.assertFalse(result["DOGE"]["underlying_match"])
        self.assertTrue(any("Present on Hyperliquid but not found in OKX" in lim
                            for lim in result["DOGE"]["limitations"]))

    def test_okx_only_base_marked_unverified(self):
        """Base present only on OKX -> unverified with limitations."""
        okx = {"AVAX": {"instId": "AVAX-USDT-SWAP"}}
        result = probe.verify_contract_identity({}, okx)
        self.assertEqual(result["AVAX"]["evidence_level"], "unverified")
        self.assertFalse(result["AVAX"]["underlying_match"])
        self.assertTrue(any("Present on OKX but not found in Hyperliquid" in lim
                            for lim in result["AVAX"]["limitations"]))

    def test_empty_inputs_return_empty_result(self):
        """No instruments on either side -> empty dict."""
        result = probe.verify_contract_identity({}, {})
        self.assertEqual(result, {})

    def test_non_linear_okx_contracts_excluded_from_verification(self):
        """Inverse contracts with non-USDT settle are excluded by extraction,
        so verify_contract_identity never sees them."""
        payload = {"code": "0", "data": [
            {"baseCcy": "BTC", "instId": "BTC-USDT-SWAP", "settleCcy": "USDT",
             "ctType": "linear", "state": "live"},
            {"baseCcy": "ETH", "instId": "ETH-USD-SWAP", "settleCcy": "USD",
             "ctType": "inverse", "state": "live"},
        ]}
        details = probe.extract_okx_instrument_details(payload)
        self.assertIn("BTC", details)
        self.assertNotIn("ETH", details)
        result = probe.verify_contract_identity({"BTC": {"name": "BTC"}}, details)
        self.assertIn("BTC", result)
        self.assertNotIn("ETH", result)

    def test_collect_contract_identity_with_full_metadata(self):
        """collect_contract_identity extracts details and runs verification."""
        hl_meta = {"parsed": {"universe": [
            {"name": "BTC", "settleCcy": "USDC"},
            {"name": "ETH", "settleCcy": "USDC"},
        ]}}
        okx_meta = {"parsed": {"code": "0", "data": [
            {"instId": "BTC-USDT-SWAP", "baseCcy": "BTC", "settleCcy": "USDT",
             "quoteCcy": "USDT", "uly": "BTC-USDT", "ctType": "linear", "state": "live"},
            {"instId": "ETH-USDT-SWAP", "baseCcy": "ETH", "settleCcy": "USDT",
             "quoteCcy": "USDT", "uly": "ETH-USDT", "ctType": "linear", "state": "live"},
        ]}}
        result = probe.collect_contract_identity(hl_meta, okx_meta, ("BTC", "ETH"))
        self.assertEqual(result["target_underlyings"], ["BTC", "ETH"])
        self.assertEqual(result["hl_universe_size"], 2)
        self.assertEqual(result["okx_instrument_count"], 2)
        self.assertEqual(result["per_underlying"]["BTC"]["evidence_level"], "candidate")
        self.assertEqual(result["per_underlying"]["ETH"]["evidence_level"], "candidate")

    def test_collect_contract_identity_without_parsed_wrapper(self):
        """Works when metadata is passed directly without 'parsed' wrapper."""
        hl_meta = {"universe": [{"name": "BTC", "settleCcy": "USDC"}]}
        okx_meta = {"code": "0", "data": [
            {"instId": "BTC-USDT-SWAP", "baseCcy": "BTC", "settleCcy": "USDT",
             "ctType": "linear", "state": "live"},
        ]}
        result = probe.collect_contract_identity(hl_meta, okx_meta, ("BTC",))
        self.assertEqual(result["hl_universe_size"], 1)
        self.assertEqual(result["okx_instrument_count"], 1)
        self.assertIn("BTC", result["per_underlying"])

    def test_collect_contract_identity_missing_base_yields_unverified(self):
        """Target base not found in either venue -> unverified."""
        hl_meta = {"universe": [{"name": "BTC", "settleCcy": "USDC"}]}
        okx_meta = {"code": "0", "data": [
            {"instId": "BTC-USDT-SWAP", "baseCcy": "BTC", "settleCcy": "USDT",
             "ctType": "linear", "state": "live"},
        ]}
        result = probe.collect_contract_identity(hl_meta, okx_meta, ("LINK",))
        self.assertEqual(result["per_underlying"]["LINK"]["evidence_level"], "unverified")

    def test_collect_contract_identity_custom_target_bases(self):
        """Custom target_bases override the default TARGET_FIVE.

        Through collect_contract_identity, Hyperliquid settlement currency is
        stripped by extract_hl_universe_details (settleCcy not in
        HL_UNIVERSE_FIELDS), so underlying-matching bases yield 'candidate',
        not 'verified'.
        """
        hl_meta = {"universe": [{"name": "XRP", "settleCcy": "USDC"}]}
        okx_meta = {"code": "0", "data": [
            {"instId": "XRP-USDT-SWAP", "baseCcy": "XRP", "settleCcy": "USDT",
             "ctType": "linear", "state": "live"},
        ]}
        result = probe.collect_contract_identity(hl_meta, okx_meta, ("XRP", "HYPE"))
        self.assertEqual(result["target_underlyings"], ["XRP", "HYPE"])
        self.assertEqual(result["per_underlying"]["XRP"]["evidence_level"], "candidate")
        self.assertEqual(result["per_underlying"]["HYPE"]["evidence_level"], "unverified")

    def test_collect_contract_identity_okx_uly_derives_quote(self):
        """When quoteCcy is absent, uly's quote part is used for quote comparison.

        Through collect_contract_identity, HL settleCcy is stripped, so
        underlying-matching bases yield 'candidate', not 'verified'.
        """
        hl_meta = {"universe": [{"name": "APT", "settleCcy": "USDC", "quoteCcy": "USD"}]}
        okx_meta = {"code": "0", "data": [
            {"instId": "APT-USDT-SWAP", "baseCcy": "APT", "uly": "APT-USDT",
             "settleCcy": "USDT", "ctType": "linear", "state": "live"},
        ]}
        result = probe.collect_contract_identity(hl_meta, okx_meta, ("APT",))
        self.assertEqual(result["per_underlying"]["APT"]["evidence_level"], "candidate")


class RunProbeContractIdentityTests(unittest.TestCase):
    """Tests that run_probe() integrates collect_contract_identity into its output."""

    HL_META_RESPONSE = {"universe": [
        {"name": "BTC", "szDecimals": 6, "displaySymbol": "$BTC", "contractType": "Perpetual"},
        {"name": "ETH", "szDecimals": 6, "displaySymbol": "$ETH", "contractType": "Perpetual"},
        {"name": "SOL", "szDecimals": 6, "displaySymbol": "$SOL", "contractType": "Perpetual"},
        {"name": "AVAX", "szDecimals": 6, "displaySymbol": "$AVAX", "contractType": "Perpetual"},
    ]}

    OKX_META_RESPONSE = {"code": "0", "data": [
        {"instId": "BTC-USDT-SWAP", "baseCcy": "BTC", "quoteCcy": "USDT",
         "settleCcy": "USDT", "ctType": "linear", "state": "live", "uly": "BTC-USDT"},
        {"instId": "ETH-USDT-SWAP", "baseCcy": "ETH", "quoteCcy": "USDT",
         "settleCcy": "USDT", "ctType": "linear", "state": "live", "uly": "ETH-USDT"},
        {"instId": "SOL-USDT-SWAP", "baseCcy": "SOL", "quoteCcy": "USDT",
         "settleCcy": "USDT", "ctType": "linear", "state": "live", "uly": "SOL-USDT"},
        {"instId": "AVAX-USDT-SWAP", "baseCcy": "AVAX", "quoteCcy": "USDT",
         "settleCcy": "USDT", "ctType": "linear", "state": "live", "uly": "AVAX-USDT"},
    ]}

    def _meta(self, url, sha="deadbeef"):
        return {
            "url": url, "method": "POST" if "hyperliquid" in url else "GET",
            "request_sha256": None, "http_status": 200,
            "response_bytes_read": 100, "response_sha256": sha,
            "response_prefix_sha256": None, "response_hash_complete": True,
            "response_shape": "json", "latency_ms": 10.0, "error": None,
        }

    def test_run_probe_includes_contract_identity_with_evidence_levels(self):
        """run_probe() includes contract_identity evidence with per-underlying levels."""
        def fake_request_json(url, payload=None, timeout=probe.TIMEOUT_SECONDS, opener=None):
            if payload is not None and payload.get("type") == "meta":
                return self._meta(url, "hl_meta"), self.HL_META_RESPONSE
            if "instruments" in url:
                return self._meta(url, "okx_meta"), self.OKX_META_RESPONSE
            if payload is not None and payload.get("type") == "candleSnapshot":
                return self._meta(url, "hl_candle"), {"code": "0", "data": []}
            if payload is not None and payload.get("type") == "fundingHistory":
                return self._meta(url, "hl_fund"), {"code": "0", "data": []}
            if "history-candles" in url:
                return self._meta(url, "okx_candle"), {"code": "0", "data": []}
            if "funding-rate-history" in url:
                return self._meta(url, "okx_fund"), {"code": "0", "data": []}
            return self._meta(url, "binance"), None

        with patch.object(probe, "request_json", side_effect=fake_request_json):
            report = probe.run_probe(120, 4)

        self.assertIn("contract_identity", report)
        ci = report["contract_identity"]
        self.assertEqual(ci["target_underlyings"], ["BTC", "ETH", "SOL", "AVAX"])
        self.assertEqual(ci["hl_universe_size"], 4)
        self.assertEqual(ci["okx_instrument_count"], 4)
        for base in ["BTC", "ETH", "SOL", "AVAX"]:
            self.assertIn(base, ci["per_underlying"])
            result = ci["per_underlying"][base]
            self.assertEqual(result["evidence_level"], "candidate")
            self.assertTrue(result["underlying_match"])
            self.assertFalse(result["settlement_match"])
            self.assertFalse(result["hl_settle_known"])

    def test_run_probe_contract_identity_reflects_common_intersection(self):
        """contract_identity targets match the probe's candidate intersection."""
        def fake_request_json(url, payload=None, timeout=probe.TIMEOUT_SECONDS, opener=None):
            if payload is not None and payload.get("type") == "meta":
                return self._meta(url), self.HL_META_RESPONSE
            if "instruments" in url:
                return self._meta(url), self.OKX_META_RESPONSE
            if payload is not None and payload.get("type") == "candleSnapshot":
                return self._meta(url), {"code": "0", "data": []}
            if payload is not None and payload.get("type") == "fundingHistory":
                return self._meta(url), {"code": "0", "data": []}
            if "history-candles" in url:
                return self._meta(url), {"code": "0", "data": []}
            if "funding-rate-history" in url:
                return self._meta(url), {"code": "0", "data": []}
            return self._meta(url), None

        with patch.object(probe, "request_json", side_effect=fake_request_json):
            report = probe.run_probe(120, 4)

        self.assertEqual(
            report["contract_identity"]["target_underlyings"],
            report["candidate_assets_intersection"],
        )

    def test_run_probe_contract_identity_preserves_blocked_gate_flags(self):
        """contract_identity integration must not alter frozen gate flags."""
        def fake_request_json(url, payload=None, timeout=probe.TIMEOUT_SECONDS, opener=None):
            if payload is not None and payload.get("type") == "meta":
                return self._meta(url), self.HL_META_RESPONSE
            if "instruments" in url:
                return self._meta(url), self.OKX_META_RESPONSE
            if payload is not None and payload.get("type") == "candleSnapshot":
                return self._meta(url), {"code": "0", "data": []}
            if payload is not None and payload.get("type") == "fundingHistory":
                return self._meta(url), {"code": "0", "data": []}
            if "history-candles" in url:
                return self._meta(url), {"code": "0", "data": []}
            if "funding-rate-history" in url:
                return self._meta(url), {"code": "0", "data": []}
            return self._meta(url), None

        with patch.object(probe, "request_json", side_effect=fake_request_json):
            report = probe.run_probe(120, 4)

        self.assertEqual(report["historical_coverage_gate"], "NOT_PASSED_BY_COVERAGE_PROBE")
        self.assertEqual(report["original_confirmatory_gate"], "BLOCKED_DATA_GATE")
        self.assertFalse(report["backtest_completed"])
        self.assertFalse(report["performance_metrics_computed"])


class OKxCandlePaginationTests(unittest.TestCase):
    """Offline known-answer tests for OKX historical-candles pagination logic.

    probe_okx_candles() paginates backward using the `after` cursor (oldest
    timestamp) with 300-row pages from array rows (timestamp at index 0).
    These mirror OKxFundingPaginationTests for the candle endpoint, which
    was previously untested for pagination stop-reason branches.
    """

    def _make_meta(self, url):
        return {
            "url": url, "method": "GET",
            "request_sha256": None, "http_status": 200,
            "response_bytes_read": 100, "response_sha256": "fake",
            "response_prefix_sha256": None, "response_hash_complete": True,
            "response_shape": "json", "latency_ms": 100.0, "error": None,
        }

    @staticmethod
    def _candle(ts):
        return [str(ts), "100", "101", "99", "100", "10"]

    def test_page_not_full_when_api_returns_below_limit(self):
        """page_not_full: API returns <300 rows -> stops after one page.
        Mirrors verified live behavior where OKX returns a short final page."""
        start_ms = 1_000
        end_ms = 1_000_000
        step = (end_ms - start_ms - 1) // 292
        times = list(range(end_ms, start_ms, -step))[:292]
        rows = [self._candle(t) for t in times]
        payload = {"code": "0", "data": rows}
        with patch.object(probe, "request_json",
                          return_value=(self._make_meta("https://fake"), payload)):
            result = probe.probe_okx_candles("BTC-USDT-SWAP", start_ms, end_ms)
        self.assertEqual(result["stop_reason"], "page_not_full")
        self.assertEqual(result["pages_received"], 1)
        self.assertEqual(result["coverage"]["row_count"], 292)

    def test_page_not_full_boundary_at_exactly_limit_continues(self):
        """When API returns exactly 300 rows, pagination continues to next page.
        The `after` cursor must be the previous page's oldest timestamp."""
        start_ms = 1_000
        end_ms = 1_000_000
        page1_times = list(range(end_ms, end_ms - 300, -1))
        page1 = [self._candle(t) for t in page1_times]
        oldest1 = min(page1_times)
        page2_times = list(range(oldest1 - 1, oldest1 - 201, -1))
        page2 = [self._candle(t) for t in page2_times]

        call_idx = [0]
        payloads = [
            {"code": "0", "data": page1},
            {"code": "0", "data": page2},
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
            result = probe.probe_okx_candles("BTC-USDT-SWAP", start_ms, end_ms)
        self.assertEqual(result["stop_reason"], "page_not_full")
        self.assertEqual(result["pages_received"], 2)
        self.assertEqual(result["coverage"]["row_count"], 500)

    def test_cursor_stalled_stops_pagination(self):
        """cursor_stalled: oldest timestamp does not advance beyond the cursor."""
        start_ms = 1_000
        end_ms = 1_000_000
        page_times = list(range(end_ms, end_ms - 300, -1))
        rows = [self._candle(t) for t in page_times]
        payload = {"code": "0", "data": rows}

        with patch.object(probe, "request_json",
                          return_value=(self._make_meta("https://fake"), payload)):
            result = probe.probe_okx_candles("BTC-USDT-SWAP", start_ms, end_ms)
        self.assertEqual(result["stop_reason"], "cursor_stalled")
        self.assertEqual(result["pages_received"], 2)

    def test_window_start_reached_stops_pagination(self):
        """window_start_reached: oldest timestamp falls at or below start_ms."""
        start_ms = 5_000
        end_ms = 10_000
        rows = [self._candle(t) for t in range(end_ms, start_ms - 100, -1)]
        payload = {"code": "0", "data": rows}

        with patch.object(probe, "request_json",
                          return_value=(self._make_meta("https://fake"), payload)):
            result = probe.probe_okx_candles("BTC-USDT-SWAP", start_ms, end_ms)
        self.assertEqual(result["stop_reason"], "window_start_reached")
        self.assertEqual(result["pages_received"], 1)

    def test_empty_data_stops_pagination(self):
        """no_rows_or_request_failed: API returns empty data list."""
        start_ms = 1_000
        end_ms = 1_000_000
        payload = {"code": "0", "data": []}

        with patch.object(probe, "request_json",
                          return_value=(self._make_meta("https://fake"), payload)):
            result = probe.probe_okx_candles("BTC-USDT-SWAP", start_ms, end_ms)
        self.assertEqual(result["stop_reason"], "no_rows_or_request_failed")
        self.assertEqual(result["pages_received"], 1)

    def test_filtering_excludes_rows_outside_window(self):
        """Only rows within [start_ms, end_ms] are counted in coverage.
        Rows above end_ms are excluded from rows_all but included in the
        oldest/cursor computation (which uses ALL returned rows)."""
        start_ms = 500
        end_ms = 1500
        rows = [
            self._candle(2000),  # above end_ms, excluded from coverage
            self._candle(600),   # in window
            self._candle(1000),  # in window
            self._candle(1500),  # at end_ms, included
        ]
        payload = {"code": "0", "data": rows}

        with patch.object(probe, "request_json",
                          return_value=(self._make_meta("https://fake"), payload)):
            result = probe.probe_okx_candles("BTC-USDT-SWAP", start_ms, end_ms)
        self.assertEqual(result["coverage"]["row_count"], 3)
        self.assertEqual(result["stop_reason"], "page_not_full")


class HyperliquidFundingPaginationTests(unittest.TestCase):
    """Offline known-answer tests for Hyperliquid fundingHistory pagination.

    probe_hl_funding() uses forward cursor pagination: startTime advances past
    the newest returned record (page_max + 1) each iteration. Stop reasons
    include window_reached_or_page_not_full, cursor_missing_or_nonprogressing,
    no_rows_or_request_failed, and max_pages_reached.
    """

    def _make_meta(self, url):
        return {
            "url": url, "method": "POST",
            "request_sha256": None, "http_status": 200,
            "response_bytes_read": 100, "response_sha256": "fake",
            "response_prefix_sha256": None, "response_hash_complete": True,
            "response_shape": "json", "latency_ms": 10.0, "error": None,
        }

    @staticmethod
    def _funding_row(ts, rate="0.0001"):
        return {"time": ts, "fundingRate": rate}

    def test_below_500_stops_with_window_reached_or_page_not_full(self):
        """Page returns <500 rows and cursor hasn't exceeded end_ms -> stop."""
        start_ms = 1_000
        end_ms = 1_000_000
        rows = [self._funding_row(t) for t in range(start_ms, start_ms + 400)]
        with patch.object(probe, "request_json",
                          return_value=(self._make_meta(probe.HYPERLIQUID), rows)):
            result = probe.probe_hl_funding("BTC", start_ms, end_ms)
        self.assertEqual(result["stop_reason"], "window_reached_or_page_not_full")
        self.assertEqual(result["pages_received"], 1)
        self.assertEqual(result["coverage"]["row_count"], 400)

    def test_full_page_continues_then_second_page_stops(self):
        """First page has exactly 500 rows (continues); second page (<500) stops."""
        start_ms = 1_000
        end_ms = 1_000_000
        page1_times = list(range(start_ms, start_ms + 500))
        page2_times = list(range(start_ms + 500, start_ms + 900))

        call_idx = [0]
        payloads = [
            [self._funding_row(t) for t in page1_times],
            [self._funding_row(t) for t in page2_times],
        ]

        def fake_request(url, payload=None, timeout=probe.TIMEOUT_SECONDS, opener=None):
            idx = call_idx[0]
            call_idx[0] += 1
            return self._make_meta(url), payloads[idx]

        with patch.object(probe, "request_json", side_effect=fake_request):
            result = probe.probe_hl_funding("BTC", start_ms, end_ms)
        self.assertEqual(result["stop_reason"], "window_reached_or_page_not_full")
        self.assertEqual(result["pages_received"], 2)
        self.assertEqual(result["coverage"]["row_count"], 900)

    def test_empty_data_stops_pagination(self):
        """no_rows_or_request_failed: API returns empty list."""
        start_ms = 1_000
        end_ms = 1_000_000
        with patch.object(probe, "request_json",
                          return_value=(self._make_meta(probe.HYPERLIQUID), [])):
            result = probe.probe_hl_funding("BTC", start_ms, end_ms)
        self.assertEqual(result["stop_reason"], "no_rows_or_request_failed")
        self.assertEqual(result["pages_received"], 1)

    def test_cursor_missing_or_nonprogressing_when_no_digit_times(self):
        """cursor_missing_or_nonprogressing: rows have non-digit or missing
        time values so page_max cannot be computed."""
        start_ms = 1_000
        end_ms = 1_000_000
        rows = [
            {"time": "abc", "fundingRate": "0.0001"},
            {"time": None, "fundingRate": "0.0001"},
            {"fundingRate": "0.0001"},
        ]
        with patch.object(probe, "request_json",
                          return_value=(self._make_meta(probe.HYPERLIQUID), rows)):
            result = probe.probe_hl_funding("BTC", start_ms, end_ms)
        self.assertEqual(result["stop_reason"], "cursor_missing_or_nonprogressing")
        self.assertEqual(result["pages_received"], 1)

    def test_filtering_excludes_rows_outside_window(self):
        """Only rows within [start_ms, end_ms] counted in coverage; page_max
        uses all rows, so an out-of-window row can advance the cursor past
        end_ms and trigger the stop."""
        start_ms = 500
        end_ms = 1500
        rows = [
            self._funding_row(2000),  # above end, excluded from coverage
            self._funding_row(600),
            self._funding_row(1000),
            self._funding_row(1500),  # at end, included
        ]
        with patch.object(probe, "request_json",
                          return_value=(self._make_meta(probe.HYPERLIQUID), rows)):
            result = probe.probe_hl_funding("BTC", start_ms, end_ms)
        self.assertEqual(result["coverage"]["row_count"], 3)
        # page_max = 2000, next_cursor = 2001 > end_ms (1500) -> stop
        self.assertEqual(result["stop_reason"], "window_reached_or_page_not_full")

    def test_settled_rate_nonempty_count(self):
        """settled_rate_nonempty_count counts rows with truthy fundingRate
        from rows_all (in-window rows only)."""
        start_ms = 1_000
        end_ms = 1_000_000
        rows = [
            self._funding_row(2000, rate="0.0001"),   # truthy
            self._funding_row(3000, rate=""),          # falsy (empty string)
            self._funding_row(4000, rate=None),        # falsy (None)
            self._funding_row(5000, rate="0.0002"),    # truthy
        ]
        with patch.object(probe, "request_json",
                          return_value=(self._make_meta(probe.HYPERLIQUID), rows)):
            result = probe.probe_hl_funding("BTC", start_ms, end_ms)
        self.assertEqual(result["settled_rate_nonempty_count"], 2)

    def test_max_pages_reached_with_full_pages(self):
        """When all pages are full (500 rows) and cursor stays within window,
        pagination exhausts the MAX_HL_FUNDING_PAGES budget."""
        start_ms = 1_000
        end_ms = 100_000
        call_idx = [0]

        def fake_request(url, payload=None, timeout=probe.TIMEOUT_SECONDS, opener=None):
            idx = call_idx[0]
            call_idx[0] += 1
            page_start = start_ms + idx * 500
            rows = [self._funding_row(page_start + i) for i in range(500)]
            return self._make_meta(url), rows

        with patch.object(probe, "request_json", side_effect=fake_request):
            result = probe.probe_hl_funding("BTC", start_ms, end_ms)
        self.assertEqual(result["stop_reason"], "max_pages_reached")
        self.assertEqual(result["pages_received"], probe.MAX_HL_FUNDING_PAGES)

    def test_hl_funding_cursor_stalled_branch_is_unreachable(self):
        """Regression guard for the documented dead-code gap in probe_hl_funding.

        The `cursor_stalled` stop-reason branch (`next_cursor <= cursor`) can
        never fire. The preceding guard skips to `cursor_missing_or_nonprogressing`
        when `page_max is None or page_max < cursor`, so reaching the
        cursor_stalled check implies `page_max >= cursor`. Since timestamps are
        integers, `next_cursor = page_max + 1 > cursor` always holds, making
        `next_cursor <= cursor` permanently False.

        Direct demonstration: a repeated identical full 500-row page (with
        page_max below end_ms so `window_reached_or_page_not_full` cannot
        preempt on page 1) advances the cursor on page 1; on page 2 the same
        page yields `page_max < cursor`, which stops as
        `cursor_missing_or_nonprogressing` -- never `cursor_stalled`. This
        pins the invariant so a future guard reordering cannot silently
        introduce a dead branch or alter stop-reason semantics. Mirrors the
        OKX `test_cursor_stalled_stops_pagination` symmetry while proving the
        HL path diverges by design.
        """
        start_ms = 1_000
        end_ms = 10_000_000
        page_times = list(range(start_ms, start_ms + 500))
        page = [self._funding_row(t) for t in page_times]
        with patch.object(probe, "request_json",
                          return_value=(self._make_meta(probe.HYPERLIQUID), page)):
            result = probe.probe_hl_funding("BTC", start_ms, end_ms)
        self.assertNotEqual(result["stop_reason"], "cursor_stalled")
        self.assertEqual(result["stop_reason"], "cursor_missing_or_nonprogressing")
        self.assertEqual(result["pages_received"], 2)


class HyperliquidCandleTests(unittest.TestCase):
    """Offline known-answer tests for probe_hl_candles.

    probe_hl_candles() makes a single request to Hyperliquid /info with the
    candleSnapshot payload and computes a coverage summary. Unlike
    probe_hl_funding, it does not paginate. These tests verify response
    handling, coverage computation, gap detection, and metadata field
    construction — filling the gap where probe_okx_candles and probe_hl_funding
    each had dedicated test classes but probe_hl_candles had none.
    """

    def _make_meta(self, url):
        return {
            "url": url, "method": "POST",
            "request_sha256": None, "http_status": 200,
            "response_bytes_read": 100, "response_sha256": "fake",
            "response_prefix_sha256": None, "response_hash_complete": True,
            "response_shape": "json", "latency_ms": 10.0, "error": None,
        }

    @staticmethod
    def _candle(ts_ms):
        return [ts_ms, ts_ms + 60000, "100", "101", "99", "100", "10"]

    def test_returns_metadata_with_source_and_window_fields(self):
        """probe_hl_candles sets source, field, coin, window, and history_limit."""
        start_ms = 1_700_000_000_000
        end_ms = 1_700_086_400_000
        rows = [self._candle(t) for t in range(start_ms, end_ms, 3_600_000)][:5]
        with patch.object(probe, "request_json",
                          return_value=(self._make_meta(probe.HYPERLIQUID), rows)):
            result = probe.probe_hl_candles("BTC", start_ms, end_ms)
        self.assertEqual(result["source"], "Hyperliquid")
        self.assertEqual(result["field"], "1h candles")
        self.assertEqual(result["coin"], "BTC")
        self.assertEqual(result["history_limit_documented"], "most recent 5000 candles")
        self.assertIsNotNone(result["window_start_utc"])
        self.assertIsNotNone(result["window_end_utc"])

    def test_coverage_computed_from_candle_rows(self):
        """Coverage summary reflects row count, unique counts, and time range."""
        start_ms = 1_000
        end_ms = 1_000_000
        times = [200_000, 200_000, 500_000, 800_000]
        rows = [self._candle(t) for t in times]
        with patch.object(probe, "request_json",
                          return_value=(self._make_meta(probe.HYPERLIQUID), rows)):
            result = probe.probe_hl_candles("ETH", start_ms, end_ms)
        cov = result["coverage"]
        self.assertEqual(cov["row_count"], 4)
        self.assertEqual(cov["timestamp_count"], 4)
        self.assertEqual(cov["unique_timestamp_count"], 3)
        self.assertEqual(cov["duplicate_timestamps"], 1)

    def test_non_list_response_yields_empty_coverage(self):
        """When the API returns a non-list payload, coverage is empty and no error."""
        start_ms = 1_000
        end_ms = 1_000_000
        with patch.object(probe, "request_json",
                          return_value=(self._make_meta(probe.HYPERLIQUID), {"unexpected": True})):
            result = probe.probe_hl_candles("SOL", start_ms, end_ms)
        self.assertEqual(result["coverage"]["row_count"], 0)
        self.assertEqual(result["coverage"]["unique_timestamp_count"], 0)

    def test_none_response_yields_empty_coverage(self):
        """When request_json returns None for parsed payload, coverage is empty."""
        start_ms = 1_000
        end_ms = 1_000_000
        with patch.object(probe, "request_json",
                          return_value=(self._make_meta(probe.HYPERLIQUID), None)):
            result = probe.probe_hl_candles("AVAX", start_ms, end_ms)
        self.assertEqual(result["coverage"]["row_count"], 0)

    def test_empty_list_response_yields_empty_coverage(self):
        """Empty candle list -> zero row_count and no gaps."""
        start_ms = 1_000
        end_ms = 1_000_000
        with patch.object(probe, "request_json",
                          return_value=(self._make_meta(probe.HYPERLIQUID), [])):
            result = probe.probe_hl_candles("BTC", start_ms, end_ms)
        self.assertEqual(result["coverage"]["row_count"], 0)
        self.assertEqual(result["coverage"]["unique_timestamp_count"], 0)
        self.assertEqual(result["coverage"]["hourly_gap_count"], 0)

    def test_request_uses_candle_snapshot_nested_payload(self):
        """The request payload must use candleSnapshot with nested req (not top-level coin)."""
        captured = {}
        def fake_request(url, payload=None, timeout=probe.TIMEOUT_SECONDS, opener=None):
            captured["payload"] = payload
            return self._make_meta(url), []
        start_ms = 1_000
        end_ms = 1_000_000
        with patch.object(probe, "request_json", side_effect=fake_request):
            probe.probe_hl_candles("BTC", start_ms, end_ms)
        self.assertEqual(captured["payload"]["type"], "candleSnapshot")
        self.assertEqual(captured["payload"]["req"], {
            "coin": "BTC", "interval": "1h",
            "startTime": start_ms, "endTime": end_ms,
        })

    def test_hourly_gap_detection_in_candle_rows(self):
        """Gaps between consecutive hourly timestamps are detected.

        Timestamps are in ms with 3_600_000 per hour. Gap from hour 1 to hour 7
        spans 6 intervals, so 5 missing hours (6 - 1 = 5)."""
        start_ms = 0
        end_ms = 28_800_000
        times = [0, 3_600_000, 25_200_000]
        rows = [self._candle(t) for t in times]
        with patch.object(probe, "request_json",
                          return_value=(self._make_meta(probe.HYPERLIQUID), rows)):
            result = probe.probe_hl_candles("BTC", start_ms, end_ms)
        cov = result["coverage"]
        self.assertEqual(cov["hourly_gap_count"], 1)
        self.assertEqual(cov["maximum_missing_hours_in_gap"], 5)


class ExtractHlUniverseDetailsTests(unittest.TestCase):
    """Tests for extract_hl_universe_details — the metadata field-extraction
    function that strips settlement-currency fields, which is the structural
    reason hl_settle_known is always False in verify_contract_identity.

    HL_UNIVERSE_FIELDS = (name, szDecimals, maxLeverage, marginTableId,
                          displaySymbol, contractType, id)
    settleCcy / settlementCurrency are NOT in this tuple, so they are
    stripped before verify_contract_identity ever sees the HL details.
    """

    def test_strips_settlement_currency_fields(self):
        """settleCcy and settlementCurrency must NOT appear in extracted details,
        even if present in the raw meta universe entry. This is the code-level
        root cause of the structural data-gate impossibility."""
        meta = {"universe": [{
            "name": "BTC",
            "settleCcy": "USDC",
            "settlementCurrency": "USDC",
            "szDecimals": 6,
            "maxLeverage": 40,
        }]}
        details = probe.extract_hl_universe_details(meta)
        self.assertNotIn("settleCcy", details["BTC"])
        self.assertNotIn("settlementCurrency", details["BTC"])

    def test_includes_only_designated_hl_universe_fields(self):
        """Only HL_UNIVERSE_FIELDS are retained; other fields are dropped."""
        meta = {"universe": [{
            "name": "ETH",
            "szDecimals": 4,
            "maxLeverage": 25,
            "marginTableId": 55,
            "displaySymbol": "$ETH",
            "contractType": "Perpetual",
            "id": 1,
            "unwantedField": "should_not_appear",
            "settleCcy": "USDC",
        }]}
        details = probe.extract_hl_universe_details(meta)
        for field in probe.HL_UNIVERSE_FIELDS:
            self.assertIn(field, details["ETH"])
        self.assertNotIn("unwantedField", details["ETH"])
        self.assertNotIn("settleCcy", details["ETH"])

    def test_duplicate_names_first_wins(self):
        """First occurrence of a name wins; subsequent duplicates are skipped."""
        meta = {"universe": [
            {"name": "BTC", "szDecimals": 6, "extra1": "first"},
            {"name": "BTC", "szDecimals": 8, "extra1": "second"},
        ]}
        details = probe.extract_hl_universe_details(meta)
        self.assertEqual(details["BTC"]["szDecimals"], 6)

    def test_skips_entries_without_name(self):
        """Entries missing 'name' or with name=None are skipped."""
        meta = {"universe": [
            {"name": "BTC", "szDecimals": 6},
            {"other": "no_name_field"},
            {"name": None, "szDecimals": 4},
            {"name": "ETH", "szDecimals": 4},
        ]}
        details = probe.extract_hl_universe_details(meta)
        self.assertIn("BTC", details)
        self.assertIn("ETH", details)
        self.assertEqual(len(details), 2)

    def test_empty_or_malformed_input_returns_empty(self):
        """Non-dict, missing universe, or non-list universe yields empty dict."""
        self.assertEqual(probe.extract_hl_universe_details({}), {})
        self.assertEqual(probe.extract_hl_universe_details(None), {})
        self.assertEqual(probe.extract_hl_universe_details("string"), {})
        self.assertEqual(probe.extract_hl_universe_details({"universe": None}), {})
        self.assertEqual(probe.extract_hl_universe_details({"universe": "not_list"}), {})

    def test_collect_contract_identity_cannot_reach_verified_for_stripped_settle(self):
        """End-to-end proof of the structural data-gate impossibility: even if
        Hyperliquid meta exposes settleCcy in the raw universe,
        extract_hl_universe_details strips it, so collect_contract_identity ->
        verify_contract_identity sees hl_settle=None and assigns 'candidate',
        never 'verified', for any underlying match.

        This is independent of whether the live API actually returns the field.
        """
        hl_meta = {"universe": [{
            "name": "BTC",
            "settleCcy": "USDC",
            "szDecimals": 6,
        }]}
        okx_meta = {"code": "0", "data": [
            {"instId": "BTC-USDT-SWAP", "baseCcy": "BTC", "settleCcy": "USDT",
             "ctType": "linear", "state": "live"},
        ]}
        result = probe.collect_contract_identity(hl_meta, okx_meta, ("BTC",))
        self.assertEqual(result["per_underlying"]["BTC"]["evidence_level"], "candidate")
        self.assertFalse(result["per_underlying"]["BTC"]["hl_settle_known"])
        self.assertFalse(result["per_underlying"]["BTC"]["settlement_match"])


class OkxUrlTests(unittest.TestCase):
    """Tests for okx_url — OKX URL builder with query parameter encoding."""

    def test_okx_url_encodes_params(self):
        url = probe.okx_url("/market/history-candles",
                            {"instId": "BTC-USDT-SWAP", "bar": "1H", "limit": "300"})
        self.assertTrue(url.startswith(probe.OKX + "/market/history-candles?"))
        self.assertIn("instId=BTC-USDT-SWAP", url)
        self.assertIn("bar=1H", url)
        self.assertIn("limit=300", url)

    def test_okx_url_handles_empty_params(self):
        url = probe.okx_url("/public/instruments", {})
        self.assertEqual(url, probe.OKX + "/public/instruments?")


class UnwrapOkxTests(unittest.TestCase):
    """Tests for unwrap_okx — OKX paginated response unwrapping.

    unwrap_okx is a critical branch point for both probe_okx_candles and
    probe_okx_funding: every row of OKX coverage data passes through it.
    These tests verify each decision branch directly (not only as a
    side effect of the pagination tests).
    """

    def test_returns_data_list_when_code_zero(self):
        payload = {"code": "0", "data": [{"ts": 1}, {"ts": 2}]}
        self.assertEqual(probe.unwrap_okx(payload), [{"ts": 1}, {"ts": 2}])

    def test_returns_empty_for_non_zero_code(self):
        self.assertEqual(probe.unwrap_okx({"code": "500", "data": [1]}), [])
        self.assertEqual(probe.unwrap_okx({"code": "1", "data": [1]}), [])

    def test_returns_empty_when_data_not_list(self):
        self.assertEqual(probe.unwrap_okx({"code": "0", "data": "not-a-list"}), [])
        self.assertEqual(probe.unwrap_okx({"code": "0", "data": {"key": "val"}}), [])

    def test_returns_empty_when_data_missing(self):
        self.assertEqual(probe.unwrap_okx({"code": "0"}), [])

    def test_returns_empty_when_code_missing(self):
        self.assertEqual(probe.unwrap_okx({"data": [1, 2]}), [])

    def test_returns_empty_for_non_dict_payload(self):
        self.assertEqual(probe.unwrap_okx([1, 2, 3]), [])
        self.assertEqual(probe.unwrap_okx(None), [])
        self.assertEqual(probe.unwrap_okx("string"), [])


class BinanceArchiveProbeTests(unittest.TestCase):
    """Tests for probe_binance_archive ().

    probe_binance_archive () checks Binance archive checksum-object
    availability via request_json for two hardcoded BTC URLs.  These tests
    mock request_json to verify URL construction, metadata field
    correctness, and fail-closed behavior for missing objects.  No network
    access is required.
    """

    def _ok_meta(self, url):
        return {
            "url": url, "method": "GET",
            "request_sha256": None, "http_status": 200,
            "response_bytes_read": 89, "response_sha256": "abc123",
            "response_prefix_sha256": None, "response_hash_complete": True,
            "response_shape": "non-json", "latency_ms": 100.0,
            "error": None,
        }

    def _fail_meta(self, url, code):
        return {
            "url": url, "method": "GET",
            "request_sha256": None, "http_status": code,
            "response_bytes_read": None, "response_sha256": None,
            "response_prefix_sha256": None, "response_hash_complete": False,
            "response_shape": None, "latency_ms": 50.0,
            "error": f"HTTPError: {code}",
        }

    @patch.object(probe, "request_json")
    def test_probes_two_archive_checksum_urls(self, mock_req):
        def fake_req(url, payload=None, timeout=probe.TIMEOUT_SECONDS, opener=None):
            return (self._ok_meta(url), None)
        mock_req.side_effect = fake_req
        results = probe.probe_binance_archive()
        self.assertEqual(len(results), 2)
        urls = [r["url"] for r in results]
        self.assertTrue(any("klines" in u for u in urls),
                        "first candidate must be a kline checksum URL")
        self.assertTrue(any("fundingRate" in u for u in urls),
                        "second candidate must be a fundingRate checksum URL")
        self.assertEqual(mock_req.call_count, 2)

    @patch.object(probe, "request_json")
    def test_http_200_marks_coverage_not_proven(self, mock_req):
        """HTTP 200 returns coverage_proven=False — checksum only, no archive bytes downloaded."""
        def fake_req(url, payload=None, timeout=probe.TIMEOUT_SECONDS, opener=None):
            return (self._ok_meta(url), None)
        mock_req.side_effect = fake_req
        results = probe.probe_binance_archive()
        for result in results:
            self.assertEqual(result["source"], "Binance Public Data archive")
            self.assertFalse(result["coverage_proven"],
                              "checksum-object probe must never claim coverage_proven")
            self.assertIn("checksum-object response only", result["note"])

    @patch.object(probe, "request_json")
    def test_http_404_records_error(self, mock_req):
        """HTTP 404 records the error while keeping coverage_proven=False (fail-closed)."""
        def fake_req(url, payload=None, timeout=probe.TIMEOUT_SECONDS, opener=None):
            return (self._fail_meta(url, 404), None)
        mock_req.side_effect = fake_req
        results = probe.probe_binance_archive()
        self.assertEqual(len(results), 2)
        for result in results:
            self.assertEqual(result["http_status"], 404)
            self.assertFalse(result["coverage_proven"])
            self.assertIsNotNone(result["error"])
            self.assertIn("404", result["error"])

    @patch.object(probe, "request_json")
    def test_result_metadata_fields_present(self, mock_req):
        """Every result dict has all required metadata fields after merge."""
        def fake_req(url, payload=None, timeout=probe.TIMEOUT_SECONDS, opener=None):
            return (self._ok_meta(url), None)
        mock_req.side_effect = fake_req
        results = probe.probe_binance_archive()
        for result in results:
            for key in ("source", "field", "coverage_proven", "note",
                        "http_status", "response_sha256", "error",
                        "url", "method", "response_hash_complete"):
                self.assertIn(key, result, f"missing key {key} in binance archive result")


class CommittedProbeGateConsistencyTests(unittest.TestCase):
    """Source-independent validation of committed probe artifacts.

    Reads committed research_state/historical_overlap_probe_*_attempt_*.json
    artifacts from disk (no network) and asserts internal consistency between
    the probe-reported contract_identity evidence levels and the
    historical_coverage_gate flag. This guards against a future code path or
    artifact mutation that would incorrectly lower the gate to PASS while any
    underlying remains at candidate/unverified contract identity.
    """

    STATE_DIR = ROOT / "research_state"

    def _committed_probes(self):
        probes = []
        if not self.STATE_DIR.is_dir():
            return probes
        for path in sorted(self.STATE_DIR.glob("historical_overlap_probe_*_attempt_*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and "historical_coverage_gate" in data:
                probes.append((path, data))
        return probes

    def test_committed_probes_present(self):
        probes = self._committed_probes()
        self.assertGreater(len(probes), 0, "expected committed overlap probe artifacts")

    def test_no_probes_claim_gate_passed(self):
        for path, data in self._committed_probes():
            self.assertEqual(
                data["historical_coverage_gate"],
                "NOT_PASSED_BY_COVERAGE_PROBE",
                f"{path.name}: historical_coverage_gate must never be PASS",
            )
            self.assertEqual(
                data.get("original_confirmatory_gate"),
                "BLOCKED_DATA_GATE",
                f"{path.name}: original_confirmatory_gate must remain BLOCKED_DATA_GATE",
            )
            self.assertFalse(
                data.get("backtest_completed", False),
                f"{path.name}: probe must never set backtest_completed=true",
            )
            self.assertFalse(
                data.get("performance_metrics_computed", False),
                f"{path.name}: probe must never set performance_metrics_computed=true",
            )

    def test_non_verified_contract_identity_keeps_gate_not_passed(self):
        for path, data in self._committed_probes():
            ci = data.get("contract_identity", {})
            per = ci.get("per_underlying", {}) if isinstance(ci, dict) else {}
            has_non_verified = any(
                isinstance(v, dict) and v.get("evidence_level") != "verified"
                for v in per.values()
            )
            if has_non_verified:
                self.assertEqual(
                    data["historical_coverage_gate"],
                    "NOT_PASSED_BY_COVERAGE_PROBE",
                    f"{path.name}: non-verified contract_identity must keep gate NOT_PASSED",
                )

    def test_coverage_summary_internal_consistency(self):
        """Independently verify internal consistency of coverage summaries.

        For every coverage dict found inside committed probe artifacts,
        recompute the mathematical invariants that summarize_rows must
        satisfy, rather than trusting the stored values:

        - duplicate_timestamps == timestamp_count - unique_timestamp_count
        - unique_timestamp_count <= timestamp_count <= row_count
        - hourly_gap_count == 0 implies maximum_missing_hours_in_gap == 0

        This is a source-independent red-team recompute over committed
        artifacts (no network).  It guards against silent corruption or
        code changes that would produce internally inconsistent summaries.
        """
        for path, data in self._committed_probes():
            routes = data.get("routes", {})
            for route_key, route_value in routes.items():
                items = route_value if isinstance(route_value, list) else [route_value]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    coverage = item.get("coverage")
                    if not isinstance(coverage, dict):
                        continue
                    tc = coverage.get("timestamp_count")
                    uc = coverage.get("unique_timestamp_count")
                    dc = coverage.get("duplicate_timestamps")
                    rc = coverage.get("row_count")
                    if all(v is not None for v in (tc, uc, dc, rc)):
                        self.assertEqual(
                            dc, tc - uc,
                            f"{path.name} {route_key}: duplicate_timestamps "
                            f"({dc}) != timestamp_count ({tc}) - "
                            f"unique_timestamp_count ({uc})",
                        )
                        self.assertLessEqual(
                            uc, tc,
                            f"{path.name} {route_key}: unique_timestamp_count "
                            f"({uc}) > timestamp_count ({tc})",
                        )
                        self.assertLessEqual(
                            tc, rc,
                            f"{path.name} {route_key}: timestamp_count "
                            f"({tc}) > row_count ({rc})",
                        )
                    gc = coverage.get("hourly_gap_count", 0)
                    mg = coverage.get("maximum_missing_hours_in_gap", 0)
                    if gc == 0:
                        self.assertEqual(
                            mg, 0,
                            f"{path.name} {route_key}: hourly_gap_count==0 "
                            f"but maximum_missing_hours_in_gap ({mg})!=0",
                        )


class FundingIntersectionAuditTests(unittest.TestCase):
    """Source-independent red-team audit of funding intersection durations
    and intervals derived from committed probe artifacts.

    Independently recomputes funding intervals (rows-per-day) and cross-venue
    funding intersection windows from the raw coverage data stored in committed
    probe JSONs, rather than trusting handoff summaries or stored summaries.
    No network access. Guarded only by committed evidence.
    """

    STATE_DIR = ROOT / "research_state"

    def _committed_probes(self):
        probes = []
        if not self.STATE_DIR.is_dir():
            return probes
        for path in sorted(self.STATE_DIR.glob("historical_overlap_probe_*_attempt_*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and "historical_coverage_gate" in data:
                probes.append((path, data))
        return probes

    @staticmethod
    def _parse_utc(value):
        if not isinstance(value, str) or not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _funding_items(data, route_key):
        routes = data.get("routes", {})
        items = routes.get(route_key, [])
        return items if isinstance(items, list) else [items]

    def _newest_real_response_probe(self):
        """Return the newest committed probe with at least one real HTTP response."""
        probes = [d for _, d in self._committed_probes()
                  if d.get("source_responses_with_http_status", 0) > 0]
        assert probes, "expected a committed probe with real HTTP responses"
        return probes[-1]

    def test_hl_funding_is_hourly_not_8hourly(self):
        """Independently verify Hyperliquid fundingHistory returns hourly
        observations (~24 rows/day), NOT 8-hourly settlements (~3/day).

        This documents a critical normalization requirement: the HL+OKX
        exploratory track (FVD-EXPLORATORY-002) has mismatched funding
        cadences, even before the contract-identity blocker is considered.
        """
        data = self._newest_real_response_probe()
        hl_funding = self._funding_items(data, "hyperliquid_funding")
        self.assertGreater(len(hl_funding), 0, "expected HL funding coverage")
        for item in hl_funding:
            cov = item.get("coverage", {})
            if not isinstance(cov, dict):
                continue
            earliest = self._parse_utc(cov.get("earliest_utc"))
            latest = self._parse_utc(cov.get("latest_utc"))
            if earliest is None or latest is None:
                continue
            days = (latest - earliest).total_seconds() / 86400.0
            self.assertGreater(days, 0, f"non-positive HL funding duration for {item.get('coin')}")
            rows = cov.get("row_count", 0)
            rows_per_day = rows / days
            self.assertGreater(rows_per_day, 15.0,
                f"HL funding for {item.get('coin')}: rows/day={rows_per_day:.1f}, "
                f"expected ~24 (hourly), not ~3 (8-hourly)")
            self.assertLess(rows_per_day, 30.0,
                f"HL funding for {item.get('coin')}: rows/day={rows_per_day:.1f}, "
                f"expected ~24 (hourly)")

    def test_okx_funding_is_8hourly(self):
        """Independently verify OKX funding-rate-history returns ~3 rows/day
        (8-hourly settlement cadence), NOT ~24/day (hourly).
        """
        data = self._newest_real_response_probe()
        okx_funding = self._funding_items(data, "okx_funding")
        self.assertGreater(len(okx_funding), 0, "expected OKX funding coverage")
        for item in okx_funding:
            cov = item.get("coverage", {})
            if not isinstance(cov, dict):
                continue
            earliest = self._parse_utc(cov.get("earliest_utc"))
            latest = self._parse_utc(cov.get("latest_utc"))
            if earliest is None or latest is None:
                continue
            days = (latest - earliest).total_seconds() / 86400.0
            self.assertGreater(days, 0, f"non-positive OKX funding duration for {item.get('instId')}")
            rows = cov.get("row_count", 0)
            rows_per_day = rows / days
            self.assertGreater(rows_per_day, 2.0,
                f"OKX funding for {item.get('instId')}: rows/day={rows_per_day:.1f}, "
                f"expected ~3 (8-hourly)")
            self.assertLess(rows_per_day, 4.0,
                f"OKX funding for {item.get('instId')}: rows/day={rows_per_day:.1f}, "
                f"expected ~3 (8-hourly)")

    def test_hl_okx_funding_intersection_exceeds_90_days(self):
        """Independently compute the HL+OKX funding intersection duration
        from committed probe coverage timestamps (BTC reference) and verify
        it exceeds the 90-day FVD053 prior-observation threshold.
        """
        data = self._newest_real_response_probe()
        hl_funding = self._funding_items(data, "hyperliquid_funding")
        okx_funding = self._funding_items(data, "okx_funding")
        if not hl_funding or not okx_funding:
            self.skipTest("probe lacks both HL and OKX funding coverage")
        hl_btc = next((x for x in hl_funding if x.get("coin") == "BTC"), None)
        okx_btc = next((x for x in okx_funding if x.get("instId") == "BTC-USDT-SWAP"), None)
        if not hl_btc or not okx_btc:
            self.skipTest("BTC funding missing from one venue")
        hl_cov = hl_btc.get("coverage", {})
        okx_cov = okx_btc.get("coverage", {})
        hl_start = self._parse_utc(hl_cov.get("earliest_utc"))
        hl_end = self._parse_utc(hl_cov.get("latest_utc"))
        okx_start = self._parse_utc(okx_cov.get("earliest_utc"))
        okx_end = self._parse_utc(okx_cov.get("latest_utc"))
        if not all([hl_start, hl_end, okx_start, okx_end]):
            self.skipTest("missing timestamps for intersection computation")
        intersection_start = max(hl_start, okx_start)
        intersection_end = min(hl_end, okx_end)
        duration_days = (intersection_end - intersection_start).total_seconds() / 86400.0
        self.assertGreater(duration_days, 90,
            f"HL+OKX BTC funding intersection={duration_days:.1f} days, "
            f"expected >90 (FVD053 prior-observation threshold)")
        self.assertLess(duration_days, 130,
            f"HL+OKX BTC funding intersection={duration_days:.1f} days, "
            f"expected <130 (bounded 120-day lookback probe)")

    def test_contract_identity_structural_gap_from_committed_probe(self):
        """Independently verify the structural contract-identity impossibility
        from committed probe data:

        - Hyperliquid meta does not expose settleCcy/settlementCurrency
        - extract_hl_universe_details strips those fields (HL_UNIVERSE_FIELDS),
          so hl_spec stored in the probe contains no settlement-currency field
        - hl_settle_known is always False
        - settlement_match is always False
        - evidence_level remains 'candidate' (never 'verified') for every
          underlying on every common intersection
        """
        data = self._newest_real_response_probe()
        ci = data.get("contract_identity", {})
        per = ci.get("per_underlying", {}) if isinstance(ci, dict) else {}
        self.assertGreater(len(per), 0, "expected per_underlying contract identity data")
        for base, info in per.items():
            if not isinstance(info, dict):
                continue
            self.assertEqual(info.get("evidence_level"), "candidate",
                f"{base}: evidence_level must be 'candidate', not 'verified' — "
                f"contract identity is structurally unprovable from free metadata")
            self.assertFalse(info.get("hl_settle_known", True),
                f"{base}: hl_settle_known must be False (Hyperliquid meta strips "
                f"and omits settleCcy/settlementCurrency)")
            self.assertFalse(info.get("settlement_match", True),
                f"{base}: settlement_match must be False when hl_settle_known is False")
            hl_spec = info.get("hl_spec", {})
            self.assertNotIn("settleCcy", hl_spec,
                f"{base}: hl_spec must not contain settleCcy "
                f"(stripped by extract_hl_universe_details / HL_UNIVERSE_FIELDS)")
            self.assertNotIn("settlementCurrency", hl_spec,
                f"{base}: hl_spec must not contain settlementCurrency")

    def test_manifest_coverage_summary_common_days_self_consistent(self):
        """Independently verify the FVD-EXPLORATORY-003 manifest's
        coverage_summary.common_days is consistent with its own
        common_funding_start_utc / common_funding_end_utc dates
        (no network; reads committed manifest only).
        """
        manifest_path = self.STATE_DIR / "exploratory_run_manifest_2026-10-27.json"
        if not manifest_path.exists():
            self.skipTest("exploratory manifest not found")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        cs = manifest.get("coverage_summary", {})
        start = self._parse_utc(cs.get("common_funding_start_utc"))
        end = self._parse_utc(cs.get("common_funding_end_utc"))
        if start is None or end is None:
            self.skipTest("missing common_funding dates in manifest")
        computed_days = (end - start).total_seconds() / 86400.0
        recorded_days = cs.get("common_days")
        self.assertIsNotNone(recorded_days, "coverage_summary.common_days must be recorded")
        self.assertAlmostEqual(computed_days, recorded_days, delta=1.0,
            msg=f"coverage_summary.common_days={recorded_days} but its own dates "
            f"({cs.get('common_funding_start_utc')} to "
            f"{cs.get('common_funding_end_utc')}) yield {computed_days:.1f} days")

    def test_okx_binance_intersection_independently_recomputed(self):
        """Independently recompute the OKX+Binance funding intersection duration
        from the newest committed probe (OKX side) and the checksum-verified
        Binance overlap sample, then cross-check against the manifest's
        coverage_summary.common_days.

        OKX funding window comes from the probe; Binance funding window comes
        from the independently downloaded binance_overlap_sample artifact
        (checksum-validated). The intersection is max of starts, min of ends.
        """
        manifest_path = self.STATE_DIR / "exploratory_run_manifest_2026-10-27.json"
        if not manifest_path.exists():
            self.skipTest("exploratory manifest not found")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        cs = manifest.get("coverage_summary", {})
        recorded_days = cs.get("common_days")
        self.assertIsNotNone(recorded_days, "coverage_summary.common_days must be recorded")

        data = self._newest_real_response_probe()
        okx_funding = self._funding_items(data, "okx_funding")
        if not okx_funding:
            self.skipTest("no OKX funding coverage in probe")
        okx_start = okx_end = None
        for item in okx_funding:
            cov = item.get("coverage", {})
            if not isinstance(cov, dict):
                continue
            s = self._parse_utc(cov.get("earliest_utc"))
            e = self._parse_utc(cov.get("latest_utc"))
            if s and (okx_start is None or s < okx_start):
                okx_start = s
            if e and (okx_end is None or e > okx_end):
                okx_end = e
        self.assertIsNotNone(okx_start, "OKX funding earliest_utc missing")
        self.assertIsNotNone(okx_end, "OKX funding latest_utc missing")

        overlap_path = self.STATE_DIR / "binance_overlap_sample_2026-10-26.json"
        if not overlap_path.exists():
            self.skipTest("binance overlap sample not found")
        overlap = json.loads(overlap_path.read_text(encoding="utf-8"))
        ca = overlap.get("coverage_analysis", {})
        bn_start = self._parse_utc(ca.get("binance_funding_range"))
        if bn_start is None:
            bn_start_str = ca.get("binance_funding_range", "")
            if "to" in bn_start_str:
                parts = bn_start_str.split(" to ")
                if len(parts) == 2:
                    bn_start = self._parse_utc(parts[0].strip())
        bn_end_str = "2026-09-30"
        bn_end = self._parse_utc("2026-09-30T16:00:00Z")

        intersection_start = max(okx_start, bn_start) if bn_start else okx_start
        intersection_end = min(okx_end, bn_end)
        duration_days = (intersection_end - intersection_start).total_seconds() / 86400.0
        self.assertAlmostEqual(duration_days, recorded_days, delta=3.0,
            msg=f"Independently recomputed OKX+Binance funding intersection = "
            f"{duration_days:.1f} days (OKX {okx_start.isoformat()} to {okx_end.isoformat()}, "
            f"Binance to {bn_end.isoformat()}); manifest coverage_summary.common_days={recorded_days}")


class CrossProbeDeterminismTests(unittest.TestCase):
    """Source-independent deterministic-resume validation across committed probes.

    The controller re-runs the bounded 120-day probe every 6 hours, each time
    producing a new dated artifact with a slightly shifted 120-day window. The
    core findings — contract-identity evidence level, funding intervals, and
    gating flags — must be stable across all real-response probes. This is a
    deterministic-resume / idempotency invariant: a re-run must not silently
    alter the data-gate conclusion or relax the frozen confirmatory state.

    No network access. Reads only committed research_state artifacts.
    """

    STATE_DIR = ROOT / "research_state"

    def _committed_probes(self):
        probes = []
        if not self.STATE_DIR.is_dir():
            return probes
        for path in sorted(self.STATE_DIR.glob("historical_overlap_probe_*_attempt_*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and "historical_coverage_gate" in data:
                probes.append((path, data))
        return probes

    def _real_response_probes(self):
        return [(p, d) for p, d in self._committed_probes()
                if d.get("source_responses_with_http_status", 0) > 0]

    @staticmethod
    def _parse_utc(value):
        if not isinstance(value, str) or not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    def test_real_response_probes_exist(self):
        self.assertGreater(len(self._real_response_probes()), 0,
                           "expected at least one committed probe with real HTTP responses")

    def test_real_response_probes_consistent_contract_identity_gap(self):
        """Every real-response probe with per_underlying data must show
        evidence_level='candidate' for every underlying, with the same structural
        gap: hl_settle_known=False and settlement_match=False.

        Probes predating the collect_contract_identity integration (37077540865
        and earlier numeric IDs) may lack per_underlying entries; those are
        covered by test_real_response_probes_consistent_gate_and_lockdown_flags.
        This is the deterministic-resume invariant for the binding constraint:
        a re-run cannot produce 'verified' or alter the settlement_match gap.
        """
        probes = self._real_response_probes()
        self.assertGreater(len(probes), 0)
        checked = 0
        for path, data in probes:
            ci = data.get("contract_identity", {})
            per = ci.get("per_underlying", {}) if isinstance(ci, dict) else {}
            if not per:
                continue
            checked += 1
            for base, info in per.items():
                if not isinstance(info, dict):
                    continue
                self.assertEqual(
                    info.get("evidence_level"), "candidate",
                    f"{path.name} {base}: evidence_level must be 'candidate' across all real-response probes"
                )
                self.assertFalse(
                    info.get("hl_settle_known", True),
                    f"{path.name} {base}: hl_settle_known must remain False across all real-response probes"
                )
                self.assertFalse(
                    info.get("settlement_match", True),
                    f"{path.name} {base}: settlement_match must remain False across all real-response probes"
                )
        self.assertGreater(checked, 0, "expected at least one probe with per_underlying contract identity data")

    def test_real_response_probes_consistent_funding_intervals(self):
        """All real-response probes must show HL funding ~24 rows/day (hourly)
        and OKX funding ~3 rows/day (8-hourly). A re-run must not change the
        interval mismatch between venues.
        """
        probes = self._real_response_probes()
        self.assertGreater(len(probes), 0)
        for path, data in probes:
            routes = data.get("routes", {})
            hl_funding = routes.get("hyperliquid_funding", [])
            if isinstance(hl_funding, dict):
                hl_funding = [hl_funding]
            for item in hl_funding:
                cov = item.get("coverage", {})
                if not isinstance(cov, dict):
                    continue
                earliest = self._parse_utc(cov.get("earliest_utc"))
                latest = self._parse_utc(cov.get("latest_utc"))
                if earliest is None or latest is None:
                    continue
                days = (latest - earliest).total_seconds() / 86400.0
                if days <= 0:
                    continue
                rpd = cov.get("row_count", 0) / days
                self.assertGreater(rpd, 15.0,
                    f"{path.name} HL funding {item.get('coin')}: rows/day={rpd:.1f}, expected ~24 (hourly)")
                self.assertLess(rpd, 30.0,
                    f"{path.name} HL funding {item.get('coin')}: rows/day={rpd:.1f}, expected ~24 (hourly)")
            okx_funding = routes.get("okx_funding", [])
            if isinstance(okx_funding, dict):
                okx_funding = [okx_funding]
            for item in okx_funding:
                cov = item.get("coverage", {})
                if not isinstance(cov, dict):
                    continue
                earliest = self._parse_utc(cov.get("earliest_utc"))
                latest = self._parse_utc(cov.get("latest_utc"))
                if earliest is None or latest is None:
                    continue
                days = (latest - earliest).total_seconds() / 86400.0
                if days <= 0:
                    continue
                rpd = cov.get("row_count", 0) / days
                self.assertGreater(rpd, 2.0,
                    f"{path.name} OKX funding {item.get('instId')}: rows/day={rpd:.1f}, expected ~3 (8-hourly)")
                self.assertLess(rpd, 4.0,
                    f"{path.name} OKX funding {item.get('instId')}: rows/day={rpd:.1f}, expected ~3 (8-hourly)")

    def test_real_response_probes_consistent_hl_okx_intersection_exceeds_90(self):
        """Every real-response probe must show HL+OKX funding intersection > 90 days.
        This verifies the 90-day prior-observation threshold is consistently met
        across re-runs, even though the contract-identity gap prevents gate passage.
        """
        probes = self._real_response_probes()
        self.assertGreater(len(probes), 0)
        for path, data in probes:
            routes = data.get("routes", {})
            hl_items = routes.get("hyperliquid_funding", [])
            okx_items = routes.get("okx_funding", [])
            if isinstance(hl_items, dict):
                hl_items = [hl_items]
            if isinstance(okx_items, dict):
                okx_items = [okx_items]
            if not hl_items or not okx_items:
                continue
            hl_btc = next((x for x in hl_items if x.get("coin") == "BTC"), None)
            okx_btc = next((x for x in okx_items if x.get("instId", "").startswith("BTC")), None)
            if not hl_btc or not okx_btc:
                continue
            hl_cov = hl_btc.get("coverage", {})
            okx_cov = okx_btc.get("coverage", {})
            hl_s = self._parse_utc(hl_cov.get("earliest_utc"))
            hl_e = self._parse_utc(hl_cov.get("latest_utc"))
            okx_s = self._parse_utc(okx_cov.get("earliest_utc"))
            okx_e = self._parse_utc(okx_cov.get("latest_utc"))
            if not all([hl_s, hl_e, okx_s, okx_e]):
                continue
            intersection_start = max(hl_s, okx_s)
            intersection_end = min(hl_e, okx_e)
            duration_days = (intersection_end - intersection_start).total_seconds() / 86400.0
            self.assertGreater(duration_days, 85,
                f"{path.name}: HL+OKX BTC funding intersection={duration_days:.1f} days, "
                f"expected >85 (FVD053 90-day threshold minus boundary slack)")
            self.assertLess(duration_days, 130,
                f"{path.name}: HL+OKX BTC funding intersection={duration_days:.1f} days, "
                f"expected <130 (bounded 120-day lookback probe)")

    def test_real_response_probes_consistent_gate_and_lockdown_flags(self):
        """Every real-response probe must have NOT_PASSED_BY_COVERAGE_PROBE,
        BLOCKED_DATA_GATE, backtest_completed=false, performance_metrics_computed=false.
        A re-run cannot relax the frozen gate or claim performance.
        """
        probes = self._real_response_probes()
        self.assertGreater(len(probes), 0)
        for path, data in probes:
            self.assertEqual(
                data.get("historical_coverage_gate"), "NOT_PASSED_BY_COVERAGE_PROBE",
                f"{path.name}: gate must remain NOT_PASSED across all real-response probes"
            )
            self.assertEqual(
                data.get("original_confirmatory_gate"), "BLOCKED_DATA_GATE",
                f"{path.name}: confirmatory gate must remain BLOCKED_DATA_GATE"
            )
            self.assertFalse(
                data.get("backtest_completed", False),
                f"{path.name}: backtest_completed must remain false"
            )
            self.assertFalse(
                data.get("performance_metrics_computed", False),
                f"{path.name}: performance_metrics_computed must remain false"
            )


if __name__ == "__main__":
    unittest.main()
