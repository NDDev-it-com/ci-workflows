#!/usr/bin/env python3
"""Fail closed on PR-hygiene commitlint input regressions."""
from __future__ import annotations

import copy
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from _workflow_yaml import WORKFLOWS_DIR, get_on, load_yaml

WORKFLOW = WORKFLOWS_DIR / "pr-hygiene.yml"
DEFAULT_NAME = "commitlint (default configuration)"
EXPLICIT_NAME = "commitlint (explicit configuration)"
VALIDATE_NAME = "Validate explicit commitlint configuration"
ACTION = "wagoid/commitlint-github-action@b948419dd99f3fd78a6548d48f94e3df7f6bf3ed"


def _steps(doc: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = doc.get("jobs") or {}
    job = jobs.get("commitlint") if isinstance(jobs, dict) else None
    values = job.get("steps", []) if isinstance(job, dict) else []
    return [step for step in values if isinstance(step, dict)]


def _named(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(step.get("name")): step for step in _steps(doc)}


def validate(doc: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    by_name = _named(doc)
    validation = by_name.get(VALIDATE_NAME, {})
    default = by_name.get(DEFAULT_NAME, {})
    explicit = by_name.get(EXPLICIT_NAME, {})
    on = get_on(doc)
    workflow_call = on.get("workflow_call", {}) if isinstance(on, dict) else {}
    workflow_outputs = workflow_call.get("outputs", {}) \
        if isinstance(workflow_call, dict) else {}
    expected_workflow_outputs = {
        "labeler_new_labels": "${{ jobs.labeler.outputs.new_labels }}",
        "labeler_all_labels": "${{ jobs.labeler.outputs.all_labels }}",
    }
    for name, value in expected_workflow_outputs.items():
        if (workflow_outputs.get(name) or {}).get("value") != value:
            problems.append(f"workflow output {name} must expose the labeler output")

    if validation.get("if") != "${{ inputs.commitlint_config != '' }}":
        problems.append("explicit config validation must run only for non-empty input")
    if validation.get("id") != "commitlint_config":
        problems.append("explicit config validation must expose commitlint_config output")
    env = validation.get("env") or {}
    if env.get("COMMITLINT_CONFIG") != "${{ inputs.commitlint_config }}" \
            or env.get("WORKSPACE") != "${{ github.workspace }}":
        problems.append("explicit config must cross the shell boundary through env")
    run = str(validation.get("run", ""))
    for marker in (
        "python3 -I", "supplied.is_absolute()", "resolved.relative_to(workspace)",
        "resolved.is_file()", "config_file={raw}",
    ):
        if marker not in run:
            problems.append(f"explicit config validation missing marker {marker!r}")

    if default.get("if") != "${{ inputs.commitlint_config == '' }}" \
            or default.get("uses") != ACTION:
        problems.append("default action invocation must be exclusive to empty input")
    if "with" in default:
        problems.append("default action invocation must omit the with mapping entirely")

    if explicit.get("if") != "${{ inputs.commitlint_config != '' }}" \
            or explicit.get("uses") != ACTION:
        problems.append("explicit action invocation must be exclusive to non-empty input")
    if (explicit.get("with") or {}).get("configFile") != \
            "${{ steps.commitlint_config.outputs.config_file }}":
        problems.append("explicit action must receive the exact validated path")

    jobs = doc.get("jobs") or {}
    labeler = jobs.get("labeler", {}) if isinstance(jobs, dict) else {}
    label_steps = {
        step.get("name"): step for step in labeler.get("steps", [])
        if isinstance(step, dict)
    }
    label_step = label_steps.get("Label pull request", {})
    if label_step.get("id") != "label":
        problems.append("label action needs a stable id for observable outputs")
    if labeler.get("outputs") != {
        "new_labels": "${{ steps.label.outputs.new-labels }}",
        "all_labels": "${{ steps.label.outputs.all-labels }}",
    }:
        problems.append("labeler job must expose upstream new-labels and all-labels")
    return problems


def _exercise_validator(run: str, supplied: str, make_file: bool) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as directory:
        workspace = Path(directory)
        if make_file:
            target = workspace / supplied
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("export default {};\n", encoding="utf-8")
        output = workspace / "output"
        env = {
            **os.environ,
            "COMMITLINT_CONFIG": supplied,
            "GITHUB_OUTPUT": str(output),
            "WORKSPACE": str(workspace),
        }
        result = subprocess.run(
            ["bash", "-euo", "pipefail", "-c", run], env=env,
            text=True, capture_output=True, check=False,
        )
        if result.returncode == 0:
            result.stdout += output.read_text(encoding="utf-8")
        return result


def check() -> list[str]:
    doc = load_yaml(WORKFLOW)
    problems = validate(doc)
    probes: list[tuple[str, Callable[[dict[str, Any]], object]]] = [
        ("empty reaches action", lambda d: _named(d)[DEFAULT_NAME].update({
            "with": {"configFile": "${{ inputs.commitlint_config }}"}
        })),
        ("default and explicit overlap", lambda d: _named(d)[EXPLICIT_NAME].update({
            "if": "${{ inputs.commitlint_config == '' }}"
        })),
        ("unvalidated explicit input", lambda d: _named(d)[EXPLICIT_NAME]["with"].update({
            "configFile": "${{ inputs.commitlint_config }}"
        })),
    ]
    for label, mutate in probes:
        candidate = copy.deepcopy(doc)
        mutate(candidate)
        if not validate(candidate):
            problems.append(f"negative mutation accepted {label}")

    run = str(_named(doc).get(VALIDATE_NAME, {}).get("run", ""))
    valid = _exercise_validator(run, ".github/commitlint.config.mjs", True)
    if valid.returncode != 0 or "config_file=.github/commitlint.config.mjs" not in valid.stdout:
        problems.append("explicit existing config path was not preserved exactly")
    for label, supplied in (
        ("empty", ""), ("missing", ".github/missing.mjs"),
        ("absolute", "/tmp/config.mjs"), ("escape", "../config.mjs"),
    ):
        if _exercise_validator(run, supplied, False).returncode == 0:
            problems.append(f"explicit config validator accepted {label} path")
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
