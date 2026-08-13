#!/usr/bin/env python3
"""Fail-closed regression checks for the monorepo changed-paths router.

The router runs in the caller checkout, so its base-resolution and matching
logic is embedded in workflow YAML. This validator extracts that exact Python
program and exercises it against hermetic temporary Git repositories: invalid
bases must fail the run, uncertain push bases must conservatively report every
group as changed, and the strict no-wildcard filter language must hold its
boundary semantics.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from ci_workflows_tools._workflow_yaml import WORKFLOWS_DIR, load_yaml
from ci_workflows_tools.check_python_execution_contract import clean_environment

ROUTER = WORKFLOWS_DIR / "monorepo-changed-paths.yml"
ZERO_BEFORE = "0" * 40
UNREACHABLE_BEFORE = "1" * 40
EXPECTED_ENV_KEYS = {
    "FILTERS",
    "BASE_REF",
    "EVENT_NAME",
    "PR_BASE_SHA",
    "MERGE_GROUP_BASE_SHA",
    "PUSH_BEFORE",
}


def _detect_step(workflow: dict[str, Any]) -> dict[str, Any] | None:
    jobs = workflow.get("jobs", {})
    job = jobs.get("changes", {}) if isinstance(jobs, dict) else {}
    steps = job.get("steps", []) if isinstance(job, dict) else []
    if not isinstance(steps, list):
        return None
    for step in steps:
        if isinstance(step, dict) and step.get("id") == "detect":
            return step
    return None


def _embedded_python(step: dict[str, Any] | None) -> str:
    if not isinstance(step, dict) or not isinstance(step.get("run"), str):
        raise ValueError("detect step has no run program")
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


def _run(
    command: list[str], *, cwd: Path, env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    process_env = clean_environment(env)
    return subprocess.run(
        command,
        cwd=cwd,
        env=process_env,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _git(root: Path, *args: str) -> str:
    result = _run(["git", *args], cwd=root)
    if result.returncode != 0:
        raise RuntimeError(
            f"fixture git {' '.join(args)} failed: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _init_repo(root: Path) -> None:
    _git(root, "init", "--quiet", "-b", "main")
    _git(root, "config", "user.name", "Routing Validator")
    _git(root, "config", "user.email", "routing-validator@example.invalid")


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _commit(root: Path, message: str) -> str:
    _git(root, "add", "--all")
    _git(root, "commit", "-qm", message)
    return _git(root, "rev-parse", "HEAD")


def _route(
    program: str,
    root: Path,
    scratch: Path,
    filters: Any,
    **env_overrides: str,
) -> tuple[int, dict[str, Any] | None, str]:
    output_file = tempfile.NamedTemporaryFile(
        dir=scratch, prefix="gh-output-", delete=False
    )
    summary_file = tempfile.NamedTemporaryFile(
        dir=scratch, prefix="gh-summary-", delete=False
    )
    output_file.close()
    summary_file.close()
    env = {
        "FILTERS": filters if isinstance(filters, str) else json.dumps(filters),
        "BASE_REF": "",
        "EVENT_NAME": "push",
        "PR_BASE_SHA": "",
        "MERGE_GROUP_BASE_SHA": "",
        "PUSH_BEFORE": "",
        "GITHUB_OUTPUT": output_file.name,
        "GITHUB_STEP_SUMMARY": summary_file.name,
    }
    env.update(env_overrides)
    completed = _run(
        [sys.executable, "-I", "-"], cwd=root, env=env, input_text=program
    )
    parsed: dict[str, Any] | None = None
    if completed.returncode == 0:
        for line in Path(output_file.name).read_text(encoding="utf-8").splitlines():
            if line.startswith("result="):
                parsed = json.loads(line.removeprefix("result="))
    return completed.returncode, parsed, completed.stderr.strip()


def _expect_result(
    problems: list[str],
    label: str,
    outcome: tuple[int, dict[str, Any] | None, str],
    expected: dict[str, bool],
) -> None:
    returncode, parsed, stderr = outcome
    if returncode != 0:
        problems.append(f"routing fixture failed unexpectedly: {label}: {stderr}")
    elif parsed != expected:
        problems.append(f"routing fixture {label}: got {parsed}, want {expected}")


def _expect_failure(
    problems: list[str], label: str, outcome: tuple[int, dict[str, Any] | None, str]
) -> None:
    if outcome[0] == 0:
        problems.append(f"routing fixture unexpectedly passed: {label}")


def _check_static(problems: list[str]) -> dict[str, Any] | None:
    workflow = load_yaml(ROUTER)
    text = ROUTER.read_text(encoding="utf-8")
    step = _detect_step(workflow)
    if step is None:
        problems.append("router detect step is missing")
        return None
    run = step.get("run", "")
    if "|| true" in run:
        problems.append("router must not suppress git failures with `|| true`")
    for line_number, line in enumerate(text.splitlines(), start=1):
        if "python3" in line and re.search(r"\bpython3\s+(?!-I\b)", line):
            problems.append(
                f"{ROUTER.name}:{line_number}: embedded Python must use isolated mode (-I)"
            )
    env = step.get("env", {})
    if not isinstance(env, dict) or set(env) != EXPECTED_ENV_KEYS:
        problems.append(
            "router detect env must expose exactly "
            + ", ".join(sorted(EXPECTED_ENV_KEYS))
        )
    jobs = workflow.get("jobs", {})
    job = jobs.get("changes", {}) if isinstance(jobs, dict) else {}
    steps = job.get("steps", []) if isinstance(job, dict) else []
    checkout = next(
        (
            candidate
            for candidate in steps
            if isinstance(candidate, dict)
            and str(candidate.get("uses", "")).startswith("actions/checkout@")
        ),
        None,
    )
    checkout_with = checkout.get("with", {}) if isinstance(checkout, dict) else {}
    if not isinstance(checkout_with, dict) or checkout_with.get("fetch-depth") != 0:
        problems.append("router checkout must use fetch-depth: 0")
    if isinstance(checkout_with, dict) and checkout_with.get(
        "persist-credentials"
    ) is not False:
        problems.append("router checkout must not persist credentials")
    return step


def check() -> list[str]:
    problems: list[str] = []
    step = _check_static(problems)
    if step is None:
        return problems
    try:
        program = _embedded_python(step)
    except ValueError as exc:
        problems.append(f"router embedded-program extraction failed: {exc}")
        return problems

    two_groups = {"api": ["services/api/"], "docs": ["README.md"]}
    three_groups = {
        "api": ["services/api/"],
        "docs": ["README.md"],
        "web": ["apps/web/"],
    }

    with tempfile.TemporaryDirectory(prefix="nddev-routing-") as raw_scratch:
        scratch = Path(raw_scratch)

        # Fixture A: linear history c0 -> c1 (README) -> c2 (services/api).
        linear = scratch / "linear"
        linear.mkdir()
        _init_repo(linear)
        _write(linear, "README.md", "v0\n")
        _write(linear, "services/api/app.txt", "v0\n")
        _write(linear, "pyproject.toml", "[project]\n")
        _write(linear, "pyproject.toml.bak", "stale\n")
        c0 = _commit(linear, "c0")
        _write(linear, "README.md", "v1\n")
        c1 = _commit(linear, "c1: docs")
        _write(linear, "services/api/app.txt", "v1\n")
        _commit(linear, "c2: api")

        _expect_failure(
            problems,
            "explicit-base/invalid",
            _route(program, linear, scratch, two_groups, BASE_REF="deadbeef"),
        )
        _expect_result(
            problems,
            "explicit-base/valid",
            _route(program, linear, scratch, two_groups, BASE_REF=c0),
            {"api": True, "docs": True},
        )
        _expect_result(
            problems,
            "push/zero-before-branch-creation",
            _route(
                program, linear, scratch, three_groups,
                EVENT_NAME="push", PUSH_BEFORE=ZERO_BEFORE,
            ),
            {"api": True, "docs": True, "web": True},
        )
        _expect_result(
            problems,
            "push/unreachable-before-force-push",
            _route(
                program, linear, scratch, three_groups,
                EVENT_NAME="push", PUSH_BEFORE=UNREACHABLE_BEFORE,
            ),
            {"api": True, "docs": True, "web": True},
        )
        _expect_result(
            problems,
            "push/multi-commit-covers-earlier-commits",
            _route(
                program, linear, scratch, two_groups,
                EVENT_NAME="push", PUSH_BEFORE=c0,
            ),
            {"api": True, "docs": True},
        )
        _expect_result(
            problems,
            "push/single-commit-exact",
            _route(
                program, linear, scratch, two_groups,
                EVENT_NAME="push", PUSH_BEFORE=c1,
            ),
            {"api": True, "docs": False},
        )
        _expect_result(
            problems,
            "event/no-base-conservative",
            _route(program, linear, scratch, two_groups, EVENT_NAME="schedule"),
            {"api": True, "docs": True},
        )
        _expect_failure(
            problems,
            "pull-request/missing-base",
            _route(program, linear, scratch, two_groups, EVENT_NAME="pull_request"),
        )
        # pull_request_target must be rejected even with a resolvable base and a
        # valid explicit base_ref: under that event GitHub checks out the base
        # branch, so the router can never see the PR and must never report a
        # green all-false. Both forms fail closed.
        _expect_failure(
            problems,
            "pull-request-target/valid-base-still-rejected",
            _route(
                program, linear, scratch, two_groups,
                EVENT_NAME="pull_request_target", PR_BASE_SHA=c0,
            ),
        )
        _expect_failure(
            problems,
            "pull-request-target/explicit-base-ref-still-rejected",
            _route(
                program, linear, scratch, two_groups,
                EVENT_NAME="pull_request_target", BASE_REF=c0,
            ),
        )
        _expect_result(
            problems,
            "merge-group/base-sha",
            _route(
                program, linear, scratch, two_groups,
                EVENT_NAME="merge_group", MERGE_GROUP_BASE_SHA=c0,
            ),
            {"api": True, "docs": True},
        )
        _expect_failure(
            problems,
            "merge-group/missing-base",
            _route(program, linear, scratch, two_groups, EVENT_NAME="merge_group"),
        )

        for label, filters in (
            ("filters/wildcard-star", {"src": ["src*"]}),
            ("filters/wildcard-globstar", {"src": ["src/**"]}),
            ("filters/yaml-not-json", "src:\n  - 'src/**'\n"),
            ("filters/empty-object", {}),
            ("filters/empty-group", {"src": []}),
            ("filters/bad-group-name", {"bad name": ["src/"]}),
            ("filters/traversal", {"src": ["../src/"]}),
            ("filters/absolute", {"src": ["/src/"]}),
            ("filters/empty-pattern", {"src": [""]}),
        ):
            _expect_failure(
                problems, label, _route(program, linear, scratch, filters)
            )

        # Fixture B: prefix-boundary and exact-file semantics.
        boundary = scratch / "boundary"
        boundary.mkdir()
        _init_repo(boundary)
        _write(boundary, "src/one.txt", "v0\n")
        _write(boundary, "src-old/two.txt", "v0\n")
        _write(boundary, "pyproject.toml", "[project]\n")
        _write(boundary, "pyproject.toml.bak", "stale\n")
        b0 = _commit(boundary, "b0")
        _write(boundary, "src-old/two.txt", "v1\n")
        _write(boundary, "pyproject.toml.bak", "still stale\n")
        b1 = _commit(boundary, "b1: outside the boundary")
        _expect_result(
            problems,
            "boundary/src-does-not-match-src-old",
            _route(
                program, boundary, scratch,
                {"src": ["src/"], "cfg": ["pyproject.toml"]},
                EVENT_NAME="push", PUSH_BEFORE=b0,
            ),
            {"src": False, "cfg": False},
        )
        _write(boundary, "src/one.txt", "v1\n")
        _write(boundary, "pyproject.toml", "[project]\n# touched\n")
        _commit(boundary, "b2: inside the boundary")
        _expect_result(
            problems,
            "boundary/inside-matches",
            _route(
                program, boundary, scratch,
                {"src": ["src/"], "cfg": ["pyproject.toml"]},
                EVENT_NAME="push", PUSH_BEFORE=b1,
            ),
            {"src": True, "cfg": True},
        )

        # Fixture C: pull request merge-base semantics.
        fork = scratch / "fork"
        fork.mkdir()
        _init_repo(fork)
        _write(fork, "README.md", "v0\n")
        _write(fork, "services/api/app.txt", "v0\n")
        _commit(fork, "f0")
        _git(fork, "checkout", "-q", "-b", "feature")
        _write(fork, "services/api/app.txt", "feature\n")
        _commit(fork, "f1: api on feature")
        _git(fork, "checkout", "-q", "main")
        _write(fork, "README.md", "mainline\n")
        main_tip = _commit(fork, "f2: docs on main after branch point")
        _git(fork, "checkout", "-q", "feature")
        _expect_result(
            problems,
            "pull-request/merge-base-ignores-post-branch-main-changes",
            _route(
                program, fork, scratch, two_groups,
                EVENT_NAME="pull_request", PR_BASE_SHA=main_tip,
            ),
            {"api": True, "docs": False},
        )

        # Fixture D: renames, deletions, and unusual filenames.
        churn = scratch / "churn"
        churn.mkdir()
        _init_repo(churn)
        _write(churn, "docs/a.md", "v0\n")
        _write(churn, "docs/has space.md", "v0\n")
        _write(churn, "services/api/app.txt", "v0\n")
        d0 = _commit(churn, "d0")
        (churn / "guides").mkdir()
        (churn / "docs" / "a.md").rename(churn / "guides" / "a.md")
        d1 = _commit(churn, "d1: rename docs -> guides")
        _expect_result(
            problems,
            "churn/rename-marks-both-sides",
            _route(
                program, churn, scratch,
                {"docs": ["docs/"], "guides": ["guides/"]},
                EVENT_NAME="push", PUSH_BEFORE=d0,
            ),
            {"docs": True, "guides": True},
        )
        (churn / "services/api/app.txt").unlink()
        _write(churn, "docs/has space.md", "v1\n")
        _commit(churn, "d2: delete api, touch spaced filename")
        _expect_result(
            problems,
            "churn/delete-and-space-filename",
            _route(
                program, churn, scratch,
                {"api": ["services/api/"], "docs": ["docs/"]},
                EVENT_NAME="push", PUSH_BEFORE=d1,
            ),
            {"api": True, "docs": True},
        )

    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_monorepo_routing: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("check_monorepo_routing: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
