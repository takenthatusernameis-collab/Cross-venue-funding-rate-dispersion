"""Source-independent resumable rank-frontier persistence for point-in-time universes.

Pure deterministic calculations plus atomic JSON persistence; no network calls.
Implements the historical-universe persistence contract: a content-bound
snapshot id, a rank frontier sorted by market capitalization descending with a
deterministic asset-ID tie-break, a last-completed-rank cursor, completed and
pending asset ids, explicit exclusions with reasons, source hashes, pagination
cursors and resume state.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class FrontierError(ValueError):
    """Fail-closed validation error for frontier records and state transitions."""


def _utc(value: str | datetime, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
        except ValueError as exc:
            raise FrontierError(f"{field} must be ISO-8601 or datetime") from exc
    else:
        raise FrontierError(f"{field} must be ISO-8601 or datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FrontierError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _now() -> str:
    return _iso(datetime.now(timezone.utc))


def _positive_finite_cap(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise FrontierError(f"{field} must be a number") from exc
    if not math.isfinite(number) or number <= 0:
        raise FrontierError(f"{field} must be a positive finite market cap")
    return number


def compute_snapshot_id(source_id: str, source_hash: str, snapshot_at: str | datetime, records: list[dict[str, Any]]) -> str:
    """Deterministic snapshot id bound to source, content hash, time and payload."""
    snapshot = _utc(snapshot_at, "snapshot_at")
    payload = {
        "source_id": str(source_id),
        "source_hash": str(source_hash),
        "snapshot_at": _iso(snapshot),
        "records": sorted(
            (
                str(record.get("asset", "")),
                repr(float(record["market_cap_usd"])) if "market_cap_usd" in record else "<missing>",
                str(record.get("as_of", "")),
                str(record.get("published_at", "")),
            )
            for record in records
        ),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"FVD-SNAP-{digest[:16]}"


def rank_universe(records: list[dict[str, Any]], snapshot_at: str | datetime) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Validate and rank point-in-time market-cap records for one snapshot.

    A record is admissible only when its effective and publication timestamps
    are both no later than the snapshot and its market cap is positive and
    finite. Per asset, the newest effective/published record wins. Results are
    sorted by market cap descending with deterministic asset-ID tie-break and
    ranked from 1. Excluded records carry an explicit reason and a UTC
    exclusion timestamp.
    """
    snapshot = _utc(snapshot_at, "snapshot_at")
    now = _now()
    latest: dict[str, tuple[tuple[datetime, datetime], float]] = {}
    excluded: list[dict[str, str]] = []
    for record in records:
        asset = str(record.get("asset", "")).strip()
        if not asset:
            excluded.append({"asset": "<missing>", "reason": "missing asset id", "excluded_at_utc": now})
            continue
        try:
            effective = _utc(record["as_of"], "as_of")
            published = _utc(record["published_at"], "published_at")
            cap = _positive_finite_cap(record["market_cap_usd"], "market_cap_usd")
        except (KeyError, TypeError, ValueError, FrontierError) as exc:
            excluded.append({"asset": asset, "reason": f"invalid record: {exc}", "excluded_at_utc": now})
            continue
        if effective > snapshot:
            excluded.append({"asset": asset, "reason": f"effective {_iso(effective)} after snapshot {_iso(snapshot)}", "excluded_at_utc": now})
            continue
        if published > snapshot:
            excluded.append({"asset": asset, "reason": f"published {_iso(published)} after snapshot {_iso(snapshot)}", "excluded_at_utc": now})
            continue
        key = (effective, published)
        prior = latest.get(asset)
        if prior is not None and key <= prior[0]:
            excluded.append({"asset": asset, "reason": "superseded by newer effective/published record", "excluded_at_utc": now})
            continue
        latest[asset] = (key, cap)
    ordered = sorted(latest.items(), key=lambda item: (-item[1][1], item[0]))
    ranked = [
        {
            "rank": position,
            "asset": asset,
            "market_cap_usd": values[1],
            "as_of": _iso(values[0][0]),
            "published_at": _iso(values[0][1]),
        }
        for position, (asset, values) in enumerate(ordered, 1)
    ]
    return ranked, excluded


