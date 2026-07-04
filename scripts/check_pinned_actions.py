#!/usr/bin/env python3
"""Every third-party `uses:` must be pinned to a full 40-char commit SHA with a
version comment. Local reusable calls (`./.github/...`) are exempt.
"""
from __future__ import annotations

import re
import sys

from _workflow_yaml import workflow_files

# `uses: owner/repo[/path]@<40-hex>  # vX.Y.Z`
USES_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*(?P<ref>\S+)(?P<rest>.*)$")
SHA_RE = re.compile(r"@[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"@sha256:[0-9a-f]{64}$")


def check() -> list[str]:
    problems: list[str] = []
    for path in workflow_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            m = USES_RE.match(line)
            if not m:
                continue
            ref = m.group("ref").strip().strip("'\"")
            rest = m.group("rest")
            where = f"{path.name}:{lineno}"
            if ref.startswith("./"):
                continue  # local reusable workflow
            if ref.startswith("docker://"):
                if not DIGEST_RE.search(ref):
                    problems.append(f"{where}: docker image not digest-pinned: {ref}")
                continue
            if "@" not in ref:
                problems.append(f"{where}: action not pinned (no @ref): {ref}")
                continue
            if not SHA_RE.search(ref):
                problems.append(f"{where}: action not pinned to a 40-char SHA: {ref}")
                continue
            if "#" not in rest:
                problems.append(f"{where}: SHA pin missing a `# vX.Y.Z` version comment: {ref}")
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_pinned_actions: FAIL", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print("check_pinned_actions: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
