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
* **The required surface is derived, not listed.** `ci-gate`'s own `needs` graph
  says which jobs a merge depends on, and a `uses:` job is followed into the
  workflow it calls. Any step in that surface running an action that caches by
  default must carry a declared refusal. The hand-written list missed exactly
  this: `zizmor-sarif.yml` backs the required `zizmor` job and took setup-uv's
  default, while the contract's own closing paragraph asserted that the
  undeclared remainder could not reach a required check.

What this cannot see, stated plainly rather than implied: an action that caches
by default and exposes no input at all is invisible to static analysis, and
`default_caches` is a claim about somebody else's code. So it is no longer only
a claim: `upstream_default` records the literal default the pinned `action.yml`
declares, and `check_cache_upstream_defaults.py` resolves it from that file in
the advisory sweep. That is what caught `astral-sh/setup-uv` being recorded as
not caching by default when it declares `auto`, which resolves to true on a
GitHub-hosted runner -- an entry believed for long enough that two gate jobs
carried a comment saying their explicit `false` changed nothing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ci_workflows_tools._strict_yaml import strict_load
from ci_workflows_tools._workflow_yaml import load_yaml, workflow_files

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "catalog/cache-contract.yml"
CI = ".github/workflows/ci.yml"
GATE_JOB = "ci-gate"


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


def _required_surface() -> set[tuple[str, str]]:
    """Every (workflow, job) a merge depends on, read from `ci-gate`'s own graph.

    A `uses:` job is followed into the workflow it calls, because that is where
    its steps actually live -- and where the cache-capable step that started all
    of this was hiding.
    """
    surface: set[tuple[str, str]] = set()
    gate = ((load_yaml(ROOT / CI).get("jobs") or {}).get(GATE_JOB) or {})
    needs = gate.get("needs") or []
    queue = [(CI, str(job)) for job in ([needs] if isinstance(needs, str) else needs)]
    while queue:
        relative, job_id = queue.pop()
        if (relative, job_id) in surface:
            continue
        path = ROOT / relative
        if not path.is_file():
            continue
        surface.add((relative, job_id))
        job = (load_yaml(path).get("jobs") or {}).get(job_id) or {}
        uses = str(job.get("uses") or "")
        if uses.startswith("./"):
            called = uses[2:]
            if (ROOT / called).is_file():
                for called_job in (load_yaml(ROOT / called).get("jobs") or {}):
                    queue.append((called, str(called_job)))
    return surface


def _required_refusal_problems(producers: dict, refusals: list) -> list[str]:
    """A caching step inside the required surface must carry a declared refusal."""
    problems: list[str] = []
    declared = {
        (str(entry["workflow"]), str(entry["job"]), str(entry["action"]))
        for entry in refusals
    }
    for relative, job_id in sorted(_required_surface()):
        workflow = load_yaml(ROOT / relative)
        job = (workflow.get("jobs") or {}).get(job_id) or {}
        for step in job.get("steps") or []:
            if not isinstance(step, dict) or not step.get("uses"):
                continue
            action = _action(step)
            producer = producers.get(action)
            if not producer or not producer.get("default_caches"):
                continue
            if producer.get("control") is None:
                continue
            if (relative, job_id, action) not in declared:
                problems.append(
                    f"{relative}: job {job_id!r} is required by {GATE_JOB} and runs "
                    f"{action}, which caches with no input, but no refusal is "
                    "declared for it in catalog/cache-contract.yml")
    return problems


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

    problems += _required_refusal_problems(producers, refusals)

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