def validate_ranked_assets(ranked_assets: list[dict[str, Any]]) -> None:
    """Fail-closed validation of an externally supplied rank frontier."""
    ranks: list[int] = []
    seen: set[str] = set()
    for item in ranked_assets:
        try:
            rank = int(item["rank"])
            asset = str(item.get("asset", "")).strip()
            cap = _positive_finite_cap(item.get("market_cap_usd"), "market_cap_usd")
        except (KeyError, TypeError, ValueError, FrontierError) as exc:
            raise FrontierError(f"invalid ranked asset entry: {exc}") from exc
        _ = cap
        if rank < 1:
            raise FrontierError("ranks must start at 1")
        if not asset:
            raise FrontierError("ranked asset missing asset id")
        if asset in seen:
            raise FrontierError(f"duplicate asset {asset} in rank frontier")
        seen.add(asset)
        ranks.append(rank)
    if len(set(ranks)) != len(ranks):
        raise FrontierError("duplicate ranks in rank frontier")
    expected = 1
    for rank in ranks:
        if rank != expected:
            raise FrontierError(f"rank frontier gap: expected rank {expected}, found {rank}")
        expected += 1


def build_not_started_frontier(next_action: str | None = None) -> dict[str, Any]:
    """Canonical NOT_STARTED frontier stub.

    Before any free source passes the point-in-time market-cap gate the
    frontier is an explicit not-started state: the full schema with every field
    present but no snapshot id, no ranked assets and no completed ranks. This
    builder is the single source of truth for that stub so the committed file
    and the library can never drift apart.
    """
    return {
        "schema_version": "1.0",
        "experiment_id": "FVD-DISPERSION-V1",
        "status": "NOT_STARTED",
        "snapshot_id": None,
        "snapshot_at": None,
        "previous_snapshot_id": None,
        "rank_frontier": [],
        "last_completed_rank": 0,
        "completed_asset_ids": [],
        "pending_asset_ids": [],
        "excluded_assets": [],
        "current_cohort": [],
        "next_action": next_action,
        "source": {"id": None, "hash": None, "retrieved_at_utc": None},
        "pagination": {"cursor": None, "batch_size": 0, "has_more": False},
        "resume": {
            "next_rank": 1,
            "next_asset": None,
            "batch_window": None,
            "has_more": False,
            "frontier_size": 0,
            "snapshot_id": None,
        },
        "updated_at_utc": None,
    }


