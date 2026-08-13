#!/usr/bin/env python3
"""What a reusable needs from the machine it lands on, derived and enforced.

A caller choosing a runner is choosing a machine, and the library never said
what its workflows need from one. `required_permissions` answers what the token
needs and `required_settings` what the repository needs; nothing answered what
the *host* needs. A private caller picking between fleet classes — one with a
Docker daemon, one without — had to read the workflow and guess, and guessing
wrong fails at runtime with a message about a missing socket rather than about a
missing class.

The surface turns out to be small and worth stating precisely: of 46 reusables,
44 need nothing but a shell. Two need a container runtime — `secret-scan`, whose
gitleaks is a digest-pinned image, and `container-ci`, whose Trivy action shells
out to Docker. That is the whole distinction, and it is why this is a declared
fact rather than a `runner_class` input: an input would have to name somebody's
private label taxonomy inside a public library, which is the thing ADR 0004
exists to forbid, and it would sit next to `runner` as a second way to choose
one machine.

The requirement is derived from the workflow itself and compared against the
catalog, so the two cannot drift. Add `docker run` to a workflow and the gate
fails until the catalog says the workflow needs a container runtime.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from _strict_yaml import strict_load  # noqa: E402
from _workflow_yaml import REPO_ROOT, get_on, workflow_files  # noqa: E402

CONTAINER_RUNTIME = "container-runtime"

# A step that shells out to the daemon, or an action that does it for you.
DOCKER_COMMAND = re.compile(r"\bdocker\s+(run|build|pull|push|save|load)\b")
DOCKER_ACTIONS = ("aquasecurity/trivy-action", "docker/build-push-action")


def derive(path: Path) -> set[str]:
    """The host capabilities this workflow actually uses."""
    document = strict_load(path)
    needs: set[str] = set()
    for job in (document.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        # `services:` and a job-level `container:` are both run by the daemon.
        if job.get("services") or job.get("container"):
            needs.add(CONTAINER_RUNTIME)
        for step in job.get("steps") or []:
            if not isinstance(step, dict):
                continue
            if DOCKER_COMMAND.search(str(step.get("run") or "")):
                needs.add(CONTAINER_RUNTIME)
            if any(action in str(step.get("uses") or "") for action in DOCKER_ACTIONS):
                needs.add(CONTAINER_RUNTIME)
    return needs


def check() -> list[str]:
    problems: list[str] = []
    catalog = strict_load(REPO_ROOT / "catalog" / "capabilities.yml")
    entries = catalog.get("capabilities") or catalog.get("entries") or []
    declared: dict[str, set[str]] = {}
    for entry in entries:
        workflow = entry.get("workflow")
        if not workflow:
            continue
        value = entry.get("runtime_requirements")
        if value is None:
            continue
        if not isinstance(value, list):
            problems.append(
                f"capabilities.yml: {entry['id']}: runtime_requirements must be a "
                f"list, got {type(value).__name__}"
            )
            continue
        unknown = set(value) - {CONTAINER_RUNTIME}
        if unknown:
            problems.append(
                f"capabilities.yml: {entry['id']}: unknown runtime requirement(s) "
                f"{sorted(unknown)}. Only {CONTAINER_RUNTIME!r} is defined; add a "
                "new one here and to derive() together, or the field becomes prose."
            )
        declared.setdefault(workflow, set()).update(
            v for v in value if v == CONTAINER_RUNTIME
        )

    for path in workflow_files():
        triggers = get_on(strict_load(path))
        if not (isinstance(triggers, dict) and "workflow_call" in triggers):
            continue
        rel = f".github/workflows/{path.name}"
        actual = derive(path)
        # A workflow with no capability row cannot declare anything; the catalog
        # validator already fails that case, so only compare where a row exists.
        if rel not in declared and not actual:
            continue
        stated = declared.get(rel, set())
        for missing in sorted(actual - stated):
            problems.append(
                f"{path.name}: uses a container runtime but no capability row "
                f"declares runtime_requirements: [{missing}]. A caller on a fleet "
                "class without a Docker daemon gets a missing-socket error at "
                "runtime instead of choosing the right class up front."
            )
        for extra in sorted(stated - actual):
            problems.append(
                f"{path.name}: capability declares runtime_requirements "
                f"[{extra}] but the workflow no longer uses it. An overstated "
                "requirement pushes callers onto a scarcer class than they need."
            )
    problems += _selftest()
    return problems


def _selftest() -> list[str]:
    """derive() must see both shapes, and must not invent a third."""
    problems: list[str] = []
    known = {
        "secret-scan.yml": {CONTAINER_RUNTIME},
        "container-ci.yml": {CONTAINER_RUNTIME},
        "actionlint.yml": set(),
        "go-ci.yml": set(),
        "zizmor-no-sarif.yml": set(),
    }
    for name, expected in known.items():
        path = REPO_ROOT / ".github" / "workflows" / name
        if not path.is_file():
            problems.append(f"check_runtime_requirements self-test: {name} is gone")
            continue
        got = derive(path)
        if got != expected:
            problems.append(
                f"check_runtime_requirements self-test: derive({name}) is "
                f"{sorted(got)}, expected {sorted(expected)}"
            )
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_runtime_requirements: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("check_runtime_requirements: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
