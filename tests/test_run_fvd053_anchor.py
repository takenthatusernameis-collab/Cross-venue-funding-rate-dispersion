"""Known-answer and adversarial tests for scripts/run_fvd053_anchor.py.

All fetchers are mocked; no network is used. The end-to-end anchor run uses
deterministic synthetic funding/price history so every reported figure is a
known answer. Fixture shapes match the real Hyperliquid / OKX responses that
the fetchers parse.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import unittest
from urllib.error import URLError
from unittest.mock import patch

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_fvd053_anchor as anchor


def ms(value: str) -> int:
    return anchor.utc_ms(value)


# ---------------------------------------------------------------------------
# Synthetic deterministic history generator (no network).
# Raw API shapes: HL fundingHistory -> {"time","fundingRate"};
# OKX funding-rate-history -> {"fundingTime","fundingRate"};
# HL candleSnapshot -> [[t,T,s,i,o,c,h,l,v,n], ...];
# OKX history-candles -> [[ts,o,h,l,c,vol,...], ...].
# ---------------------------------------------------------------------------

def _hourly_range(start_ms: int, end_ms: int, step_ms: int):
    t = start_ms
    while t <= end_ms:
        yield t
        t += step_ms


def hl_funding_raw(start_ms: int, end_ms: int, rate: float) -> list[dict]:
    return [{"time": t, "fundingRate": rate} for t in _hourly_range(start_ms, end_ms, 3_600_000)]


def okx_funding_raw(start_ms: int, end_ms: int, rate: float) -> list[dict]:
    rows = []
    t = start_ms - (start_ms % (8 * 3_600_000))
    while t <= end_ms:
        rows.append({"fundingTime": t, "fundingRate": rate})
        t += 8 * 3_600_000
    return rows


def hl_candles_raw(start_ms: int, end_ms: int, open_price: float, close_price: float) -> list[dict]:
    rows = []
    for t in _hourly_range(start_ms, end_ms, 3_600_000):
        rows.append({"t": t, "T": t + 3_600_000, "s": "BTC", "i": "1h",
                     "o": str(open_price), "c": str(close_price), "h": str(close_price),
                     "l": str(open_price), "v": "1.0", "n": 1})
    return rows


def okx_candles_raw(start_ms: int, end_ms: int, open_price: float, close_price: float) -> list[list]:
    return [
        [t, open_price, close_price, open_price, close_price, 1.0]
        for t in _hourly_range(start_ms, end_ms, 3_600_000)
    ]


def internal_hl_funding_series(start_ms: int, end_ms: int, rate: float) -> list[dict]:
    """Normalized internal HL funding series on the hourly settlement grid."""
    return [{"time": t, "rate": rate} for t in _hourly_range(start_ms, end_ms, 3_600_000)]


def internal_okx_funding_series(start_ms: int, end_ms: int, rate: float) -> list[dict]:
    """Normalized internal OKX funding series on the 8-hour settlement grid."""
    rows = []
    t = start_ms - (start_ms % (8 * 3_600_000))
    while t <= end_ms:
        if t >= start_ms:
            rows.append({"time": t, "rate": rate})
        t += 8 * 3_600_000
    return rows


def internal_candle_list(start_ms: int, end_ms: int, open_price: float, close_price: float) -> list[dict]:
    return [
        {"time": t, "open": open_price, "close": close_price}
        for t in _hourly_range(start_ms, end_ms, 3_600_000)
    ]


WINDOW_START = "2026-08-01T00:00:00Z"
WINDOW_END = "2026-08-10T16:00:00Z"
START_MS = ms(WINDOW_START)
END_MS = ms(WINDOW_END)

HL_RATE = 0.0001   # hourly funding rate
OKX_RATE = 0.0002  # 8-hourly funding rate
PRICE_OPEN = 100.0
PRICE_CLOSE = 101.0


def fake_response_for(url: str, payload: dict | None) -> bytes:
    """Deterministic synthetic body for HL/OKX funding and candles routes."""
    if isinstance(payload, dict) and payload.get("type") == "fundingHistory":
        return json.dumps(hl_funding_raw(START_MS, END_MS, HL_RATE)).encode()
    if isinstance(payload, dict) and payload.get("type") == "candleSnapshot":
        return json.dumps(hl_candles_raw(START_MS, END_MS, PRICE_OPEN, PRICE_CLOSE)).encode()
    if isinstance(url, str) and url.startswith(anchor.OKX):
        if "funding-rate-history" in url:
            return json.dumps({"code": "0", "data": okx_funding_raw(START_MS, END_MS, OKX_RATE)}).encode()
        if "history-candles" in url:
            return json.dumps({"code": "0", "data": okx_candles_raw(START_MS, END_MS, PRICE_OPEN, PRICE_CLOSE)}).encode()
    return b""


def fake_fetch_json_result(url, payload=None, timeout=None, opener=None):
    """Deterministic (parsed, metadata) result for patching anchor.fetch_json; no network."""
    body = fake_response_for(url, payload)
    status = 200 if body else None
    try:
        parsed = json.loads(body.decode("utf-8")) if body else None
    except (ValueError, UnicodeDecodeError):
        parsed = None
    return parsed, {
        "url": url, "method": "GET" if payload is None else "POST",
        "request_sha256": None, "http_status": status,
        "response_bytes_read": len(body) if body else 0, "error": None if body else "empty body",
    }


class FakeResponse:
    status = 200
    def __init__(self, body):
        self._body = body
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, size=None):
        return self._body if size is None else self._body[:size]


def fake_fetch_json(req, timeout=anchor.TIMEOUT_SECONDS, opener=None):
    """Deterministic fake opener (urlopen contract); no network."""
    url = getattr(req, "full_url", "") or ""
    payload = None
    if getattr(req, "data", None) is not None:
        try:
            payload = json.loads(req.data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, AttributeError):
            payload = None
    body = fake_response_for(url, payload)
    return FakeResponse(body)


class ParseTests(unittest.TestCase):
    def test_hl_funding_parse(self):
        rows, meta = anchor.fetch_hl_funding("BTC", START_MS, END_MS, opener=fake_fetch_json)
        self.assertEqual(meta["pages"][0]["http_status"], 200)
        self.assertGreaterEqual(len(rows), 24)
        self.assertEqual(rows[0]["rate"], HL_RATE)
        self.assertTrue(all(START_MS <= r["time"] <= END_MS for r in rows))
        self.assertTrue(all(r["time"] % 3_600_000 == 0 for r in rows))

    def test_okx_funding_parse(self):
        rows, meta = anchor.fetch_okx_funding("BTC-USDT-SWAP", START_MS, END_MS, opener=fake_fetch_json)
        self.assertEqual(meta["pages"][0]["http_status"], 200)
        self.assertGreaterEqual(len(rows), 3)
        self.assertEqual(rows[0]["rate"], OKX_RATE)
        for r in rows:
            self.assertEqual(r["time"] % (8 * 3_600_000), 0)

    def test_hl_candles_parse(self):
        rows, meta = anchor.fetch_hl_candles("BTC", START_MS, END_MS, opener=fake_fetch_json)
        self.assertEqual(meta["http_status"], 200)
        self.assertEqual(rows[0]["open"], PRICE_OPEN)
        self.assertEqual(rows[0]["close"], PRICE_CLOSE)

    def test_okx_candles_parse(self):
        rows, meta = anchor.fetch_okx_candles("BTC-USDT-SWAP", START_MS, END_MS, opener=fake_fetch_json)
        self.assertEqual(meta["pages"][0]["http_status"], 200)
        self.assertEqual(rows[0]["open"], PRICE_OPEN)

    def test_failed_fetch_returns_none(self):
        def boom(req, timeout=10):
            raise URLError("down")
        rows, meta = anchor.fetch_hl_funding("BTC", START_MS, END_MS, opener=boom)
        self.assertEqual(rows, [])
        self.assertTrue(any(p.get("error") for p in meta["pages"]))


class LatestAtOrBeforeTests(unittest.TestCase):
    def test_returns_rate_at_or_before(self):
        rows = [{"time": 1000, "rate": 0.1}, {"time": 3000, "rate": 0.2}]
        self.assertEqual(anchor._latest_at_or_before(rows, 1000), 0.1)
        self.assertEqual(anchor._latest_at_or_before(rows, 2999), 0.1)
        self.assertEqual(anchor._latest_at_or_before(rows, 3000), 0.2)
        self.assertIsNone(anchor._latest_at_or_before(rows, 500))


class SimulateSignalTests(unittest.TestCase):
    def _data(self):
        return {
            "BTC": {
                "hl_funding": internal_hl_funding_series(START_MS, END_MS, HL_RATE),
                "okx_funding": internal_okx_funding_series(START_MS, END_MS, OKX_RATE),
                "hl_candles": internal_candle_list(START_MS, END_MS, PRICE_OPEN, PRICE_CLOSE),
                "okx_candles": internal_candle_list(START_MS, END_MS, PRICE_OPEN, PRICE_CLOSE),
            }
        }

    def test_known_answer_pair_pnl(self):
        u = "BTC"
        notional = 5000.0
        entry = dt.datetime(2026, 8, 2, 23, 0, tzinfo=dt.timezone.utc)
        exit_ = dt.datetime(2026, 8, 3, 23, 0, tzinfo=dt.timezone.utc)
        res = anchor.simulate_signal(
            u, "OKX", "Hyperliquid", notional, entry, exit_, self._data(),
            anchor.ANCHOR_PARAMS["fee_bps_per_side"],
            anchor.ANCHOR_PARAMS["slippage_bps_per_side"],
        )
        self.assertFalse(res["skipped"])
        self.assertEqual(res["long_venue"], "OKX")
        self.assertEqual(res["short_venue"], "Hyperliquid")
        self.assertEqual(res["gross_exposure"], 2.0 * notional)
        self.assertAlmostEqual(res["price_basis_pnl"], 0.0)
        # HL short settlements in (entry, exit]: 24 hourly @ +0.5 = +12.0
        # OKX long settlements in (entry, exit]: 3 x 8h @ -1.0 = -3.0
        self.assertAlmostEqual(res["funding_cash_flow"], 9.0)
        self.assertEqual(res["funding_settlements"], 27)
        self.assertAlmostEqual(res["fees"], 10.0)
        self.assertAlmostEqual(res["slippage"], 10.0)
        self.assertAlmostEqual(res["net_pnl"], -11.0)
        self.assertAlmostEqual(res["net_return"], -0.0011)

    def test_missing_candle_skips_signal(self):
        u = "BTC"
        notional = 5000.0
        entry = dt.datetime(2026, 8, 2, 23, 0, tzinfo=dt.timezone.utc)
        exit_ = dt.datetime(2026, 8, 3, 23, 0, tzinfo=dt.timezone.utc)
        data = self._data()
        data[u]["hl_candles"] = {}
        res = anchor.simulate_signal(
            u, "OKX", "Hyperliquid", notional, entry, exit_, data,
            anchor.ANCHOR_PARAMS["fee_bps_per_side"],
            anchor.ANCHOR_PARAMS["slippage_bps_per_side"],
        )
        self.assertTrue(res["skipped"])
        self.assertEqual(res["reason"], "missing_candle_at_entry_or_exit")


class SelectSignalAssetsTests(unittest.TestCase):
    def test_selects_top_tail_above_threshold(self):
        daily = {
            "2026-08-02": {"BTC": 0.003, "ETH": 0.001, "SOL": 0.002, "AVAX": 0.0005, "LINK": 0.0001},
        }
        samples = {u: [] for u in anchor.UNDERLYINGS}
        with patch.object(anchor, "prior_daily_threshold", return_value=0.001):
            sel = anchor.select_signal_assets(
                daily, samples, "2026-08-02", 80, 90, 30, 0.1,
            )
        self.assertEqual(sel, [("BTC", 0.003)])

    def test_no_signal_when_below_threshold(self):
        daily = {"2026-08-02": {"BTC": 0.0005, "ETH": 0.0004}}
        samples = {u: [] for u in anchor.UNDERLYINGS}
        with patch.object(anchor, "prior_daily_threshold", return_value=0.001):
            sel = anchor.select_signal_assets(
                daily, samples, "2026-08-02", 80, 90, 30, 0.1,
            )
        self.assertEqual(sel, [])

    def test_no_signal_when_no_dispersion(self):
        daily = {"2026-08-02": {"BTC": None, "ETH": None}}
        samples = {u: [] for u in anchor.UNDERLYINGS}
        with patch.object(anchor, "prior_daily_threshold", return_value=0.001):
            sel = anchor.select_signal_assets(
                daily, samples, "2026-08-02", 80, 90, 30, 0.1,
            )
        self.assertEqual(sel, [])


def _strip_observed(payload: dict) -> dict:
    out = json.loads(json.dumps(payload, sort_keys=True))
    out.pop("observed_at_utc", None)
    return out


class AnchorEndToEndTests(unittest.TestCase):
    def setUp(self):
        self._patches = [
            patch.object(anchor, "WINDOW_START_UTC", WINDOW_START),
            patch.object(anchor, "WINDOW_END_UTC", WINDOW_END),
            patch.object(anchor, "fetch_json", side_effect=fake_fetch_json_result),
            patch.object(anchor, "prior_daily_threshold", return_value=1e-6),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()

    def test_run_anchor_produces_deterministic_descriptive_output(self):
        result = anchor.run_anchor()
        self.assertEqual(result["status"], "EXPLORATORY_ONLY")
        self.assertTrue(result["inconclusive"])
        self.assertFalse(result["backtest_completed"])
        self.assertFalse(result["performance_metrics_computed"])
        self.assertEqual(result["confirmatory_status_preserved"], "BLOCKED_DATA_GATE")
        self.assertEqual(result["anchor"], "FVD053")
        self.assertEqual(result["experiment_id"], "FVD-EXPLORATORY-002")
        self.assertEqual(result["equity"], 10000.0)
        self.assertGreater(result["signal_count"], 0)

        n = result["signal_count"]
        # Deterministic known answer: AVAX selected every date (top-10% tail = 1 of 5;
        # identical dispersion, alphabetical tie-break picks AVAX), net -11.0 each.
        self.assertAlmostEqual(result["attribution"]["total_net_pnl"], -11.0 * n)
        self.assertAlmostEqual(result["net_return"], -0.0011 * n)
        self.assertAlmostEqual(result["attribution"]["total_funding_cash_flow"], 9.0 * n)
        self.assertAlmostEqual(result["attribution"]["total_fees"], 10.0 * n)
        self.assertAlmostEqual(result["attribution"]["total_slippage"], 10.0 * n)
        self.assertEqual(result["total_funding_settlements"], 27 * n)

        for s in result["signals"]:
            self.assertEqual(s["underlying"], "AVAX")
            self.assertEqual(s["long_venue"], "OKX")
            self.assertEqual(s["short_venue"], "Hyperliquid")
            self.assertAlmostEqual(s["net_pnl"], -11.0)
            self.assertLessEqual(s["gross_exposure"], 10000.0 + 1e-9)

        # No forbidden performance-claim tokens in the serialized artifact.
        text = json.dumps(_strip_observed(result)).lower()
        for token in (
            "sharpe", "annualized_return", "max_drawdown", "pnl_total",
            "equity_curve", "edge_detected", "profit_factor", "sortino",
            "calmar", "cagr", "win_rate", "hit_rate", "information_ratio",
        ):
            self.assertNotIn(token, text)

    def test_run_anchor_is_deterministic(self):
        r1 = _strip_observed(anchor.run_anchor())
        r2 = _strip_observed(anchor.run_anchor())
        self.assertEqual(json.dumps(r1, sort_keys=True), json.dumps(r2, sort_keys=True))

    def test_artifact_has_provenance_and_window(self):
        result = anchor.run_anchor()
        self.assertEqual(result["window_start_utc"], WINDOW_START)
        self.assertEqual(result["window_end_utc"], WINDOW_END)
        self.assertEqual(result["underlyings"], ["BTC", "ETH", "SOL", "AVAX", "LINK"])
        self.assertEqual(result["venues"], ["Hyperliquid", "OKX"])
        self.assertIsNotNone(result["fetch_metadata"])


if __name__ == "__main__":
    unittest.main()
