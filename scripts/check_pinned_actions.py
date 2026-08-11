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
# The comment must say *which release* the SHA is, because that is the only
# human-readable half of the pin: a reviewer diffing a Dependabot bump reads the
# comment, and a bare `#` or `# bumped` both satisfied the old presence-only
# test. Two accepted forms — a semantic version, or an ISO date for upstreams
# that publish no releases at all (`google/clusterfuzzlite`), where a date is
# the honest identifier rather than an invented version.
PIN_COMMENT_RE = re.compile(r"#\s*(v?\d+\.\d+(?:\.\d+)?[\w.+-]*|\d{4}-\d{2}-\d{2})\b")


def check() -> list[str]:
    problems: list[str] = _selftest()
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
            elif PIN_COMMENT_RE.search(rest) is None:
                problems.append(
                    f"{where}: SHA pin comment must name the release "
                    f"(`# vX.Y.Z`, or `# YYYY-MM-DD` for an upstream that tags no "
                    f"releases), got {rest.strip()!r}: {ref}"
                )
    return problems


def _selftest() -> list[str]:
    """Accept the real forms in this tree; reject a comment that says nothing."""
    problems: list[str] = []
    for good in ("  # v7.0.1", "  # v2.20.0", "  # 2024-09-19", "  # v0.36.0",
                 "  # v12.3114", "  # v4.1.1  (attest storage record)"):
        if PIN_COMMENT_RE.search(good) is None:
            problems.append(f"check_pinned_actions self-test: rejected {good.strip()!r}")
    for bad in ("  #", "  # bumped", "  # see PR", "  # latest", "  #  "):
        if PIN_COMMENT_RE.search(bad) is not None:
            problems.append(f"check_pinned_actions self-test: accepted {bad.strip()!r}")
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
