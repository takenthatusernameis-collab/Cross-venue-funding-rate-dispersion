#!/usr/bin/env python3
"""Bounded, checksum-verified content probe for Binance USD-M monthly archives.

Standard library only. No credentials, no paid tier, no order endpoints.

This is the content-level companion to the checksum-object availability check in
`scripts/probe_historical_overlap.py` (which only proves an object path answers
HTTP 200 and never downloads archive bytes). For each requested
symbol x field x month it:

1. downloads the small `.zip.CHECKSUM` object and parses the expected sha256;
2. downloads the bounded `.zip` object (capped by MAX_ZIP_BYTES);
3. recomputes the sha256 and fails closed on any mismatch;
4. parses the CSV member with `parse_binance_archive` (strict schema, no
   silent row skipping) and records row counts, first/last timestamps and the
   observed funding interval.

It writes a compact JSON summary only. Bulk archive bytes are never committed
and no strategy outcome, backtest or performance metric is computed.
"""
import argparse
import hashlib
import io
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import parse_binance_archive as parser

ARCHIVE_BASE = "https://data.binance.vision"
TIMEOUT_SECONDS = 30
MAX_CHECKSUM_BYTES = 4096
MAX_ZIP_BYTES = 8_000_000
FIELDS = {
    "fundingRate": {
        "url": "data/futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip",
        "kind": "funding",
    },
    "klines": {
        "url": "data/futures/um/monthly/klines/{symbol}/1h/{symbol}-1h-{month}.zip",
        "kind": "klines",
    },
}
DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def object_url(symbol: str, field: str, month: str) -> str:
    return ARCHIVE_BASE + "/" + FIELDS[field]["url"].format(symbol=symbol, month=month)


def parse_checksum_text(text: str):
    """Return the (sha256, filename) recorded in a Binance .CHECKSUM object.

    Binance writes a single `<sha256>  <filename>` line. Anything that is not
    exactly one 64-hex-digit digest followed by a filename fails closed.
    """
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            raise ValueError("checksum line missing filename: %r" % (line,))
        digest = parts[0].lower()
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("checksum digest is not sha256 hex: %r" % (parts[0],))
        return digest, parts[1]
    raise ValueError("empty checksum object")


def _fetch_bytes(url: str, max_bytes: int, opener=None) -> bytes:
    open_fn = opener or urlopen
    req = Request(url, method="GET")
    with open_fn(req, timeout=TIMEOUT_SECONDS) as resp:
        body = resp.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise ValueError("response exceeds %d-byte cap for %s" % (max_bytes, url))
    return body


def verify_object(symbol: str, field: str, month: str, opener=None) -> dict:
    """Download, checksum-verify and parse one monthly archive object.

    Returns a compact record. Never raises for a failed object: the failure is
    recorded with `checksum_match=False` and an `error` string so a caller can
    fail closed on inspection instead of losing the partial evidence.
    """
    url = object_url(symbol, field, month)
    record = {
        "symbol": symbol,
        "field": field,
        "month": month,
        "url": url,
        "checksum_url": url + ".CHECKSUM",
        "expected_sha256": None,
        "actual_sha256": None,
        "checksum_match": False,
        "zip_bytes": None,
        "rows": None,
        "first_utc": None,
        "last_utc": None,
        "funding_interval_hours": None,
        "error": None,
    }
    try:
        checksum_text = _fetch_bytes(url + ".CHECKSUM", MAX_CHECKSUM_BYTES, opener).decode("utf-8", "replace")
        expected, checksum_name = parse_checksum_text(checksum_text)
        record["expected_sha256"] = expected
        record["checksum_object_filename"] = checksum_name
        zip_bytes = _fetch_bytes(url, MAX_ZIP_BYTES, opener)
        actual = hashlib.sha256(zip_bytes).hexdigest()
        record["actual_sha256"] = actual
        record["zip_bytes"] = len(zip_bytes)
        if actual != expected:
            raise ValueError("checksum mismatch: expected %s actual %s" % (expected, actual))
        record["checksum_match"] = True
        members = [
            name for name in zipfile.ZipFile(io.BytesIO(zip_bytes)).namelist()
            if name.lower().endswith(".csv")
        ]
        if len(members) != 1:
            raise ValueError("expected exactly one CSV member, found %r" % (members,))
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            text = archive.read(members[0]).decode("utf-8", "replace")
        if FIELDS[field]["kind"] == "funding":
            rows = parser.parse_funding_csv(text, symbol=symbol)
            record["rows"] = len(rows)
            record["first_utc"] = rows[0]["timestamp_utc"]
            record["last_utc"] = rows[-1]["timestamp_utc"]
            record["funding_interval_hours"] = sorted({r["funding_interval_hours"] for r in rows})
        else:
            rows = parser.parse_klines_csv(text, symbol=symbol)
            record["rows"] = len(rows)
            record["first_utc"] = rows[0]["timestamp_utc"]
            record["last_utc"] = rows[-1]["timestamp_utc"]
        record["csv_member"] = members[0]
    except Exception as exc:  # fail closed, keep partial evidence
        record["error"] = "%s: %s" % (type(exc).__name__, exc)
    return record


