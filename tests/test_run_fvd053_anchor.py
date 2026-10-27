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
from unittest.mock import patch

from cross_venue_funding_dispersion.recompute import attribution_check

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

    def test_handles_unsorted_rows(self):
        """_latest_at_or_before calls sorted() internally with key=lambda r: r['time'].

        Unsorted input must produce identical results to sorted input, because the
        funding-simulation loop iterates over rows that may arrive in any order.
        The sort key r['time'] requires every row to carry a 'time' key, which all
        parsed HL/OKX funding rows satisfy after extraction.
        """
        sorted_rows = [
            {"time": 1000, "rate": 0.1},
            {"time": 2000, "rate": 0.15},
            {"time": 3000, "rate": 0.2},
        ]
        unsorted_rows = [
            {"time": 3000, "rate": 0.2},
            {"time": 1000, "rate": 0.1},
            {"time": 2000, "rate": 0.15},
        ]
        for t_ms in [500, 1000, 1500, 2000, 2500, 3000, 3500]:
            self.assertEqual(
                anchor._latest_at_or_before(sorted_rows, t_ms),
                anchor._latest_at_or_before(unsorted_rows, t_ms),
            )
        self.assertIsNone(anchor._latest_at_or_before(unsorted_rows, 500))
        self.assertEqual(anchor._latest_at_or_before(unsorted_rows, 2000), 0.15)


