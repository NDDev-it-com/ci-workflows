#!/usr/bin/env python3
"""`ci.yml` must pick a tier from the tree, never from how the run was triggered.

The changed-path job resolves a base from the event and, when it could not,
fell through to `validate_all.py --tier scheduled` under a message that said it
was "running the full sweep". It was doing neither. `scheduled` does not contain
the blocking changed-path checks, so every one of them was skipped; and it does
contain calendar and network checks that need a token and two external hosts
this job deliberately does not grant, so a required gate could go red because a
third party's tariff expired. Both halves fired on `workflow_dispatch`, branch
creation, and any force-push beyond reachable history.

`--tier touched --all-paths` is not the fix either, and the reason is worth
recording so it is not proposed again: `validate_product_facts.facts_reached_by`
returns "all facts" as soon as the ledger or the capability catalog is in scope,
and the whole-tree fallback in `validate_all.changed_paths` puts them there. A
whole-tree touched run *is* the calendar sweep, which is precisely what the tier
split moved off the pull-request path.

So the base is resolved rather than abandoned: everything the ref adds on top of
the default branch. Two properties are checked here, and the first is executed
rather than read, because a rule about which tier runs is worth nothing if the
step that chooses it is only pattern-matched:

1. The embedded resolver, run against real temporary Git repositories for every
   event shape GitHub can deliver, including the ones that produce no base.
2. No job reachable from `ci-gate` invokes the advisory tier at all.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

from ci_workflows_tools._workflow_yaml import REPO_ROOT, load_yaml
from ci_workflows_tools.check_python_execution_contract import clean_environment

CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
GATE_JOB = "ci-gate"
RESOLVER_JOB = "validate-touched"
RESOLVER_STEP = "Resolve the change base"
ADVISORY_TIER = "scheduled"
ZERO_OID = "0" * 40


def _steps(job_id: str) -> list[dict]:
    doc = load_yaml(CI)
    job = (doc.get("jobs") or {}).get(job_id) or {}
    return [step for step in (job.get("steps") or []) if isinstance(step, dict)]


def _embedded_resolver() -> str:
    """The exact program `ci.yml` runs, not a copy of it."""
    for step in _steps(RESOLVER_JOB):
        if str(step.get("name")) != RESOLVER_STEP:
            continue
        body = str(step.get("run") or "")
        match = re.search(r"python3 -I <<'PY'\n(.*?)\n\s*PY\s*$", body, re.S)
        if match is None:
            raise ValueError(
                f"{RESOLVER_JOB}/{RESOLVER_STEP} no longer embeds a `python3 -I` program")
        # The YAML block scalar is already dedented by the parser; stripping
        # further would silently corrupt the program into something that only
        # looks like what the job runs.
        return match.group(1)
    raise ValueError(f"{CI.name} has no {RESOLVER_JOB}/{RESOLVER_STEP} step")


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, env=clean_environment({"PATH": "/usr/bin:/bin"}),
        capture_output=True, text=True, check=False, timeout=30)


def _fixture(root: Path) -> dict[str, str]:
    """A repository with a default branch, a topic branch, and an orphan.

    Built rather than mocked: the resolver shells out to git, and a fake that
    answers for git would be the copy this file exists to stop trusting.
    """
    def run(*args: str) -> str:
        done = _git(*args, cwd=root)
        if done.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {done.stderr.strip()}")
        return done.stdout.strip()

    run("init", "--quiet", "--initial-branch", "main")
    run("config", "user.email", "fixture@example.invalid")
    run("config", "user.name", "fixture")
    run("config", "commit.gpgsign", "false")
    (root / "a.txt").write_text("a\n", encoding="utf-8")
    run("add", "a.txt")
    run("commit", "--quiet", "-m", "base")
    base = run("rev-parse", "HEAD")
    # The remote-tracking ref a `fetch-depth: 0` checkout would have.
    run("update-ref", "refs/remotes/origin/main", base)

    run("checkout", "--quiet", "-b", "topic")
    (root / "b.txt").write_text("b\n", encoding="utf-8")
    run("add", "b.txt")
    run("commit", "--quiet", "-m", "one")
    first = run("rev-parse", "HEAD")
    (root / "c.txt").write_text("c\n", encoding="utf-8")
    run("add", "c.txt")
    run("commit", "--quiet", "-m", "two")
    return {"base": base, "first": first, "head": run("rev-parse", "HEAD")}


def _resolve(program: Path, root: Path, env: dict[str, str]) -> tuple[int, str]:
    """Run the resolver the way the job does, and read the output it writes."""
    output = root / "github_output"
    output.write_text("", encoding="utf-8")
    done = subprocess.run(
        [sys.executable, "-I", str(program)], cwd=root,
        env=clean_environment({"PATH": "/usr/bin:/bin",
                               "GITHUB_OUTPUT": str(output), **env}),
        capture_output=True, text=True, timeout=60)
    written = output.read_text(encoding="utf-8")
    match = re.search(r"^base=(.*)$", written, re.M)
    return done.returncode, (match.group(1) if match else "")


def _behaviour_problems(program: Path) -> list[str]:
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        oids = _fixture(root)
        default = {"DEFAULT_BRANCH": "main"}
        # (label, env, expected base key or None, expected exit)
        cases = [
            # These two deliberately carry `first`, not `base`: the fallback
            # resolves to `base`, so using it here would let a resolver that
            # reads the wrong event field pass by arriving at the right answer
            # for the wrong reason. Mutation testing caught exactly that.
            ("pull request carries its own base",
             {"EVENT_NAME": "pull_request", "PR_BASE_SHA": oids["first"], **default},
             "first", 0),
            ("merge group carries its own base",
             {"EVENT_NAME": "merge_group", "MERGE_GROUP_BASE_SHA": oids["first"], **default},
             "first", 0),
            ("push carries the previous tip",
             {"EVENT_NAME": "push", "PUSH_BEFORE": oids["first"], **default},
             "first", 0),
            ("branch creation sends an all-zero oid",
             {"EVENT_NAME": "push", "PUSH_BEFORE": ZERO_OID, **default}, "base", 0),
            ("workflow_dispatch sends no base at all",
             {"EVENT_NAME": "workflow_dispatch", **default}, "base", 0),
            ("an unknown event sends no base",
             {"EVENT_NAME": "schedule", **default}, "base", 0),
            ("no base and no default branch fails closed",
             {"EVENT_NAME": "workflow_dispatch", "DEFAULT_BRANCH": ""}, None, 1),
            ("no base and an absent default branch fails closed",
             {"EVENT_NAME": "workflow_dispatch", "DEFAULT_BRANCH": "nonexistent"}, None, 1),
        ]
        for label, env, expected_key, expected_code in cases:
            code, base = _resolve(program, root, env)
            if code != expected_code:
                problems.append(
                    f"tier-selection case {label!r}: exit {code}, expected {expected_code}")
                continue
            if expected_key is None:
                continue
            if base != oids[expected_key]:
                problems.append(
                    f"tier-selection case {label!r}: base {base or '<empty>'}, "
                    f"expected {oids[expected_key]}")

        # Dispatching on the default branch itself resolves to HEAD, which scopes
        # to nothing. That is the honest answer, and it must not be an error.
        if _git("checkout", "--quiet", "main", cwd=root).returncode == 0:
            code, base = _resolve(
                program, root, {"EVENT_NAME": "workflow_dispatch", **default})
            if code != 0 or base != oids["base"]:
                problems.append(
                    "tier-selection case 'dispatch on the default branch': "
                    f"exit {code} base {base or '<empty>'}, expected exit 0 "
                    f"base {oids['base']}")
            _git("checkout", "--quiet", "topic", cwd=root)

    with tempfile.TemporaryDirectory() as raw:
        # A remote-tracking ref that exists but shares no history. Without this
        # the only unresolvable case failed at the fetch in front of the merge
        # base, so breaking the merge-base check itself went unnoticed.
        root = Path(raw)
        _git("init", "--quiet", "--initial-branch", "main", cwd=root)
        _git("config", "user.email", "fixture@example.invalid", cwd=root)
        _git("config", "user.name", "fixture", cwd=root)
        (root / "a.txt").write_text("a\n", encoding="utf-8")
        _git("add", "a.txt", cwd=root)
        _git("commit", "--quiet", "-m", "trunk", cwd=root)
        _git("update-ref", "refs/remotes/origin/main",
             _git("rev-parse", "HEAD", cwd=root).stdout.strip(), cwd=root)
        _git("checkout", "--quiet", "--orphan", "detached", cwd=root)
        (root / "b.txt").write_text("b\n", encoding="utf-8")
        _git("add", "b.txt", cwd=root)
        _git("commit", "--quiet", "-m", "unrelated", cwd=root)
        code, base = _resolve(
            program, root, {"EVENT_NAME": "workflow_dispatch", "DEFAULT_BRANCH": "main"})
        if code == 0:
            problems.append(
                "tier-selection case 'histories share no merge base': "
                f"exit 0 base {base or '<empty>'}, expected a failure rather than "
                "a base that scopes to the whole tree")

    with tempfile.TemporaryDirectory() as raw:
        # No remote-tracking ref and no origin to fetch one from.
        root = Path(raw)
        _git("init", "--quiet", "--initial-branch", "main", cwd=root)
        _git("config", "user.email", "fixture@example.invalid", cwd=root)
        _git("config", "user.name", "fixture", cwd=root)
        (root / "a.txt").write_text("a\n", encoding="utf-8")
        _git("add", "a.txt", cwd=root)
        _git("commit", "--quiet", "-m", "only", cwd=root)
        code, _ = _resolve(
            program, root, {"EVENT_NAME": "workflow_dispatch", "DEFAULT_BRANCH": "main"})
        if code == 0:
            problems.append(
                "tier-selection case 'no remote-tracking ref and no origin': "
                "exit 0, expected a failure rather than an empty scope")
    return problems


def _gate_jobs(doc: dict) -> list[str]:
    """The jobs a merge actually depends on, read from the graph, not a list."""
    gate = (doc.get("jobs") or {}).get(GATE_JOB) or {}
    needs = gate.get("needs") or []
    if isinstance(needs, str):
        needs = [needs]
    return [str(job) for job in needs]


def _advisory_problems() -> list[str]:
    problems: list[str] = []
    doc = load_yaml(CI)
    jobs = doc.get("jobs") or {}
    gate_jobs = _gate_jobs(doc)
    if not gate_jobs:
        return [f"{CI.name}: {GATE_JOB} declares no `needs`; nothing is required"]
    for job_id in gate_jobs:
        job = jobs.get(job_id)
        if job is None:
            problems.append(f"{CI.name}: {GATE_JOB} needs {job_id!r}, which is not a job")
            continue
        for step in (job.get("steps") or []):
            if not isinstance(step, dict):
                continue
            body = str(step.get("run") or "")
            if re.search(rf"--tier\s+{ADVISORY_TIER}\b", body):
                problems.append(
                    f"{CI.name}: job {job_id!r} is required by {GATE_JOB} and runs "
                    f"`--tier {ADVISORY_TIER}`; the advisory tier needs a token and "
                    "external hosts a blocking job must not depend on, and omits "
                    "the blocking changed-path checks entirely")
    return problems


def check() -> list[str]:
    try:
        program_text = _embedded_resolver()
    except (ValueError, OSError) as exc:
        return [str(exc)]
    problems = _advisory_problems()
    with tempfile.TemporaryDirectory() as raw:
        program = Path(raw) / "resolve_base.py"
        program.write_text(program_text, encoding="utf-8")
        problems += _behaviour_problems(program)
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_ci_tier_selection: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("check_ci_tier_selection: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
