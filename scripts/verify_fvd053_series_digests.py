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


def verify(artifact_path: Path, output_path: Path, underlyings: list[str] | None = None) -> dict:
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    recorded = artifact.get("series_digests") or {}
    start_ms = utc_ms(artifact["window_start_utc"])
    end_ms = utc_ms(artifact["fetch_end_utc"])
    targets = underlyings or list(recorded)

    series: dict[str, dict] = {}
    for u in targets:
        hl_candles, hl_meta = fetch_hl_candles(u, start_ms, end_ms)
        hl_funding, hl_funding_meta = fetch_hl_funding(u, start_ms, end_ms)
        okx_candles, okx_meta = fetch_okx_candles(OKX_INST_ID[u], start_ms, end_ms)
        okx_funding, okx_funding_meta = fetch_okx_funding(OKX_INST_ID[u], start_ms, end_ms)

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
        "verdict": "PASS" if not failed else "FAIL",
        "backtest_completed": False,
        "performance_metrics_computed": False,
        "confirmatory_status_preserved": artifact.get("confirmatory_status_preserved"),
        "economic_claim": False,
        "limitations": [
            "Coverage/provenance verification only: no signal, outcome, or performance metric is computed.",
            "A matching digest proves the recorded candle series reproduces from the current public venue API bytes; "
            "it does not prove the venue never revised history.",
            "Funding row counts are reported separately from the candle digests because OKX publishes a rolling "
            "~3-month funding history: rows older than the retention boundary cannot be refetched even though they "
            "remain persisted in the target artifact's settlement and selection evidence.",
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
    print(f"SERIES_DIGEST_VERIFICATION={result['verdict']} "
          f"candle_checks={len(result['checks'])} failed={result['failed_checks']} "
          f"funding_row_mismatches={result['funding_row_count_mismatches']}")
    for name in result["failed_check_names"]:
        print(f"  FAILED {name}")
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
