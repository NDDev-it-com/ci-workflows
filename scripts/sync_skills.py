#!/usr/bin/env python3
"""Generate the .claude/skills mirror from the canonical .agents/skills source.

`.agents/skills/` is the single authored source (Codex / OpenCode discover it).
`.claude/skills/` is a deterministic, symlink-free copy for Claude Code — never
edit it by hand. Each mirrored skill carries a `.generated-from-agents-skills`
marker recording the source path and the SHA-256 of the mirrored SKILL.md, so
`check_skills.py` can prove the mirror is in sync. Symlinks are avoided so the
release source archive (which rejects symlinks) stays portable.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CANONICAL = REPO_ROOT / ".agents" / "skills"
MIRROR = REPO_ROOT / ".claude" / "skills"
MARKER = ".generated-from-agents-skills"


def sync() -> int:
    if not CANONICAL.is_dir():
        print(f"missing canonical skill directory: {CANONICAL}", file=sys.stderr)
        return 1
    if MIRROR.exists():
        shutil.rmtree(MIRROR)
    MIRROR.mkdir(parents=True)
    skills = sorted(p for p in CANONICAL.iterdir() if p.is_dir())
    for skill in skills:
        target = MIRROR / skill.name
        shutil.copytree(skill, target)
        payload = (target / "SKILL.md").read_bytes()
        (target / MARKER).write_text(
            f"source=.agents/skills/{skill.name}/SKILL.md\n"
            f"sha256={hashlib.sha256(payload).hexdigest()}\n",
            encoding="utf-8",
        )
    print(f"generated {len(skills)} Claude skill mirrors under {MIRROR.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(sync())
