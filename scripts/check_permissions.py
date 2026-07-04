#!/usr/bin/env python3
"""Least-privilege hygiene: every workflow declares a top-level `permissions:`,
and every job declares `permissions:` and (for non-reusable-caller jobs) a
`timeout-minutes:`. Jobs that only call a reusable workflow (`uses:`) may omit
`timeout-minutes` (the reusable owns it) but must still declare `permissions`.
"""
from __future__ import annotations

import sys
from typing import Any

from _workflow_yaml import load_yaml, workflow_files


def check() -> list[str]:
    problems: list[str] = []
    for path in workflow_files():
        doc = load_yaml(path)
        name = path.name
        if "permissions" not in doc:
            problems.append(f"{name}: missing top-level `permissions:`")
        jobs: dict[str, Any] = doc.get("jobs", {}) or {}
        for job_id, job in jobs.items():
            if not isinstance(job, dict):
                continue
            calls_reusable = "uses" in job
            if "permissions" not in job:
                problems.append(f"{name}: job `{job_id}` missing `permissions:`")
            if not calls_reusable and "timeout-minutes" not in job:
                problems.append(f"{name}: job `{job_id}` missing `timeout-minutes:`")
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_permissions: FAIL", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print("check_permissions: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
