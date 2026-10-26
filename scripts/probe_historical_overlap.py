#!/usr/bin/env python3
"""Bounded no-credential probe of correct free historical funding/price routes.

This is a coverage probe, not a backtest. It stores response hashes and summaries,
not raw market rows. The original FVD data gate is never marked as passed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

HYPERLIQUID = "https://api.hyperliquid.xyz/info"
OKX = "https://www.okx.com/api/v5"
BINANCE_ARCHIVE = "https://data.binance.vision"
TIMEOUT_SECONDS = 8
MAX_RESPONSE_BYTES = 2_000_000
MAX_ASSETS = 5
MAX_HL_FUNDING_PAGES = 12
MAX_OKX_FUNDING_PAGES = 12
MAX_OKX_CANDLE_PAGES = 16
PAGE_DELAY_SECONDS = 0.12
PRIORITY_BASES = ("BTC", "ETH", "SOL", "AVAX", "LINK", "XRP", "DOGE", "BNB", "HYPE", "ARB", "OP")
TARGET_FIVE = ("BTC", "ETH", "SOL", "AVAX", "LINK")


def utc_iso_ms(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def request_json(url: str, payload: dict | None = None, timeout: int = TIMEOUT_SECONDS,
                 opener=None) -> tuple[dict, Any]:
    """Make one bounded, unauthenticated JSON request and retain its exact byte hash."""
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode() if payload is not None else None
    headers = {"User-Agent": "cross-venue-funding-dispersion-research/2.1"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
    metadata = {
        "url": url,
        "method": req.get_method(),
        "request_sha256": hashlib.sha256(body).hexdigest() if body is not None else None,
        "http_status": None,
        "response_bytes_read": None,
        "response_sha256": None,
        "response_prefix_sha256": None,
        "response_hash_complete": False,
        "response_shape": None,
        "latency_ms": None,
        "error": None,
    }
    start = time.monotonic()
    open_fn = opener or urlopen
    raw = b""
    try:
        with open_fn(req, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            metadata["http_status"] = response.status
    except HTTPError as exc:
        metadata["http_status"] = exc.code
        try:
            raw = exc.read(MAX_RESPONSE_BYTES + 1)
        except Exception:
            raw = b""
        metadata["error"] = f"HTTPError: {exc.code}"
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        metadata["error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
    finally:
        metadata["latency_ms"] = round((time.monotonic() - start) * 1000, 1)

    if raw:
        metadata["response_bytes_read"] = len(raw)
        digest = hashlib.sha256(raw).hexdigest()
        if len(raw) > MAX_RESPONSE_BYTES:
            # urlopen.read(MAX_RESPONSE_BYTES + 1) intentionally truncates large
            # responses. A digest of this prefix must never be mislabeled as the
            # checksum of the complete source response.
            metadata["response_prefix_sha256"] = digest
            metadata["response_hash_complete"] = False
            metadata["response_shape"] = "oversize"
            metadata["error"] = metadata["error"] or "response exceeded configured byte cap; only prefix was read"
            return metadata, None
        metadata["response_sha256"] = digest
        metadata["response_hash_complete"] = True
        try:
            parsed = json.loads(raw.decode("utf-8"))
            metadata["response_shape"] = "json"
            return metadata, parsed
        except (UnicodeDecodeError, json.JSONDecodeError):
            metadata["response_shape"] = "non-json"
            return metadata, None
    return metadata, None


def hl_candle_payload(coin: str, start_ms: int, end_ms: int, interval: str = "1h") -> dict:
    """Hyperliquid candleSnapshot requires fields nested under req."""
    return {
        "type": "candleSnapshot",
        "req": {
            "coin": coin,
            "interval": interval,
            "startTime": int(start_ms),
            "endTime": int(end_ms),
        },
    }


HL_UNIVERSE_FIELDS = (
    "name", "szDecimals", "maxLeverage", "marginTableId",
    "displaySymbol", "contractType", "id",
)


def extract_hl_coins(meta: Any) -> set[str]:
    if not isinstance(meta, dict) or not isinstance(meta.get("universe"), list):
        return set()
    return {str(row["name"]) for row in meta["universe"]
            if isinstance(row, dict) and row.get("name") is not None}


def extract_hl_universe_details(meta: Any) -> dict[str, dict]:
    if not isinstance(meta, dict) or not isinstance(meta.get("universe"), list):
        return {}
    out: dict[str, dict] = {}
    for entry in meta["universe"]:
        if not isinstance(entry, dict) or entry.get("name") is None:
            continue
        name = str(entry["name"])
        if name in out:
            continue
        out[name] = {k: entry.get(k) for k in HL_UNIVERSE_FIELDS if k in entry}
    return out


def extract_okx_linear_usdt_swaps(payload: Any) -> dict[str, dict]:
    if not isinstance(payload, dict) or payload.get("code") != "0" or not isinstance(payload.get("data"), list):
        return {}
    out = {}
    for item in payload["data"]:
        if not isinstance(item, dict):
            continue
        if (item.get("ctType") == "linear" and item.get("settleCcy") == "USDT"
                and item.get("state") == "live"):
            base = item.get("baseCcy") or str(item.get("instId", "")).split("-")[0]
            if base and base not in out:
                out[str(base)] = item
    return out


OKX_INSTRUMENT_SPEC_FIELDS = (
    "instId", "baseCcy", "quoteCcy", "settleCcy", "ctType", "state",
    "ctVal", "ctValCcy", "ctMult", "uly", "instIdCode", "instCategory",
    "instFamily", "listTime", "lever", "tickSz", "lotSz", "minSz",
)


def extract_okx_instrument_details(payload: Any) -> dict[str, dict]:
    raw = extract_okx_linear_usdt_swaps(payload)
    out: dict[str, dict] = {}
    for base, item in raw.items():
        out[base] = {k: item.get(k) for k in OKX_INSTRUMENT_SPEC_FIELDS if k in item}
    return out


def verify_contract_identity(
    hl_details: dict[str, dict],
    okx_details: dict[str, dict],
) -> dict:
    """Cross-reference Hyperliquid and OKX instrument metadata to assign
    contract-identity evidence levels.

    Evidence levels per underlying:
      - verified: full metadata comparison confirms equivalent contracts (same
        underlying, same settlement semantics, no unresolved spec mismatch).
      - candidate: symbol-level underlying match exists on both venues but
        settlement-currency or full-spec equivalence cannot be confirmed from
        the available metadata.
      - unverified: no match found.

    This function performs metadata comparison only; it does not establish
    historical listing/delisting tracking or a guaranteed one-to-one contract
    identifier across venues.
    """
    results: dict[str, dict] = {}
    common = sorted(set(hl_details.keys()) & set(okx_details.keys()))
    for base in common:
        hl = hl_details[base]
        okx = okx_details[base]
        hl_settle = hl.get("settleCcy") or hl.get("settlementCurrency")
        okx_settle = okx.get("settleCcy")
        hl_quote = hl.get("quoteCcy")
        okx_quote = okx.get("quoteCcy") or okx.get("uly", "").split("-")[-1] if okx.get("uly") else None
        hl_name = hl.get("name")
        okx_base = okx.get("baseCcy") or okx.get("instId", "").split("-")[0]
        underlying_match = hl_name == okx_base
        settlement_match = hl_settle is not None and hl_settle == okx_settle
        quote_match = hl_quote is not None and hl_quote == okx_quote
        hl_settle_known = hl_settle is not None
        if underlying_match and settlement_match and hl_settle_known:
            level = "verified"
        elif underlying_match:
            level = "candidate"
        else:
            level = "unverified"
        results[base] = {
            "evidence_level": level,
            "underlying_match": underlying_match,
            "hl_name": hl_name,
            "okx_base_ccy": okx_base,
            "hl_settle_ccy": hl_settle,
            "okx_settle_ccy": okx_settle,
            "settlement_match": settlement_match,
            "hl_settle_known": hl_settle_known,
            "quote_match": quote_match,
            "hl_spec": {k: hl.get(k) for k in ("name", "szDecimals", "maxLeverage", "marginTableId")},
            "okx_spec": {k: okx.get(k) for k in ("instId", "uly", "ctVal", "ctValCcy", "ctMult", "ctType", "settleCcy", "listTime")},
            "limitations": [
                "Hyperliquid perpetual settlement currency (USDC) is not exposed in the meta endpoint; settlement equivalence is inferred, not proven.",
                "OKX baseCcy is empty for linear USDT swaps; base is derived from instId, not independently verified.",
                "No common cross-venue contract identifier or historical listing/delisting timeline is compared.",
                "Survivorship and ticker-reuse handling not assessed.",
            ],
        }
    for base in sorted(set(hl_details.keys()) - set(okx_details.keys())):
        results[base] = {"evidence_level": "unverified", "underlying_match": False,
                         "limitations": ["Present on Hyperliquid but not found in OKX linear USDT swaps."]}
    for base in sorted(set(okx_details.keys()) - set(hl_details.keys())):
        results[base] = {"evidence_level": "unverified", "underlying_match": False,
                         "limitations": ["Present on OKX but not found in Hyperliquid universe."]}
    return results


def collect_contract_identity(
    hl_meta: dict,
    okx_meta: dict,
    target_bases: tuple[str, ...] = TARGET_FIVE,
) -> dict:
    """Collect Hyperliquid and OKX instrument metadata and run cross-venue
    contract-identity verification for the requested target underlyings.
    """
    hl_details_all = extract_hl_universe_details(hl_meta.get("parsed") if isinstance(hl_meta, dict) and "parsed" in hl_meta else _meta_payload_to_universe(hl_meta))
    okx_details_all = extract_okx_instrument_details(okx_meta.get("parsed") if isinstance(okx_meta, dict) and "parsed" in okx_meta else okx_meta)
    return {
        "target_underlyings": list(target_bases),
        "hl_universe_size": len(hl_details_all),
        "okx_instrument_count": len(okx_details_all),
        "per_underlying": {b: verify_contract_identity(
            {b: hl_details_all[b]} if b in hl_details_all else {},
            {b: okx_details_all[b]} if b in okx_details_all else {},
        ).get(b, {"evidence_level": "unverified", "underlying_match": False,
                  "limitations": ["Target base not found in either venue metadata."]}) for b in target_bases},
    }


def _meta_payload_to_universe(payload: Any) -> dict:
    if isinstance(payload, dict) and "universe" in payload:
        return payload
    return {}


def summarize_rows(rows: list, timestamp_field: str | None = None,
                   hourly_candles: bool = False) -> dict:
    timestamps = []
    for row in rows:
        try:
            raw_ts = row.get(timestamp_field) if isinstance(row, dict) and timestamp_field else (
                row[0] if isinstance(row, (list, tuple)) and row else None
            )
            if raw_ts is not None:
                timestamps.append(int(raw_ts))
        except (TypeError, ValueError, IndexError):
            continue
    unique = sorted(set(timestamps))
    gaps = []
    if hourly_candles and len(unique) > 1:
        gaps = [(b - a) // 3_600_000 - 1 for a, b in zip(unique, unique[1:])
                if b - a > 3_600_000]
    return {
        "row_count": len(rows),
        "timestamp_count": len(timestamps),
        "unique_timestamp_count": len(unique),
        "duplicate_timestamps": len(timestamps) - len(unique),
        "earliest_utc": utc_iso_ms(unique[0]) if unique else None,
        "latest_utc": utc_iso_ms(unique[-1]) if unique else None,
        "hourly_gap_count": len(gaps),
        "maximum_missing_hours_in_gap": max(gaps) if gaps else 0,
    }


def unwrap_okx(payload: Any) -> list:
    if not isinstance(payload, dict) or payload.get("code") != "0":
        return []
    return payload.get("data", []) if isinstance(payload.get("data"), list) else []


def probe_hl_candles(coin: str, start_ms: int, end_ms: int) -> dict:
    meta, rows = request_json(HYPERLIQUID, hl_candle_payload(coin, start_ms, end_ms))
    rows = rows if isinstance(rows, list) else []
    meta.update({"source": "Hyperliquid", "field": "1h candles", "coin": coin,
                 "window_start_utc": utc_iso_ms(start_ms), "window_end_utc": utc_iso_ms(end_ms),
                 "history_limit_documented": "most recent 5000 candles",
                 "coverage": summarize_rows(rows, "t", hourly_candles=True)})
    return meta


def probe_hl_funding(coin: str, start_ms: int, end_ms: int) -> dict:
    pages, rows_all, seen, cursor = [], [], set(), start_ms
    stop_reason = "max_pages_reached"
    for _ in range(MAX_HL_FUNDING_PAGES):
        meta, rows = request_json(HYPERLIQUID, {
            "type": "fundingHistory", "coin": coin, "startTime": int(cursor), "endTime": int(end_ms)
        })
        meta["page"] = len(pages) + 1
        pages.append(meta)
        if not isinstance(rows, list) or not rows:
            stop_reason = "no_rows_or_request_failed"
            break
        valid = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                ts = int(row["time"])
            except (KeyError, TypeError, ValueError):
                continue
            if start_ms <= ts <= end_ms and ts not in seen:
                seen.add(ts)
                valid.append(row)
        rows_all.extend(valid)
        page_max = max((int(x["time"]) for x in rows if isinstance(x, dict) and str(x.get("time", "")).isdigit()), default=None)
        if page_max is None or page_max < cursor:
            stop_reason = "cursor_missing_or_nonprogressing"
            break
        next_cursor = page_max + 1
        if next_cursor <= cursor:
            stop_reason = "cursor_stalled"
            break
        cursor = next_cursor
        if cursor > end_ms or len(rows) < 500:
            stop_reason = "window_reached_or_page_not_full"
            break
        time.sleep(PAGE_DELAY_SECONDS)
    return {
        "source": "Hyperliquid", "field": "settled funding history", "coin": coin,
        "window_start_utc": utc_iso_ms(start_ms), "window_end_utc": utc_iso_ms(end_ms),
        "pages": pages, "pages_received": len(pages), "stop_reason": stop_reason,
        "coverage": summarize_rows(rows_all, "time"),
        "settled_rate_nonempty_count": sum(bool(x.get("fundingRate")) for x in rows_all),
    }


def okx_url(path: str, params: dict) -> str:
    return f"{OKX}{path}?{urlencode(params)}"


def probe_okx_candles(inst_id: str, start_ms: int, end_ms: int) -> dict:
    rows_all, seen, pages, cursor = [], set(), [], None
    stop_reason = "max_pages_reached"
    for _ in range(MAX_OKX_CANDLE_PAGES):
        params = {"instId": inst_id, "bar": "1H", "limit": "300"}
        if cursor is not None:
            params["after"] = str(cursor)
        meta, payload = request_json(okx_url("/market/history-candles", params))
        meta["page"] = len(pages) + 1
        pages.append(meta)
        rows = unwrap_okx(payload)
        if not rows:
            stop_reason = "no_rows_or_request_failed"
            break
        valid = []
        for row in rows:
            try:
                ts = int(row[0])
            except (TypeError, ValueError, IndexError):
                continue
            if start_ms <= ts <= end_ms and ts not in seen:
                seen.add(ts)
                valid.append(row)
        rows_all.extend(valid)
        try:
            oldest = min(int(row[0]) for row in rows)
        except (ValueError, TypeError, IndexError):
            stop_reason = "timestamp_missing"
            break
        if oldest <= start_ms:
            stop_reason = "window_start_reached"
            break
        if cursor is not None and oldest >= cursor:
            stop_reason = "cursor_stalled"
            break
        cursor = oldest
        if len(rows) < 300:
            stop_reason = "page_not_full"
            break
        time.sleep(PAGE_DELAY_SECONDS)
    return {
        "source": "OKX", "field": "1h historical candles", "instId": inst_id,
        "window_start_utc": utc_iso_ms(start_ms), "window_end_utc": utc_iso_ms(end_ms),
        "pages": pages, "pages_received": len(pages), "stop_reason": stop_reason,
        "coverage": summarize_rows(rows_all, hourly_candles=True),
        "history_endpoint": "market/history-candles",
    }


def probe_okx_funding(inst_id: str, start_ms: int, end_ms: int) -> dict:
    rows_all, seen, pages, cursor = [], set(), [], None
    stop_reason = "max_pages_reached"
    for _ in range(MAX_OKX_FUNDING_PAGES):
        params = {"instId": inst_id, "limit": "400"}
        if cursor is not None:
            params["after"] = str(cursor)
        meta, payload = request_json(okx_url("/public/funding-rate-history", params))
        meta["page"] = len(pages) + 1
        pages.append(meta)
        rows = unwrap_okx(payload)
        if not rows:
            stop_reason = "no_rows_or_request_failed"
            break
        for row in rows:
            try:
                ts = int(row["fundingTime"])
            except (TypeError, ValueError, KeyError):
                continue
            if start_ms <= ts <= end_ms and ts not in seen:
                seen.add(ts)
                rows_all.append(row)
        try:
            oldest = min(int(row["fundingTime"]) for row in rows)
        except (ValueError, TypeError, KeyError):
            stop_reason = "timestamp_missing"
            break
        if oldest <= start_ms:
            stop_reason = "window_start_reached"
            break
        if cursor is not None and oldest >= cursor:
            stop_reason = "cursor_stalled"
            break
        cursor = oldest
        if len(rows) < 400:
            stop_reason = "page_not_full"
            break
        time.sleep(PAGE_DELAY_SECONDS)
    return {
        "source": "OKX", "field": "funding rate history", "instId": inst_id,
        "window_start_utc": utc_iso_ms(start_ms), "window_end_utc": utc_iso_ms(end_ms),
        "pages": pages, "pages_received": len(pages), "stop_reason": stop_reason,
        "coverage": summarize_rows(rows_all, "fundingTime"),
        "realized_rate_nonempty_count": sum(bool(x.get("realizedRate")) for x in rows_all),
        "history_limit_documented": "up to three months",
    }


def probe_binance_archive() -> list[dict]:
    candidates = [
        (f"{BINANCE_ARCHIVE}/data/futures/um/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2024-01.zip.CHECKSUM",
         "USD-M hourly kline archive checksum"),
        (f"{BINANCE_ARCHIVE}/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2024-01.zip.CHECKSUM",
         "candidate fundingRate archive checksum; object availability must be verified"),
    ]
    results = []
    for url, label in candidates:
        meta, payload = request_json(url)
        meta.update({"source": "Binance Public Data archive", "field": label,
                     "coverage_proven": False, "note": "checksum-object response only; does not download/validate archive bytes"})
        results.append(meta)
    return results


def run_probe(lookback_days: int = 120, max_assets: int = MAX_ASSETS) -> dict:
    if lookback_days < 90 or lookback_days > 180:
        raise ValueError("lookback_days must be between 90 and 180 for this bounded coverage probe")
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    end_ms = (now_ms // 3_600_000) * 3_600_000 - 1  # last fully closed UTC hour
    start_ms = end_ms - lookback_days * 86_400_000

    hl_meta_result, hl_meta = request_json(HYPERLIQUID, {"type": "meta"})
    hl_coins = extract_hl_coins(hl_meta)
    okx_meta_result, okx_meta = request_json(okx_url("/public/instruments", {"instType": "SWAP"}))
    okx_instruments = extract_okx_linear_usdt_swaps(okx_meta)
    # Prefer the five assets mentioned in the verified probe evidence
    common = [base for base in TARGET_FIVE if base in hl_coins and base in okx_instruments]
    # Fall back to priority order if any missing
    if len(common) < max_assets:
        for base in PRIORITY_BASES:
            if base in common:
                continue
            if base in hl_coins and base in okx_instruments:
                common.append(base)
            if len(common) >= max_assets:
                break
    common = common[:max_assets]

    contract_identity = collect_contract_identity(hl_meta, okx_meta, tuple(common))

    routes = {
        "hyperliquid_meta": {**hl_meta_result, "source": "Hyperliquid", "field": "perpetual instrument metadata"},
        "okx_instruments": {**okx_meta_result, "source": "OKX", "field": "current linear USDT swap metadata",
                            "candidate_count": len(okx_instruments)},
        "hyperliquid_candles": [],
        "hyperliquid_funding": [],
        "okx_candles": [],
        "okx_funding": [],
        "binance_archive_candidates": [],
    }
    for base in common:
        routes["hyperliquid_candles"].append(probe_hl_candles(base, start_ms, end_ms))
        routes["hyperliquid_funding"].append(probe_hl_funding(base, start_ms, end_ms))
        inst_id = str(okx_instruments[base].get("instId", ""))
        routes["okx_candles"].append(probe_okx_candles(inst_id, start_ms, end_ms))
        routes["okx_funding"].append(probe_okx_funding(inst_id, start_ms, end_ms))
    routes["binance_archive_candidates"] = probe_binance_archive()

    any_http = any(
        item.get("http_status") is not None
        for value in routes.values()
        for item in (value if isinstance(value, list) else [value])
        if isinstance(item, dict)
    )
    source_responses = sum(
        item.get("http_status") is not None
        for value in routes.values()
        for item in (value if isinstance(value, list) else [value])
        if isinstance(item, dict)
    )
    status = "SOURCE_PROBE_COMPLETED" if any_http else "NETWORK_UNAVAILABLE_FROM_THIS_HOST"
    return {
        "schema_version": "1.0",
        "run_type": "bounded_free_historical_overlap_probe",
        "status": status,
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "window_start_utc": utc_iso_ms(start_ms),
        "window_end_utc": utc_iso_ms(end_ms),
        "lookback_days_requested": lookback_days,
        "candidate_assets_intersection": common,
        "candidate_asset_count": len(common),
        "contract_identity": contract_identity,
        "routes": routes,
        "source_responses_with_http_status": source_responses,
        "historical_coverage_gate": "NOT_PASSED_BY_COVERAGE_PROBE",
        "original_confirmatory_gate": "BLOCKED_DATA_GATE",
        "backtest_completed": False,
        "performance_metrics_computed": False,
        "limitations": [
            "This is a bounded source probe, not a strategy backtest.",
            "Current instrument metadata does not prove historical listing/delisting or contract identity.",
            "The short candidate list is a probe sample, not the full expanding research universe.",
            "Response availability does not prove data completeness, event maturity, executable fills, or point-in-time market-cap ranks.",
            "No response hash or coverage is reported for requests that failed before receiving response bytes.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookback-days", type=int, default=120)
    parser.add_argument("--max-assets", type=int, default=MAX_ASSETS, choices=range(1, MAX_ASSETS + 1))
    parser.add_argument("--output", default="/tmp/cross-venue-historical-overlap-probe.json")
    args = parser.parse_args(argv)
    report = run_probe(args.lookback_days, args.max_assets)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"], "output": str(out),
        "candidate_asset_count": report["candidate_asset_count"],
        "source_responses_with_http_status": report["source_responses_with_http_status"],
        "original_confirmatory_gate": report["original_confirmatory_gate"],
        "backtest_completed": False, "performance_metrics_computed": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
