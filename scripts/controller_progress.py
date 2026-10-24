#!/usr/bin/env python3
"""Fail-closed accounting for controller-verified Kilo project progress."""
from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path

KILO_COMMITTER_EMAIL = "kilo-autonomous@users.noreply.github.com"


def _git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(repo), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.decode('utf-8', errors='replace').strip()}")
    return result.stdout


def _nul_paths(raw: bytes) -> set[str]:
    return {part.decode("utf-8", errors="surrogateescape") for part in raw.split(b"\0") if part}


def has_meaningful_committed_progress(repo: str | Path, base_sha: str, head_sha: str, verified_remote_sha: str | None = None) -> bool:
    repo = Path(repo)
    if verified_remote_sha is not None and (not verified_remote_sha or verified_remote_sha != head_sha):
        return False
    if base_sha == head_sha:
        return False
    ancestor = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", base_sha, head_sha], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False)
    if ancestor.returncode != 0:
        if ancestor.returncode == 1:
            return False
        raise RuntimeError("could not verify commit ancestry")
    net_paths = _nul_paths(_git(repo, "diff", "--name-only", "-z", base_sha, head_sha))
    log = _git(repo, "log", "--format=%H%x09%ce", f"{base_sha}..{head_sha}").decode("utf-8", errors="replace")
    kilo_paths = set()
    for row in log.splitlines():
        sha, separator, email = row.partition("\t")
        if separator and email.casefold() == KILO_COMMITTER_EMAIL.casefold():
            kilo_paths |= _nul_paths(_git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "-m", "--root", "-z", sha))
    return bool({p for p in net_paths & kilo_paths if not p.startswith(".github/workflows/")})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--verified-remote-sha")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args(argv)
    try:
        eligible = has_meaningful_committed_progress(args.repo, args.base_sha, args.head_sha, args.verified_remote_sha)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"controller progress check failed closed: {exc}", file=sys.stderr)
        return 2
    print("Meaningful committed project change detected." if eligible else "No eligible committed project change.")
    return 0 if eligible else 1


if __name__ == "__main__":
    raise SystemExit(main())
