#!/usr/bin/env python3
"""Select reachable zero-cost Kilo Gateway models without credentials or paid fallback.

The script intentionally uses only the public Kilo model catalog and models whose
catalog pricing is explicitly zero for both input and output. It sends a tiny
health-check prompt, never repository content, and stores only response hashes
and outcome metadata. No API key, account credential, or Authorization header is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

GATEWAY = "https://ai-gateway.kilo.ai/api/v1"
MODELS_URL = f"{GATEWAY}/models"
CHAT_URL = f"{GATEWAY}/chat/completions"
TIMEOUT_SECONDS = 12
MAX_RESPONSE_BYTES = 2_000_000
MAX_MODEL_TESTS = 5
USER_AGENT = "cross-venue-funding-research-free-model-preflight/1.0"

# Current public catalog coding candidates, not a hard-coded allow-list. They are
# considered only if the live catalog still reports a zero input and output price.
PREFERRED_MODEL_IDS = (
    "poolside/laguna-s-2.1:free",
    "dots-studio/dots-3-note-preview:free",
    "nvidia/nemotron-3.5-super-vl:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
)
OPEN_FN = Callable[..., Any]


def _response_status(response: Any) -> int:
    status = getattr(response, "status", None)
    if status is None:
        getcode = getattr(response, "getcode", None)
        status = getcode() if callable(getcode) else 200
    return int(status)


def request_json(
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: int = TIMEOUT_SECONDS,
    opener: OPEN_FN | None = None,
) -> tuple[dict[str, Any], Any | None]:
    """Fetch bounded JSON, returning only safe request/response metadata on failure."""
    method = "POST" if payload is not None else "GET"
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    open_request = opener or urllib.request.urlopen
    started = time.monotonic()
    metadata: dict[str, Any] = {
        "url": url,
        "method": method,
        "http_status": None,
        "response_bytes": None,
        "response_sha256": None,
        "response_hash_complete": False,
        "latency_ms": None,
        "response_shape": None,
        "error": None,
    }
    if body is not None:
        metadata["request_sha256"] = hashlib.sha256(body).hexdigest()
    try:
        with open_request(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            metadata["http_status"] = _response_status(response)
    except urllib.error.HTTPError as exc:
        # Hash error bytes too, but never persist the body: error payloads are untrusted.
        try:
            raw = exc.read(MAX_RESPONSE_BYTES + 1)
        except Exception:
            raw = b""
        metadata["http_status"] = int(exc.code)
        metadata["error"] = f"HTTPError:{exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        metadata["latency_ms"] = round((time.monotonic() - started) * 1000, 2)
        metadata["error"] = type(exc).__name__
        return metadata, None
    finally:
        # No response text or request body is included in diagnostics.
        pass

    metadata["latency_ms"] = round((time.monotonic() - started) * 1000, 2)
    metadata["response_bytes"] = len(raw)
    if len(raw) > MAX_RESPONSE_BYTES:
        metadata["response_shape"] = "oversize"
        metadata["error"] = metadata["error"] or "response exceeded configured byte cap"
        return metadata, None
    metadata["response_sha256"] = hashlib.sha256(raw).hexdigest()
    metadata["response_hash_complete"] = True
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        metadata["response_shape"] = "non-json"
        metadata["error"] = metadata["error"] or "response was not valid JSON"
        return metadata, None
    metadata["response_shape"] = "json"
    return metadata, decoded


def _is_zero_price(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    try:
        return Decimal(str(value)) == Decimal("0")
    except (InvalidOperation, ValueError):
        return False


def _explicit_zero_pricing(row: dict[str, Any]) -> bool:
    pricing = row.get("pricing")
    if not isinstance(pricing, dict):
        return False
    input_price = pricing.get("prompt", pricing.get("input"))
    output_price = pricing.get("completion", pricing.get("output"))
    return _is_zero_price(input_price) and _is_zero_price(output_price)


def extract_free_model_ids(payload: Any, max_models: int = MAX_MODEL_TESTS) -> list[str]:
    """Return live-catalog models with explicitly zero input/output prices."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return []
    rows: dict[str, dict[str, Any]] = {}
    for row in payload["data"]:
        if not isinstance(row, dict):
            continue
        model_id = row.get("id")
        if not isinstance(model_id, str) or not model_id or len(model_id) > 256:
            continue
        if any(ch.isspace() for ch in model_id) or model_id.startswith("kilo-auto/"):
            continue
        if not _explicit_zero_pricing(row):
            continue
        rows[model_id] = row

    live_ids = list(rows)
    ordered = [model_id for model_id in PREFERRED_MODEL_IDS if model_id in rows]
    ordered.extend(model_id for model_id in live_ids if model_id not in ordered)

    # Diversify by provider before trying multiple variants from the same provider.
    diverse: list[str] = []
    seen_providers: set[str] = set()
    for model_id in ordered:
        provider = model_id.split("/", 1)[0]
        if provider not in seen_providers:
            diverse.append(model_id)
            seen_providers.add(provider)
    diverse.extend(model_id for model_id in ordered if model_id not in diverse)
    return diverse[:max(0, max_models)]


