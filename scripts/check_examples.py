#!/usr/bin/env python3
"""Validate copy-paste caller workflow examples.

Examples are part of the public contract: they must parse as GitHub Actions
YAML, keep least-privilege permissions, and use either the documented `@<sha>`
placeholder or a full-SHA reusable workflow reference.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from _workflow_yaml import get_on, load_yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"
USES_RE = re.compile(
    r"^NDDev-it-com/ci-workflows/\.github/workflows/[^@]+\.ya?ml@(<sha>|[0-9a-f]{40})$"
)


def _events(doc: dict[str, Any]) -> set[str]:
    raw = get_on(doc)
    if isinstance(raw, str):
        return {raw}
    if isinstance(raw, list):
        return {str(item) for item in raw}
    if isinstance(raw, dict):
        return {str(key) for key in raw}
    return set()


def check() -> list[str]:
    problems: list[str] = []
    if not EXAMPLES_DIR.is_dir():
        return [f"missing examples directory: {EXAMPLES_DIR}"]

    for path in sorted(EXAMPLES_DIR.rglob("*.yml")):
        rel = str(path.relative_to(REPO_ROOT))
        doc = load_yaml(path)
        if not isinstance(doc, dict):
            problems.append(f"{rel}: example is not a mapping")
            continue
        events = _events(doc)
        if "pull_request_target" in events:
            problems.append(f"{rel}: canonical examples must not use pull_request_target")
        if "permissions" not in doc:
            problems.append(f"{rel}: missing top-level permissions")
        jobs = doc.get("jobs", {}) or {}
        if not jobs:
            problems.append(f"{rel}: missing jobs")
        for job_id, job in jobs.items():
            if not isinstance(job, dict):
                problems.append(f"{rel}: job `{job_id}` is not a mapping")
                continue
            if "permissions" not in job:
                problems.append(f"{rel}: job `{job_id}` missing permissions")
            uses = str(job.get("uses", ""))
            if uses and not USES_RE.match(uses):
                problems.append(f"{rel}: job `{job_id}` reusable ref is not @<sha> or full SHA: {uses}")
        if rel.endswith("scorecard.yml") and events != {"push", "schedule"}:
            problems.append(f"{rel}: Scorecard example must use only push + schedule")
        if rel == "examples/private-free/security.yml":
            for job_id, job in jobs.items():
                perms = job.get("permissions", {}) if isinstance(job, dict) else {}
                if isinstance(perms, dict) and "security-events" in perms:
                    problems.append(f"{rel}: private-free job `{job_id}` must not request security-events")
            text = path.read_text(encoding="utf-8")
            if "zizmor-no-sarif.yml" not in text:
                problems.append(f"{rel}: private-free security must use zizmor-no-sarif.yml")
            if "enable_harden_runner" in text:
                problems.append(
                    f"{rel}: private-free callers must use workflows that contain "
                    "no Harden-Runner action, not the unsafe legacy step toggle"
                )
        if rel.endswith("dependency-review.yml") and events != {"pull_request"}:
            problems.append(f"{rel}: dependency-review example must use pull_request only")
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_examples: FAIL")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("check_examples: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
