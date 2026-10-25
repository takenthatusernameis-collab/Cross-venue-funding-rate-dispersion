#!/usr/bin/env python3
"""Offline conformance check for repository Agent Skills files."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / ".agents/skills"


def validate_skills(root=ROOT, skill_root=SKILL_ROOT) -> list[str]:
    errors = []
    agents = root / "AGENTS.md"
    if not agents.is_file():
        errors.append("AGENTS.md missing")
    elif len(agents.read_text(encoding="utf-8").splitlines()) > 100:
        errors.append("AGENTS.md exceeds 100-line project target")
    skills = sorted(skill_root.glob("*/SKILL.md"))
    if len(skills) < 4:
        errors.append("expected at least four atomic skills")
    names = set()
    for path in skills:
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        if not content.startswith("---\n") or "\n---\n" not in content[4:]:
            errors.append(f"{path.relative_to(root)} has invalid frontmatter delimiters")
            continue
        front = content.split("---", 2)[1]
        match = re.search(r"^name:\s*([a-z0-9-]+)\s*$", front, re.M)
        description = re.search(r"^description:\s*\S", front, re.M)
        if not match:
            errors.append(f"{path.relative_to(root)} has no valid name")
        elif match.group(1) != path.parent.name:
            errors.append(f"{path.relative_to(root)} name must match its directory")
        elif match.group(1) in names:
            errors.append(f"duplicate skill name: {match.group(1)}")
        else:
            names.add(match.group(1))
        if not description:
            errors.append(f"{path.relative_to(root)} has no description")
        if len(lines) > 500:
            errors.append(f"{path.relative_to(root)} exceeds 500 lines")
    return errors


def main() -> int:
    errors = validate_skills()
    if errors:
        print("SKILLS_VALIDATION=FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    skills = sorted(SKILL_ROOT.glob("*/SKILL.md"))
    print(f"SKILLS_VALIDATION=PASS count={len(skills)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
