#!/usr/bin/env python3
"""The advisory sweep's one durable output must survive the things that break it.

`maintenance.yml` moves calendar and network debt off the pull-request path, and
the whole justification for that move is the last step: findings become a single
tracking issue a human meets, instead of a red run nobody opens. That step had
two defects, and both were only reachable on a run that had never happened.

It checked out shallow, while the sweep it runs reconciles CHANGELOG headings
against SemVer tags and fails closed when it can see none -- so its first run
would have reported a defect in its own checkout. And it filed the issue with
`gh issue create --label maintenance` while no `maintenance` label existed in the
repository, under `set -e`: the finding would have been computed, printed to the
step summary, and then thrown away when the label lookup aborted the step.

The label is a filing convenience. The report is the point. So the step creates
first and labels after, and the cases below execute the real step against a fake
`gh` -- the `check_side_effect_fixture_contract` idiom -- rather than reading it.
A contract about what happens when an API call fails cannot be established by
looking at the shell that makes it.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from ci_workflows_tools._workflow_yaml import REPO_ROOT, load_yaml
from ci_workflows_tools.check_python_execution_contract import clean_environment

WORKFLOW = REPO_ROOT / ".github/workflows/maintenance.yml"
JOB = "sweep"
CHECKOUT_STEP = "Checkout"
REPORT_STEP = "File or update the tracking issue"

FAKE_GH = """#!/usr/bin/env bash
set -u
printf '%s\\n' "$*" >> "$FAKE_GH_LOG"
kind="${1:-} ${2:-}"
case "$kind" in
  "issue list")
    case "$FAKE_GH_MODE" in
      list-fails) printf 'the search backend is down\\n' >&2; exit 1 ;;
      existing)   printf '%s\\n' "42" ;;
      *)          printf '' ;;
    esac
    ;;
  "issue create")
    if [ "$FAKE_GH_MODE" = create-fails ]; then
      printf 'validation failed\\n' >&2; exit 1
    fi
    # What GitHub actually does: creating with a label that does not exist is
    # rejected outright, taking the issue with it. Modelling `--label` as
    # harmless here would let the original defect pass this contract.
    if [ "$FAKE_GH_MODE" = label-missing ] && [[ " $* " == *" --label "* ]]; then
      printf "could not add label: 'maintenance' not found\\n" >&2; exit 1
    fi
    printf 'https://github.com/o/r/issues/7\\n'
    ;;
  "issue edit")
    if [ "$FAKE_GH_MODE" = label-missing ]; then
      printf "could not add label: 'maintenance' not found\\n" >&2; exit 1
    fi
    ;;
esac
exit 0
"""


def _steps() -> list[dict]:
    doc = load_yaml(WORKFLOW)
    job = (doc.get("jobs") or {}).get(JOB) or {}
    return [step for step in (job.get("steps") or []) if isinstance(step, dict)]


def _step(name: str) -> dict:
    for step in _steps():
        if str(step.get("name")) == name:
            return step
    raise ValueError(f"{WORKFLOW.name}: job {JOB!r} has no step named {name!r}")


def _run_with_fake_gh(script: str, mode: str, env: dict[str, str]):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        binaries = root / "bin"
        binaries.mkdir()
        gh = binaries / "gh"
        gh.write_text(FAKE_GH, encoding="utf-8")
        gh.chmod(0o755)
        log = root / "gh.log"
        log.write_text("", encoding="utf-8")
        (root / "sweep.txt").write_text("[FAIL] product-facts-calendar\n", encoding="utf-8")
        done = subprocess.run(
            ["bash", "-c", script], cwd=root,
            env=clean_environment({
                "PATH": f"{binaries}:/usr/bin:/bin",
                "FAKE_GH_MODE": mode,
                "FAKE_GH_LOG": str(log),
                "GH_TOKEN": "fake",
                "RUN_URL": "https://example.invalid/run/1",
                "LABEL": "maintenance",
                **env,
            }),
            capture_output=True, text=True, timeout=60)
        return done, log.read_text(encoding="utf-8")


def _checkout_problems() -> list[str]:
    try:
        options = _step(CHECKOUT_STEP).get("with") or {}
    except ValueError as exc:
        return [str(exc)]
    problems: list[str] = []
    if options.get("fetch-depth") != 0:
        problems.append(
            f"{WORKFLOW.name}: {CHECKOUT_STEP} must set `fetch-depth: 0`; the sweep "
            "reconciles the release ledger against SemVer tags and fails closed "
            "without them")
    if options.get("fetch-tags") is not True:
        problems.append(
            f"{WORKFLOW.name}: {CHECKOUT_STEP} must set `fetch-tags: true`; "
            "`fetch-depth: 0` alone still fetches no tags")
    return problems


def _report_problems() -> list[str]:
    try:
        script = str(_step(REPORT_STEP).get("run") or "")
    except ValueError as exc:
        return [str(exc)]
    if not script.strip():
        return [f"{WORKFLOW.name}: {REPORT_STEP} runs nothing"]

    problems: list[str] = []
    findings = {"SWEEP_STATUS": "1"}
    clean = {"SWEEP_STATUS": "0"}

    # (label, mode, env, expected exit, substrings the gh log must/must not hold)
    cases = [
        ("a finding with no open issue files one", "none", findings, 0, ["issue create"], []),
        ("a finding with an open issue comments on it", "existing", findings, 0,
         ["issue comment"], ["issue create"]),
        ("a clean sweep with an open issue closes it", "existing", clean, 0,
         ["issue close"], ["issue create"]),
        ("a clean sweep with no open issue files nothing", "none", clean, 0, [],
         ["issue create", "issue comment"]),
        # The defect this file exists for.
        ("a missing label does not destroy the report", "label-missing", findings, 0,
         ["issue create", "issue edit"], []),
        # Fail closed where failing open would mislead.
        ("an unreadable issue list is not treated as 'none'", "list-fails", findings, 1,
         [], ["issue create"]),
        ("a failed creation is not reported as filed", "create-fails", findings, 1, [], []),
    ]
    for label, mode, env, expected, must, must_not in cases:
        done, log = _run_with_fake_gh(script, mode, env)
        if done.returncode != expected:
            problems.append(
                f"maintenance report case {label!r}: exit {done.returncode}, expected "
                f"{expected}{'; stderr: ' + done.stderr.strip()[:160] if done.stderr.strip() else ''}")
            continue
        for needle in must:
            if needle not in log:
                problems.append(
                    f"maintenance report case {label!r}: never called `gh {needle}`")
        for needle in must_not:
            if needle in log:
                problems.append(
                    f"maintenance report case {label!r}: unexpectedly called `gh {needle}`")
    return problems


def check() -> list[str]:
    return _checkout_problems() + _report_problems()


def main() -> int:
    problems = check()
    if problems:
        print("check_maintenance_report_contract: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("check_maintenance_report_contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