def build_frontier(
    snapshot_at: str | datetime,
    source_id: str,
    source_hash: str,
    *,
    records: list[dict[str, Any]] | None = None,
    ranked_assets: list[dict[str, Any]] | None = None,
    batch_size: int = 50,
    last_completed_rank: int = 0,
    completed_asset_ids: list[str] | None = None,
    excluded_assets: list[dict[str, str]] | None = None,
    cursor: str | None = None,
    previous_snapshot_id: str | None = None,
    current_cohort: list[str] | None = None,
    next_action: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build a deterministic frontier state without touching the network."""
    if batch_size < 1:
        raise FrontierError("batch_size must be positive")
    if last_completed_rank < 0:
        raise FrontierError("last_completed_rank must be non-negative")
    if current_cohort is not None and not isinstance(current_cohort, list):
        raise FrontierError("current_cohort must be a list when provided")
    if next_action is not None and not isinstance(next_action, str):
        raise FrontierError("next_action must be a string when provided")
    if current_cohort is not None and not isinstance(current_cohort, list):
        raise FrontierError("current_cohort must be a list when provided")
    if kwargs:
        raise FrontierError(f"unknown frontier field: {sorted(kwargs)}")
    snapshot = _utc(snapshot_at, "snapshot_at")
    now = _now()
    if ranked_assets is None:
        if records is None:
            raise FrontierError("records or ranked_assets must be provided")
        ranked_assets, record_exclusions = rank_universe(records, snapshot)
        exclusions = list(record_exclusions)
    else:
        validate_ranked_assets(ranked_assets)
        exclusions = []
    remaining = [item for item in ranked_assets if int(item["rank"]) > last_completed_rank]
    expected = last_completed_rank + 1
    for item in remaining:
        if int(item["rank"]) != expected:
            raise FrontierError(f"rank frontier gap: expected rank {expected}, found {int(item['rank'])}")
        expected += 1
    batch = remaining[:batch_size]
    pending = [item["asset"] for item in remaining[batch_size:]]
    completed = sorted(
        {str(item["asset"]).strip() for item in ranked_assets if int(item["rank"]) <= last_completed_rank}
        | set(completed_asset_ids or [])
    )
    merged_exclusions: list[dict[str, str]] = []
    seen_exclusions: set[tuple[str, str]] = set()
    for entry in list(excluded_assets or []) + exclusions:
        key = (str(entry.get("asset", "")), str(entry.get("reason", "")))
        if key in seen_exclusions:
            continue
        seen_exclusions.add(key)
        merged_entry = dict(entry)
        merged_entry.setdefault("excluded_at_utc", now)
        merged_exclusions.append(merged_entry)
    snapshot_id = compute_snapshot_id(source_id, source_hash, snapshot_at, ranked_assets)
    state: dict[str, Any] = {
        "schema_version": "1.0",
        "experiment_id": "FVD-DISPERSION-V1",
        "status": "COMPLETED" if not pending else "OPEN",
        "snapshot_id": snapshot_id,
        "snapshot_at": _iso(snapshot),
        "previous_snapshot_id": previous_snapshot_id,
        "rank_frontier": ranked_assets,
        "last_completed_rank": last_completed_rank,
        "completed_asset_ids": completed,
        "pending_asset_ids": pending,
        "excluded_assets": merged_exclusions,
        "source": {"id": str(source_id), "hash": str(source_hash), "retrieved_at_utc": now},
        "pagination": {"cursor": cursor, "batch_size": batch_size, "has_more": bool(pending)},
        "resume": {
            "next_rank": last_completed_rank + 1,
            "next_asset": batch[0]["asset"] if batch else None,
            "batch_window": [int(batch[0]["rank"]), int(batch[-1]["rank"])] if batch else None,
            "has_more": bool(pending),
            "frontier_size": len(ranked_assets),
            "snapshot_id": snapshot_id,
        },
        "current_cohort": [item["asset"] for item in batch],
        "next_action": next_action,
        "updated_at_utc": now,
    }
    return state


def save_frontier(path: str | Path, state: dict[str, Any]) -> None:
    """Atomically persist frontier state as UTF-8 JSON with UTC timestamps."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not isinstance(state, dict):
        raise FrontierError("frontier state must be a JSON object")
    required = {
        "schema_version",
        "experiment_id",
        "status",
        "snapshot_id",
        "rank_frontier",
        "last_completed_rank",
    }
    missing = required - set(state)
    if missing:
        raise FrontierError(f"missing frontier state fields: {sorted(missing)}")
    payload = json.dumps(state, sort_keys=True, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=".frontier-", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o644)
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def load_frontier(path: str | Path) -> dict[str, Any]:
    """Load and validate a persisted frontier state."""
    target = Path(path)
    if not target.is_file():
        raise FrontierError(f"frontier state not found: {target}")
    try:
        state = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        raise FrontierError(f"unreadable frontier state {target}: {exc}") from exc
    if not isinstance(state, dict):
        raise FrontierError("frontier state must be a JSON object")
    required = {
        "schema_version",
        "experiment_id",
        "status",
        "snapshot_id",
        "rank_frontier",
        "last_completed_rank",
        "completed_asset_ids",
        "pending_asset_ids",
        "excluded_assets",
        "source",
        "pagination",
        "resume",
        "current_cohort",
        "next_action",
        "updated_at_utc",
    }
    missing = required - set(state)
    if missing:
        raise FrontierError(f"frontier state missing fields: {sorted(missing)}")
    return state


def persist_frontier(
    path: str | Path,
    snapshot_at: str | datetime,
    source_id: str,
    source_hash: str,
    *,
    records: list[dict[str, Any]] | None = None,
    ranked_assets: list[dict[str, Any]] | None = None,
    batch_size: int = 50,
    last_completed_rank: int = 0,
    completed_asset_ids: list[str] | None = None,
    excluded_assets: list[dict[str, str]] | None = None,
    cursor: str | None = None,
    previous_snapshot_id: str | None = None,
    current_cohort: list[str] | None = None,
    next_action: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build and atomically persist a frontier state; returns the state."""
    state = build_frontier(
        snapshot_at,
        source_id,
        source_hash,
        records=records,
        ranked_assets=ranked_assets,
        batch_size=batch_size,
        last_completed_rank=last_completed_rank,
        completed_asset_ids=completed_asset_ids,
        excluded_assets=excluded_assets,
        cursor=cursor,
        previous_snapshot_id=previous_snapshot_id,
        current_cohort=current_cohort,
        next_action=next_action,
        **kwargs,
    )
    save_frontier(path, state)
    return state
