#!/usr/bin/env python3
"""Deterministic parser for Binance USD-M futures archive CSV rows (standard library only).

No network access. No archive downloads. Parses CSV row tuples into structured
funding and klines records using the schema documented and checksum-verified
in research_state/binance_archive_feasibility_assessment_2026-10-26.json.

Funding CSV header: calc_time,funding_interval_hours,last_funding_rate
Klines CSV header:  open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore
"""
import csv
import io
import sys
from datetime import datetime, timezone

FUNDING_SCHEMA_FIELDS = ["calc_time", "funding_interval_hours", "last_funding_rate"]
KLINES_SCHEMA_FIELDS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "count", "taker_buy_volume",
    "taker_buy_quote_volume", "ignore",
]
BINANCE_FUNDING_INTERVAL_HOURS = 8.0


def ms_to_iso(ms) -> str:
    """Convert a millisecond Unix timestamp to a UTC ISO-8601 string."""
    ms_int = int(ms)
    if ms_int < 0:
        raise ValueError("negative timestamp: %r" % (ms,))
    dt = datetime.fromtimestamp(ms_int / 1000.0, tz=timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_funding_row(row, symbol=None) -> dict:
    """Parse a single fundingRate CSV row into a structured record.

    Expected field order: calc_time, funding_interval_hours, last_funding_rate.
    Rejects rows with wrong arity, non-numeric timestamps, non-finite rates,
    or unknown interval hours.
    """
    if len(row) < 3:
        raise ValueError("funding row has too few fields: %r" % (row,))
    calc_time_ms = int(row[0])
    interval_hours = float(row[1])
    rate = float(row[2])
    import math
    if not math.isfinite(rate):
        raise ValueError("non-finite funding rate: %r" % (row[2],))
    if not math.isfinite(interval_hours):
        raise ValueError("non-finite interval: %r" % (row[1],))
    if interval_hours <= 0:
        raise ValueError("non-positive interval: %r" % (row[1],))
    return {
        "symbol": symbol,
        "calc_time_ms": calc_time_ms,
        "timestamp_utc": ms_to_iso(calc_time_ms),
        "funding_interval_hours": interval_hours,
        "rate": rate,
    }


def parse_funding_csv(text, symbol=None, expected_interval=BINANCE_FUNDING_INTERVAL_HOURS) -> list[dict]:
    """Parse a full fundingRate CSV text blob into ordered records.

    Validates the header matches the documented schema and that every row's
    interval matches the expected value (8.0 for Binance USD-M). Raises on
    any schema or value mismatch; never silently skips or invents rows.
    """
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if header is None:
        raise ValueError("empty funding CSV")
    if list(header) != FUNDING_SCHEMA_FIELDS:
        raise ValueError("unexpected funding header: %r" % (header,))
    records = []
    for row in reader:
        if not row:
            continue
        record = parse_funding_row(row, symbol=symbol)
        if record["funding_interval_hours"] != expected_interval:
            raise ValueError(
                "funding interval %s != expected %s for row %r"
                % (record["funding_interval_hours"], expected_interval, row)
            )
        records.append(record)
    if not records:
        raise ValueError("no data rows after header")
    return records


def parse_klines_row(row, symbol=None) -> dict:
    """Parse a single 1h klines CSV row into a structured record.

    Expected field order: open_time,open,high,low,close,volume,close_time,
    quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore.
    """
    if len(row) < 7:
        raise ValueError("klines row has too few fields: %r" % (row,))
    open_time_ms = int(row[0])
    open_price = float(row[1])
    high_price = float(row[2])
    low_price = float(row[3])
    close_price = float(row[4])
    volume = float(row[5])
    close_time_ms = int(row[6])
    import math
    for name, value in [
        ("open", open_price), ("high", high_price),
        ("low", low_price), ("close", close_price), ("volume", volume),
    ]:
        if not math.isfinite(value):
            raise ValueError("non-finite %s: %r" % (name, row))
        if value < 0:
            raise ValueError("negative %s: %r" % (name, row))
    if close_time_ms < open_time_ms:
        raise ValueError("close_time before open_time: %r" % (row,))
    result = {
        "symbol": symbol,
        "open_time_ms": open_time_ms,
        "timestamp_utc": ms_to_iso(open_time_ms),
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": volume,
        "close_time_ms": close_time_ms,
        "close_time_utc": ms_to_iso(close_time_ms),
    }
    for idx, field_name in enumerate(KLINES_SCHEMA_FIELDS[7:], start=7):
        if idx < len(row):
            result[field_name] = row[idx]
    return result


def parse_klines_csv(text, symbol=None) -> list[dict]:
    """Parse a full 1h klines CSV text blob into ordered records.

    Validates the header and rejects rows with non-finite prices, non-monotonic
    timestamps, or wrong arity. Returns records sorted by open_time (ascending).
    """
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if header is None:
        raise ValueError("empty klines CSV")
    if list(header) != KLINES_SCHEMA_FIELDS:
        raise ValueError("unexpected klines header: %r" % (header,))
    records = []
    for row in reader:
        if not row:
            continue
        record = parse_klines_row(row, symbol=symbol)
        records.append(record)
    if records:
        open_times = [r["open_time_ms"] for r in records]
        if open_times != sorted(open_times):
            raise ValueError("klines rows not sorted by open_time")
        if len(set(open_times)) != len(open_times):
            raise ValueError("duplicate kline open_time timestamps")
    if not records:
        raise ValueError("no data rows after header")
    return records


def funding_csv_to_observations(records, venue="Binance") -> list[dict]:
    """Convert parsed funding records into the observation dict shape expected
    by cross_venue_funding_dispersion.signals.time_weighted_mean and
    dispersion_from_venue_histories.

    Preserves original rate and venue alongside the 8h-normalized rate per
    the funding-accounting skill ('preserve original rate, units, event time
    and normalized value').
    """
    from cross_venue_funding_dispersion.signals import normalize_funding_rate
    observations = []
    for r in records:
        observations.append({
            "timestamp": r["timestamp_utc"],
            "original_rate": r["rate"],
            "interval_hours": r["funding_interval_hours"],
            "venue": venue,
            "rate_8h": normalize_funding_rate(r["rate"], r["funding_interval_hours"]),
        })
    return observations


def main():
    if len(sys.argv) < 3:
        print("usage: parse_binance_archive.py <funding|klines> <csv_file>", file=sys.stderr)
        return 2
    kind, csv_path = sys.argv[1], sys.argv[2]
    text = Path(csv_path).read_text(encoding="utf-8")
    if kind == "funding":
        records = parse_funding_csv(text)
    elif kind == "klines":
        records = parse_klines_csv(text)
    else:
        print("unknown kind: %s" % kind, file=sys.stderr)
        return 2
    import json
    print(json.dumps({"records": records}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
