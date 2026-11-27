#!/usr/bin/env python3
"""Source-reproducibility check for the persisted FVD053 candle series digests.

Closes the audited limitation "series content is bound by a recorded SHA-256
digest over (time, open, close) that cannot be re-derived without refetching the
raw venue data": this script refetches the same bounded free public candle
windows and recomputes every digest with an independent canonicalisation
implementation, then compares it to the value recorded in the target artifact.

Coverage-only. No signal, outcome, backtest, or performance metric is computed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_fvd053_anchor import (  # noqa: E402  (data retrieval only, not digesting)
    OKX_INST_ID,
    fetch_hl_candles,
    fetch_hl_funding,
    fetch_okx_candles,
    fetch_okx_funding,
    utc_ms,
)


def canonical_digest(rows: list[dict]) -> dict:
    """Independent implementation of the recorded candle-series digest.

    Canonical payload is the time-sorted list of ``{time, open, close}`` objects
    serialised with sorted keys and no whitespace; the digest is its SHA-256.
    """
    ordered = sorted(rows, key=lambda row: int(row["time"]))
    payload = json.dumps(
        [{"close": r.get("close"), "open": r.get("open"), "time": r.get("time")} for r in ordered],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return {
        "row_count": len(ordered),
        "first_time_utc": _iso(ordered[0]["time"]) if ordered else None,
        "last_time_utc": _iso(ordered[-1]["time"]) if ordered else None,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _window(rows: list[dict]) -> dict:
    times = [int(r["time"]) for r in rows if "time" in r]
    if not times:
        return {"first_time_utc": None, "last_time_utc": None}
    return {"first_time_utc": _iso(min(times)), "last_time_utc": _iso(max(times))}


def _candle_index(rows: list[dict]) -> dict[str, dict]:
    """Map ISO open-time -> candle row so evidence timestamps resolve exactly."""
    return {_iso(row["time"]): row for row in rows if "time" in row}


def _funding_index(rows: list[dict]) -> dict[str, float]:
    """Map ISO settlement-time -> original funding rate from a refetched series."""
    return {_iso(row["time"]): float(row["rate"]) for row in rows if "time" in row}


def _to_ms(timestamp_utc: str | None) -> int | None:
    if not timestamp_utc:
        return None
    try:
        return int(datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00")).timestamp() * 1000 + 0.5)
    except ValueError:
        return None


def funding_settlement_checks(
    signals: list[dict],
    funding_by_venue: dict[tuple[str, str], list[dict]],
    retention_truncated: dict[tuple[str, str], bool] | None = None,
) -> dict:
    """Compare every recorded settlement cash-flow input against refetched funding rows.

    Each ``funding_evidence`` row stores the venue, side, settlement timestamp, the
    original venue rate, the documented settlement interval, the 8h-normalized rate
    and the cash flow. A row passes only when the refetched funding series still
    serves that exact settlement timestamp with an identical rate (tolerance 0) and
    the recorded normalization/cash-flow arithmetic reproduces exactly.

    A settlement older than the venue's refetched history is labelled
    ``outside_retention`` (a documented vendor retention limit, not a failure) only
    when the fetch itself proves the venue truncated the series. Any other missing
    timestamp is a failure and is never silently skipped.
    """
    retention_truncated = retention_truncated or {}
    index = {key: _funding_index(rows) for key, rows in funding_by_venue.items()}
    windows: dict[tuple[str, str], tuple[int | None, int | None]] = {}
    for key, rows in funding_by_venue.items():
        times = [int(r["time"]) for r in rows if "time" in r]
        windows[key] = (min(times), max(times)) if times else (None, None)

    expected_interval = {"Hyperliquid": 1.0, "OKX": 8.0}
    rows_out: list[dict] = []
    for signal_index, signal in enumerate(signals):
        underlying = signal.get("underlying")
        for evidence in signal.get("funding_evidence") or []:
            venue = evidence.get("venue")
            timestamp = evidence.get("settlement_time_utc")
            rate = evidence.get("original_rate")
            interval = evidence.get("interval_hours")
            notional = evidence.get("notional")
            side = evidence.get("side")
            cash_flow = evidence.get("cash_flow")
            rate_8h = evidence.get("rate_8h")

            refetched_rate = (index.get((underlying, venue)) or {}).get(timestamp)
            interval_expected = expected_interval.get(venue)
            interval_ok = (
                interval_expected is None
                or (isinstance(interval, (int, float)) and float(interval) == interval_expected)
            )
            arithmetic_ok = True
            cash_expected = rate_8h_expected = None
            if isinstance(rate, (int, float)) and isinstance(interval, (int, float)) and interval > 0:
                rate_8h_expected = rate * 8.0 / interval
            if (isinstance(rate, (int, float)) and isinstance(notional, (int, float))
                    and side in (-1, 1)):
                cash_expected = -side * notional * rate
            if cash_expected is not None and cash_expected != cash_flow:
                arithmetic_ok = False
            if rate_8h_expected is not None and rate_8h_expected != rate_8h:
                arithmetic_ok = False

            row = {
                "signal_index": signal_index,
                "underlying": underlying,
                "venue": venue,
                "side": side,
                "settlement_time_utc": timestamp,
                "recorded_rate": rate,
                "refetched_rate": refetched_rate,
                "recorded_interval_hours": interval,
                "recorded_cash_flow": cash_flow,
                "recomputed_cash_flow": cash_expected,
                "interval_matches_venue": interval_ok,
                "arithmetic_reproduces": arithmetic_ok,
                "found": refetched_rate is not None,
            }
            if refetched_rate is None:
                start, _ = windows.get((underlying, venue), (None, None))
                ms = _to_ms(timestamp)
                outside = (
                    ms is not None
                    and start is not None
                    and ms < start
                    and bool(retention_truncated.get((underlying, venue)))
                )
                row["status"] = "outside_retention" if outside else "not_found"
                row["passed"] = outside and arithmetic_ok and interval_ok
            else:
                rate_ok = float(refetched_rate) == float(rate)
                row["rate_matches"] = rate_ok
                row["status"] = "matched" if (rate_ok and arithmetic_ok and interval_ok) else "mismatch"
                row["passed"] = row["status"] == "matched"
            rows_out.append(row)

    failed = [r for r in rows_out if not r["passed"]]
    return {
        "rows_expected": len(rows_out),
        "rows_matched": sum(1 for r in rows_out if r["status"] == "matched"),
        "rows_outside_retention": sum(1 for r in rows_out if r["status"] == "outside_retention"),
        "rows_not_found": sum(1 for r in rows_out if r["status"] == "not_found"),
        "rows_failed": len(failed),
        "recorded_cash_flow_total": sum(
            float(r["recorded_cash_flow"]) for r in rows_out
            if isinstance(r["recorded_cash_flow"], (int, float))
        ),
        "recomputed_cash_flow_total": sum(
            float(r["recomputed_cash_flow"]) for r in rows_out
            if isinstance(r["recomputed_cash_flow"], (int, float))
        ),
        "all_matched": not failed,
        "rows": rows_out,
    }


def execution_price_checks(signals: list[dict], candles_by_venue: dict[tuple[str, str], list[dict]]) -> dict:
    """Compare every recorded entry/exit candle against the refetched candle rows.

    ``candles_by_venue`` is keyed by ``(underlying, venue)``. Each signal carries
    its own ``underlying`` and four ``candle_evidence`` rows (long/short x
    entry/exit). A row passes only when the refetched candle at that exact
    timestamp has identical ``open`` and ``close`` values (tolerance 0).
    """
    index = {key: _candle_index(rows) for key, rows in candles_by_venue.items()}
    rows: list[dict] = []
    for signal_index, signal in enumerate(signals):
        underlying = signal.get("underlying")
        entry_time = signal.get("entry_time_utc")
        exit_time = signal.get("exit_time_utc")
        for evidence in signal.get("candle_evidence") or []:
            venue = evidence.get("venue")
            timestamp = evidence.get("timestamp_utc")
            role = "entry" if timestamp == entry_time else ("exit" if timestamp == exit_time else "unknown")
            candle = (index.get((underlying, venue)) or {}).get(timestamp)
            row = {
                "signal_index": signal_index,
                "underlying": underlying,
                "venue": venue,
                "side": evidence.get("side"),
                "role": role,
                "timestamp_utc": timestamp,
                "recorded_open": evidence.get("open"),
                "recorded_close": evidence.get("close"),
                "refetched_open": candle.get("open") if candle else None,
                "refetched_close": candle.get("close") if candle else None,
                "found": candle is not None,
            }
            row["passed"] = bool(
                candle is not None
                and row["refetched_open"] == row["recorded_open"]
                and row["refetched_close"] == row["recorded_close"]
            )
            rows.append(row)

    internal: list[dict] = []
    for signal_index, signal in enumerate(signals):
        entry_time = signal.get("entry_time_utc")
        exit_time = signal.get("exit_time_utc")
        long_venue = signal.get("long_venue")
        short_venue = signal.get("short_venue")
        for role, expected_time, price_key in (
            ("entry", entry_time, "entry_price_long"),
            ("exit", exit_time, "exit_price_long"),
        ):
            match = next(
                (e for e in (signal.get("candle_evidence") or [])
                 if e.get("venue") == long_venue and e.get("timestamp_utc") == expected_time),
                None,
            )
            internal.append({
                "signal_index": signal_index,
                "underlying": signal.get("underlying"),
                "venue": long_venue,
                "role": role,
                "timestamp_utc": expected_time,
                "recorded_signal_price": signal.get(price_key),
                "recorded_candle_open": match.get("open") if match else None,
                "passed": bool(match is not None and match.get("open") == signal.get(price_key)),
            })
            price_key = "entry_price_short" if role == "entry" else "exit_price_short"
            match = next(
                (e for e in (signal.get("candle_evidence") or [])
                 if e.get("venue") == short_venue and e.get("timestamp_utc") == expected_time),
                None,
            )
            internal.append({
                "signal_index": signal_index,
                "underlying": signal.get("underlying"),
                "venue": short_venue,
                "role": role,
                "timestamp_utc": expected_time,
                "recorded_signal_price": signal.get(price_key),
                "recorded_candle_open": match.get("open") if match else None,
                "passed": bool(match is not None and match.get("open") == signal.get(price_key)),
            })

    failed = [r for r in rows if not r["passed"]]
    internal_failed = [r for r in internal if not r["passed"]]
    return {
        "rows_expected": len(rows),
        "rows_matched": len(rows) - len(failed),
        "rows_failed": len(failed),
        "rows_not_found": sum(1 for r in failed if not r["found"]),
        "internal_price_checks": len(internal),
        "internal_price_failed": len(internal_failed),
        "all_matched": not failed and not internal_failed,
        "rows": rows,
        "internal_checks": internal,
    }


def verify(artifact_path: Path, output_path: Path, underlyings: list[str] | None = None) -> dict:
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    recorded = artifact.get("series_digests") or {}
    start_ms = utc_ms(artifact["window_start_utc"])
    end_ms = utc_ms(artifact["fetch_end_utc"])
    targets = underlyings or list(recorded)

    series: dict[str, dict] = {}
    candles_by_venue: dict[tuple[str, str], list[dict]] = {}
    funding_by_venue: dict[tuple[str, str], list[dict]] = {}
    retention_truncated: dict[tuple[str, str], bool] = {}
    for u in targets:
        hl_candles, hl_meta = fetch_hl_candles(u, start_ms, end_ms)
        hl_funding, hl_funding_meta = fetch_hl_funding(u, start_ms, end_ms)
        okx_candles, okx_meta = fetch_okx_candles(OKX_INST_ID[u], start_ms, end_ms)
        okx_funding, okx_funding_meta = fetch_okx_funding(OKX_INST_ID[u], start_ms, end_ms)
        candles_by_venue[(u, "Hyperliquid")] = hl_candles
        candles_by_venue[(u, "OKX")] = okx_candles
        funding_by_venue[(u, "Hyperliquid")] = hl_funding
        funding_by_venue[(u, "OKX")] = okx_funding
        retention_truncated[(u, "Hyperliquid")] = False
        retention_truncated[(u, "OKX")] = okx_funding_meta.get("stop_reason") == "page_not_full"

        per_venue = {}
        for venue, candles, funding, cmeta, fmeta in (
            ("Hyperliquid", hl_candles, hl_funding, hl_meta, hl_funding_meta),
            ("OKX", okx_candles, okx_funding, okx_meta, okx_funding_meta),
        ):
            recomputed = canonical_digest(candles)
            reference = (recorded.get(u) or {}).get(venue) or {}
            ref_candles = reference.get("candles") or {}
            per_venue[venue] = {
                "recorded": ref_candles,
                "recomputed": recomputed,
                "candle_digest_match": (
                    ref_candles.get("sha256") == recomputed["sha256"]
                    and ref_candles.get("row_count") == recomputed["row_count"]
                    and ref_candles.get("first_time_utc") == recomputed["first_time_utc"]
                    and ref_candles.get("last_time_utc") == recomputed["last_time_utc"]
                ),
                "recorded_funding_rows": reference.get("funding_rows"),
                "recomputed_funding_rows": len(funding),
                "funding_row_count_match": reference.get("funding_rows") == len(funding),
                "funding_window": _window(funding),
                "fetch": {
                    "candles": cmeta,
                    "funding": fmeta,
                },
            }
        series[u] = per_venue

    checks = []
    funding_observations = []
    for u, per_venue in series.items():
        for venue, record in per_venue.items():
            checks.append({
                "check": f"candle_digest:{u}:{venue}",
                "passed": record["candle_digest_match"],
                "detail": {"recorded_sha256": record["recorded"].get("sha256"),
                           "recomputed_sha256": record["recomputed"]["sha256"]},
            })
            funding_observations.append({
                "underlying": u,
                "venue": venue,
                "recorded_rows": record["recorded_funding_rows"],
                "recomputed_rows": record["recomputed_funding_rows"],
                "reproduced": record["funding_row_count_match"],
                "recomputed_earliest_utc": record["funding_window"]["first_time_utc"],
                "recomputed_latest_utc": record["funding_window"]["last_time_utc"],
            })

    failed = [c for c in checks if not c["passed"]]
    truncated = [o for o in funding_observations if not o["reproduced"]]
    execution = execution_price_checks(artifact.get("signals") or [], candles_by_venue)
    funding = funding_settlement_checks(
        artifact.get("signals") or [], funding_by_venue, retention_truncated
    )
    verdict = "PASS" if not failed and execution["all_matched"] and funding["all_matched"] else "FAIL"
    return {
        "schema_version": "fvd053-series-digest-verification-v1",
        "run_type": "SOURCE_REPRODUCIBILITY_VERIFICATION",
        "target_artifact": str(artifact_path.name),
        "target_experiment_id": artifact.get("experiment_id"),
        "target_observed_at_utc": artifact.get("observed_at_utc"),
        "target_file_sha256": _file_sha256(artifact_path),
        "window_start_utc": artifact["window_start_utc"],
        "fetch_end_utc": artifact["fetch_end_utc"],
        "underlyings": targets,
        "series": series,
        "checks": checks,
        "funding_row_observations": funding_observations,
        "funding_row_counts_reproduced": not truncated,
        "funding_row_count_mismatches": len(truncated),
        "passed_checks": len(checks) - len(failed),
        "failed_checks": len(failed),
        "failed_check_names": [c["check"] for c in failed],
        "execution_price_provenance": execution,
        "execution_price_rows_matched": execution["rows_matched"],
        "execution_price_rows_expected": execution["rows_expected"],
        "execution_price_rows_failed": execution["rows_failed"],
        "funding_settlement_provenance": funding,
        "funding_settlement_rows_expected": funding["rows_expected"],
        "funding_settlement_rows_matched": funding["rows_matched"],
        "funding_settlement_rows_outside_retention": funding["rows_outside_retention"],
        "funding_settlement_rows_failed": funding["rows_failed"],
        "verdict": verdict,
        "backtest_completed": False,
        "performance_metrics_computed": False,
        "confirmatory_status_preserved": artifact.get("confirmatory_status_preserved"),
        "economic_claim": False,
        "limitations": [
            "Coverage/provenance verification only: no signal, outcome, or performance metric is computed.",
            "A matching digest proves the recorded candle series reproduces from the current public venue API bytes; "
            "it does not prove the venue never revised history.",
            "Execution-price checks compare recorded entry/exit candle open/close values to refetched rows with "
            "tolerance 0; they prove price provenance only, not that the trades were executable at those prices.",
            "Funding row counts are reported separately from the candle digests because OKX publishes a rolling "
            "~3-month funding history: rows older than the retention boundary cannot be refetched even though they "
            "remain persisted in the target artifact's settlement and selection evidence.",
            "Funding settlement checks compare each recorded venue/side/settlement-timestamp rate, interval, 8h "
            "normalization and cash flow against refetched rows with tolerance 0. Settlements older than a venue's "
            "refetched history are labelled outside_retention only when the fetch itself proves truncation "
            "(OKX stop_reason=page_not_full); they are not counted as matched source observations.",
            "Contract identity remains underlying-symbol-mapped candidate level.",
        ],
        "recomputed_at_utc": datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--underlyings", nargs="*", default=None)
    args = parser.parse_args(argv)

    result = verify(Path(args.artifact), Path(args.output), args.underlyings)
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    execution = result["execution_price_provenance"]
    funding = result["funding_settlement_provenance"]
    print(f"SERIES_DIGEST_VERIFICATION={result['verdict']} "
          f"candle_checks={len(result['checks'])} failed={result['failed_checks']} "
          f"funding_row_mismatches={result['funding_row_count_mismatches']} "
          f"execution_price_rows={execution['rows_matched']}/{execution['rows_expected']} "
          f"failed={execution['rows_failed']} "
          f"internal_price_failed={execution['internal_price_failed']} "
          f"funding_settlements={funding['rows_matched']}/{funding['rows_expected']} "
          f"outside_retention={funding['rows_outside_retention']} "
          f"failed={funding['rows_failed']}")
    for name in result["failed_check_names"]:
        print(f"  FAILED {name}")
    for row in execution["rows"]:
        if not row["passed"]:
            print(f"  PRICE_MISMATCH signal={row['signal_index']} {row['underlying']} {row['venue']} "
                  f"{row['role']} {row['timestamp_utc']} recorded=({row['recorded_open']},{row['recorded_close']}) "
                  f"refetched=({row['refetched_open']},{row['refetched_close']})")
    for row in execution["internal_checks"]:
        if not row["passed"]:
            print(f"  INTERNAL_PRICE_MISMATCH signal={row['signal_index']} {row['underlying']} {row['venue']} "
                  f"{row['role']} {row['timestamp_utc']} signal={row['recorded_signal_price']} "
                  f"candle={row['recorded_candle_open']}")
    for row in funding["rows"]:
        if not row["passed"]:
            print(f"  FUNDING_MISMATCH signal={row['signal_index']} {row['underlying']} {row['venue']} "
                  f"{row['settlement_time_utc']} status={row['status']} "
                  f"recorded_rate={row['recorded_rate']} refetched_rate={row['refetched_rate']} "
                  f"interval_matches={row['interval_matches_venue']} arithmetic={row['arithmetic_reproduces']}")
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
