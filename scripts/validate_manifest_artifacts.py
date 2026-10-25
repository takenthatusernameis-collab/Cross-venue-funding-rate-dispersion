#!/usr/bin/env python3
"""Offline conformance check for research-state artifact integrity.

Verifies that every path listed under output_artifacts in the committed run
manifests exists on disk and that its sha256 matches the recorded digest.
Standard library only; no network calls; no economic result.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MANIFESTS = [
    ROOT / "research_state" / "run_manifest.json",
    ROOT / "research_state" / "exploratory_run_manifest_2026-10-24.json",
]


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_manifest_artifacts(manifest_paths, root):
    """Return list of error messages (empty means pass)."""
    errors = []
    for mf in manifest_paths:
        mf = Path(mf)
        if not mf.is_file():
            errors.append(f"manifest missing: {mf}")
            continue
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            errors.append(f"{mf}: {e}")
            continue
        artifacts = data.get("output_artifacts", [])
        if not isinstance(artifacts, list):
            errors.append(f"{mf}: output_artifacts not a list")
            continue
        for art in artifacts:
            if not isinstance(art, dict):
                errors.append(f"{mf}: artifact not an object")
                continue
            rel = art.get("path")
            digest = art.get("sha256")
            if not isinstance(rel, str) or not rel:
                errors.append(f"{mf}: artifact missing path")
                continue
            if not isinstance(digest, str) or len(digest) != 64:
                errors.append(f"{mf}: artifact bad sha256: {rel}")
                continue
            target = Path(root) / rel
            if not target.is_file():
                errors.append(f"{mf}: artifact file missing: {rel}")
                continue
            actual = sha256_file(target)
            if actual != digest:
                errors.append(f"{mf}: sha256 mismatch: {rel}")
            else:
                pass
    return errors


def main():
    errors = validate_manifest_artifacts(MANIFESTS, ROOT)
    for e in errors:
        print("FAIL:", e)
    # print OK lines? keep minimal; original printed OK per artifact. Preserve for committed.
    # Recompute OK lines for passing artifacts to match original output style.
    ok = not errors
    if ok:
        for mf in MANIFESTS:
            data = json.loads(Path(mf).read_text(encoding="utf-8"))
            for art in data.get("output_artifacts", []):
                print("OK:", art.get("path"))
        print("MANIFEST_ARTIFACTS_VALIDATION=PASS")
    else:
        print("MANIFEST_ARTIFACTS_VALIDATION=FAIL")
        sys.exit(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
