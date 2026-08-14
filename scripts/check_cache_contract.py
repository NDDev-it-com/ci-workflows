#!/usr/bin/env python3
"""Enforce `catalog/cache-contract.yml` against the workflows in the tree.

Caching here used to be whatever each pinned setup action does by default, so
the safe properties were true by accident. `release.yml` disables the uv cache
for a stated reason -- a cache entry written from a lower-trust ref would become
an input to a release build -- and until now nothing but a comment stopped a
later edit from dropping it.

Three rules, all properties of the tree:

* **Refusals hold.** Every workflow/job the contract says must refuse a cache
  carries the exact input and value. This is the rule with teeth: it is what
  keeps a publishing job, a required gate and a CodeQL analysis from silently
  gaining an unreviewed input.
* **Producers are declared.** A step that exposes a cache-shaped input must be a
  declared producer, so a new caching dependency has to be classified rather
  than inherited.
* **Declarations describe the tree.** A producer nobody uses and a refusal whose
  job no longer exists are both findings, because a contract that names things
  that are gone stops being read.

What this cannot see, stated plainly rather than implied: an action that caches
by default and exposes no input at all is invisible to static analysis. The
contract records `default_caches` for exactly that reason -- three of the eight
producers cache without being asked -- and classifying a new dependency remains
a human judgement made when it is added.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ci_workflows_tools._strict_yaml import strict_load
from ci_workflows_tools._workflow_yaml import load_yaml, workflow_files

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "catalog/cache-contract.yml"


def _steps(workflow: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    for job_id, job in (workflow.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict) and step.get("uses"):
                found.append((str(job_id), step))
    return found


def _action(step: dict[str, Any]) -> str:
    return str(step.get("uses", "")).split("@")[0]


def check() -> list[str]:
    problems: list[str] = []
    contract = strict_load(CONTRACT)
    producers = {str(entry["action"]): entry for entry in contract["producers"]}
    refusals = contract["refusals"]

    used: set[str] = set()
    for path in workflow_files():
        relative = path.relative_to(ROOT).as_posix()
        workflow = load_yaml(path)
        for job_id, step in _steps(workflow):
            action = _action(step)
            options = step.get("with") or {}
            cache_inputs = sorted(k for k in options if "cache" in str(k).lower())
            # Two signals, because one is not enough: an action that takes a
            # cache-shaped input, and an action whose name says it caches.
            # `hendrikmuhs/ccache-action` has no such input -- its key is called
            # `key` -- so the input test alone let it out of the contract.
            looks_like_cache = "cache" in action.lower()
            if action in producers:
                used.add(action)
            elif cache_inputs or looks_like_cache:
                why = f"with {cache_inputs}" if cache_inputs else "and caches by name"
                problems.append(
                    f"{relative}: job {job_id!r} uses {action} {why} but it is not a "
                    "declared producer in catalog/cache-contract.yml")

    for action in sorted(set(producers) - used):
        problems.append(
            f"catalog/cache-contract.yml declares producer {action}, which no workflow uses")

    for refusal in refusals:
        relative = str(refusal["workflow"])
        job_id = str(refusal["job"])
        action = str(refusal["action"])
        name = str(refusal["input"])
        expected = refusal["value"]
        path = ROOT / relative
        if not path.is_file():
            problems.append(f"cache refusal names a missing workflow {relative}")
            continue
        matches = [
            step for found_job, step in _steps(load_yaml(path))
            if found_job == job_id and _action(step) == action
        ]
        if not matches:
            problems.append(
                f"{relative}: cache refusal names job {job_id!r} using {action}, "
                "which is not there")
            continue
        for step in matches:
            actual = (step.get("with") or {}).get(name, "<unset>")
            if actual != expected:
                problems.append(
                    f"{relative}: job {job_id!r} must set {action} {name}={expected!r} "
                    f"but has {actual!r} — {str(refusal['reason']).strip().splitlines()[0]}")
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_cache_contract: FAIL")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("check_cache_contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
