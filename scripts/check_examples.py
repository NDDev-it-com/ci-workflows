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
REUSABLE_RE = re.compile(
    r"^NDDev-it-com/ci-workflows/\.github/workflows/([^@]+\.ya?ml)@"
)
# Runner labels every GitHub account can resolve. Anything else is somebody's
# private fleet.
HOSTED_RUNNER_PREFIXES = ("ubuntu-", "macos-", "windows-")
# `examples/nddev/` is estate-specific by name and may name the NDDev fleet.
# Every other example is copy-paste material for a repository we do not own.
ESTATE_EXAMPLE_PREFIX = "examples/nddev/"


def _reusable_runner_default(uses: str) -> str | None:
    """The `runner` default of a locally-defined reusable, or None.

    Returns None when the reference is not a local reusable or exposes no
    `runner` input — in both cases the caller has nothing to choose.
    """
    match = REUSABLE_RE.match(uses)
    if not match:
        return None
    path = REPO_ROOT / ".github" / "workflows" / match.group(1)
    if not path.is_file():
        return None
    on_block = get_on(load_yaml(path))
    call = on_block.get("workflow_call") if isinstance(on_block, dict) else None
    inputs = (call or {}).get("inputs") if isinstance(call, dict) else None
    runner = (inputs or {}).get("runner") if isinstance(inputs, dict) else None
    if not isinstance(runner, dict):
        return None
    return str(runner.get("default", ""))


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
            # An example that omits `runner` inherits whatever the pinned
            # commit defaults to. Most reusables here default to the NDDev
            # self-hosted label, so a copied example either fails on a label
            # the copier does not own, or — worse, when the copier is inside
            # this estate and the repository is public — routes untrusted fork
            # code onto trusted infrastructure. The default is a property of
            # the pin, not of the example, so the example must state it.
            if not rel.startswith(ESTATE_EXAMPLE_PREFIX):
                default = _reusable_runner_default(uses)
                if default is not None and not default.startswith(HOSTED_RUNNER_PREFIXES):
                    with_values = job.get("with")
                    if not isinstance(with_values, dict) or "runner" not in with_values:
                        problems.append(
                            f"{rel}: job `{job_id}` must set `runner` explicitly — "
                            f"the reusable defaults to {default!r}, which is not a "
                            "hosted runner an arbitrary consumer can resolve"
                        )
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
