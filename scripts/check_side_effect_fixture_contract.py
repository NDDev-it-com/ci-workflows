#!/usr/bin/env python3
"""Fail-closed structure and mutation probes for event/write runtime fixtures."""
from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any, Callable

from _strict_yaml import strict_load
from _workflow_yaml import get_on

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/runtime-fixtures-event-write.yml"


def _job(doc: dict[str, Any], name: str) -> dict[str, Any]:
    jobs = doc.get("jobs") or {}
    value = jobs.get(name) if isinstance(jobs, dict) else None
    return value if isinstance(value, dict) else {}


def validate(doc: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    triggers = get_on(doc)
    if not isinstance(triggers, dict) or set(triggers) != {
        "push", "pull_request", "workflow_dispatch"
    }:
        problems.append("side-effect fixture must have push/PR/manual event-correct triggers")
    if doc.get("permissions") != {}:
        problems.append("side-effect fixture must deny permissions at top level")
    concurrency = doc.get("concurrency") or {}
    if concurrency.get("cancel-in-progress") is not False:
        problems.append("side-effect fixture must preserve the first run; cancellation hides evidence")

    benchmark = _job(doc, "fixture-benchmark")
    if benchmark.get("permissions") != {"contents": "write"}:
        problems.append("benchmark caller must grant exactly contents:write")
    benchmark_with = benchmark.get("with") or {}
    if not benchmark_with.get("external_data_json_path"):
        problems.append("benchmark fixture must use file-backed history")
    branch = str(benchmark_with.get("history_branch", ""))
    if not branch.startswith("${{ needs.prepare-benchmark.outputs.branch"):
        problems.append("benchmark fixture must use the prepared disposable branch")

    benchmark_cleanup = _job(doc, "cleanup-benchmark")
    if benchmark_cleanup.get("permissions") != {"contents": "write"}:
        problems.append("benchmark cleanup must grant exactly contents:write")
    if set(benchmark_cleanup.get("needs") or []) != {
        "prepare-benchmark", "fixture-benchmark"
    }:
        problems.append("benchmark cleanup must observe preparation and caller")
    cleanup_text = str((benchmark_cleanup.get("steps") or [{}])[0].get("run", ""))
    for marker in (
        "^runtime-evidence/benchmark-[0-9]+-[0-9]+$",
        "--method DELETE",
        "CALLER_RESULT",
        "disposable branch remains",
    ):
        if marker not in cleanup_text:
            problems.append(f"benchmark cleanup missing fail-closed marker {marker!r}")

    hygiene = _job(doc, "fixture-pr-hygiene")
    if hygiene.get("permissions") != {
        "contents": "read", "issues": "write", "pull-requests": "write"
    }:
        problems.append("PR-hygiene caller has broader or insufficient permissions")
    hygiene_with = hygiene.get("with") or {}
    expected = {"commitlint": True, "pr_title": True, "labeler": True, "stale": False}
    if any(hygiene_with.get(key) != value for key, value in expected.items()):
        problems.append("PR-hygiene fixture must run read lanes plus labeler and exclude stale")

    pr_cleanup = _job(doc, "cleanup-pr-hygiene")
    if pr_cleanup.get("permissions") != {"pull-requests": "write"}:
        problems.append("PR cleanup must grant exactly pull-requests:write")
    if set(pr_cleanup.get("needs") or []) != {
        "prepare-pr-hygiene", "fixture-pr-hygiene"
    }:
        problems.append("PR cleanup must observe preparation and caller")
    pr_text = str((pr_cleanup.get("steps") or [{}])[0].get("run", ""))
    for marker in (
        "labeler did not apply the expected ci label",
        "--method DELETE",
        "prior label state was not restored",
        "CALLER_RESULT",
    ):
        if marker not in pr_text:
            problems.append(f"PR cleanup missing fail-closed marker {marker!r}")

    for evidence_job, caller, cleanup in (
        ("evidence-benchmark", "fixture-benchmark", "cleanup-benchmark"),
        ("evidence-pr-hygiene", "fixture-pr-hygiene", "cleanup-pr-hygiene"),
    ):
        evidence = _job(doc, evidence_job)
        if set(evidence.get("needs") or []) != {caller, cleanup}:
            problems.append(f"{evidence_job} must depend on caller and cleanup")
        env = ((evidence.get("steps") or [{}, {}])[-1].get("env") or {})
        if caller not in str(env.get("PROVES")) or cleanup not in str(env.get("GUARDS")):
            problems.append(f"{evidence_job} must bind proof to its cleanup guard")
    return problems


def check() -> list[str]:
    doc = strict_load(WORKFLOW)
    problems = validate(doc)
    probes: list[tuple[str, Callable[[dict[str, Any]], object]]] = [
        ("broad benchmark permission", lambda d: _job(d, "fixture-benchmark")["permissions"].update({"issues": "write"})),
        ("stale false-green", lambda d: _job(d, "fixture-pr-hygiene")["with"].update({"stale": True})),
        ("missing cleanup guard", lambda d: (_job(d, "evidence-benchmark")["steps"][-1]["env"].pop("GUARDS"))),
        ("cleanup without caller", lambda d: _job(d, "cleanup-pr-hygiene").update({"needs": ["prepare-pr-hygiene"]})),
    ]
    for label, mutate in probes:
        candidate = copy.deepcopy(doc)
        mutate(candidate)
        if not validate(candidate):
            problems.append(f"negative probe accepted {label}")
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_side_effect_fixture_contract: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("check_side_effect_fixture_contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
