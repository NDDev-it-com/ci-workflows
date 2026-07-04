#!/usr/bin/env python3
"""Check local Markdown links in repository docs.

External links are source citations and are validated by periodic research, not
by CI. This checker focuses on local link rot caused by renames and generated
docs drift.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

REPO_ROOT = Path(__file__).resolve().parent.parent
LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
DOC_ROOTS = ("README.md", "CONTRIBUTING.md", "SECURITY.md", "SUPPORT.md", "docs", "catalog", "examples")


def _markdown_files() -> list[Path]:
    files: list[Path] = []
    for root in DOC_ROOTS:
        path = REPO_ROOT / root
        if path.is_file() and path.suffix == ".md":
            files.append(path)
        elif path.is_dir():
            files.extend(sorted(path.rglob("*.md")))
    return sorted(set(files))


def _target_exists(source: Path, raw: str) -> bool:
    target = raw.split("#", 1)[0].strip()
    if not target or target.startswith(("http://", "https://", "mailto:")):
        return True
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    target = unquote(target)
    return (source.parent / target).resolve().exists()


def check() -> list[str]:
    problems: list[str] = []
    for path in _markdown_files():
        rel = path.relative_to(REPO_ROOT)
        text = path.read_text(encoding="utf-8")
        for match in LINK_RE.finditer(text):
            target = match.group(1)
            if not _target_exists(path, target):
                problems.append(f"{rel}: broken local markdown link: {target}")
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_docs_links: FAIL")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("check_docs_links: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
