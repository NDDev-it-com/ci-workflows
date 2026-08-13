#!/usr/bin/env python3
"""Least-privilege contract for the split benchmark lanes.

benchmark.yml is the history-publishing lane (`contents: write`, with
`auto-push` enabled only for branch-backed history); benchmark-compare.yml is the read-only lane
(`contents: read`, `auto-push: false`) whose job-scoped GITHUB_TOKEN cannot
write. The two lanes must stay byte-parallel except for that one
publish/compare difference, so a future edit cannot silently reintroduce a
write-capable token into the compare path.
"""

from __future__ import annotations

import sys
from typing import Any

from _workflow_yaml import WORKFLOWS_DIR, get_on, load_yaml

BENCHMARK = WORKFLOWS_DIR / "benchmark.yml"
BENCHMARK_COMPARE = WORKFLOWS_DIR / "benchmark-compare.yml"
GITHUB_TOKEN_EXPR = "${{ secrets.GITHUB_TOKEN }}"
PUBLISH_AUTO_PUSH_EXPR = "${{ inputs.external_data_json_path == '' }}"


def _job(workflow: dict[str, Any], job_id: str) -> dict[str, Any]:
    jobs = workflow.get("jobs", {})
    job = jobs.get(job_id, {}) if isinstance(jobs, dict) else {}
    return job if isinstance(job, dict) else {}


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    steps = job.get("steps", [])
    if not isinstance(steps, list):
        return []
    return [step for step in steps if isinstance(step, dict)]


def _inputs(workflow: dict[str, Any]) -> Any:
    on = get_on(workflow)
    if not isinstance(on, dict):
        return None
    call = on.get("workflow_call", {})
    return call.get("inputs") if isinstance(call, dict) else None


def check() -> list[str]:
    problems: list[str] = []
    publish = load_yaml(BENCHMARK)
    compare = load_yaml(BENCHMARK_COMPARE)

    for path in (BENCHMARK, BENCHMARK_COMPARE):
        if "auto_push" in path.read_text(encoding="utf-8"):
            problems.append(
                f"{path.name}: the auto_push toggle was split into publish/compare "
                "lanes and must not reappear"
            )

    publish_job = _job(publish, "benchmark")
    compare_job = _job(compare, "benchmark")
    if publish_job.get("permissions") != {"contents": "write"}:
        problems.append(
            "benchmark.yml: publish lane must request exactly `contents: write`"
        )
    if compare_job.get("permissions") != {"contents": "read"}:
        problems.append(
            "benchmark-compare.yml: compare lane must request exactly "
            "`contents: read` so the job token cannot write"
        )

    if _inputs(publish) != _inputs(compare):
        problems.append("benchmark lanes must expose identical workflow_call inputs")

    publish_steps = _steps(publish_job)
    compare_steps = _steps(compare_job)
    publish_names = [step.get("name") for step in publish_steps]
    compare_names = [step.get("name") for step in compare_steps]
    if publish_names != compare_names or "Compare and alert" not in publish_names:
        problems.append("benchmark lanes must run the same step sequence")
        return problems

    for publish_step, compare_step in zip(publish_steps, compare_steps):
        name = publish_step.get("name")
        if name != "Compare and alert":
            if publish_step != compare_step:
                problems.append(
                    f"benchmark lane step drifted between publish and compare: {name}"
                )
            continue
        publish_with = publish_step.get("with", {})
        compare_with = compare_step.get("with", {})
        if not isinstance(publish_with, dict) or not isinstance(compare_with, dict):
            problems.append("benchmark Compare and alert steps are malformed")
            continue
        if publish_with.get("auto-push") != PUBLISH_AUTO_PUSH_EXPR:
            problems.append(
                "benchmark.yml: publish lane must auto-push only when file-backed "
                "history is disabled"
            )
        if compare_with.get("auto-push") is not False:
            problems.append(
                "benchmark-compare.yml: compare lane must set auto-push: false"
            )
        for lane, with_block in (("publish", publish_with), ("compare", compare_with)):
            if with_block.get("github-token") != GITHUB_TOKEN_EXPR:
                problems.append(
                    f"benchmark {lane} lane must pass the workflow GITHUB_TOKEN "
                    "(scoped by its job permissions), not another credential"
                )
            if with_block.get("comment-on-alert") is not False:
                problems.append(
                    f"benchmark {lane} lane must keep comment-on-alert: false"
                )
        stripped_publish = {
            key: value for key, value in publish_with.items() if key != "auto-push"
        }
        stripped_compare = {
            key: value for key, value in compare_with.items() if key != "auto-push"
        }
        if stripped_publish != stripped_compare:
            problems.append(
                "benchmark Compare and alert steps may differ only in auto-push"
            )
        remainder_publish = {
            key: value for key, value in publish_step.items() if key != "with"
        }
        remainder_compare = {
            key: value for key, value in compare_step.items() if key != "with"
        }
        if remainder_publish != remainder_compare:
            problems.append(
                "benchmark Compare and alert step metadata drifted between lanes"
            )
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_benchmark_contract: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("check_benchmark_contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
