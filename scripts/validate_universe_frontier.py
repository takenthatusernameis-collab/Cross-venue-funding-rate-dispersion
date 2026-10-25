#!/usr/bin/env python3
"""Offline conformance check for the rank-frontier persistence contract.

Generates deterministic frontier fixtures with build_frontier/persist_frontier
(standard library only, no network) and enforces: required schema fields, UTC
timestamps, FVD-SNAP snapshot id format, descending ranks with asset-ID
tie-break and no rank gaps from the last completed rank, source id/hash
present, pagination cursor and resume state present, completed/pending
consistency. Rejects malformed states fail-closed.
"""
from pathlib import Path
import json
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.frontier import (  # noqa: E402
    build_frontier,
    FrontierError,
    load_frontier,
    persist_frontier,
    rank_universe,
    save_frontier,
)

SNAPSHOT_ID_RE = re.compile(r"^FVD-SNAP-[0-9a-f]{16}$")
REQUIRED_FIELDS = {
    "schema_version",
    "experiment_id",
    "status",
    "snapshot_id",
    "snapshot_at",
    "rank_frontier",
    "last_completed_rank",
    "completed_asset_ids",
    "pending_asset_ids",
    "excluded_assets",
    "source",
    "pagination",
    "resume",
    "updated_at_utc",
}

RECORD_TEMPLATE = {
    "asset": "ASSET",
    "market_cap_usd": 100.0,
    "as_of": "2024-01-01T00:00:00Z",
    "published_at": "2024-01-01T01:00:00Z",
}


def _utc_iso(value: str) -> str:
    from datetime import datetime, timezone

    parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FrontierError(f"{value} is not timezone-aware")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _make_record(index: int, cap: float | None = None) -> dict:
    record = dict(RECORD_TEMPLATE)
    record["asset"] = f"ASSET{index:03d}"
    if cap is not None:
        record["market_cap_usd"] = cap
    return record


