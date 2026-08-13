#!/usr/bin/env python3
"""Privileged-event guard contract.

A reusable workflow that accepts a caller-supplied ``checkout_ref`` hands the
choice of checked-out code to its caller. That is safe on ``pull_request``,
where the job runs with a read-only token and no secrets, and unsafe on a
privileged event such as ``pull_request_target`` or ``workflow_run``, where the
job holds the caller's write token and secrets. Because a reusable workflow
inherits the caller's ``github`` context, it can detect that itself instead of
delegating the rule to prose.

This validator enforces that every workflow exposing ``checkout_ref``:

* declares the guard as the **first** step of every job that checks out, so no
  step can run before the refusal;
* refuses the full privileged-event set (fail closed, no opt-out input);
* reads its inputs through the environment, never ``${{ }}`` interpolation
  inside ``run:``.

It then **executes** the extracted guard body against an accept/reject matrix,
so the contract is proven by behaviour rather than by pattern matching.
"""
from __future__ import annotations

import subprocess
import sys

from _workflow_yaml import get_on, load_yaml, workflow_files
from check_python_execution_contract import clean_environment

GUARD_STEP_NAME = "Reject caller-supplied ref on a privileged event"

# Events that run with the base repository's token and secrets while being
# triggered by content an outside contributor controls.
PRIVILEGED_EVENTS = (
    "pull_request_target",
    "workflow_run",
    "issue_comment",
    "issues",
    "discussion",
    "discussion_comment",
)

# Events that legitimately combine a caller-supplied ref with a safe token.
SAFE_EVENTS = ("pull_request", "push", "workflow_dispatch", "schedule", "merge_group")


def _guarded_workflows() -> list[tuple[str, dict]]:
    """Every reusable workflow that exposes a ``checkout_ref`` input."""
    found: list[tuple[str, dict]] = []
    for path in workflow_files():
        doc = load_yaml(path)
        on = get_on(doc)
        if not isinstance(on, dict):
            continue
        call = on.get("workflow_call")
        if not isinstance(call, dict):
            continue
        inputs = call.get("inputs")
        if isinstance(inputs, dict) and "checkout_ref" in inputs:
            found.append((path.name, doc))
    return found


def _run_guard(body: str, event: str, ref: str) -> int:
    """Execute the extracted guard body the way the runner would."""
    completed = subprocess.run(
        ["bash", "-c", body],
        env=clean_environment({
            "PATH": "/usr/bin:/bin", "CALLER_EVENT": event, "CHECKOUT_REF": ref,
        }),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.returncode


def check() -> list[str]:
    problems: list[str] = []
    guarded = _guarded_workflows()

    if not guarded:
        problems.append(
            "no workflow exposes `checkout_ref`; delete this validator or restore "
            "the guarded workflows"
        )
        return problems

    for name, doc in guarded:
        jobs = doc.get("jobs", {}) or {}
        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                continue
            steps = job.get("steps") or []
            checks_out = any(
                isinstance(s, dict) and str(s.get("uses", "")).startswith("actions/checkout@")
                for s in steps
            )
            if not checks_out:
                continue

            if not steps or not isinstance(steps[0], dict):
                problems.append(f"{name}: job {job_name!r} has no steps to guard")
                continue

            first = steps[0]
            if first.get("name") != GUARD_STEP_NAME:
                problems.append(
                    f"{name}: job {job_name!r} must start with the step "
                    f"{GUARD_STEP_NAME!r}, found {first.get('name')!r}"
                )
                continue

            env = first.get("env") or {}
            if env.get("CALLER_EVENT") != "${{ github.event_name }}":
                problems.append(
                    f"{name}: guard must read the caller event via the "
                    "CALLER_EVENT environment variable"
                )
            if env.get("CHECKOUT_REF") != "${{ inputs.checkout_ref }}":
                problems.append(
                    f"{name}: guard must read the ref via the CHECKOUT_REF "
                    "environment variable"
                )

            body = first.get("run") or ""
            if "${{" in body:
                problems.append(
                    f"{name}: guard `run:` must not interpolate ${{{{ }}}}; "
                    "use environment indirection"
                )
                continue
            if first.get("shell") != "bash":
                problems.append(
                    f"{name}: guard must pin `shell: bash` so it behaves "
                    "identically on Linux, macOS, and Windows runners"
                )

            # Behavioural proof: the guard must reject every privileged event
            # that carries a ref, and must let every safe combination through.
            for event in PRIVILEGED_EVENTS:
                if _run_guard(body, event, "refs/pull/1/head") == 0:
                    problems.append(
                        f"{name}: guard accepted checkout_ref on privileged "
                        f"event {event!r}"
                    )
                if _run_guard(body, event, "") != 0:
                    problems.append(
                        f"{name}: guard rejected event {event!r} with no "
                        "checkout_ref; the default checkout stays legitimate"
                    )
            for event in SAFE_EVENTS:
                if _run_guard(body, event, "refs/pull/1/head") != 0:
                    problems.append(
                        f"{name}: guard rejected checkout_ref on safe event {event!r}"
                    )

    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_privileged_ref_guard: FAIL", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print("check_privileged_ref_guard: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
