#!/usr/bin/env python3
"""Bounded, no-secret public endpoint preflight; never claims historical coverage."""
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MAX_RESPONSE_BYTES = 1_000_000
TIMEOUT_SECONDS = 8
PROBES = [
    {"id":"binance-usdm-time","url":"https://fapi.binance.com/fapi/v1/time","method":"GET"},
    {"id":"bybit-public-time","url":"https://api.bybit.com/v5/market/time","method":"GET"},
    {"id":"okx-public-time","url":"https://www.okx.com/api/v5/public/time","method":"GET"},
    {"id":"coingecko-public-ping","url":"https://api.coingecko.com/api/v3/ping","method":"GET"},
    {"id":"hyperliquid-public-info","url":"https://api.hyperliquid.xyz/info","method":"POST","body":{"type":"meta"}},
]


def is_json(raw: bytes) -> bool:
    try:
        json.loads(raw.decode("utf-8"))
        return True
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False


def probe(item: dict) -> dict:
    body = json.dumps(item["body"]).encode() if "body" in item else None
    headers = {"User-Agent":"cross-venue-funding-dispersion-research/0.1"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(item["url"], data=body, headers=headers, method=item["method"])
    start = time.monotonic()
    result = {"source_id":item["id"],"url":item["url"],"method":item["method"],"http_status":None,"reachable":False,"latency_ms":None,"response_shape":None,"error":None,"historical_coverage_proven":False}
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            result["http_status"] = response.status
            result["reachable"] = 200 <= response.status < 300
            result["response_shape"] = "oversize" if len(raw) > MAX_RESPONSE_BYTES else "json" if is_json(raw) else "non-json"
    except HTTPError as exc:
        result["http_status"] = exc.code
        result["error"] = f"HTTPError: {exc.code}"
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        result["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    finally:
        result["latency_ms"] = round((time.monotonic() - start) * 1000, 1)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="/tmp/funding-source-preflight.json")
    args = parser.parse_args()
    report = {"schema_version":"1.0","run_type":"public_endpoint_reachability_only","status":"PREFLIGHT_ONLY","observed_at_utc":datetime.now(timezone.utc).isoformat(),"performance_metrics_computed":False,"historical_point_in_time_market_cap_gate":"NOT_VERIFIED","timeout_seconds":TIMEOUT_SECONDS,"max_response_bytes":MAX_RESPONSE_BYTES,"probes":[probe(item) for item in PROBES],"limitations":["Endpoint reachability does not prove usable history, pagination completeness, delisted coverage, contract mapping, or point-in-time market-cap availability."]}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status":report["status"],"output":str(output),"reachable":sum(x["reachable"] for x in report["probes"]),"probes":len(report["probes"]),"historical_point_in_time_market_cap_gate":"NOT_VERIFIED","performance_metrics_computed":False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
