#!/usr/bin/env python3
"""`.gds/repository.yaml` tells a control plane how to verify this repository.

It is read across a submodule boundary by `github-device-sync`, which runs what
it finds under `verification.commands`. Nothing here checked that those commands
work, and for weeks after the launcher split they did not: the file declared
`python3 scripts/validate_all.py`, which aborts with `ModuleNotFoundError` by
design. The estate was told to verify this repository with a command that could
not run, and the reason it went unnoticed for so long is that both `AGENTS.md`
and `.claude/CLAUDE.md` described all of `.gds/**` as a generated projection, so
the fix looked like somebody else's to make. `.gds/bundle.lock.yaml` is the
authority and lists exactly one projection output, `.gds/compiled-policy.json`;
this file is an input owned here, and an edit to it is durable.

The commands are exempt from the launcher-form rule in
`catalog/python-execution.yml`, deliberately: a consuming control plane runs them
where this repository's `.venv` does not exist, so they must be the portable
`python3 -I -B` form. Exempt from the *form* rule is not exempt from working, so
this executes them.

`--launch validate_all.py` is executed as a form check only -- running the full
validator from inside the validator would recurse -- while the commands that can
be run outright are run outright.
"""
from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

from ci_workflows_tools._strict_yaml import strict_load
from ci_workflows_tools.check_python_execution_contract import clean_environment

REPO_ROOT = Path(__file__).resolve().parent.parent
ANCHOR = REPO_ROOT / ".gds/repository.yaml"
SCRIPTS = REPO_ROOT / "scripts"
# Running the aggregate validator from inside itself would recurse forever.
NOT_EXECUTED = "validate_all.py"


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv, cwd=REPO_ROOT, env=clean_environment({"PATH": "/usr/bin:/bin"}),
        capture_output=True, text=True, check=False, timeout=300)


def check() -> list[str]:
    if not ANCHOR.is_file():
        return [f"{ANCHOR.relative_to(REPO_ROOT)} is missing"]
    anchor = strict_load(ANCHOR)
    verification = (anchor.get("verification") or {})
    commands = verification.get("commands") or {}
    required = verification.get("required") or []
    problems: list[str] = []

    for name in required:
        if name not in commands:
            problems.append(
                f".gds/repository.yaml: `verification.required` names {name!r}, "
                "which `verification.commands` does not define")
    if not commands:
        return problems + [".gds/repository.yaml declares no verification commands"]

    for name, declared in sorted(commands.items()):
        for command in declared or []:
            argv = shlex.split(str(command))
            scripts = [part for part in argv if part.endswith(".py")]
            for script in scripts:
                target = REPO_ROOT / script if "/" in script else SCRIPTS / script
                if not target.is_file():
                    problems.append(
                        f".gds/repository.yaml: {name} command names {script}, "
                        "which does not exist")
            if any(part.endswith(NOT_EXECUTED) for part in argv):
                # Form only: it must still be an invocation this repository
                # supports, which is what silently stopped being true before.
                if "--launch" not in argv:
                    problems.append(
                        f".gds/repository.yaml: {name} command runs {NOT_EXECUTED} "
                        "directly; a bare `python3 scripts/...` aborts with "
                        "ModuleNotFoundError by design")
                continue
            if not argv:
                continue
            done = _run(argv)
            if done.returncode != 0:
                detail = (done.stderr or done.stdout).strip().splitlines()
                problems.append(
                    f".gds/repository.yaml: {name} command `{command}` exits "
                    f"{done.returncode} — {detail[-1] if detail else 'no output'}")
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_gds_verification_commands: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("check_gds_verification_commands: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
