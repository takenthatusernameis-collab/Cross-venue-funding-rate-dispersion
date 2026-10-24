"""Point-in-time market-cap ranking and resumable descending cohorts."""
from __future__ import annotations
from datetime import datetime, timezone
import math
from typing import Any, Iterable


def _utc(value: str | datetime, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    else:
        raise ValueError(f"{field} must be ISO-8601 or datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def rank_point_in_time(records: Iterable[dict[str, Any]], snapshot_at: str | datetime) -> list[dict[str, Any]]:
    """Use only positive finite caps effective and published by snapshot_at."""
    snapshot = _utc(snapshot_at, "snapshot_at")
    latest: dict[str, tuple[datetime, datetime, float]] = {}
    for record in records:
        asset = str(record.get("asset", "")).strip()
        if not asset:
            continue
        try:
            effective = _utc(record["as_of"], "as_of")
            published = _utc(record["published_at"], "published_at")
            cap = float(record["market_cap_usd"])
        except (KeyError, TypeError, ValueError):
            continue
        if effective > snapshot or published > snapshot or not math.isfinite(cap) or cap <= 0:
            continue
        candidate = (effective, published, cap)
        prior = latest.get(asset)
        if prior is None or candidate[:2] > prior[:2]:
            latest[asset] = candidate
    ordered = sorted(latest.items(), key=lambda item: (-item[1][2], item[0]))
    return [{"rank":i,"asset":asset,"market_cap_usd":values[2],"as_of":values[0].isoformat().replace("+00:00","Z"),"published_at":values[1].isoformat().replace("+00:00","Z")} for i,(asset,values) in enumerate(ordered,1)]


def next_ranked_cohort(ranked_assets: list[dict[str, Any]], last_completed_rank: int, batch_size: int) -> list[dict[str, Any]]:
    """Return the next batch after a verified rank cursor; no fixed top-N eligibility."""
    if last_completed_rank < 0:
        raise ValueError("last_completed_rank must be non-negative")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    ranks = [int(item["rank"]) for item in ranked_assets]
    if len(set(ranks)) != len(ranks):
        raise ValueError("ranked universe contains duplicate ranks")
    remaining = sorted((item for item in ranked_assets if int(item["rank"]) > last_completed_rank), key=lambda item:int(item["rank"]))
    expected = last_completed_rank + 1
    for item in remaining:
        rank = int(item["rank"])
        if rank != expected:
            raise ValueError(f"rank frontier gap: expected rank {expected}, found {rank}")
        expected += 1
    return remaining[:batch_size]
