"""Strict YAML loading for every canonical file in this repository.

``yaml.safe_load`` accepts a duplicate mapping key and silently keeps the last
value. In a repository whose whole design rests on "the catalog is the source of
truth", that is the worst possible failure mode: a merge or a hand edit can drop
a field, every validator stays green, and the generated docs quietly render the
surviving value.

This module is the single loader for catalogs, profiles, ledgers, workflows, and
skill frontmatter. A duplicate key is a hard error naming the file, the line, and
the key, so the malformed byte is rejected at parse time rather than surviving as
a plausible-looking value.

The workflow-specific helpers live in ``_workflow_yaml``; this module owns only
the parse.
"""
from __future__ import annotations

from collections.abc import Hashable
from pathlib import Path
from typing import Any

import yaml

# This module is the bottom of the dependency stack: `_workflow_yaml` imports it,
# so it must not import `_workflow_yaml` back. It previously reached into that
# module for REPO_ROOT from inside `check()`, which worked only because the
# import was deferred — CodeQL flagged the cycle, correctly. The constant is two
# lines of pathlib; duplicating it is cheaper than a cycle.
REPO_ROOT = Path(__file__).resolve().parent.parent

MERGE_TAG = "tag:yaml.org,2002:merge"


class DuplicateKeyError(ValueError):
    """A canonical YAML file repeated a mapping key."""


class StrictLoader(yaml.SafeLoader):
    """SafeLoader that refuses duplicate mapping keys."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        seen: set[Hashable] = set()
        for key_node, _ in node.value:
            if key_node.tag == MERGE_TAG:
                continue
            key = self.construct_object(key_node, deep=True)
            if not isinstance(key, Hashable):
                continue
            if key in seen:
                mark = key_node.start_mark
                origin = mark.name or "<yaml>"
                raise DuplicateKeyError(
                    f"{origin}:{mark.line + 1}: duplicate mapping key {key!r}; "
                    "a canonical file may not define a key twice"
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def strict_loads(text: str, origin: str = "<string>") -> Any:
    """Parse YAML text, rejecting duplicate mapping keys."""
    return yaml.load(_named(text, origin), Loader=StrictLoader)  # noqa: S506


def strict_load(path: Path) -> Any:
    """Parse a YAML file, rejecting duplicate mapping keys."""
    return strict_loads(path.read_text(encoding="utf-8"), str(path))


def _named(text: str, origin: str):
    """Wrap text so PyYAML reports ``origin`` in its marks."""
    import io

    stream = io.StringIO(text)
    stream.name = origin
    return stream


def check() -> list[str]:
    """Every canonical YAML file parses strictly."""
    problems: list[str] = []
    roots = [
        REPO_ROOT / "catalog",
        REPO_ROOT / ".github" / "workflows",
        REPO_ROOT / "examples",
        REPO_ROOT / ".github",
    ]
    seen: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.yml")) + sorted(root.rglob("*.yaml")):
            if path in seen:
                continue
            seen.add(path)
            try:
                strict_load(path)
            except DuplicateKeyError as exc:
                problems.append(str(exc).replace(f"{REPO_ROOT}/", ""))
            except yaml.YAMLError as exc:
                rel = path.relative_to(REPO_ROOT)
                problems.append(f"{rel}: is not parseable YAML: {exc}")
    problems += _selftest()
    return problems


def _selftest() -> list[str]:
    """The loader must reject a duplicate and accept a legitimate repeat."""
    problems: list[str] = []

    duplicate = "entries:\n  - workflow: a.yml\n    validator: x\n    validator: y\n"
    try:
        strict_loads(duplicate, "<fixture>")
    except DuplicateKeyError:
        pass
    else:
        problems.append(
            "strict-yaml selftest: a duplicate mapping key was accepted"
        )

    # The same key name under two different mappings is legitimate.
    distinct = "a:\n  validator: x\nb:\n  validator: y\n"
    try:
        parsed = strict_loads(distinct, "<fixture>")
    except DuplicateKeyError as exc:
        problems.append(f"strict-yaml selftest: rejected a legal document: {exc}")
    else:
        if parsed != {"a": {"validator": "x"}, "b": {"validator": "y"}}:
            problems.append("strict-yaml selftest: legal document parsed incorrectly")

    # A duplicate nested deep inside a sequence must still be caught.
    nested = "top:\n  - name: one\n    spec:\n      k: 1\n      k: 2\n"
    try:
        strict_loads(nested, "<fixture>")
    except DuplicateKeyError:
        pass
    else:
        problems.append("strict-yaml selftest: a nested duplicate key was accepted")

    return problems


def main() -> int:
    import sys

    problems = check()
    if problems:
        print("strict_yaml: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("strict_yaml: OK")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main())
