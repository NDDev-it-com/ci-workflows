#!/usr/bin/env python3
"""Runner-contract regression checks for the actionlint workflow.

actionlint.yml downloads the upstream linux_amd64 tarball, verifies it with
sha256sum, and installs into /usr/local/bin, so its reusable interface is
honest only for Linux X64 runners. The workflow's first step must be an
explicit guard that rejects every other OS/architecture before the download;
this validator extracts that guard program and executes it against a
supported/unsupported runner matrix.
"""

from __future__ import annotations

import re
import subprocess
import sys
from typing import Any

from _workflow_yaml import WORKFLOWS_DIR, get_on, load_yaml
from check_python_execution_contract import clean_environment

ACTIONLINT = WORKFLOWS_DIR / "actionlint.yml"
GUARD_ENV_KEYS = {"ACTIONLINT_RUNNER_OS", "ACTIONLINT_RUNNER_ARCH"}
SUPPORTED = (("Linux", "X64"),)
UNSUPPORTED = (
    ("Linux", "ARM64"),
    ("macOS", "X64"),
    ("macOS", "ARM64"),
    ("Windows", "X64"),
    ("Windows", "ARM64"),
)


def _job(workflow: dict[str, Any], job_id: str) -> dict[str, Any]:
    jobs = workflow.get("jobs", {})
    job = jobs.get(job_id, {}) if isinstance(jobs, dict) else {}
    return job if isinstance(job, dict) else {}


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    steps = job.get("steps", [])
    if not isinstance(steps, list):
        return []
    return [step for step in steps if isinstance(step, dict)]


def _embedded_python(step: dict[str, Any] | None) -> str:
    if not isinstance(step, dict) or not isinstance(step.get("run"), str):
        raise ValueError("step has no run program")
    lines = step["run"].splitlines()
    starts = [
        index
        for index, line in enumerate(lines)
        if re.search(r"\bpython3\s+-I\s+<<'PY'$", line.strip())
    ]
    if len(starts) != 1:
        raise ValueError(f"expected one isolated Python heredoc, found {len(starts)}")
    start = starts[0] + 1
    try:
        end = next(index for index in range(start, len(lines)) if lines[index] == "PY")
    except StopIteration as exc:
        raise ValueError("isolated Python heredoc is not terminated") from exc
    return "\n".join(lines[start:end]) + "\n"


def _run_guard(program: str, runner_os: str, runner_arch: str) -> int:
    env = clean_environment({
        "ACTIONLINT_RUNNER_OS": runner_os,
        "ACTIONLINT_RUNNER_ARCH": runner_arch,
    })
    return subprocess.run(
        [sys.executable, "-I", "-"],
        input=program,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    ).returncode


def check() -> list[str]:
    problems: list[str] = []
    workflow = load_yaml(ACTIONLINT)
    text = ACTIONLINT.read_text(encoding="utf-8")

    if "linux_amd64" not in text:
        problems.append(
            "actionlint.yml no longer downloads linux_amd64; update the runner "
            "contract guard and this validator together"
        )

    on = get_on(workflow)
    call = on.get("workflow_call", {}) if isinstance(on, dict) else {}
    inputs = call.get("inputs", {}) if isinstance(call, dict) else {}
    runner_input = inputs.get("runner", {}) if isinstance(inputs, dict) else {}
    description = (
        runner_input.get("description", "") if isinstance(runner_input, dict) else ""
    )
    if "Linux X64" not in str(description):
        problems.append(
            "actionlint.yml: the runner input description must state the "
            "Linux X64 contract"
        )

    job = _job(workflow, "actionlint")
    steps = _steps(job)
    if not steps or steps[0].get("name") != "Validate runner contract":
        problems.append(
            "actionlint.yml: the runner-contract guard must be the first step, "
            "before any download"
        )
        return problems
    guard = steps[0]
    if guard.get("shell") != "bash":
        problems.append(
            "actionlint.yml: the guard must pin shell: bash so it fails with a "
            "clear message on non-Linux runners"
        )
    env = guard.get("env", {})
    if not isinstance(env, dict) or set(env) != GUARD_ENV_KEYS:
        problems.append(
            "actionlint.yml: the guard must read runner.os/runner.arch via "
            + " and ".join(sorted(GUARD_ENV_KEYS))
        )

    try:
        program = _embedded_python(guard)
    except ValueError as exc:
        problems.append(f"actionlint guard extraction failed: {exc}")
        return problems

    for runner_os, runner_arch in SUPPORTED:
        if _run_guard(program, runner_os, runner_arch) != 0:
            problems.append(
                f"actionlint guard rejected the supported {runner_os}/{runner_arch} runner"
            )
    for runner_os, runner_arch in UNSUPPORTED:
        if _run_guard(program, runner_os, runner_arch) == 0:
            problems.append(
                f"actionlint guard accepted the unsupported {runner_os}/{runner_arch} "
                "runner although the workflow downloads a linux_amd64 binary"
            )
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_actionlint_contract: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("check_actionlint_contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
