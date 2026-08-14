#!/usr/bin/env python3
"""A tier is a promise about what its checks need. Every caller must keep it.

`validate_all.py --tier scheduled` needs a GitHub token, two external hosts and
the tag refs. That requirement was written down once, as comments beside
`maintenance.yml`'s egress allow-list, and enforced nowhere. Three jobs invoked
the tier and one of them granted what it needs:

* `release.yml` ran every tier with no token, no tags and an allow-list omitting
  both SDK hosts, so a release stopped in preflight on four capability failures
  -- before its own promotion gate, and long before the missing evidence
  manifest that is the *known* release blocker.
* `ci.yml` fell back to the advisory tier whenever it could not resolve a change
  base, which put calendar and network work inside a required gate while
  skipping the blocking changed-path checks it was there to run.

Neither was visible, because neither path had ever executed. So the requirement
becomes data in `catalog/validation-tiers.yml`, and this holds every caller to
it: tier membership is read from `validate_all` itself, the capability each
check needs is read from the catalog, and what a job grants is read from the job.

Discovery is fail-closed in both directions. An invocation the catalog does not
declare is a finding, because a closed allowlist that only checks what it was
told is how the first version of this problem stayed invisible; and a declared
invocation that no longer exists is a finding too, because a contract naming
things that are gone stops being read.
"""
from __future__ import annotations

import re
import sys
from typing import Any

from ci_workflows_tools._strict_yaml import strict_load
from ci_workflows_tools._workflow_yaml import REPO_ROOT, load_yaml, workflow_files

CONTRACT = REPO_ROOT / "catalog/validation-tiers.yml"
TOOL = "validate_all.py"
INVOCATION = re.compile(rf"--launch\s+{re.escape(TOOL)}\s+--(?P<rest>[^\n]*)")
TIER_FLAG = re.compile(r"--tier\s+(?P<tier>[a-z]+)")
NETWORK = "network:"


def _tiers() -> dict[str, list[str]]:
    """Tier membership, read from the module that defines it.

    Imported here rather than at module scope: `validate_all` registers this
    check, so a top-level import is a cycle. Reading the lists when they are
    needed also means this can never disagree with what actually ran.
    """
    from ci_workflows_tools import validate_all

    return {
        "core": [name for name, _ in validate_all.CORE],
        "touched": [name for name, _ in validate_all.TOUCHED],
        "scheduled": [name for name, _ in validate_all.SCHEDULED],
        "release": [name for name, _ in validate_all.RELEASE],
        "all": [name for name, _ in (*validate_all.CORE, *validate_all.TOUCHED,
                                     *validate_all.SCHEDULED)],
    }


def _catalog_problems(contract: dict[str, Any], tiers: dict[str, list[str]]) -> list[str]:
    problems: list[str] = []
    capabilities = contract.get("capabilities") or {}
    requirements = contract.get("requirements") or {}
    known_checks = {name for names in tiers.values() for name in names}
    for check, needed in requirements.items():
        if check not in known_checks:
            problems.append(
                f"catalog/validation-tiers.yml: {check!r} needs {needed}, but no tier "
                "registers a check by that name")
        for capability in needed or []:
            if capability not in capabilities:
                problems.append(
                    f"catalog/validation-tiers.yml: {check!r} needs undeclared "
                    f"capability {capability!r}")
    for capability, description in capabilities.items():
        if not str(description).strip():
            problems.append(
                f"catalog/validation-tiers.yml: capability {capability!r} has no description")
        if not any(capability in (needed or []) for needed in requirements.values()):
            problems.append(
                f"catalog/validation-tiers.yml: capability {capability!r} is declared "
                "but no check needs it")
    return problems


def _needed(tier: str, tiers: dict[str, list[str]], requirements: dict) -> set[str]:
    return {
        capability
        for check in tiers.get(tier, [])
        for capability in (requirements.get(check) or [])
    }


