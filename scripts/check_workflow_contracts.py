#!/usr/bin/env python3
"""Reusable-workflow contract: every workflow except the self workflows
(`ci.yml`, `release.yml`) must be reusable (`on: workflow_call`). The self
workflows must NOT be reusable, and `ci.yml` must expose the `ci-gate` job that
branch protection requires as a status check. Caller-provided command runners
must also fail on the first failing command instead of returning the status of
only the final command.
"""
from __future__ import annotations

import sys

from _workflow_yaml import SELF_WORKFLOWS, is_reusable, load_yaml, workflow_files


def check() -> list[str]:
    problems: list[str] = []
    for path in workflow_files():
        doc = load_yaml(path)
        reusable = is_reusable(doc)
        if path.name in SELF_WORKFLOWS:
            if reusable:
                problems.append(f"{path.name}: self workflow must not be `on: workflow_call`")
        elif not reusable:
            problems.append(f"{path.name}: reusable workflow missing `on: workflow_call`")

    ci = load_yaml((workflow_files()[0].parent / "ci.yml"))
    jobs = ci.get("jobs", {}) or {}
    if "ci-gate" not in jobs:
        problems.append("ci.yml: missing required `ci-gate` job (branch-protection status check)")

    private_static = load_yaml((workflow_files()[0].parent / "private-static.yml"))
    static_steps = private_static.get("jobs", {}).get("static", {}).get("steps", [])
    steps_by_name = {step.get("name"): step for step in static_steps if isinstance(step, dict)}
    fail_fast_commands = {
        "Run install command": 'bash -euo pipefail -c "$INSTALL_COMMAND"',
        "Run validation": 'bash -euo pipefail -c "$VALIDATION_COMMAND"',
    }
    for name, expected in fail_fast_commands.items():
        actual = steps_by_name.get(name, {}).get("run")
        if actual != expected:
            problems.append(
                f"private-static.yml: {name!r} must use the fail-fast runner {expected!r}"
            )
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_workflow_contracts: FAIL", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print("check_workflow_contracts: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
