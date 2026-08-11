#!/usr/bin/env python3
"""`catalog/tools.yml` must describe the actions this repository actually uses.

Two silent divergences, both found by comparing the catalog to the tree rather
than by any check:

* **`used_by` was incomplete.** `actions/checkout` declared 9 workflows and was
  used in 46; `setup-python` declared 3 of 6; `upload-artifact` 2 of 7. The
  field is documented as "workflow paths that consume the tool", and it is what
  a reviewer reads to answer "which workflows does this SHA bump affect?" — so
  an incomplete list gives a confidently wrong answer during exactly the review
  that matters most.

* **Four actions were not registered at all**: `EmbarkStudios/cargo-deny-action`
  and `taiki-e/install-action` (rust-supply-chain.yml), and both
  `google/clusterfuzzlite/actions/*` (clusterfuzzlite.yml). The pin validators
  check pin *format*, never catalog *membership*, so three newly added workflows
  bypassed the registry while the gate stayed green.

The registry is derived from the tree here, so neither can recur. `used_by`
covers `.github/workflows/` only; examples pin the reusables, not the actions.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

from _strict_yaml import strict_load
from _workflow_yaml import REPO_ROOT, load_yaml, workflow_files

TOOLS = REPO_ROOT / "catalog" / "tools.yml"
# Calls to this repository's own reusables are not third-party tools.
LOCAL_PREFIXES = ("./", "NDDev-it-com/ci-workflows/")


def _actual_usage() -> dict[str, set[str]]:
    """action repo (owner/name[/path]) -> workflow paths that call it.

    Walks the parsed document rather than grepping for ``uses:``. A regex over
    the raw text also matches the word inside a header comment — this file's
    first draft "found" an action named `` ` `` in release.yml, whose header
    quotes actionlint's message about ``uses``.
    """
    uses: dict[str, set[str]] = defaultdict(set)
    for path in workflow_files():
        where = f".github/workflows/{path.name}"
        for job in (load_yaml(path).get("jobs") or {}).values():
            if not isinstance(job, dict):
                continue
            candidates = [job.get("uses")]
            for step in job.get("steps") or []:
                if isinstance(step, dict):
                    candidates.append(step.get("uses"))
            for raw in candidates:
                if not isinstance(raw, str) or not raw:
                    continue
                ref = raw.strip().strip("'\"")
                if ref.startswith(LOCAL_PREFIXES) or ref.startswith("docker://"):
                    continue
                uses[ref.split("@")[0]].add(where)
    return uses


def check() -> list[str]:
    problems: list[str] = []
    if not TOOLS.is_file():
        return ["catalog/tools.yml: missing"]
    tools = (strict_load(TOOLS) or {}).get("tools") or []
    usage = _actual_usage()

    registered: list[str] = []
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("kind") != "action":
            continue
        tool_id = str(tool.get("id"))
        repo = str(tool.get("pin") or "").split("@")[0]
        if not repo:
            problems.append(f"tools.yml: action {tool_id!r} has no pin to derive its repo from")
            continue
        registered.append(repo)

        # An action may expose sub-paths (github/codeql-action/{init,analyze}),
        # so match the repo prefix rather than the exact key.
        actual: set[str] = set()
        for ref, files in usage.items():
            if ref == repo or ref.startswith(repo + "/"):
                actual |= files
        declared = {str(p) for p in tool.get("used_by") or []}
        for missing in sorted(actual - declared):
            problems.append(
                f"tools.yml: {tool_id!r} is used by {missing} but does not declare it "
                "in used_by — a pin bump review reads this list"
            )
        for stale in sorted(declared - actual):
            problems.append(
                f"tools.yml: {tool_id!r} declares used_by {stale} but does not appear there"
            )

    for ref in sorted(usage):
        if not any(ref == repo or ref.startswith(repo + "/") for repo in registered):
            where = ", ".join(sorted(usage[ref]))
            problems.append(
                f"tools.yml: {ref} is used by {where} but has no catalog entry — "
                "every third-party action this repository runs must be registered"
            )
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_tool_registry: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("check_tool_registry: OK")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
