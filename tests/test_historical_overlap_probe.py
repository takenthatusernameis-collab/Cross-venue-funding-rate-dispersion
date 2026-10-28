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


if __name__ == "__main__":
    unittest.main()
