#!/usr/bin/env python3
"""Offline conformance check for controller-verified Kilo progress accounting.

Standard library only. Spawns throwaway git repositories in a temporary
directory to verify the fail-closed behavior of `has_meaningful_committed_progress`
against the controller contract: credit requires a Kilo-authored commit that
touches project files outside `.github/workflows/`, with a verified remote SHA
that matches the head, on an ancestor chain. Workflow-only or non-Kilo commits
must not count as progress.

No network calls, no project mutation, no performance claim.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from controller_progress import has_meaningful_committed_progress  # noqa: E402

KILO_EMAIL = "kilo-autonomous@users.noreply.github.com"


def check(cond, msg):
    if not cond:
        print("FAIL:", msg)
        sys.exit(1)


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def fresh_repo():
    temp = tempfile.TemporaryDirectory()
    repo = Path(temp.name)
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "initial")
    git(repo, "config", "user.email", "initial@example.invalid")
    (repo / "baseline.txt").write_text("baseline\n")
    git(repo, "add", "baseline.txt")
    git(repo, "commit", "-m", "initial")
    return repo, git(repo, "rev-parse", "HEAD"), temp


def kilo_commit(repo, path, content):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    git(repo, "add", path)
    git(
        repo,
        "-c",
        "user.name=kilo-autonomous",
        "-c",
        f"user.email={KILO_EMAIL}",
        "commit",
        "-m",
        "agent checkpoint",
    )
    return git(repo, "rev-parse", "HEAD")


def other_commit(repo, path, content):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    git(repo, "add", path)
    git(repo, "commit", "-m", "other commit")
    return git(repo, "rev-parse", "HEAD")


def main():
    # 1. Kilo-authored commit touching src/ counts as progress.
    repo, base, temp = fresh_repo()
    head = kilo_commit(repo, "src/new.py", "value=1\n")
    check(
        has_meaningful_committed_progress(repo, base, head, head),
        "kilo src commit should count",
    )
    temp.cleanup()

    # 2. Kilo-authored commit touching only .github/workflows/ does NOT count.
    repo, base, temp = fresh_repo()
    head = kilo_commit(repo, ".github/workflows/main.yml", "name: test\n")
    check(
        not has_meaningful_committed_progress(repo, base, head, head),
        "workflow-only kilo commit must not count",
    )
    temp.cleanup()

    # 3. Non-Kilo-authored commit does not count even with matching remote.
    repo, base, temp = fresh_repo()
    head = other_commit(repo, "docs/x.md", "# x\n")
    check(
        not has_meaningful_committed_progress(repo, base, head, head),
        "non-kilo commit must not count",
    )
    temp.cleanup()

    # 4. base == head is not progress.
    repo, base, temp = fresh_repo()
    check(
        not has_meaningful_committed_progress(repo, base, base, base),
        "base==head must not count",
    )
    temp.cleanup()

    # 5. Remote SHA mismatch fails closed.
    repo, base, temp = fresh_repo()
    head = kilo_commit(repo, "src/new.py", "value=1\n")
    check(
        not has_meaningful_committed_progress(repo, base, head, "wrong"),
        "remote mismatch must fail closed",
    )
    temp.cleanup()

    # 6. Empty remote SHA fails closed.
    repo, base, temp = fresh_repo()
    head = kilo_commit(repo, "src/new.py", "value=1\n")
    check(
        not has_meaningful_committed_progress(repo, base, head, ""),
        "empty remote sha must fail closed",
    )
    temp.cleanup()

    # 7. Non-ancestor base fails closed.
    repo, base, temp = fresh_repo()
    head = other_commit(repo, "docs/x.md", "# x\n")
    other_base = git(repo, "rev-parse", f"{head}~1")
    check(
        not has_meaningful_committed_progress(repo, head, other_base, other_base),
        "non-ancestor base must fail closed",
    )
    temp.cleanup()

    # 8. Bad repo path raises (fail-closed), not silently False.
    repo, base, temp = fresh_repo()
    head = kilo_commit(repo, "src/new.py", "value=1\n")
    raised = False
    try:
        has_meaningful_committed_progress("/nonexistent/repo/zzz", base, head, head)
    except (OSError, RuntimeError, ValueError):
        raised = True
    check(raised, "bad repo path must raise")
    temp.cleanup()

    # 9. Kilo commit touching tests/ counts (project files, not workflow).
    repo, base, temp = fresh_repo()
    head = kilo_commit(repo, "tests/test_x.py", "import unittest\n")
    check(
        has_meaningful_committed_progress(repo, base, head, head),
        "kilo tests commit should count",
    )
    temp.cleanup()

    # 10. Kilo commit touching scripts/ counts.
    repo, base, temp = fresh_repo()
    head = kilo_commit(repo, "scripts/x.py", "x=1\n")
    check(
        has_meaningful_committed_progress(repo, base, head, head),
        "kilo scripts commit should count",
    )
    temp.cleanup()

    # 11. Kilo commit touching configs/ counts.
    repo, base, temp = fresh_repo()
    head = kilo_commit(repo, "configs/x.json", "{}\n")
    check(
        has_meaningful_committed_progress(repo, base, head, head),
        "kilo configs commit should count",
    )
    temp.cleanup()

    # 12. Kilo commit touching research_state/ counts.
    repo, base, temp = fresh_repo()
    head = kilo_commit(repo, "research_state/x.json", "{}\n")
    check(
        has_meaningful_committed_progress(repo, base, head, head),
        "kilo research_state commit should count",
    )
    temp.cleanup()

    print("CONTROLLER_PROGRESS_VALIDATION=PASS")


if __name__ == "__main__":
    main()