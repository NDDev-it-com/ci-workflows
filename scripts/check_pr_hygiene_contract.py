#!/usr/bin/env python3
"""Fail closed on PR-hygiene option normalization regressions."""
from __future__ import annotations

import copy
import sys
from typing import Any

from _workflow_yaml import WORKFLOWS_DIR, load_yaml

WORKFLOW = WORKFLOWS_DIR / "pr-hygiene.yml"


def validate(doc: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    jobs = doc.get("jobs") or {}
    commitlint = jobs.get("commitlint") if isinstance(jobs, dict) else None
    steps = commitlint.get("steps", []) if isinstance(commitlint, dict) else []
    by_name = {
        step.get("name"): step for step in steps if isinstance(step, dict)
    }
    normalize = by_name.get("Normalize commitlint configuration", {})
    action = by_name.get("commitlint", {})
    if normalize.get("id") != "commitlint_opts":
        problems.append("commitlint options must be normalized before the action")
    if (normalize.get("env") or {}).get("COMMITLINT_CONFIG") != \
            "${{ inputs.commitlint_config }}":
        problems.append("commitlint config input must cross the shell boundary via env")
    run = str(normalize.get("run", ""))
    for marker in ("[ -z \"$config_file\" ]", "./commitlint.config.mjs", "GITHUB_OUTPUT"):
        if marker not in run:
            problems.append(f"commitlint normalization missing marker {marker!r}")
    config_file = (action.get("with") or {}).get("configFile")
    if config_file != "${{ steps.commitlint_opts.outputs.config_file }}":
        problems.append("commitlint action must receive the normalized non-empty path")
    return problems


def check() -> list[str]:
    doc = load_yaml(WORKFLOW)
    problems = validate(doc)
    for label, mutate in (
        ("direct empty input", lambda d: next(
            step for step in d["jobs"]["commitlint"]["steps"]
            if step.get("name") == "commitlint"
        )["with"].update({"configFile": "${{ inputs.commitlint_config }}"})),
        ("missing empty fallback", lambda d: next(
            step for step in d["jobs"]["commitlint"]["steps"]
            if step.get("name") == "Normalize commitlint configuration"
        ).update({"run": "printf 'config_file=%s\\n' \"$COMMITLINT_CONFIG\" >>\"$GITHUB_OUTPUT\""})),
    ):
        candidate = copy.deepcopy(doc)
        mutate(candidate)
        if not validate(candidate):
            problems.append(f"negative probe accepted {label}")
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_pr_hygiene_contract: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("check_pr_hygiene_contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