class FundingObservationsTests(unittest.TestCase):
    """Verify _funding_observations preserves original rate/units/venue and normalizes correctly."""

    def test_preserves_original_rate_interval_and_venue(self):
        rows = [{"time": START_MS, "rate": 0.0001}]
        obs = anchor._funding_observations(rows, 1.0, START_MS, END_MS, venue="Hyperliquid")
        self.assertEqual(len(obs), 1)
        self.assertAlmostEqual(obs[0]["original_rate"], 0.0001)
        self.assertEqual(obs[0]["interval_hours"], 1.0)
        self.assertEqual(obs[0]["venue"], "Hyperliquid")
        self.assertAlmostEqual(obs[0]["rate_8h"], 0.0008)

    def test_hyperliquid_1h_to_8h_normalization(self):
        """Hyperliquid hourly rate normalizes to 8h equivalent by multiplying by 8."""
        rows = [{"time": START_MS + i * 3_600_000, "rate": 0.0001} for i in range(24)]
        obs = anchor._funding_observations(rows, 1.0, START_MS, START_MS + 12 * 3_600_000, venue="Hyperliquid")
        self.assertEqual(len(obs), 13)
        for entry in obs:
            self.assertAlmostEqual(entry["original_rate"], 0.0001)
            self.assertEqual(entry["interval_hours"], 1.0)
            self.assertEqual(entry["venue"], "Hyperliquid")
            self.assertAlmostEqual(entry["rate_8h"], 0.0008)  # 0.0001 * 8 / 1

    def test_okx_8h_normalization_preserves_rate(self):
        """OKX 8h rate is already 8h equivalent; normalization is identity."""
        rows = [{"time": START_MS, "rate": 0.0002}]
        obs = anchor._funding_observations(rows, 8.0, START_MS, END_MS, venue="OKX")
        self.assertEqual(len(obs), 1)
        self.assertAlmostEqual(obs[0]["original_rate"], 0.0002)
        self.assertEqual(obs[0]["interval_hours"], 8.0)
        self.assertEqual(obs[0]["venue"], "OKX")
        self.assertAlmostEqual(obs[0]["rate_8h"], 0.0002)  # 0.0002 * 8 / 8

    def test_window_filtering(self):
        early = START_MS - 3_600_000
        late = END_MS + 3_600_000
        rows = [
            {"time": early, "rate": 0.1},
            {"time": START_MS, "rate": 0.2},
            {"time": END_MS, "rate": 0.3},
            {"time": late, "rate": 0.4},
        ]
        obs = anchor._funding_observations(rows, 1.0, START_MS, END_MS, venue="Hyperliquid")
        self.assertEqual(len(obs), 2)
        self.assertAlmostEqual(obs[0]["original_rate"], 0.2)
        self.assertAlmostEqual(obs[1]["original_rate"], 0.3)

    def test_disjoint_intervals_preserved(self):
        """A 4h-interval venue normalizes by multiplying by 2 (8/4)."""
        rows = [{"time": START_MS, "rate": 0.001}]
        obs = anchor._funding_observations(rows, 4.0, START_MS, END_MS, venue="Bitfinex")
        self.assertAlmostEqual(obs[0]["rate_8h"], 0.002)
        self.assertEqual(obs[0]["interval_hours"], 4.0)

    def test_cash_flow_uses_raw_not_normalized_rate(self):
        """Funding cash flow must use the actual settled rate, not the 8h-normalized rate.

        This is a known-answer test: a 1h venue rate of 0.0001 over 24 settlements
        produces 24 * 0.0001 = 0.0024 nominal rate on 5000 notional = 12.0 cash flow.
        The normalized (0.0008) rate would wrongly produce 96.0.
        """
        u = "BTC"
        notional = 5000.0
        entry = dt.datetime(2026, 8, 2, 23, 0, tzinfo=dt.timezone.utc)
        exit_ = dt.datetime(2026, 8, 3, 23, 0, tzinfo=dt.timezone.utc)
        data = {
            "BTC": {
                "hl_funding": internal_hl_funding_series(START_MS, END_MS, HL_RATE),
                "okx_funding": internal_okx_funding_series(START_MS, END_MS, OKX_RATE),
                "hl_candles": internal_candle_list(START_MS, END_MS, PRICE_OPEN, PRICE_CLOSE),
                "okx_candles": internal_candle_list(START_MS, END_MS, PRICE_OPEN, PRICE_CLOSE),
            }
        }
        res = anchor.simulate_signal(
            u, "OKX", "Hyperliquid", notional, entry, exit_, data,
            anchor.ANCHOR_PARAMS["fee_bps_per_side"],
            anchor.ANCHOR_PARAMS["slippage_bps_per_side"],
        )
        # HL (short, side=-1): 24 settlements * funding_cash_flow(-1, 5000, 0.0001) = +12.0
        # OKX (long, side=1): 3 settlements * funding_cash_flow(1, 5000, 0.0002) = -3.0
        self.assertAlmostEqual(res["funding_cash_flow"], 9.0)
        self.assertEqual(res["funding_settlements"], 27)

    def test_partial_venue_coverage_fails_closed(self):
        """When only one venue has funding in the lookback window, dispersion fails closed."""
        start = "2026-08-02T23:00:00Z"
        end = "2026-08-02T23:30:00Z"
        histories = {
            "Hyperliquid": [
                {"timestamp": start, "rate_8h": 0.001,
                 "original_rate": 0.000125, "interval_hours": 1.0, "venue": "Hyperliquid"},
            ],
            "OKX": [],
        }
        from cross_venue_funding_dispersion.signals import dispersion_from_venue_histories
        disp, means = dispersion_from_venue_histories(
            histories, start, end, minimum_venues=2, max_staleness_hours=24,
        )
        self.assertIsNone(disp)
        self.assertIn("Hyperliquid", means)
        self.assertNotIn("OKX", means)

    def test_non_finite_funding_rate_in_observations_skipped_or_raises(self):
        """normalize_funding_rate must reject non-finite rates; observations use it."""
        rows = [{"time": START_MS, "rate": 0.001}, {"time": START_MS + 3600000, "rate": float("nan")}]
        with self.assertRaises(ValueError):
            anchor._funding_observations(rows, 1.0, START_MS, END_MS, venue="Hyperliquid")


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

    def test_price_basis_pnl_separated_from_funding_with_differing_prices(self):
        """When long and short venues have different entry/exit prices, price/basis PnL
        must be correctly attributed separately from funding cash flow.

        Known-answer: OKX (long) entry=100->exit=120, HL (short) entry=100->exit=80.
        long_price_pnl  = 5000 * (120/100 - 1) = 1000.0
        short_price_pnl = -5000 * (80/100 - 1)  = 1000.0
        net_price_basis_pnl = 2000.0
        funding_cash_flow = 9.0  (same constant-rate fixture as test_known_answer_pair_pnl)
        fees = 10.0, slippage = 10.0
        net_pnl = 2000.0 + 9.0 - 10.0 - 10.0 = 1989.0
        """
        u = "BTC"
        notional = 5000.0
        entry = dt.datetime(2026, 8, 2, 23, 0, tzinfo=dt.timezone.utc)
        exit_ = dt.datetime(2026, 8, 3, 23, 0, tzinfo=dt.timezone.utc)
        entry_ms = anchor.utc_ms(entry)
        exit_ms = anchor.utc_ms(exit_)

        # Build candle lists with differing entry/exit open prices per venue.
        hl_candles = internal_candle_list(START_MS, END_MS, 100.0, 101.0)
        okx_candles = internal_candle_list(START_MS, END_MS, 100.0, 101.0)
        for c in hl_candles:
            if c["time"] == entry_ms:
                c["open"] = 100.0
            elif c["time"] == exit_ms:
                c["open"] = 80.0
        for c in okx_candles:
            if c["time"] == entry_ms:
                c["open"] = 100.0
            elif c["time"] == exit_ms:
                c["open"] = 120.0

        data = {
            "BTC": {
                "hl_funding": internal_hl_funding_series(START_MS, END_MS, HL_RATE),
                "okx_funding": internal_okx_funding_series(START_MS, END_MS, OKX_RATE),
                "hl_candles": hl_candles,
                "okx_candles": okx_candles,
            }
        }
        res = anchor.simulate_signal(
            u, "OKX", "Hyperliquid", notional, entry, exit_, data,
            anchor.ANCHOR_PARAMS["fee_bps_per_side"],
            anchor.ANCHOR_PARAMS["slippage_bps_per_side"],
        )
        self.assertFalse(res["skipped"])
        self.assertEqual(res["long_venue"], "OKX")
        self.assertEqual(res["short_venue"], "Hyperliquid")
        self.assertAlmostEqual(res["entry_price_long"], 100.0)
        self.assertAlmostEqual(res["entry_price_short"], 100.0)
        self.assertAlmostEqual(res["exit_price_long"], 120.0)
        self.assertAlmostEqual(res["exit_price_short"], 80.0)
        self.assertAlmostEqual(res["price_basis_pnl"], 2000.0)
        self.assertAlmostEqual(res["funding_cash_flow"], 9.0)
        self.assertAlmostEqual(res["fees"], 10.0)
        self.assertAlmostEqual(res["slippage"], 10.0)
        self.assertAlmostEqual(res["net_pnl"], 1989.0)

    def test_multi_venue_1h_8h_interval_split_known_answer(self):
        """Known-answer test for the 1h/8h settlement-interval split in simulate_signal.

        HL (Hyperliquid) settles funding hourly (1h interval); OKX settles
        every 8h. The funding cash flow MUST use the raw per-event rate, not
        the 8h-normalized rate. This test uses rates chosen so that the
        8h-normalized values would give a different cash flow than the raw rates,
        proving the interval split is handled correctly.

        Fixture:
          HL rate (1h)  = 0.0004  -> normalized 8h = 0.0032
          OKX rate (8h) = 0.0016  -> normalized 8h = 0.0016  (raw == normalized)

        Over a 24h holding period:
          HL: 24 hourly settlements, raw rate 0.0004
          OKX: 3  eight-hourly settlements, raw rate 0.0016

        Independent computation (using accounting primitives directly):
          HL short (side=-1): 24 * funding_cash_flow(-1, 5000, 0.0004)
                              = 24 * (-(-1) * 5000 * 0.0004) = 24 * 2.0 = +48.0
          OKX long (side=+1): 3 * funding_cash_flow(1, 5000, 0.0016)
                              = 3 * (-(1) * 5000 * 0.0016) = 3 * (-8.0) = -24.0
          Net funding = 48.0 - 24.0 = 24.0

        If the code incorrectly used normalized rates for HL:
          HL: 24 * funding_cash_flow(-1, 5000, 0.0032) = 24 * 16.0 = +384.0
          Net funding = 384.0 - 24.0 = 360.0  (WRONG — would fail the assertion)

        Prices are flat (entry == exit) so price_basis_pnl = 0.0.
        fees = 4 fills * execution_cost(5000, 5.0, 0.0) = 4 * 2.5 = 10.0
        slippage = 4 fills * execution_cost(5000, 0.0, 5.0) = 4 * 2.5 = 10.0
        net_pnl = 0.0 + 24.0 - 10.0 - 10.0 = 4.0
        net_return = 4.0 / 10000.0 = 0.0004
        """
        from cross_venue_funding_dispersion.accounting import (
            execution_cost, funding_cash_flow,
        )
        u = "BTC"
        notional = 5000.0
        hl_rate = 0.0004
        okx_rate = 0.0016
        entry = dt.datetime(2026, 8, 2, 23, 0, tzinfo=dt.timezone.utc)
        exit_ = dt.datetime(2026, 8, 3, 23, 0, tzinfo=dt.timezone.utc)
        data = {
            "BTC": {
                "hl_funding": internal_hl_funding_series(START_MS, END_MS, hl_rate),
                "okx_funding": internal_okx_funding_series(START_MS, END_MS, okx_rate),
                "hl_candles": internal_candle_list(START_MS, END_MS, PRICE_OPEN, PRICE_OPEN),
                "okx_candles": internal_candle_list(START_MS, END_MS, PRICE_OPEN, PRICE_OPEN),
            },
        }
        res = anchor.simulate_signal(
            u, "OKX", "Hyperliquid", notional, entry, exit_, data,
            anchor.ANCHOR_PARAMS["fee_bps_per_side"],
            anchor.ANCHOR_PARAMS["slippage_bps_per_side"],
        )
        self.assertFalse(res["skipped"])
        self.assertEqual(res["long_venue"], "OKX")
        self.assertEqual(res["short_venue"], "Hyperliquid")
        self.assertEqual(res["gross_exposure"], 2.0 * notional)

        # Independent known-answer: raw rates, not normalized.
        hl_short_cf = funding_cash_flow(-1, notional, hl_rate)  # per settlement
        okx_long_cf = funding_cash_flow(1, notional, okx_rate)  # per settlement
        hl_settlements = 24  # hourly over 24h
        okx_settlements = 3  # 8h over 24h
        expected_funding = hl_short_cf * hl_settlements + okx_long_cf * okx_settlements
        expected_fees = execution_cost(notional, 5.0, 0.0) * 4  # 2 legs * 2 fills
        expected_slippage = execution_cost(notional, 0.0, 5.0) * 4
        expected_net = 0.0 + expected_funding - expected_fees - expected_slippage

        self.assertAlmostEqual(res["funding_cash_flow"], expected_funding)
        self.assertAlmostEqual(res["funding_cash_flow"], 24.0)
        self.assertEqual(res["funding_settlements"], 27)
        self.assertAlmostEqual(res["price_basis_pnl"], 0.0)
        self.assertAlmostEqual(res["fees"], expected_fees)
        self.assertAlmostEqual(res["slippage"], expected_slippage)
        self.assertAlmostEqual(res["net_pnl"], expected_net)
        self.assertAlmostEqual(res["net_pnl"], 4.0)
        self.assertAlmostEqual(res["net_return"], 4.0 / anchor.EQUITY)

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

    def test_duplicate_timestamp_not_double_counted(self):
        """Duplicate settlement timestamps within (entry, exit] are counted once per venue.

        Known-answer: injecting a duplicate Hyperliquid settlement row at the same
        timestamp inside the funding window must not change the funding cash flow
        or settlement count relative to the deduplicated case (9.0, 27).
        """
        u = "BTC"
        notional = 5000.0
        entry = dt.datetime(2026, 8, 2, 23, 0, tzinfo=dt.timezone.utc)
        exit_ = dt.datetime(2026, 8, 3, 23, 0, tzinfo=dt.timezone.utc)
        data = self._data()
        hl = data[u]["hl_funding"]
        in_window_times = [r["time"] for r in hl if anchor.utc_ms(entry) < r["time"] <= anchor.utc_ms(exit_)]
        self.assertGreater(len(in_window_times), 0)
        hl.append({"time": in_window_times[0], "rate": HL_RATE})
        res = anchor.simulate_signal(
            u, "OKX", "Hyperliquid", notional, entry, exit_, data,
            anchor.ANCHOR_PARAMS["fee_bps_per_side"],
            anchor.ANCHOR_PARAMS["slippage_bps_per_side"],
        )
        self.assertAlmostEqual(res["funding_cash_flow"], 9.0)
        self.assertEqual(res["funding_settlements"], 27)


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

    def test_red_team_independent_recomputation_from_signal_ledger(self):
        """Red-team check: recompute all attribution fields independently from the
        immutable signal ledger rows in result['signals'] and assert they match the
        aggregated attribution fields exactly.

        This test does NOT call the aggregation code path; it independently sums the
        per-signal fields and verifies the net_pnl identity:
            net_pnl = price_basis_pnl + funding_cash_flow - fees - slippage.
        """
        result = anchor.run_anchor()
        signals = result["signals"]
        self.assertGreater(len(signals), 0)

        # Independent summation from individual signal rows (do not reuse the anchor's own code).
        recomputed_total_net = sum(s["net_pnl"] for s in signals)
        recomputed_total_price = sum(s["price_basis_pnl"] for s in signals)
        recomputed_total_funding = sum(s["funding_cash_flow"] for s in signals)
        recomputed_total_fees = sum(s["fees"] for s in signals)
        recomputed_total_slippage = sum(s["slippage"] for s in signals)
        recomputed_total_settlements = sum(s["funding_settlements"] for s in signals)
        recomputed_turnover = sum(4 * s["notional_per_leg"] for s in signals)

        attr = result["attribution"]
        self.assertAlmostEqual(recomputed_total_net, attr["total_net_pnl"])
        self.assertAlmostEqual(recomputed_total_price, attr["total_price_basis_pnl"])
        self.assertAlmostEqual(recomputed_total_funding, attr["total_funding_cash_flow"])
        self.assertAlmostEqual(recomputed_total_fees, attr["total_fees"])
        self.assertAlmostEqual(recomputed_total_slippage, attr["total_slippage"])
        self.assertEqual(recomputed_total_settlements, result["total_funding_settlements"])
        self.assertAlmostEqual(recomputed_turnover, result["turnover_notional"])

        # Verify the per-signal accounting identity independently.
        for s in signals:
            expected_net = s["price_basis_pnl"] + s["funding_cash_flow"] - s["fees"] - s["slippage"]
            self.assertAlmostEqual(
                s["net_pnl"], expected_net,
                msg=f"net_pnl identity broken for {s['underlying']}",
            )
            # gross exposure must respect the 1.0x equity cap.
            self.assertLessEqual(s["gross_exposure"], anchor.EQUITY + 1e-9)


