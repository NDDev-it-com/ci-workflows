#!/usr/bin/env python3
"""Enforce the public/private boundary for StepSecurity Harden-Runner.

Harden-Runner is a JavaScript action with pre and post entry points. GitHub can
execute those hooks even when the workflow step has a false ``if`` condition,
so a boolean input is not a valid way to make a reusable workflow private-free.
Only explicitly public/GHAS workflows may reference the action, and those
references must be unconditional and first in their job.
"""
from __future__ import annotations

import sys
from typing import Any

from _workflow_yaml import load_yaml, workflow_files

HARDEN_RUNNER = (
    "step-security/harden-runner@"
    "bf7454d06d71f1098171f2acdf0cd4708d7b5920"
)

HARDENED_WORKFLOWS = {
    "ci.yml",
    "maintenance.yml",
    "public-codeql.yml",
    "public-dependency-review.yml",
    "public-scorecard-json.yml",
    "public-scorecard.yml",
    "release.yml",
    "zizmor-sarif.yml",
}


def _steps(job: Any) -> list[Any]:
    if not isinstance(job, dict):
        return []
    steps = job.get("steps", [])
    return steps if isinstance(steps, list) else []


def check() -> list[str]:
    problems: list[str] = []
    seen_hardened: set[str] = set()

    for path in workflow_files():
        text = path.read_text(encoding="utf-8")
        if "enable_harden_runner" in text:
            problems.append(
                f"{path.name}: conditional Harden-Runner toggles are unsafe; "
                "split the public/GHAS and private-free contracts"
            )

        doc = load_yaml(path)
        jobs = doc.get("jobs", {})
        if not isinstance(jobs, dict):
            continue

        for job_id, job in jobs.items():
            for index, step in enumerate(_steps(job)):
                if not isinstance(step, dict):
                    continue
                uses = step.get("uses")
                if not isinstance(uses, str) or not uses.startswith(
                    "step-security/harden-runner@"
                ):
                    continue

                seen_hardened.add(path.name)
                where = f"{path.name}:jobs.{job_id}"
                if path.name not in HARDENED_WORKFLOWS:
                    problems.append(
                        f"{where}: private-free/cross-tier workflow must not "
                        "reference Harden-Runner"
                    )
                if uses != HARDEN_RUNNER:
                    problems.append(
                        f"{where}: Harden-Runner must use the audited v2.20.0 pin"
                    )
                if "if" in step:
                    problems.append(
                        f"{where}: Harden-Runner must not use a step-level `if`; "
                        "its pre/post hooks are independent of that condition"
                    )
                if index != 0:
                    problems.append(
                        f"{where}: Harden-Runner must be the first job step"
                    )

    missing = HARDENED_WORKFLOWS - seen_hardened
    for name in sorted(missing):
        problems.append(f"{name}: explicit public/GHAS workflow lost Harden-Runner")

    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_harden_runner_contract: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("check_harden_runner_contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