def _discovered() -> dict[tuple[str, str], set[str]]:
    """Every job that runs the tool, and the tiers it runs, read from the tree."""
    found: dict[tuple[str, str], set[str]] = {}
    for path in workflow_files():
        relative = path.relative_to(REPO_ROOT).as_posix()
        doc = load_yaml(path)
        for job_id, job in (doc.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps") or []:
                if not isinstance(step, dict):
                    continue
                for match in INVOCATION.finditer(str(step.get("run") or "")):
                    tier = TIER_FLAG.search(match.group("rest"))
                    found.setdefault((relative, str(job_id)), set()).add(
                        tier.group("tier") if tier else "all")
    return found


def _granted(job: dict, step_env_names: set[str]) -> tuple[set[str], bool, bool]:
    """What the job actually provides: token, reachable hosts, tag refs."""
    job_env = {str(k) for k in (job.get("env") or {})}
    has_token = bool({"GH_TOKEN", "GITHUB_TOKEN"} & (step_env_names | job_env))
    hosts: set[str] = set()
    blocked = False
    tags = False
    for step in job.get("steps") or []:
        if not isinstance(step, dict):
            continue
        uses = str(step.get("uses") or "")
        options = step.get("with") or {}
        if "harden-runner" in uses:
            if str(options.get("egress-policy") or "") == "block":
                blocked = True
                for entry in str(options.get("allowed-endpoints") or "").split():
                    hosts.add(entry.rsplit(":", 1)[0])
        if "actions/checkout" in uses and options.get("fetch-tags") is True:
            tags = True
    return hosts, has_token, (tags, blocked)  # type: ignore[return-value]


def check() -> list[str]:
    contract = strict_load(CONTRACT)
    tiers = _tiers()
    problems = _catalog_problems(contract, tiers)
    requirements = contract.get("requirements") or {}
    declared = {
        (str(entry["workflow"]), str(entry["job"])): str(entry["tier"])
        for entry in (contract.get("invocations") or [])
    }
    discovered = _discovered()

    for key in sorted(set(discovered) - set(declared)):
        problems.append(
            f"{key[0]}: job {key[1]!r} runs {TOOL} but is not declared in "
            "catalog/validation-tiers.yml; every caller must state the tier it runs "
            "so the capabilities it needs can be checked")
    for key in sorted(set(declared) - set(discovered)):
        problems.append(
            f"catalog/validation-tiers.yml declares {key[0]} job {key[1]!r} as a "
            f"{TOOL} caller, which it no longer is")

    for key, tiers_run in sorted(discovered.items()):
        relative, job_id = key
        expected = declared.get(key)
        if expected is None:
            continue
        if tiers_run != {expected}:
            problems.append(
                f"{relative}: job {job_id!r} is declared as running the {expected!r} "
                f"tier but runs {sorted(tiers_run)}")
        doc = load_yaml(REPO_ROOT / relative)
        job = (doc.get("jobs") or {}).get(job_id) or {}
        step_env: set[str] = set()
        for step in job.get("steps") or []:
            if isinstance(step, dict) and INVOCATION.search(str(step.get("run") or "")):
                step_env |= {str(k) for k in (step.get("env") or {})}
        hosts, has_token, (tags, blocked) = _granted(job, step_env)

        for capability in sorted(_needed(expected, tiers, requirements)):
            if capability == "github_token" and not has_token:
                problems.append(
                    f"{relative}: job {job_id!r} runs the {expected!r} tier, which needs "
                    "a GitHub token, but neither the step nor the job sets GH_TOKEN or "
                    "GITHUB_TOKEN; those checks would fail closed on the environment")
            elif capability == "git_tags" and not tags:
                problems.append(
                    f"{relative}: job {job_id!r} runs the {expected!r} tier, which "
                    "reconciles against SemVer tags, but its checkout does not set "
                    "`fetch-tags: true`; `fetch-depth: 0` alone fetches no tags")
            elif capability.startswith(NETWORK) and blocked:
                host = capability[len(NETWORK):]
                if host not in hosts:
                    problems.append(
                        f"{relative}: job {job_id!r} runs the {expected!r} tier, which "
                        f"reaches {host}, but the harden-runner allow-list does not "
                        "include it and the egress policy is `block`")
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_validation_tier_contract: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("check_validation_tier_contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