class CommittedAnchorArtifactRecomputeTests(unittest.TestCase):
    """Source-independent red-team regression tests on the committed FVD053 anchor artifact.

    These tests do NOT re-run the anchor or touch any network. They load the
    immutable committed artifact at research_state/fvd053_anchor_run_2026-10-25.json
    and assert: (a) frozen status/label invariants are intact, and (b) the
    additive attribution identity holds when independently recomputed.
    """

    @classmethod
    def setUpClass(cls):
        cls.artifact_path = (
            ROOT / "research_state" / "fvd053_anchor_run_2026-10-25.json"
        )
        with open(cls.artifact_path) as f:
            cls.artifact = json.load(f)

    def test_frozen_status_and_labels_intact(self):
        a = self.artifact
        self.assertEqual(a["status"], "EXPLORATORY_ONLY")
        self.assertTrue(a["inconclusive"])
        self.assertFalse(a["backtest_completed"])
        self.assertFalse(a["performance_metrics_computed"])
        self.assertEqual(a["confirmatory_status_preserved"], "BLOCKED_DATA_GATE")
        self.assertEqual(a["experiment_id"], "FVD-EXPLORATORY-002")
        self.assertEqual(a["anchor"], "FVD053")
        self.assertEqual(a["signal_count"], 0)
        self.assertEqual(a["signals"], [])

    def test_attribution_additive_identity_via_recompute(self):
        """Use the shared attribution_check primitive on the committed attribution
        block (mapped into the expected 'published' schema). The identity is:
        total_net_pnl == total_price_basis_pnl + total_funding_cash_flow - total_fees - total_slippage.
        """
        published = dict(self.artifact["attribution"])
        wrapper = {"published": published}
        result = attribution_check(wrapper)
        self.assertTrue(result["consistent"], msg=f"attribution mismatch: {result}")
        self.assertAlmostEqual(result["derived_total_net_pnl"], result["published_total_net_pnl"])

    def test_independent_sum_from_signal_ledger_matches_published(self):
        """Independently sum all per-signal fields from the immutable signal ledger
        and assert equality with the published attribution aggregates.
        """
        signals = self.artifact["signals"]
        attr = self.artifact["attribution"]
        self.assertEqual(len(signals), attr.get("total_funding_settlements", 0) * 0 + 0)
        self.assertEqual(sum(s.get("net_pnl", 0) for s in signals), attr["total_net_pnl"])
        self.assertEqual(sum(s.get("price_basis_pnl", 0) for s in signals), attr["total_price_basis_pnl"])
        self.assertEqual(sum(s.get("funding_cash_flow", 0) for s in signals), attr["total_funding_cash_flow"])
        self.assertEqual(sum(s.get("fees", 0) for s in signals), attr["total_fees"])
        self.assertEqual(sum(s.get("slippage", 0) for s in signals), attr["total_slippage"])
        self.assertEqual(sum(s.get("funding_settlements", 0) for s in signals), self.artifact["total_funding_settlements"])
        self.assertEqual(sum(4 * s.get("notional_per_leg", 0) for s in signals), self.artifact["turnover_notional"])


if __name__ == "__main__":
    unittest.main()
