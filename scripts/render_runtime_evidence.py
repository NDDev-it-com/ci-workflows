#!/usr/bin/env python3
"""Render fixture evidence and fail unless every claimed caller job succeeded."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent


def render(results: dict[str, Any], proves: dict[str, str], run_url: str,
           digest_for=None, guards: dict[str, list[str]] | None = None
           ) -> tuple[str, list[str]]:
    guards = guards or {}
    digest_for = digest_for or (
        lambda workflow: hashlib.sha256(
            (REPO_ROOT / ".github" / "workflows" / workflow).read_bytes()
        ).hexdigest()
    )
    failures: list[str] = []
    lines = [
        "### Runtime evidence", "", f"Run: {run_url}", "",
        "Only a top-level reusable caller result of `success` is eligible evidence.",
        "Failed, cancelled, skipped, or missing rows prove nothing and fail this summary.",
        "A successful row still proves only the deliberately enabled fixture path.", "",
        "Side-effecting callers additionally require every named observer/cleanup guard",
        "to succeed; cleanup success never rescues a failed caller.", "",
        "| Workflow | Caller job | Result | Guards | Eligible | Repair context | proven_digest |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for job, workflow in sorted(proves.items(), key=lambda item: (item[1], item[0])):
        result = str((results.get(job) or {}).get("result", "missing"))
        try:
            digest = digest_for(workflow)
        except OSError:
            digest = "FILE MISSING"
            result = "missing"
        guard_results = {
            guard: str((results.get(guard) or {}).get("result", "missing"))
            for guard in guards.get(job, [])
        }
        guards_ok = all(value == "success" for value in guard_results.values())
        eligible = result == "success" and guards_ok
        repair = (
            "none"
            if eligible
            else "preserve first failure; inspect caller logs; fix cause; prove on a new run"
        )
        if not eligible:
            failures.append(
                f"{job} ({workflow}) result={result} guards={guard_results}"
            )
        guard_text = ", ".join(
            f"`{guard}={value}`" for guard, value in guard_results.items()
        ) or "—"
        lines.append(
            f"| `{workflow}` | `{job}` | `{result}` | "
            f"{guard_text} | {'yes' if eligible else 'NO'} | {repair} | `{digest}` |"
        )
    if failures:
        lines.extend(["", "Evidence rejected:", *[f"- {item}" for item in failures]])
    return "\n".join(lines) + "\n", failures


def check() -> list[str]:
    problems: list[str] = []
    proves = {"good": "a.yml", "other": "b.yml"}
    digest = lambda workflow: {"a.yml": "a" * 64, "b.yml": "b" * 64}[workflow]
    summary, failures = render(
        {"good": {"result": "success"}, "other": {"result": "success"}},
        proves, "https://example.invalid/run", digest,
    )
    if failures or summary.count("| `success` | — | yes |") != 2:
        problems.append("runtime evidence renderer rejected an all-success fixture")
    for false_green in ("failure", "cancelled", "skipped", "missing"):
        results = {"good": {"result": "success"}}
        if false_green != "missing":
            results["other"] = {"result": false_green}
        summary, failures = render(results, proves, "https://example.invalid/run", digest)
        if not failures or "Evidence rejected" not in summary or "| NO |" not in summary:
            problems.append(
                f"runtime evidence renderer accepted false-green result {false_green!r}"
            )
    for false_green in ("failure", "cancelled", "skipped", "missing"):
        results = {"good": {"result": "success"}}
        if false_green != "missing":
            results["cleanup"] = {"result": false_green}
        summary, failures = render(
            results, {"good": "a.yml"}, "https://example.invalid/run", digest,
            {"good": ["cleanup"]},
        )
        if not failures or "cleanup" not in summary or "| NO |" not in summary:
            problems.append(
                f"runtime evidence renderer accepted false-green guard {false_green!r}"
            )
    return problems


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--check":
        problems = check()
        if problems:
            for problem in problems:
                print(f"render-runtime-evidence: {problem}", file=sys.stderr)
            return 1
        print("render_runtime_evidence: OK")
        return 0
    try:
        results = json.loads(os.environ["RESULTS"])
        proves = json.loads(os.environ["PROVES"])
        guards = json.loads(os.environ.get("GUARDS", "{}"))
        run_url = os.environ["RUN_URL"]
    except (KeyError, json.JSONDecodeError) as exc:
        print(f"runtime evidence input invalid: {exc}", file=sys.stderr)
        return 2
    if not isinstance(results, dict) or not isinstance(proves, dict) or not proves \
            or not isinstance(guards, dict) or any(
                job not in proves or not isinstance(values, list)
                or not values or any(not isinstance(value, str) or not value for value in values)
                for job, values in guards.items()
            ):
        print("runtime evidence inputs must be non-empty mappings", file=sys.stderr)
        return 2
    summary, failures = render(results, proves, run_url, guards=guards)
    print(summary, end="")
    telemetry = {
        job: {
            "workflow": workflow,
            "result": str((results.get(job) or {}).get("result", "missing")),
            "guards": {
                guard: str((results.get(guard) or {}).get("result", "missing"))
                for guard in guards.get(job, [])
            },
            "eligible": (
                str((results.get(job) or {}).get("result", "missing")) == "success"
                and all(
                    str((results.get(guard) or {}).get("result", "missing")) == "success"
                    for guard in guards.get(job, [])
                )
            ),
        }
        for job, workflow in sorted(proves.items())
    }
    print("RUNTIME_EVIDENCE_JSON=" + json.dumps(telemetry, sort_keys=True, separators=(",", ":")))
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(summary)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
