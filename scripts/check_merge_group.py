#!/usr/bin/env python3
"""Validate merge-queue trigger coverage when rulesets enable merge queue.

GitHub merge queue evaluates required status checks on the synthetic
`merge_group` event. If a ruleset enables merge queue, this script ensures the
self-CI workflow that publishes the required `ci-gate` check also listens for
`merge_group`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from _workflow_yaml import get_on, load_yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
RULESETS_DIR = REPO_ROOT / ".github" / "rulesets"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _ruleset_has_merge_queue(doc: dict[str, Any]) -> bool:
    return any(rule.get("type") == "merge_queue" for rule in doc.get("rules", []) if isinstance(rule, dict))


def _events(path: Path) -> set[str]:
    raw = get_on(load_yaml(path))
    if isinstance(raw, str):
        return {raw}
    if isinstance(raw, list):
        return {str(item) for item in raw}
    if isinstance(raw, dict):
        return {str(key) for key in raw}
    return set()


def check() -> list[str]:
    problems: list[str] = []
    merge_queue_enabled = False
    for path in sorted(RULESETS_DIR.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if _ruleset_has_merge_queue(doc):
            merge_queue_enabled = True
    if merge_queue_enabled and "merge_group" not in _events(CI_WORKFLOW):
        problems.append("ci.yml must include `merge_group` when a ruleset enables merge_queue")
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_merge_group: FAIL")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("check_merge_group: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