def healthcheck_payload(model_id: str) -> dict[str, Any]:
    # Deliberately generic and tiny: no repository instructions, files, or secrets.
    return {
        "model": model_id,
        "messages": [{"role": "user", "content": "Reply with exactly OK."}],
        "max_tokens": 8,
        "temperature": 0,
        "stream": False,
    }


def run_selection(
    *,
    opener: OPEN_FN | None = None,
    max_models: int = MAX_MODEL_TESTS,
) -> dict[str, Any]:
    catalog_meta, catalog = request_json(MODELS_URL, opener=opener)
    catalog_models = extract_free_model_ids(catalog, max_models=max_models)
    attempts: list[dict[str, Any]] = []
    usable: list[str] = []

    for model_id in catalog_models:
        response_meta, response = request_json(
            CHAT_URL, healthcheck_payload(model_id), opener=opener
        )
        choices = response.get("choices") if isinstance(response, dict) else None
        content = None
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict):
                content = message.get("content")
        okay = (
            response_meta.get("http_status") == 200
            and isinstance(content, str)
            and bool(content.strip())
        )
        attempts.append({
            "model_id": model_id,
            "http_status": response_meta.get("http_status"),
            "latency_ms": response_meta.get("latency_ms"),
            "response_sha256": response_meta.get("response_sha256"),
            "response_hash_complete": response_meta.get("response_hash_complete"),
            "response_nonempty": bool(isinstance(content, str) and content.strip()),
            "usable": okay,
            "error": response_meta.get("error"),
        })
        if okay:
            usable.append(model_id)

    if usable:
        status = "FREE_MODEL_ROUTES_AVAILABLE"
    elif catalog_meta.get("http_status") != 200:
        status = "FREE_MODEL_CATALOG_UNAVAILABLE"
    elif not catalog_models:
        status = "NO_ZERO_COST_MODELS_IN_CATALOG"
    else:
        status = "NO_ZERO_COST_MODEL_RESPONDED"

    return {
        "schema_version": "1.0",
        "run_type": "unauthenticated_zero_cost_kilo_model_preflight",
        "status": status,
        "observed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "endpoint": MODELS_URL,
        "access_mode": "unauthenticated; no Authorization header; zero-priced models only",
        "catalog": {
            "http_status": catalog_meta.get("http_status"),
            "response_sha256": catalog_meta.get("response_sha256"),
            "response_hash_complete": catalog_meta.get("response_hash_complete"),
            "latency_ms": catalog_meta.get("latency_ms"),
            "error": catalog_meta.get("error"),
        },
        "candidate_model_ids": catalog_models,
        "attempts": attempts,
        "usable_models": usable,
        "max_models_tested": max_models,
        "paid_models_considered": 0,
        "credentials_used": False,
        "repository_content_sent": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="/tmp/kilo-free-model-preflight.json")
    parser.add_argument("--max-models", type=int, choices=range(1, MAX_MODEL_TESTS + 1),
                        default=MAX_MODEL_TESTS)
    args = parser.parse_args(argv)
    report = run_selection(max_models=args.max_models)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "output": str(out),
        "candidate_count": len(report["candidate_model_ids"]),
        "usable_count": len(report["usable_models"]),
        "paid_models_considered": 0,
        "credentials_used": False,
    }, indent=2))
    return 0 if report["usable_models"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
