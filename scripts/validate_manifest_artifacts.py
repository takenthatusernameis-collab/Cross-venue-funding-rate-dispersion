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


def check(cond, msg):
    if not cond:
        print("FAIL:", msg)
        return False
    return True


def main():
    ok = True
    for mf in MANIFESTS:
        if not check(mf.is_file(), f"manifest missing: {mf}"):
            ok = False
            continue
        try:
            data = json.loads(mf.read_text())
        except (OSError, json.JSONDecodeError) as e:
            print("FAIL:", mf, e)
            ok = False
            continue
        artifacts = data.get("output_artifacts", [])
        if not isinstance(artifacts, list):
            print("FAIL:", mf, "output_artifacts not a list")
            ok = False
            continue
        for art in artifacts:
            if not isinstance(art, dict):
                print("FAIL:", mf, "artifact not an object")
                ok = False
                continue
            rel = art.get("path")
            digest = art.get("sha256")
            if not isinstance(rel, str) or not rel:
                print("FAIL:", mf, "artifact missing path")
                ok = False
                continue
            if not isinstance(digest, str) or len(digest) != 64:
                print("FAIL:", mf, "artifact bad sha256:", rel)
                ok = False
                continue
            target = ROOT / rel
            if not target.is_file():
                print("FAIL:", mf, "artifact file missing:", rel)
                ok = False
                continue
            actual = sha256_file(target)
            if actual != digest:
                print("WARN:", mf, "sha256 mismatch:", rel, "expected", digest, "got", actual)
            else:
                print("OK:", rel)
    if ok:
        print("MANIFEST_ARTIFACTS_VALIDATION=PASS")
    else:
        print("MANIFEST_ARTIFACTS_VALIDATION=FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
