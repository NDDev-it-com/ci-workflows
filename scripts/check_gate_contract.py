#!/usr/bin/env python3
"""`gate.yml` reports; it must never claim to attest.

The reusable gate takes the caller's `needs` results as a **string input**,
because a reusable workflow cannot read its caller's `needs` context. That makes
every value in it caller-authored. Two consequences, and this validator locks
both:

1. **It must fail closed on inputs that assert nothing.** Before this contract,
   `needs_json: '{}'` with `required_jobs: ''` exited 0 — a caller could obtain
   a green named check having declared no dependency whatsoever. Reporting on a
   subset of `needs` was also accepted, so a failing job could be excluded by
   shrinking the list.

2. **It must not be sold as a security boundary.** Two adversarial inputs still
   pass and always will: a fabricated all-success object, and fabricated job
   names. No amount of validation inside the reusable can tell those from
   genuine caller data. The honest fix is the label, so the header and the
   catalog must say so, and the recommended required check must be the
   caller-native one.

The behavioural cases below are executed against the exact embedded program, the
way ``check_monorepo_routing`` does, rather than pattern-matched.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from _workflow_yaml import REPO_ROOT, load_yaml
from check_python_execution_contract import clean_environment

GATE = REPO_ROOT / ".github" / "workflows" / "gate.yml"
CATALOG = REPO_ROOT / "catalog" / "capabilities.yml"

# Phrases that must appear where a consumer will read them, so the guarantee is
# stated at the point of use rather than only in a changelog.
REQUIRED_HEADER_PHRASES = (
    "NOT an authorization primitive",
    "do not make this workflow's job your required status check",
    "caller-native",
)


def _embedded_program() -> str:
    doc = load_yaml(GATE)
    steps = (doc.get("jobs", {}).get("gate", {}) or {}).get("steps") or []
    if not steps:
        raise ValueError("gate.yml has no steps")
    body = str(steps[0].get("run") or "")
    match = re.search(r"python3 -I <<'PY'\n(.*?)\nPY\n?$", body, re.S)
    if match is None:
        raise ValueError("gate.yml step 1 does not embed a `python3 -I` program")
    return match.group(1)


def _run(program: Path, needs, required: str, allow: str = "") -> int:
    payload = "" if needs is None else json.dumps(needs)
    completed = subprocess.run(
        [sys.executable, "-I", str(program)],
        env=clean_environment({
            "PATH": "/usr/bin:/bin",
            "NEEDS_JSON": payload,
            "REQUIRED_JOBS": required,
            "ALLOW_SKIPPED": allow,
            "CHECK_NAME": "fixture",
        }),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.returncode


# (label, needs, required_jobs, allow_skipped, expected exit code)
CASES = [
    ("all declared jobs succeeded",
     {"build": {"result": "success"}, "test": {"result": "success"}}, "build,test", "", 0),
    ("a declared job failed",
     {"build": {"result": "success"}, "test": {"result": "failure"}}, "build,test", "", 1),
    ("a skip the caller explicitly allowed",
     {"build": {"result": "success"}, "cov": {"result": "skipped"}}, "build,cov", "cov", 0),
    ("a skip the caller did not allow",
     {"build": {"result": "success"}, "cov": {"result": "skipped"}}, "build,cov", "", 1),
    # The holes that were open and must stay shut.
    ("empty needs object and empty required list", {}, "", "", 1),
    ("empty needs object with a required job", {}, "build", "", 1),
    ("empty needs_json string", None, "build", "", 1),
    ("needs_json is a list, not an object", ["success"], "build", "", 1),
    ("needs_json is not JSON at all", "not json", "build", "", 1),
    ("required_jobs empty while needs has entries",
     {"build": {"result": "success"}}, "", "", 1),
    ("a failing job dropped by shrinking required_jobs",
     {"build": {"result": "success"}, "test": {"result": "failure"}}, "build", "", 1),
    ("entry carries no result field", {"build": {"outcome": "success"}}, "build", "", 1),
    ("allow_skipped names a job that is not required",
     {"build": {"result": "success"}}, "build", "ghost", 1),
    ("a required job missing from needs",
     {"build": {"result": "success"}}, "build,test", "", 1),
]

# Inputs that pass and always will: the reusable cannot distinguish fabricated
# caller data from genuine caller data. Asserted so the limitation is visible in
# the test suite rather than discovered by a consumer trusting the name.
UNFIXABLE = [
    ("fabricated all-success object",
     {"build": {"result": "success"}}, "build", ""),
    ("job names that exist in no caller workflow",
     {"invented": {"result": "success"}}, "invented", ""),
]


def check() -> list[str]:
    problems: list[str] = []
    if not GATE.is_file():
        return ["gate.yml: missing"]

    try:
        program_text = _embedded_program()
    except ValueError as exc:
        return [f"gate.yml: {exc}"]

    with tempfile.TemporaryDirectory() as tmp:
        program = Path(tmp) / "gate.py"
        program.write_text(program_text, encoding="utf-8")
        for label, needs, required, allow, expected in CASES:
            actual = _run(program, needs, required, allow)
            if actual != expected:
                verb = "accepted" if actual == 0 else "rejected"
                problems.append(
                    f"gate.yml: {verb} {label!r} (exit {actual}, expected {expected})"
                )
        for label, needs, required, allow in UNFIXABLE:
            if _run(program, needs, required, allow) != 0:
                problems.append(
                    f"gate.yml: {label!r} was rejected; if the reusable has gained "
                    "real provenance, update this validator and the header claim"
                )

    header = GATE.read_text(encoding="utf-8").lower()
    for phrase in REQUIRED_HEADER_PHRASES:
        if phrase.lower() not in header:
            problems.append(
                f"gate.yml: header must state {phrase!r} — the guarantee has to be "
                "readable at the point of use, not only in the changelog"
            )

    # The catalog must not advertise it as a merge gate either.
    if CATALOG.is_file():
        from _strict_yaml import strict_load

        for cap in (strict_load(CATALOG) or {}).get("capabilities") or []:
            if str(cap.get("id")) != "gate":
                continue
            risks = [str(r) for r in cap.get("risks") or []]
            # An exact marker, not a substring sweep: "does NOT tolerate" and
            # "required_jobs" happened to satisfy a loose "not"/"required" test
            # while the entry still advertised the workflow as a merge gate.
            if not any(r.startswith("NOT AUTHORITATIVE:") for r in risks):
                problems.append(
                    "catalog/capabilities.yml: capability 'gate' must carry a risk "
                    "beginning 'NOT AUTHORITATIVE:' — the catalog is what a "
                    "consumer reads when choosing a required check"
                )
            if not any("caller-native" in r.lower() for r in risks):
                problems.append(
                    "catalog/capabilities.yml: capability 'gate' must point at the "
                    "caller-native replacement in its risks"
                )
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_gate_contract: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("check_gate_contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