def _check(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def _check_valid_state(state: dict, errors: list[str], label: str) -> None:
    missing = REQUIRED_FIELDS - set(state)
    _check(not missing, f"{label}: missing fields {sorted(missing)}", errors)
    if missing:
        return

    timestamp_fields = [
        state.get("snapshot_at"),
        state.get("updated_at_utc"),
        state.get("source", {}).get("retrieved_at_utc"),
    ]
    timestamp_fields.extend(entry.get("excluded_at_utc", "") for entry in state.get("excluded_assets", []))
    for entry in state.get("rank_frontier", []):
        timestamp_fields.append(entry.get("as_of", ""))
        timestamp_fields.append(entry.get("published_at", ""))
    for field in timestamp_fields:
        _check(isinstance(field, str) and field.endswith("Z"), f"{label}: non-UTC timestamp {field!r}", errors)
        try:
            _utc_iso(field)
        except Exception as exc:
            _check(False, f"{label}: invalid timestamp {field!r}: {exc}", errors)

    _check(
        isinstance(state.get("snapshot_id"), str) and bool(SNAPSHOT_ID_RE.match(state["snapshot_id"])),
        f"{label}: snapshot_id must match FVD-SNAP-<16 hex>, got {state.get('snapshot_id')!r}",
        errors,
    )

    source = state.get("source", {})
    _check(
        isinstance(source, dict) and bool(str(source.get("id", "")).strip()) and bool(str(source.get("hash", "")).strip()),
        f"{label}: source id and hash must be non-empty",
        errors,
    )

    pagination = state.get("pagination", {})
    _check(
        isinstance(pagination, dict)
        and "cursor" in pagination
        and "batch_size" in pagination
        and "has_more" in pagination,
        f"{label}: pagination must carry cursor, batch_size and has_more",
        errors,
    )

    resume = state.get("resume", {})
    _check(
        isinstance(resume, dict)
        and all(key in resume for key in ("next_rank", "next_asset", "batch_window", "has_more", "frontier_size", "snapshot_id")),
        f"{label}: resume must carry next_rank, next_asset, batch_window, has_more, frontier_size, snapshot_id",
        errors,
    )
    if isinstance(resume, dict) and "snapshot_id" in resume:
        _check(resume["snapshot_id"] == state.get("snapshot_id"), f"{label}: resume snapshot_id mismatch", errors)

    frontier = state.get("rank_frontier", [])
    last_completed = state.get("last_completed_rank", -1)
    _check(isinstance(last_completed, int) and last_completed >= 0, f"{label}: last_completed_rank must be a non-negative int", errors)
    ranks = []
    seen_assets = set()
    previous_cap = None
    previous_asset = None
    for position, entry in enumerate(frontier, 1):
        _check(
            isinstance(entry, dict) and all(key in entry for key in ("rank", "asset", "market_cap_usd", "as_of", "published_at")),
            f"{label}: rank frontier entry {position} missing required entry fields",
            errors,
        )
        try:
            rank = int(entry["rank"])
        except (TypeError, ValueError):
            rank = -1
        ranks.append(rank)
        asset = str(entry.get("asset", "")).strip()
        _check(bool(asset), f"{label}: rank {position} missing asset id", errors)
        _check(asset not in seen_assets, f"{label}: duplicate asset {asset} in rank frontier", errors)
        seen_assets.add(asset)
        try:
            cap = float(entry["market_cap_usd"])
        except (TypeError, ValueError):
            cap = float("nan")
        if previous_cap is not None:
            _check(
                cap < previous_cap or (cap == previous_cap and asset > previous_asset),
                f"{label}: rank frontier not descending by cap with asset-ID tie-break at rank {position}",
                errors,
            )
        previous_cap = cap
        previous_asset = asset

    expected = 1
    for rank in ranks:
        _check(rank == expected, f"{label}: rank frontier gap: expected rank {expected}, found {rank}", errors)
        expected += 1

    ranks_above_cursor = [int(entry["rank"]) for entry in frontier if int(entry["rank"]) > last_completed]
    if ranks_above_cursor:
        _check(
            ranks_above_cursor == list(range(last_completed + 1, last_completed + 1 + len(ranks_above_cursor))),
            f"{label}: rank gap above last_completed_rank {last_completed}",
            errors,
        )

    completed = sorted(entry["asset"] for entry in frontier if int(entry["rank"]) <= last_completed)
    _check(
        sorted(state.get("completed_asset_ids", [])) == completed,
        f"{label}: completed_asset_ids inconsistent with last_completed_rank {last_completed}",
        errors,
    )

    batch_size = int(pagination.get("batch_size", 0)) if isinstance(pagination, dict) else 0
    remaining = [entry for entry in frontier if int(entry["rank"]) > last_completed]
    pending = [entry["asset"] for entry in remaining[batch_size:]]
    _check(
        state.get("pending_asset_ids") == pending,
        f"{label}: pending_asset_ids inconsistent with batch cursor",
        errors,
    )
    _check(
        state.get("status") == ("COMPLETED" if not pending else "OPEN"),
        f"{label}: status inconsistent with pending assets",
        errors,
    )
    if isinstance(resume, dict):
        _check(resume.get("next_rank") == last_completed + 1, f"{label}: resume next_rank mismatch", errors)
        _check(resume.get("frontier_size") == len(frontier), f"{label}: resume frontier_size mismatch", errors)
        if remaining:
            _check(resume.get("next_asset") == remaining[0]["asset"], f"{label}: resume next_asset mismatch", errors)
            window = resume.get("batch_window")
            _check(
                isinstance(window, list) and len(window) == 2 and int(window[0]) == remaining[0]["rank"] and int(window[1]) == remaining[min(batch_size, len(remaining)) - 1]["rank"],
                f"{label}: resume batch_window mismatch",
                errors,
            )
        else:
            _check(resume.get("next_asset") is None and resume.get("batch_window") is None, f"{label}: resume should be empty at frontier end", errors)
        _check(bool(resume.get("has_more")) == bool(pending), f"{label}: resume has_more inconsistent with pending", errors)
    _check(bool(pagination.get("has_more")) == bool(pending), f"{label}: pagination has_more inconsistent with pending", errors)


def _build_valid_fixture(snapshot_at: str, source_id: str, source_hash: str, last_completed_rank: int, batch_size: int) -> dict:
    records = [
        _make_record(1, 1_000_000_000.0),
        _make_record(2, 900_000_000.0),
        _make_record(3, 900_000_000.0),
        _make_record(4, 800_000_000.0),
        _make_record(5, 700_000_000.0),
        _make_record(6, 700_000_000.0),
        _make_record(7, 600_000_000.0),
    ]
    ranked, excluded = rank_universe(records, snapshot_at)
    return build_frontier(
        snapshot_at,
        source_id,
        source_hash,
        records=records,
        batch_size=batch_size,
        last_completed_rank=last_completed_rank,
        completed_asset_ids=[entry["asset"] for entry in ranked if entry["rank"] <= last_completed_rank],
        excluded_assets=excluded,
        cursor="page-1",
        previous_snapshot_id=None,
    )


def validate_frontier() -> list[str]:
    errors: list[str] = []
    snapshot_at = "2024-02-15T00:00:00Z"

    # Positive: multiple valid fixtures, persisted and round-tripped.
    for last_completed_rank, batch_size in ((0, 2), (2, 50), (7, 10)):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frontier.json"
            state = _build_valid_fixture(snapshot_at, "coingecko", "sha256:abc123", last_completed_rank, batch_size)
            persist_frontier(path, snapshot_at, "coingecko", "sha256:abc123", records=[
                _make_record(1, 1_000_000_000.0),
                _make_record(2, 900_000_000.0),
                _make_record(3, 900_000_000.0),
                _make_record(4, 800_000_000.0),
                _make_record(5, 700_000_000.0),
                _make_record(6, 700_000_000.0),
                _make_record(7, 600_000_000.0),
            ], batch_size=batch_size, last_completed_rank=last_completed_rank,
            completed_asset_ids=[entry["asset"] for entry in rank_universe([
                _make_record(1, 1_000_000_000.0),
                _make_record(2, 900_000_000.0),
                _make_record(3, 900_000_000.0),
                _make_record(4, 800_000_000.0),
                _make_record(5, 700_000_000.0),
                _make_record(6, 700_000_000.0),
                _make_record(7, 600_000_000.0),
            ], snapshot_at)[0] if entry["rank"] <= last_completed_rank],
            excluded_assets=rank_universe([
                _make_record(1, 1_000_000_000.0),
                _make_record(2, 900_000_000.0),
                _make_record(3, 900_000_000.0),
                _make_record(4, 800_000_000.0),
                _make_record(5, 700_000_000.0),
                _make_record(6, 700_000_000.0),
                _make_record(7, 600_000_000.0),
            ], snapshot_at)[1], cursor="page-1")
            loaded = load_frontier(path)
            _check(loaded == state, f"persisted/loaded state mismatch (last_completed_rank={last_completed_rank})", errors)
            _check_valid_state(loaded, errors, f"fixture(last_completed_rank={last_completed_rank}, batch_size={batch_size})")

    # Positive: in-memory built state passes conformance.
    state = _build_valid_fixture(snapshot_at, "external", "hash:deadbeef", 3, 2)
    _check_valid_state(state, errors, "in-memory fixture")

    # Negative: required field missing.
    bad = dict(state)
    del bad["resume"]
    _check(len(REQUIRED_FIELDS - set(bad)) == 1, "missing-field detection failed", errors)

    # Negative: non-UTC timestamp.
    bad = json.loads(json.dumps(state))
    bad["snapshot_at"] = "2024-02-15T00:00:00"
    _check_valid_state(bad, errors, "naive timestamp")
    _check(any("non-UTC timestamp" in message for message in errors), "naive timestamp not rejected", errors)
    errors.clear()

    # Negative: bad snapshot id format.
    bad = json.loads(json.dumps(state))
    bad["snapshot_id"] = "SNAP-abcdef0123456789"
    _check_valid_state(bad, errors, "bad snapshot id")
    _check(any("snapshot_id" in message for message in errors), "bad snapshot id not rejected", errors)
    errors.clear()

    # Negative: rank gap above cursor.
    bad = json.loads(json.dumps(state))
    bad["rank_frontier"] = [entry for entry in bad["rank_frontier"] if entry["rank"] != 2]
    errors.clear()
    _check_valid_state(bad, errors, "rank gap")
    _check(any("gap" in message.lower() for message in errors), "rank gap not rejected", errors)
    errors.clear()

    # Negative: unsorted (not descending) frontier.
    bad = json.loads(json.dumps(state))
    bad["rank_frontier"] = list(reversed(bad["rank_frontier"]))
    errors.clear()
    _check_valid_state(bad, errors, "unsorted frontier")
    _check(any("not descending" in message for message in errors), "unsorted frontier not rejected", errors)
    errors.clear()

    # Negative: missing source id/hash.
    bad = json.loads(json.dumps(state))
    bad["source"] = {"id": "", "hash": "", "retrieved_at_utc": state["source"]["retrieved_at_utc"]}
    errors.clear()
    _check_valid_state(bad, errors, "missing source")
    _check(any("source" in message for message in errors), "missing source not rejected", errors)
    errors.clear()

    # Negative: pending/completed inconsistency.
    bad = json.loads(json.dumps(state))
    bad["pending_asset_ids"] = []
    errors.clear()
    _check_valid_state(bad, errors, "pending mismatch")
    _check(any("pending" in message.lower() for message in errors), "pending mismatch not rejected", errors)
    errors.clear()

    # Negative: status inconsistent with pending.
    bad = json.loads(json.dumps(state))
    bad["status"] = "COMPLETED"
    errors.clear()
    _check_valid_state(bad, errors, "status mismatch")
    _check(any("status" in message.lower() for message in errors), "status mismatch not rejected", errors)
    errors.clear()

    # Negative: save_frontier rejects incomplete state.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "frontier.json"
        try:
            save_frontier(path, {"snapshot_id": "x"})
            _check(False, "save_frontier accepted incomplete state", errors)
        except FrontierError:
            pass

    # Negative: load_frontier rejects missing/corrupt file.
    with tempfile.TemporaryDirectory() as tmp:
        missing = Path(tmp) / "missing.json"
        corrupt = Path(tmp) / "corrupt.json"
        corrupt.write_text("{not json", encoding="utf-8")
        try:
            load_frontier(missing)
            _check(False, "load_frontier accepted missing file", errors)
        except FrontierError:
            pass
        try:
            load_frontier(corrupt)
            _check(False, "load_frontier accepted corrupt file", errors)
        except FrontierError:
            pass

    if errors:
        return errors
    return []


def main() -> int:
    errors = validate_frontier()
    if errors:
        print("UNIVERSE_FRONTIER_VALIDATION=FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("UNIVERSE_FRONTIER_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