def verify_month(month: str, symbols, fields, opener=None) -> list[dict]:
    records = []
    for symbol in symbols:
        for field in fields:
            records.append(verify_object(symbol, field, month, opener=opener))
    return records


def summarize(records: list[dict]) -> dict:
    verified = [r for r in records if r["checksum_match"] and r["error"] is None]
    funding = [r for r in verified if FIELDS[r["field"]]["kind"] == "funding"]
    klines = [r for r in verified if FIELDS[r["field"]]["kind"] == "klines"]
    intervals = sorted({h for r in funding for h in (r["funding_interval_hours"] or [])})
    returns = {
        "objects_requested": len(records),
        "objects_checksum_verified": len(verified),
        "objects_failed": len(records) - len(verified),
        "funding_objects_verified": len(funding),
        "klines_objects_verified": len(klines),
        "funding_rows_total": sum(r["rows"] for r in funding),
        "klines_rows_total": sum(r["rows"] for r in klines),
        "funding_interval_hours_observed": intervals,
        "content_proven": bool(records) and len(verified) == len(records),
        "earliest_utc": min((r["first_utc"] for r in verified), default=None),
        "latest_utc": max((r["last_utc"] for r in verified), default=None),
    }
    return returns


def build_artifact(month: str, symbols, fields, records, accessed_at_utc=None) -> dict:
    summary = summarize(records)
    return {
        "schema_version": "1.0",
        "artifact_type": "binance_month_content_verification",
        "status": "EXPLORATORY_ONLY",
        "backtest_completed": False,
        "performance_metrics_computed": False,
        "original_confirmatory_gate": "BLOCKED_DATA_GATE",
        "observed_at_utc": accessed_at_utc or _utc_now(),
        "source": "Binance Public Data archive (data.binance.vision)",
        "access_mode": "anonymous HTTPS, no credentials, no paid tier",
        "purpose": "Checksum-verified content check of Binance USD-M monthly funding and 1h kline archives. Upgrades object availability to parsed row coverage. No strategy outcome or performance metric.",
        "month": month,
        "symbols": list(symbols),
        "fields": list(fields),
        "objects": records,
        "coverage_summary": summary,
        "note": "Archive bytes are downloaded only in memory, checksum-verified against the official .CHECKSUM object and parsed with the strict repo parser. No bulk archive is committed.",
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Checksum-verified Binance monthly archive content probe")
    ap.add_argument("--month", required=True, help="archive month, e.g. 2026-10")
    ap.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    ap.add_argument("--fields", nargs="+", default=list(FIELDS), choices=list(FIELDS))
    ap.add_argument("--output", required=True)
    args = ap.parse_args(argv)

    records = verify_month(args.month, args.symbols, args.fields)
    artifact = build_artifact(args.month, args.symbols, args.fields, records)
    Path(args.output).write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = artifact["coverage_summary"]
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["content_proven"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
