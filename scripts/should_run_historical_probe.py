#!/usr/bin/env python3
"""Rate-limit the scheduled historical-coverage probe without discarding evidence."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

NORMAL_COOLDOWN = timedelta(hours=6)
NETWORK_FAILURE_COOLDOWN = timedelta(minutes=15)
PATTERN = "historical_overlap_probe_*.json"


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def latest_probe(state_dir: str | Path) -> dict[str, Any] | None:
    """Return the most recent parseable probe record, keeping malformed files untouched."""
    root = Path(state_dir)
    records = []
    for path in root.glob(PATTERN):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        observed = _parse_timestamp(payload.get("observed_at_utc"))
        if observed is None:
            continue
        records.append((observed, path, payload))
    if not records:
        return None
    observed, path, payload = max(records, key=lambda row: row[0])
    return {
        "path": str(path),
        "observed_at_utc": observed.isoformat().replace("+00:00", "Z"),
        "status": payload.get("status", "UNKNOWN"),
    }


def decide(state_dir: str | Path, now: datetime | None = None) -> dict[str, Any]:
    """Use a short retry interval only when the prior probe got no HTTP response."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    previous = latest_probe(state_dir)
    if previous is None:
        return {
            "schema_version": "1.0",
            "should_run": True,
            "reason": "no_prior_parseable_probe",
            "latest_probe": None,
            "age_seconds": None,
            "next_eligible_at_utc": now.isoformat().replace("+00:00", "Z"),
        }

    observed = _parse_timestamp(previous["observed_at_utc"])
    assert observed is not None
    age_seconds = max(0, int((now - observed).total_seconds()))
    cooldown = (
        NETWORK_FAILURE_COOLDOWN
        if previous["status"] == "NETWORK_UNAVAILABLE_FROM_THIS_HOST"
        else NORMAL_COOLDOWN
    )
    should_run = (now - observed) >= cooldown
    next_eligible = observed + cooldown
    return {
        "schema_version": "1.0",
        "should_run": should_run,
        "reason": "cooldown_elapsed" if should_run else "recent_probe_cooldown",
        "latest_probe": previous,
        "age_seconds": age_seconds,
        "cooldown_seconds": int(cooldown.total_seconds()),
        "next_eligible_at_utc": next_eligible.isoformat().replace("+00:00", "Z"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", default="research_state")
    parser.add_argument("--output", default="/tmp/historical-probe-schedule.json")
    args = parser.parse_args(argv)
    result = decide(args.state_dir)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
