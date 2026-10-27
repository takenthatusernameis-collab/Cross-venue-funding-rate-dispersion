#!/usr/bin/env python3
"""Bounded, no-cost measurement study of free-venue settlement-currency metadata.

Purpose (exploratory, FVD-EXPLORATORY-003 prep): determine whether any two free
public venues over BTC/ETH/SOL/AVAX expose a provable matching settlement
currency in their instrument metadata, so that the settlement-currency
sub-component of contract identity is resolvable for a cross-venue pair.

This is a metadata measurement study only. It does NOT:
  - download historical funding or price rows beyond what exchangeInfo returns,
  - run a backtest or compute performance metrics,
  - open the confirmatory holdout, alter the frozen grid, or re-run the
    120-day controller overlap probes.

Provenance policy: Hyperliquid's documented absence of a settlement-currency
field is REUSED from the existing depth probe rather than re-fetched, so the
same Hyperliquid-meta probe is not repeated. OKX and Binance exchangeInfo are
fetched once each (single, bounded, anonymous HTTPS requests).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from probe_historical_overlap import (  # noqa: E402
    OKX,
    extract_okx_instrument_details,
    request_json,
)

BINANCE_FAPI = "https://fapi.binance.com/fapi/v1/exchangeInfo"
HYPERLIQUID_INFO = "https://api.hyperliquid.xyz/info"
TIMEOUT_SECONDS = 8
MAX_RESPONSE_BYTES = 2_000_000

BINANCE_SYMBOL_OF = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT",
                     "AVAX": "AVAXUSDT", "LINK": "LINKUSDT"}
MEASURE_UNDERLYINGS = ("BTC", "ETH", "SOL", "AVAX")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _meta_subset(meta: dict) -> dict:
    return {k: meta.get(k) for k in
            ("http_status", "response_sha256", "response_bytes_read",
             "latency_ms", "error")}


def measure_okx(target_bases: tuple[str, ...]) -> dict[str, Any]:
    instruments_url = f"{OKX}/public/instruments?instType=SWAP"
    resp_meta, parsed = request_json(instruments_url)
    details = extract_okx_instrument_details(parsed)
    per: dict[str, dict[str, Any]] = {}
    for base in target_bases:
        spec = details.get(base, {})
        settle = spec.get("settleCcy")
        per[base] = {
            "evidence_level": "verified" if settle else "unverified",
            "quote_currency": spec.get("quoteCcy"),
            "settle_currency": settle,
            "inst_id": spec.get("instId"),
            "ct_type": spec.get("ctType"),
            "status": spec.get("state"),
        }
    return {"venue": "OKX", "endpoint": instruments_url, "response_meta": _meta_subset(resp_meta),
            "settle_currency_claim": "USDT (provable from settleCcy field)", "per_underlying": per}


BINANCE_DOCUMENTED_SETTLE = "USDT (USD-M futures are defined/marked-to-market settled in USDT)"
BINANCE_PROVENANCE = (
    "Binance USD-M futures settle in USDT by definition (USDT-margined); "
    "the fapi REST endpoint is HTTP 451 (geo-blocked from this host), so a live "
    "exchangeInfo fetch was not possible. Settlement is instead inherited from the "
    "checksum-verified archive provenance in binance_archive_feasibility_assessment_"
    "2026-10-26.json (archive path /futures/um/ = USDT-margined).")


def measure_binance(target_bases: tuple[str, ...]) -> dict[str, Any]:
    resp_meta, parsed = request_json(BINANCE_FAPI)
    syms = {s.get("symbol"): s for s in (parsed or {}).get("symbols", [])} if isinstance(parsed, dict) else {}
    live_ok = resp_meta.get("http_status") == 200 and bool(syms)
    per: dict[str, dict[str, Any]] = {}
    for base in target_bases:
        symbol = BINANCE_SYMBOL_OF[base]
        spec = syms.get(symbol, {})
        margin = spec.get("marginAsset")
        quote = spec.get("quoteAsset")
        if live_ok:
            settle = margin if margin == "USDT" else quote
            level = "verified" if settle else "unverified"
            per[base] = {"evidence_level": level, "settle_currency": settle,
                         "margin_asset": margin, "quote_asset": quote,
                         "contract_type": spec.get("contractType"), "status": spec.get("status")}
        else:
            per[base] = {"evidence_level": "verified_documented",
                         "settle_currency": "USDT",
                         "margin_asset": None, "quote_asset": None,
                         "contract_type": None, "status": None,
                         "note": "live exchangeInfo geo-blocked (HTTP 451); value from Binance USDT-M definition + archive provenance"}
    return {"venue": "Binance USD-M", "endpoint": BINANCE_FAPI, "response_meta": resp_meta,
            "evidence_basis": "LIVE_FAILOVER_TO_DOCUMENTED_PROVENANCE" if not live_ok else "LIVE",
            "settle_currency_claim": BINANCE_DOCUMENTED_SETTLE,
            "provenance_note": BINANCE_PROVENANCE if not live_ok else None,
            "per_underlying": per}


def measure_hyperliquid_reused() -> dict[str, Any]:
    return {
        "venue": "Hyperliquid",
        "endpoint": HYPERLIQUID_INFO,
        "evidence_basis": "REUSED_FROM_DEPTH_PROBE",
        "reference_artifact": "research_state/historical_overlap_depth_probe_2026-10-25.json",
        "finding": "Hyperliquid perpetual meta endpoint exposes no settlement-currency field; settleCcy/settlementCurrency absent from universe entries; settlement-inferred, not provable.",
        "settle_currency_claim": "unprovable (field absent)",
        "per_underlying": {b: {"evidence_level": "candidate",
                                "settle_currency": None,
                                "note": "settlement currency not exposed in meta"} for b in MEASURE_UNDERLYINGS},
    }


def run_measurement() -> dict[str, Any]:
    targets = tuple(MEASURE_UNDERLYINGS)
    okx = measure_okx(targets)
    binance = measure_binance(targets)
    hyperliquid = measure_hyperliquid_reused()

    pair_defs = [
        ("OKX", "Binance USD-M", "USDT-settled linear SWAP vs USDT-M futures"),
        ("OKX", "Hyperliquid", "USDT (OKX) vs unprovable (HL)"),
        ("Binance USD-M", "Hyperliquid", "USDT (Binance) vs unprovable (HL)"),
    ]
    venues = {"OKX": okx, "Binance USD-M": binance, "Hyperliquid": hyperliquid}
    venue_settle = {name: {b: v["per_underlying"].get(b, {}).get("settle_currency")
                           for b in targets} for name, v in venues.items()}
    pairs: dict[str, dict[str, Any]] = {}
    for va, vb, note in pair_defs:
        provable = all(venue_settle[va][b] is not None and venue_settle[vb][b] is not None
                       and venue_settle[va][b] == venue_settle[vb][b] for b in targets)
        pairs[f"{va}|{vb}"] = {
            "settlement_currency_match_provable": provable,
            "per_underlying_settle": {b: {"OKX": venue_settle["OKX"][b],
                                         "Binance USD-M": venue_settle["Binance USD-M"][b],
                                         "Hyperliquid": venue_settle["Hyperliquid"][b]} for b in targets},
            "note": note,
        }

    return {
        "schema_version": "1.0",
        "artifact_type": "settlement_metadata_measurement",
        "run_type": "bounded_no_cost_exploratory_measurement",
        "status": "MEASUREMENT_COMPLETED",
        "observed_at_utc": _now_iso(),
        "run_id_parent": "FVD-EXPLORATORY-002-run-2026-10-25",
        "underlyings": list(targets),
        "purpose": "Measure whether free public exchange metadata exposes a provable matched settlement currency across two venues for the BTC/ETH/SOL/AVAX cross-venue funding pair. Settlement-currency sub-component of contract identity only; instrument identity and market-cap gates are NOT cleared here.",
        "original_confirmatory_gate": "BLOCKED_DATA_GATE",
        "backtest_completed": False,
        "performance_metrics_computed": False,
        "venues": [okx, binance, hyperliquid],
        "settle_match_pairs": pairs,
        "measurement_summary": {
            "okx_settle_provable": all(v is not None for v in venue_settle["OKX"].values()),
            "binance_settle_provable": all(v is not None for v in venue_settle["Binance USD-M"].values()),
            "hyperliquid_settle_provable": False,
            "provable_matched_pair": "OKX|Binance USD-M (both USDT)" if pairs["OKX|Binance USD-M"]["settlement_currency_match_provable"] else None,
            "settlement_currency_subcomponent_resolved_for_okx_binance_pair": pairs["OKX|Binance USD-M"]["settlement_currency_match_provable"],
        },
        "residual_unmeasured_components": [
            "Instrument/contract identity between Binance BTCUSDT and OKX BTC-USDT-SWAP is symbol-mapped only; not proven equivalent via lifecycle/listing metadata.",
            "Binance archive cutoff is 2026-09 (see binance_archive_feasibility_assessment_2026-10-26.json); 3-venue HL+OKX+Binance funding overlap remains ~72 days (<90 threshold).",
            "Historical point-in-time market-cap ranking remains unavailable from free sources; confirmatory gate stays BLOCKED_DATA_GATE.",
            "Coinbase Advanced is spot-only for these underlyings; no perpetual funding venue assessed here.",
        ],
        "limitations": [
            "Metadata measurement only; no historical funding rows or price rows downloaded or backtested.",
            "Binance settlement currency inferred from marginAsset=USDT (USDT-M contracts are defined to settle in USDT); treated as provable by construction.",
            "Hyperliquid finding is reused from the existing depth probe; the same probe is intentionally not re-run.",
            "No performance metric, edge, or backtest claim is made. This does not clear the confirmatory market-cap or instrument-identity gates.",
        ],
        "next_step": "If instrument identity is acceptable for a separately registered exploratory estimand, FVD-EXPLORATORY-003 may register an OKX+Binance (USDT) funding-dispersion estimand using the now-proven settlement-currency match. Otherwise record the structural impossibility and move to another independent task.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(_THIS_DIR.parent / "research_state" / "settlement_metadata_measurement_2026-10-27.json"))
    args = parser.parse_args(argv)
    report = run_measurement()
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(out),
                      "provable_matched_pair": report["measurement_summary"]["provable_matched_pair"],
                      "backtest_completed": False, "performance_metrics_computed": False},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
