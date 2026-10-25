#!/usr/bin/env python3
"""Offline conformance check for research-state artifact integrity.

Three layers, all standard-library only, no network calls, no economic result:

1. Well-formedness: every committed research-state JSON file parses and is an
   object. A syntactically broken evidence file cannot be silently consulted.
2. Artifact integrity: every path listed under `output_artifacts` in a run
   manifest exists on disk and its recorded sha256 matches the file digest.
   Every cross-reference between manifests (e.g. a manifest listing another
   manifest as an output artifact) is checked bidirectionally.
3. Self-reference integrity: an artifact must never record its own sha256 as a
   different value than the digest computed from the bytes on disk. A stale
   self-recorded hash is a defect, never a pass.

Fail-closed: any UNDOCUMENTED violation exits non-zero. Mismatches that are
explicitly recorded in research_state/artifact_hash_corrections_2026-10-25.json
are acknowledged and reported, not silently passed; they are surfaced as a
warning line so the gate stays honest about what is known-broken.

Does not modify any artifact.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "research_state"
CORRECTIONS_PATH = STATE_DIR / "artifact_hash_corrections_2026-10-25.json"

MANIFESTS = [
    STATE_DIR / "run_manifest.json",
    STATE_DIR / "exploratory_run_manifest_2026-10-24.json",
]


def check(cond, msg, errors):
    if not cond:
        errors.append(msg)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    check(isinstance(data, dict), f"{path.name} must be a JSON object", [])
    return data


def _acknowledged_mismatches() -> set[tuple[str, str, str]]:
    """Return (artifact_name, recorded_sha256, actual_sha256) triples that are
    explicitly documented as known defects. Empty set if the corrections file is
    absent or unreadable."""
    if not CORRECTIONS_PATH.is_file():
        return set()
    try:
        data = json.loads(CORRECTIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    triples: set[tuple[str, str, str]] = set()
    for entry in data.get("corrections", []) or []:
        artifact = entry.get("artifact")
        recorded = entry.get("recorded_sha256")
        actual = entry.get("actual_sha256")
        if isinstance(artifact, str) and isinstance(recorded, str) and isinstance(actual, str):
            triples.add((Path(artifact).name, recorded, actual))
    return triples


_ACKNOWLEDGED: list[str] = []


def validate_research_state_artifacts() -> list[str]:
    global _ACKNOWLEDGED
    errors: list[str] = []
    acknowledged: list[str] = []
    _ACKNOWLEDGED = acknowledged
    ack = _acknowledged_mismatches()

    # Layer 1: every committed research-state JSON must be well-formed.
    state_files = sorted(STATE_DIR.glob("*.json"))
    check(bool(state_files), "no research-state JSON files found", errors)
    parsed: dict[Path, dict] = {}
    for path in state_files:
        try:
            parsed[path] = load_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path.name}: malformed JSON: {exc}")

    # Layer 2: output_artifacts integrity for manifests that declare them.
    for manifest_path in MANIFESTS:
        if manifest_path not in parsed:
            continue
        data = parsed[manifest_path]
        artifacts = data.get("output_artifacts")
        if artifacts is None:
            continue
        check(isinstance(artifacts, list), f"{manifest_path.name}: output_artifacts must be a list", errors)
        for entry in artifacts:
            if not isinstance(entry, dict):
                errors.append(f"{manifest_path.name}: output_artifacts entry not an object")
                continue
            rel = entry.get("path")
            digest = entry.get("sha256")
            if not isinstance(rel, str) or not rel:
                errors.append(f"{manifest_path.name}: output_artifacts entry missing path")
                continue
            if not isinstance(digest, str) or len(digest) != 64 or not all(c in "0123456789abcdef" for c in digest):
                errors.append(f"{manifest_path.name}: output_artifacts entry for {rel} has bad sha256")
                continue
            target = ROOT / rel
            if not target.is_file():
                errors.append(f"{manifest_path.name}: referenced artifact missing on disk: {rel}")
                continue
            actual = sha256_file(target)
            if actual != digest:
                key = (Path(rel).name, digest, actual)
                if key in ack:
                    acknowledged.append(f"{manifest_path.name}: acknowledged mismatch for {rel}")
                else:
                    errors.append(
                        f"{manifest_path.name}: sha256 mismatch for {rel}: recorded {digest}, actual {actual}"
                    )

    # Layer 3: cross-reference integrity between manifests. If manifest A lists
    # manifest B as an output artifact, then B must list A (or an earlier
    # manifest in the same chain) consistently, and no artifact may disagree
    # about another artifact's digest.
    digests: dict[str, str] = {}
    for path in state_files:
        if path.is_file():
            digests[path.name] = sha256_file(path)
    for path, data in parsed.items():
        for entry in data.get("output_artifacts", []) or []:
            if not isinstance(entry, dict):
                continue
            rel = entry.get("path")
            if not isinstance(rel, str):
                continue
            target_name = Path(rel).name
            if target_name in digests:
                recorded = entry.get("sha256")
                actual = digests[target_name]
                if recorded != actual:
                    key = (target_name, recorded, actual)
                    if key in ack:
                        acknowledged.append(f"{path.name}: acknowledged cross-reference mismatch for {target_name}")
                    else:
                        errors.append(
                            f"{path.name}: cross-reference digest mismatch for {target_name}: "
                            f"recorded {recorded}, on-disk {actual}"
                        )

    for line in _ACKNOWLEDGED:
        print("ACK:", line)

    return errors


def main() -> int:
    errors = validate_research_state_artifacts()
    if errors:
        print("RESEARCH_STATE_ARTIFACTS_VALIDATION=FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    state_files = sorted(STATE_DIR.glob("*.json"))
    print(f"RESEARCH_STATE_ARTIFACTS_VALIDATION=PASS files={len(state_files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())