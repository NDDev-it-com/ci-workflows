#!/usr/bin/env python3
"""`default_caches` is a claim about somebody else's code. Resolve it.

`catalog/cache-contract.yml` records, for every cache-capable action in the tree,
what happens with no input at all. That is the field the whole contract leans on:
a step with no cache input is only safe if the action's own default is safe, and
static analysis of this repository cannot see the difference.

It was prose, and it was wrong. `astral-sh/setup-uv` was recorded as not caching
by default while the pinned `action.yml` declares `enable-cache: auto`, and its
`getEnableCache()` returns true when `RUNNER_ENVIRONMENT` is `github-hosted`. The
entry was believed long enough that two required jobs carried a comment saying
their explicit `false` "changes nothing today". It changed something.

So `upstream_default` records the literal default the pinned action declares, and
this reads it from that exact commit every sweep. Advisory: what a third party
writes in its own `action.yml` is not a property of this tree, and the answer
changes only when a pin moves.
"""
from __future__ import annotations

import re
from pathlib import Path

from ci_workflows_tools._strict_yaml import strict_load, strict_loads
from ci_workflows_tools._workflow_yaml import workflow_files
from ci_workflows_tools.check_transitive_action_pins import (
    Unavailable,
    _candidate_paths,
    _fetch,
)

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "catalog/cache-contract.yml"
PIN = re.compile(r"uses:\s*(?P<action>[\w.-]+/[\w./-]+)@(?P<sha>[0-9a-f]{40})")


def _pinned() -> dict[str, set[str]]:
    """Every action in the tree and the commits it is pinned to."""
    pins: dict[str, set[str]] = {}
    for path in workflow_files():
        for match in PIN.finditer(path.read_text(encoding="utf-8")):
            pins.setdefault(match.group("action"), set()).add(match.group("sha"))
    return pins


def _declared_default(action: str, sha: str, control: str) -> object:
    """The default the pinned definition declares for its cache input."""
    parts = action.split("/")
    repo = "/".join(parts[:2])
    for candidate in _candidate_paths("/".join(parts[2:])):
        text = _fetch(repo, candidate, sha)
        if text is None:
            continue
        inputs = (strict_loads(text, f"{action}@{sha}").get("inputs") or {})
        entry = inputs.get(control)
        if entry is None:
            raise Unavailable(f"{action}@{sha} declares no input named {control!r}")
        return entry.get("default")
    raise Unavailable(f"{action}@{sha}: no definition at that ref")


def check() -> list[str]:
    contract = strict_load(CONTRACT)
    pins = _pinned()
    problems: list[str] = []
    for producer in contract.get("producers") or []:
        action = str(producer["action"])
        control = producer.get("control")
        expected = producer.get("upstream_default")
        if control is None:
            if expected is not None:
                problems.append(
                    f"catalog/cache-contract.yml: {action} declares no control input, "
                    f"so `upstream_default` must be null, not {expected!r}")
            continue
        shas = pins.get(action)
        if not shas:
            # `check_cache_contract` already reports a producer nobody uses; not
            # repeating it here keeps one finding to one cause.
            continue
        for sha in sorted(shas):
            try:
                actual = _declared_default(action, sha, str(control))
            except Unavailable as exc:
                problems.append(f"{action}: upstream default unverified, {exc}")
                continue
            if actual != expected:
                problems.append(
                    f"catalog/cache-contract.yml records {action} `{control}` "
                    f"defaulting to {expected!r}, but the pinned definition at "
                    f"{sha[:12]} declares {actual!r}")
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_cache_upstream_defaults: FAIL")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("check_cache_upstream_defaults: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
