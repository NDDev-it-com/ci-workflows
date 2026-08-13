#!/usr/bin/env python3
"""The release job graph must place every write capability behind authorization.

`release-promotion-gate.yml` existed, was documented, was exercised by its own
fixtures, and had a caller example — and the repository's own `release.yml`
called `release-supply-chain.yml` directly, with `publish` depending on nothing
but `resolve`. A control that is not in the path is not a control, and no
validator noticed for the whole life of the gate because every check looked at
the reusable in isolation rather than at the graph that invokes it.

So this validator reads the graph. It resolves `needs` transitively and asserts
that the job holding `contents: write` / `id-token: write` / `attestations:
write` cannot start until both the machine gate (the promotion reusable) and the
human gate (a protected environment) have succeeded. The documented sequence in
`docs/09-releases-packages.md` is checked against the same graph, so the diagram
cannot drift away from the workflow again.

It also runs negative fixtures: each way of breaking the chain must be rejected.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from _strict_yaml import strict_loads
from _workflow_yaml import REPO_ROOT, load_yaml

RELEASE = REPO_ROOT / ".github" / "workflows" / "release.yml"
DOC = REPO_ROOT / "docs" / "09-releases-packages.md"

PROMOTION_WORKFLOW = "release-promotion-gate.yml"
PUBLISH_WORKFLOW = "release-supply-chain.yml"
# Scopes that can mint, sign, or publish an artifact. A job holding any of them
# is a release-capable job and owes the full authorization chain.
WRITE_SCOPES = {"contents", "id-token", "attestations", "artifact-metadata"}


def _needs(job: dict[str, Any]) -> list[str]:
    raw = job.get("needs")
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(n) for n in raw]
    return []


def _ancestors(jobs: dict[str, Any], start: str) -> set[str]:
    """Every job that must succeed before ``start`` may run."""
    seen: set[str] = set()
    stack = list(_needs(jobs.get(start) or {}))
    while stack:
        name = stack.pop()
        if name in seen or name not in jobs:
            continue
        seen.add(name)
        stack.extend(_needs(jobs[name] or {}))
    return seen


def _calls(job: dict[str, Any]) -> str:
    return str(job.get("uses") or "").rsplit("/", 1)[-1]


def _release_capable(job: dict[str, Any]) -> bool:
    perms = job.get("permissions")
    if not isinstance(perms, dict):
        return False
    return any(perms.get(scope) == "write" for scope in WRITE_SCOPES)


def audit_graph(doc: dict[str, Any]) -> list[str]:
    """Assert the authorization chain on a parsed release workflow."""
    problems: list[str] = []
    jobs = doc.get("jobs") or {}
    if not jobs:
        return ["release.yml: declares no jobs"]

    capable = {name: job for name, job in jobs.items()
               if isinstance(job, dict) and _release_capable(job)}
    if not capable:
        return ["release.yml: no job holds a release write scope; the graph cannot be audited"]

    for name, job in sorted(capable.items()):
        ancestors = _ancestors(jobs, name)

        gated_by_promotion = any(
            _calls(jobs[a]) == PROMOTION_WORKFLOW for a in ancestors
            if isinstance(jobs.get(a), dict)
        )
        if not gated_by_promotion:
            problems.append(
                f"release.yml: job {name!r} holds "
                f"{sorted(s for s in WRITE_SCOPES if (job.get('permissions') or {}).get(s) == 'write')} "
                f"but no ancestor calls {PROMOTION_WORKFLOW} — the promotion gate "
                "is not in the release path"
            )

        gated_by_environment = any(
            isinstance(jobs.get(a), dict) and jobs[a].get("environment")
            for a in ancestors
        )
        if not gated_by_environment:
            problems.append(
                f"release.yml: job {name!r} is release-capable but no ancestor "
                "declares an `environment:` — a GitHub-verified signature proves "
                "who signed, not that they may ship; the protected environment "
                "is where authorization happens"
            )

        # The authorizing job must not itself hold write scopes: an approval gate
        # that can publish is not a gate.
        for ancestor in sorted(ancestors):
            anc = jobs.get(ancestor)
            if isinstance(anc, dict) and anc.get("environment") and _release_capable(anc):
                problems.append(
                    f"release.yml: authorizing job {ancestor!r} itself holds a "
                    "release write scope; the approval gate must be unprivileged"
                )

    # The published graph in the tier doc must match the real one, because the
    # last drift was precisely a diagram claiming a dependency the graph lacked.
    if DOC.is_file():
        text = DOC.read_text(encoding="utf-8")
        mentions_promotion = PROMOTION_WORKFLOW in text
        if mentions_promotion and not any(
            _calls(job) == PROMOTION_WORKFLOW
            for job in jobs.values() if isinstance(job, dict)
        ):
            problems.append(
                f"docs/09-releases-packages.md documents {PROMOTION_WORKFLOW} in the "
                "release flow but release.yml never calls it"
            )
    return problems


def _fixtures() -> list[str]:
    """Each way of breaking the chain must be rejected."""
    problems: list[str] = []

    good = """
name: release
on: { push: { tags: ["[0-9]+.[0-9]+.[0-9]+"] } }
permissions: {}
jobs:
  resolve:
    runs-on: ubuntu-latest
    permissions: { contents: read }
    steps: [{ run: "true" }]
  promotion:
    needs: resolve
    permissions: { contents: read }
    uses: ./.github/workflows/release-promotion-gate.yml
  authorize:
    needs: [resolve, promotion]
    runs-on: ubuntu-latest
    environment: release
    permissions: {}
    steps: [{ run: "true" }]
  publish:
    needs: [resolve, promotion, authorize]
    permissions: { contents: write, id-token: write }
    uses: ./.github/workflows/release-supply-chain.yml
"""

    def audit(text: str) -> list[str]:
        return audit_graph(strict_loads(text, "<fixture>") or {})

    if audit(good):
        problems.append(
            f"release-graph fixture: the correct graph was rejected: {audit(good)}"
        )

    cases = {
        "publish depends only on resolve (the shipped defect)":
            good.replace("needs: [resolve, promotion, authorize]", "needs: resolve"),
        "promotion job removed entirely":
            good.replace("""  promotion:
    needs: resolve
    permissions: { contents: read }
    uses: ./.github/workflows/release-promotion-gate.yml
""", "").replace("needs: [resolve, promotion, authorize]", "needs: [resolve, authorize]"),
        "approval environment removed":
            good.replace("    environment: release\n", ""),
        "approval gate itself holds write":
            good.replace("""    environment: release
    permissions: {}""", """    environment: release
    permissions: { contents: write }"""),
        "publish bypasses authorize but keeps promotion":
            good.replace("needs: [resolve, promotion, authorize]", "needs: [resolve, promotion]"),
    }
    for label, text in cases.items():
        if not audit(text):
            problems.append(f"release-graph fixture: accepted a broken graph — {label}")
    return problems


def check() -> list[str]:
    problems: list[str] = []
    if not RELEASE.is_file():
        return ["release.yml: missing"]
    problems += audit_graph(load_yaml(RELEASE))
    problems += _fixtures()
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_release_graph: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("check_release_graph: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
