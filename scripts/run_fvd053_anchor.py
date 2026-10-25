#!/usr/bin/env python3
"""Run the single frozen FVD053 anchor on the verified OKX + Hyperliquid overlap.

Exploratory-only (FVD-EXPLORATORY-002). Descriptive outputs only; no performance
claims. Fetches free public funding/price history (no credentials), applies causal
closed-bar/next-open timing and per-venue settlement-timed funding, and reports
descriptive statistics without claiming an edge or a durable metric.

Implements docs/exploratory_protocol_v1.md section 4 using the frozen FVD053
parameters from configs/cross_venue_funding_dispersion_grid_v1.json:
- 24-hour dispersion lookback; 80th-percentile threshold; 24-hour holding period;
- top 10% cross-sectional tail; at least two eligible venues.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from cross_venue_funding_dispersion.accounting import (
    execution_cost,
    funding_cash_flow,
    price_pnl,
)
from cross_venue_funding_dispersion.signals import (
    dispersion_from_venue_histories,
    normalize_funding_rate,
    prior_daily_threshold,
)

HYPERLIQUID = "https://api.hyperliquid.xyz/info"
OKX = "https://www.okx.com/api/v5"
TIMEOUT_SECONDS = 10
PAGE_DELAY_SECONDS = 0.1

UNDERLYINGS = ("BTC", "ETH", "SOL", "AVAX", "LINK")
OKX_INST_ID = {u: f"{u}-USDT-SWAP" for u in UNDERLYINGS}
VENUE_LONG_NAME = {"Hyperliquid": "Hyperliquid", "OKX": "OKX"}

# Frozen FVD053 anchor (configs/cross_venue_funding_dispersion_grid_v1.json).
ANCHOR_PARAMS = {
    "dispersion_lookback_hours": 24,
    "entry_percentile": 80,
    "holding_hours": 24,
    "portfolio_tail_fraction": 0.1,
    "minimum_eligible_venues": 2,
    "threshold_lookback_days": 90,
    "threshold_minimum_observations": 30,
    "daily_cutoff_utc": "23:00",
    "fee_bps_per_side": 5.0,
    "slippage_bps_per_side": 5.0,
    "gross_multiple": 1.0,
}

WINDOW_START_UTC = "2026-07-20T00:00:00Z"
WINDOW_END_UTC = "2026-10-25T16:00:00Z"
EQUITY = 10000.0
FILLS_PER_LEG = 2  # entry + exit for each of the two legs


def utc_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def utc_ms(value: str | datetime) -> int:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
        value[:-1] + "+00:00" if isinstance(value, str) and value.endswith("Z") else value
    )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


def fetch_json(url: str, payload: dict | None = None, timeout: int = TIMEOUT_SECONDS,
               opener=None) -> tuple[Any, dict[str, Any]]:
    """Make one bounded unauthenticated JSON request; return (parsed, metadata)."""
    body = (
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
        if payload is not None else None
    )
    headers = {"User-Agent": "cross-venue-funding-dispersion-research/2.1"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
    open_fn = opener or urlopen
    metadata: dict[str, Any] = {
        "url": url, "method": req.get_method(),
        "request_sha256": hashlib.sha256(body).hexdigest() if body is not None else None,
        "http_status": None, "response_bytes_read": None, "error": None,
    }
    start = time.monotonic()
    try:
        with open_fn(req, timeout=timeout) as response:
            raw = response.read()
            metadata["http_status"] = response.status
    except HTTPError as exc:
        metadata["http_status"] = exc.code
        metadata["error"] = f"HTTPError {exc.code}"
        try:
            raw = exc.read()
        except Exception:
            raw = b""
    except (URLError, TimeoutError, OSError) as exc:
        metadata["error"] = f"{type(exc).__name__}: {exc}"
        raw = b""
    finally:
        metadata["latency_ms"] = round((time.monotonic() - start) * 1000, 1)
    if raw:
        metadata["response_bytes_read"] = len(raw)
        try:
            parsed = json.loads(raw.decode("utf-8"))
            return parsed, metadata
        except (UnicodeDecodeError, json.JSONDecodeError):
            metadata["error"] = metadata["error"] or "non-json"
            return None, metadata
    return None, metadata


def fetch_hl_funding(coin: str, start_ms: int, end_ms: int, opener=None) -> tuple[list[dict], dict]:
    rows_all, cursor, pages = [], start_ms, []
    stop_reason = "max_pages_reached"
    for _ in range(20):
        parsed, meta = fetch_json(HYPERLIQUID, {
            "type": "fundingHistory", "coin": coin, "startTime": int(cursor), "endTime": int(end_ms)
        }, opener=opener)
        meta["page"] = len(pages) + 1
        pages.append(meta)
        rows = parsed if isinstance(parsed, list) else []
        if not rows:
            stop_reason = "no_rows_or_request_failed"
            break
        valid = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                ts = int(row["time"]); rate = float(row["fundingRate"])
            except (KeyError, TypeError, ValueError):
                continue
            if start_ms <= ts <= end_ms:
                valid.append({"time": ts, "rate": rate})
        rows_all.extend(valid)
        page_max = max(
            (int(r["time"]) for r in rows if isinstance(r, dict) and str(r.get("time", "")).isdigit()),
            default=None,
        )
        if page_max is None or page_max < cursor:
            stop_reason = "cursor_missing_or_nonprogressing"
            break
        cursor = page_max + 1
        if cursor > end_ms or len(rows) < 500:
            stop_reason = "window_reached_or_page_not_full"
            break
        time.sleep(PAGE_DELAY_SECONDS)
    return rows_all, {"pages": pages, "pages_received": len(pages), "stop_reason": stop_reason}


def fetch_hl_candles(coin: str, start_ms: int, end_ms: int, opener=None) -> tuple[list[dict], dict]:
    parsed, meta = fetch_json(HYPERLIQUID, {
        "type": "candleSnapshot",
        "req": {"coin": coin, "interval": "1h", "startTime": start_ms, "endTime": end_ms},
    }, opener=opener)
    meta.update({"source": "Hyperliquid", "field": "1h candles", "coin": coin})
    rows = parsed if isinstance(parsed, list) else []
    out = []
    for row in rows:
        try:
            if isinstance(row, list) and len(row) >= 6:
                t = int(row[0]); o = float(row[4]); c = float(row[5])
            elif isinstance(row, dict):
                t = int(row["t"]); o = float(row["o"]); c = float(row["c"])
            else:
                continue
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        if start_ms <= t <= end_ms:
            out.append({"time": t, "open": o, "close": c})
    return out, meta


def fetch_okx_funding(inst_id: str, start_ms: int, end_ms: int, opener=None) -> tuple[list[dict], dict]:
    rows_all, cursor, pages = [], None, []
    stop_reason = "max_pages_reached"
    for _ in range(12):
        params = {"instId": inst_id, "limit": "400"}
        if cursor is not None:
            params["after"] = str(cursor)
        parsed, meta = fetch_json(OKX + "/public/funding-rate-history?" + urlencode(params),
                                  opener=opener)
        meta["page"] = len(pages) + 1
        pages.append(meta)
        data = parsed.get("data", []) if isinstance(parsed, dict) else []
        if not data:
            stop_reason = "no_rows_or_request_failed"
            break
        for row in data:
            try:
                ts = int(row["fundingTime"]); rate = float(row["fundingRate"])
            except (TypeError, ValueError, KeyError):
                continue
            if start_ms <= ts <= end_ms:
                rows_all.append({"time": ts, "rate": rate})
        try:
            oldest = min(int(r["fundingTime"]) for r in data)
        except (TypeError, ValueError, KeyError):
            stop_reason = "timestamp_missing"
            break
        if oldest <= start_ms:
            stop_reason = "window_start_reached"
            break
        cursor = oldest
        if len(data) < 400:
            stop_reason = "page_not_full"
            break
        time.sleep(PAGE_DELAY_SECONDS)
    return rows_all, {"pages": pages, "pages_received": len(pages), "stop_reason": stop_reason}


def fetch_okx_candles(inst_id: str, start_ms: int, end_ms: int, opener=None) -> tuple[list[dict], dict]:
    rows_all, cursor, pages = [], None, []
    stop_reason = "max_pages_reached"
    for _ in range(16):
        params = {"instId": inst_id, "bar": "1H", "limit": "300"}
        if cursor is not None:
            params["after"] = str(cursor)
        parsed, meta = fetch_json(OKX + "/market/history-candles?" + urlencode(params),
                                  opener=opener)
        meta["page"] = len(pages) + 1
        pages.append(meta)
        data = parsed.get("data", []) if isinstance(parsed, dict) else []
        if not data:
            stop_reason = "no_rows_or_request_failed"
            break
        for row in data:
            try:
                ts = int(row[0]); o = float(row[1]); c = float(row[4])
            except (TypeError, ValueError, IndexError):
                continue
            if start_ms <= ts <= end_ms:
                rows_all.append({"time": ts, "open": o, "close": c})
        try:
            oldest = min(int(r[0]) for r in data)
        except (TypeError, ValueError, KeyError):
            stop_reason = "timestamp_missing"
            break
        if oldest <= start_ms:
            stop_reason = "window_start_reached"
            break
        cursor = oldest
        if len(data) < 300:
            stop_reason = "page_not_full"
            break
        time.sleep(PAGE_DELAY_SECONDS)
    return rows_all, {"pages": pages, "pages_received": len(pages), "stop_reason": stop_reason}


def _latest_at_or_before(rows: list[dict], t_ms: int) -> float | None:
    best = None
    for row in sorted(rows, key=lambda r: r["time"]):
        if row["time"] <= t_ms:
            best = row["rate"]
        else:
            break
    return best


def _candle_map(rows: list[dict]) -> dict[int, tuple[float, float]]:
    return {row["time"]: (row["open"], row["close"]) for row in rows}


def _funding_observations(rows: list[dict], interval_hours: float, start_ms: int, end_ms: int,
                          venue: str = "") -> list[dict[str, Any]]:
    """Normalized (8h) funding observations within [start_ms, end_ms], plus coverage guard.

    Per the funding-accounting skill, each observation preserves the original rate,
    the documented settlement interval (units), the event time, and the 8h-normalized
    value so the normalization can be independently audited and the original rate
    retained for cash-flow recomputation.
    """
    obs = []
    for row in rows:
        if start_ms <= row["time"] <= end_ms:
            obs.append({
                "timestamp": utc_iso(row["time"]),
                "original_rate": row["rate"],
                "interval_hours": interval_hours,
                "venue": venue,
                "rate_8h": normalize_funding_rate(row["rate"], interval_hours),
            })
    return obs


def _date_range(start_utc: str, end_utc: str):
    start = datetime.fromisoformat(start_utc[:-1] + "+00:00").astimezone(timezone.utc)
    end = datetime.fromisoformat(end_utc[:-1] + "+00:00").astimezone(timezone.utc)
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    while day <= end:
        out.append(day)
        day += timedelta(days=1)
    return out


def compute_daily_dispersions(data: dict[str, dict], lookback_hours: int,
                              min_staleness_hours: float) -> dict[str, dict[str, float | None]]:
    """Per UTC date, per underlying: dispersion of normalized funding across venues."""
    daily: dict[str, dict[str, float | None]] = {}
    start_ms = utc_ms(WINDOW_START_UTC)
    end_ms = utc_ms(WINDOW_END_UTC)
    for day in _date_range(WINDOW_START_UTC, WINDOW_END_UTC):
        signal_time = day.replace(hour=23, minute=0, second=0, microsecond=0)
        if utc_ms(signal_time.isoformat().replace("+00:00", "Z")) > end_ms:
            continue
        window_start = signal_time - timedelta(hours=lookback_hours)
        ws_ms = utc_ms(window_start)
        st_ms = utc_ms(signal_time.isoformat().replace("+00:00", "Z"))
        day_str = day.date().isoformat()
        daily[day_str] = {}
        for u in UNDERLYINGS:
            d = data[u]
            hl_obs = _funding_observations(d["hl_funding"], 1.0, ws_ms, st_ms, venue="Hyperliquid")
            okx_obs = _funding_observations(d["okx_funding"], 8.0, ws_ms, st_ms, venue="OKX")
            # Guard: observations must cover the window start; include history back one staleness limit.
            if not hl_obs or not okx_obs:
                daily[day_str][u] = None
                continue
            hl_ext = _funding_observations(d["hl_funding"], 1.0, ws_ms - int(min_staleness_hours * 3600 * 1000), st_ms, venue="Hyperliquid")
            okx_ext = _funding_observations(d["okx_funding"], 8.0, ws_ms - int(min_staleness_hours * 3600 * 1000), st_ms, venue="OKX")
            histories = {"Hyperliquid": hl_ext, "OKX": okx_ext}
            dispersion, _means = dispersion_from_venue_histories(
                histories, window_start, signal_time.isoformat().replace("+00:00", "Z"),
                minimum_venues=2, max_staleness_hours=min_staleness_hours,
            )
            daily[day_str][u] = dispersion
    return daily


def select_signal_assets(daily: dict[str, dict[str, float | None]],
                         samples_by_u: dict[str, list[dict]],
                         date_str: str, percentile: int, lookback_days: int,
                         min_obs: int, tail_fraction: float) -> list[tuple[str, float]]:
    """Return [(underlying, dispersion)] selected for the signal date, or []."""
    eligible: list[tuple[str, float]] = []
    for u in UNDERLYINGS:
        disp = daily.get(date_str, {}).get(u)
        if disp is None:
            continue
        threshold = prior_daily_threshold(
            samples_by_u[u], date_str, percentile,
            lookback_days=lookback_days, minimum_observations=min_obs,
        )
        if threshold is None:
            continue
        if disp >= threshold:
            eligible.append((u, disp))
    if not eligible:
        return []
    eligible.sort(key=lambda pair: (-pair[1], pair[0]))
    count = max(1, math.ceil(len(eligible) * tail_fraction))
    return eligible[:count]


def simulate_signal(u: str, long_venue: str, short_venue: str, notional: float,
                    entry_time: datetime, exit_time: datetime, data: dict[str, dict],
                    fee_bps: float, slip_bps: float) -> dict[str, Any]:
    """Simulate one equal-notional cross-venue pair with separated attribution."""
    entry_ms = utc_ms(entry_time)
    exit_ms = utc_ms(exit_time)
    d = data[u]
    hl_candles = _candle_map(d["hl_candles"])
    okx_candles = _candle_map(d["okx_candles"])
    candle_map = {"Hyperliquid": hl_candles, "OKX": okx_candles}

    def open_price(venue: str, t_ms: int) -> float | None:
        candle = candle_map[venue].get(t_ms)
        if candle is None:
            return None
        return candle[0]

    entry_long = open_price(long_venue, entry_ms)
    entry_short = open_price(short_venue, entry_ms)
    exit_long = open_price(long_venue, exit_ms)
    exit_short = open_price(short_venue, exit_ms)
    if any(p is None for p in (entry_long, entry_short, exit_long, exit_short)):
        return {"skipped": True, "reason": "missing_candle_at_entry_or_exit"}

    long_price_pnl = price_pnl(1, notional, entry_long, exit_long)
    short_price_pnl = price_pnl(-1, notional, entry_short, exit_short)
    net_price_basis_pnl = long_price_pnl + short_price_pnl

    # Per-venue settlement-timed funding over (entry_time, exit_time].
    funding = 0.0
    settlements = 0
    for venue, side in ((long_venue, 1), (short_venue, -1)):
        rates = d["hl_funding"] if venue == "Hyperliquid" else d["okx_funding"]
        seen_times: set[int] = set()
        for row in rates:
            t = row["time"]
            if entry_ms < t <= exit_ms and t not in seen_times:
                seen_times.add(t)
                rate = _latest_at_or_before(rates, t)
                if rate is None:
                    continue
                funding += funding_cash_flow(side, notional, rate)
                settlements += 1

    fills = 2 * FILLS_PER_LEG
    fees = execution_cost(notional, fee_bps, 0.0) * fills
    slippage = execution_cost(notional, 0.0, slip_bps) * fills
    total_net_pnl = net_price_basis_pnl + funding - fees - slippage
    gross_exposure = 2.0 * notional

    return {
        "skipped": False,
        "underlying": u,
        "long_venue": long_venue,
        "short_venue": short_venue,
        "entry_time_utc": entry_time.isoformat().replace("+00:00", "Z"),
        "exit_time_utc": exit_time.isoformat().replace("+00:00", "Z"),
        "entry_price_long": entry_long,
        "entry_price_short": entry_short,
        "exit_price_long": exit_long,
        "exit_price_short": exit_short,
        "notional_per_leg": notional,
        "gross_exposure": gross_exposure,
        "price_basis_pnl": net_price_basis_pnl,
        "funding_cash_flow": funding,
        "fees": fees,
        "slippage": slippage,
        "net_pnl": total_net_pnl,
        "net_return": total_net_pnl / EQUITY,
        "funding_settlements": settlements,
    }


def run_anchor(opener=None) -> dict[str, Any]:
    """Execute the frozen FVD053 anchor over the verified overlap; descriptive only."""
    params = ANCHOR_PARAMS
    start_ms = utc_ms(WINDOW_START_UTC)
    end_ms = utc_ms(WINDOW_END_UTC)

    data: dict[str, dict] = {}
    fetch_meta: dict[str, Any] = {}
    for u in UNDERLYINGS:
        hlf, hm = fetch_hl_funding(u, start_ms, end_ms, opener=opener)
        hlc, cm = fetch_hl_candles(u, start_ms, end_ms, opener=opener)
        okf, om = fetch_okx_funding(OKX_INST_ID[u], start_ms, end_ms, opener=opener)
        okc, cm2 = fetch_okx_candles(OKX_INST_ID[u], start_ms, end_ms, opener=opener)
        data[u] = {
            "hl_funding": hlf, "okx_funding": okf,
            "hl_candles": hlc, "okx_candles": okc,
        }
        fetch_meta[u] = {
            "hyperliquid_funding": hm, "hyperliquid_candles": cm,
            "okx_funding": om, "okx_candles": cm2,
        }

    daily = compute_daily_dispersions(
        data, params["dispersion_lookback_hours"], float(params["dispersion_lookback_hours"]),
    )

    # One dispersion sample per underlying per date (snapshot at the daily 23:00 cutoff).
    samples_by_u: dict[str, list[dict]] = {u: [] for u in UNDERLYINGS}
    for day_str in sorted(daily):
        for u in UNDERLYINGS:
            disp = daily[day_str].get(u)
            if disp is not None:
                samples_by_u[u].append({
                    "date": day_str, "snapshot_time_utc": "23:00:00", "dispersion": disp,
                })

    signals: list[dict] = []
    skipped_missing_candles = 0
    skipped_missing_funding = 0
    dates_with_no_dispersion = 0
    dates_with_no_signal = 0

    for day_str in sorted(daily):
        day_date = datetime.fromisoformat(day_str).date()
        signal_time = datetime(day_date.year, day_date.month, day_date.day, 23, 0, tzinfo=timezone.utc)
        entry_time = signal_time
        exit_time = signal_time + timedelta(hours=params["holding_hours"])

        selected = select_signal_assets(
            daily, samples_by_u, day_str, params["entry_percentile"],
            params["threshold_lookback_days"], params["threshold_minimum_observations"],
            params["portfolio_tail_fraction"],
        )
        if not selected:
            dates_with_no_signal += 1
            continue

        # Count underlying-dates with any dispersion but no signal eligibility.
        any_disp = any(daily[day_str].get(u) is not None for u in UNDERLYINGS)
        if any_disp and not any(disp is not None for disp in daily[day_str].values()):
            dates_with_no_dispersion += 1

        notional = EQUITY * params["gross_multiple"] / (2.0 * len(selected))
        for u, _disp in selected:
            d = data[u]
            # Latest normalized funding at/before signal time per venue (causal).
            hl_rate = _latest_at_or_before(d["hl_funding"], utc_ms(entry_time.isoformat().replace("+00:00", "Z")))
            okx_rate = _latest_at_or_before(d["okx_funding"], utc_ms(entry_time.isoformat().replace("+00:00", "Z")))
            if hl_rate is None or okx_rate is None:
                skipped_missing_funding += 1
                continue
            hl_n = normalize_funding_rate(hl_rate, 1.0)
            okx_n = normalize_funding_rate(okx_rate, 8.0)
            if hl_n <= okx_n:
                long_venue, short_venue = "Hyperliquid", "OKX"
            else:
                long_venue, short_venue = "OKX", "Hyperliquid"
            result = simulate_signal(u, long_venue, short_venue, notional, entry_time, exit_time,
                                     data, params["fee_bps_per_side"], params["slippage_bps_per_side"])
            if result.get("skipped"):
                skipped_missing_candles += 1
                continue
            signals.append(result)

    # ---- Descriptive aggregation (no performance claims) ----
    returns = [s["net_return"] for s in signals]
    total_net = sum(s["net_pnl"] for s in signals)
    total_price = sum(s["price_basis_pnl"] for s in signals)
    total_funding = sum(s["funding_cash_flow"] for s in signals)
    total_fees = sum(s["fees"] for s in signals)
    total_slippage = sum(s["slippage"] for s in signals)
    gross_exposure = signals[0]["gross_exposure"] if signals else 0.0
    venue_pairs = sorted({(s["underlying"], s["long_venue"], s["short_venue"]) for s in signals})

    def _std(values: list[float]) -> float | None:
        if len(values) < 2:
            return None
        m = sum(values) / len(values)
        return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))

    volatility = _std(returns)

    cumulative = 0.0
    peak = 0.0
    worst_decline = 0.0
    for r in returns:
        cumulative += r
        peak = max(peak, cumulative)
        worst_decline = max(worst_decline, peak - cumulative)

    total_executions = 4 * len(signals)
    turnover_notional = sum(4 * s["notional_per_leg"] for s in signals)
    total_settlements = sum(s["funding_settlements"] for s in signals)

    # Cost sensitivity: base (5/5 bps) vs stress (10/10 bps), same price/funding path.
    stress_net = sum(
        s["price_basis_pnl"] + s["funding_cash_flow"]
        - execution_cost(s["notional_per_leg"], 10.0, 0.0) * (2 * FILLS_PER_LEG)
        - execution_cost(s["notional_per_leg"], 0.0, 10.0) * (2 * FILLS_PER_LEG)
        for s in signals
    ) / EQUITY if signals else None
    optimistic_net = sum(
        s["price_basis_pnl"] + s["funding_cash_flow"]
        - execution_cost(s["notional_per_leg"], 2.0, 0.0) * (2 * FILLS_PER_LEG)
        - execution_cost(s["notional_per_leg"], 0.0, 2.0) * (2 * FILLS_PER_LEG)
        for s in signals
    ) / EQUITY if signals else None

    result = {
        "schema_version": "1.0",
        "run_type": "fvd053_anchor_exploratory",
        "experiment_id": "FVD-EXPLORATORY-002",
        "anchor": "FVD053",
        "status": "EXPLORATORY_ONLY",
        "inconclusive": True,
        "backtest_completed": False,
        "performance_metrics_computed": False,
        "confirmatory_status_preserved": "BLOCKED_DATA_GATE",
        "anchor_params": dict(params),
        "equity": EQUITY,
        "gross_exposure_cap": "1.0x equity",
        "window_start_utc": WINDOW_START_UTC,
        "window_end_utc": WINDOW_END_UTC,
        "underlyings": list(UNDERLYINGS),
        "venues": ["Hyperliquid", "OKX"],
        "data_cutoff_utc": WINDOW_END_UTC,
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sample_construction": (
            "Verified historical intersection of 5 underlyings with funding settlements "
            "+ 1h price history on 2 venues; no market-cap rank; shorter history vs the "
            ">=3-year confirmatory requirement; contract identity by underlying symbol only."
        ),
        "signal_count": len(signals),
        "dates_with_no_signal": dates_with_no_signal,
        "dates_with_no_dispersion": dates_with_no_dispersion,
        "skipped_missing_candles": skipped_missing_candles,
        "skipped_missing_funding": skipped_missing_funding,
        "total_funding_settlements": total_settlements,
        "venue_pair_count": len(venue_pairs),
        "venue_pairs": venue_pairs,
        "total_executions": total_executions,
        "turnover_notional": turnover_notional,
        "average_gross_exposure": gross_exposure,
        "average_gross_exposure_multiple": gross_exposure / EQUITY if EQUITY else None,
        "attribution": {
            "total_price_basis_pnl": total_price,
            "total_funding_cash_flow": total_funding,
            "total_fees": total_fees,
            "total_slippage": total_slippage,
            "total_net_pnl": total_net,
        },
        "net_return": total_net / EQUITY if EQUITY else None,
        "gross_price_return": total_price / EQUITY if EQUITY else None,
        "volatility_per_signal_return": volatility,
        "peak_to_trough_decline": worst_decline,
        "peak_to_trough_decline_pct_of_equity": worst_decline / EQUITY if EQUITY else None,
        "cost_sensitivity": {
            "base_fee_slippage_bps": (params["fee_bps_per_side"], params["slippage_bps_per_side"]),
            "base_net_return": total_net / EQUITY if EQUITY else None,
            "stress_fee_slippage_bps": (10.0, 10.0),
            "stress_net_return": stress_net,
            "optimistic_fee_slippage_bps": (2.0, 2.0),
            "optimistic_net_return": optimistic_net,
        },
        "uncertainty": (
            "Not estimable: signal episodes overlap within a 24-hour holding window and are "
            "not independent; the sample window is ~97 days vs the >=3-year confirmatory "
            "requirement. No block-bootstrap confidence interval is reported."
        ),
        "signals": signals,
        "fetch_metadata": fetch_meta,
    }
    return result


def write_artifact(result: dict[str, Any], path: str) -> str:
    directory = os.path.dirname(os.path.abspath(path))
    Path(directory).mkdir(parents=True, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(result, handle, sort_keys=True, indent=2)
        handle.write("\n")
    os.replace(tmp, path)
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="research_state/fvd053_anchor_run_2026-10-25.json")
    args = parser.parse_args(argv)
    result = run_anchor()
    sha = write_artifact(result, args.output)
    print(json.dumps({
        "status": result["status"],
        "experiment_id": result["experiment_id"],
        "anchor": result["anchor"],
        "signal_count": result["signal_count"],
        "net_return": result["net_return"],
        "output": args.output,
        "sha256": sha,
        "backtest_completed": False,
        "performance_metrics_computed": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
