#!/usr/bin/env python3
"""The Qt toolchain's lock, the workflow that fetches it, and the catalog agree.

`qt-ci.yml` used `uvx --from 'aqtinstall@3.3.0' --with 'py7zr==1.0.0'`. That
pinned two names and left everything they pull unbounded -- aqtinstall declares
`bs4`, `defusedxml`, `humanize`, `patch-ng`, `semantic-version` and `texttable`
with no upper bound, and `requests>=2.31.0` -- so two runs of the same workflow
SHA could install different code without this repository changing. It mattered
here more than most places, because driving aqtinstall directly was itself a
supply-chain decision, taken to escape an action whose nested graph could not be
pinned. Escaping one unpinned graph into another is not an improvement.

`requirements-qt.txt` is now the closure, all twenty-eight packages with hashes.
`qt-ci.yml` is a reusable workflow, so the checkout it runs in belongs to the
caller and the lock is not there: it is fetched from the exact commit of the
workflow file and checked against a digest published *in* that file. Three things
therefore have to agree, and this is what says so:

* the digest `qt-ci.yml` carries and the lock in the tree,
* the versions the lock pins and the versions `catalog/tools.yml` records,
* and every requirement in the lock carries hashes, or `--require-hashes` fails
  at install time rather than here.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

from ci_workflows_tools._strict_yaml import strict_load
from ci_workflows_tools._workflow_yaml import load_yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCK = REPO_ROOT / "requirements-qt.txt"
WORKFLOW = REPO_ROOT / ".github/workflows/qt-ci.yml"
TOOLS = REPO_ROOT / "catalog/tools.yml"
STEP = "Provision the locked Qt toolchain"
PINNED = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^\s;]+)", re.M)


def check() -> list[str]:
    problems: list[str] = []
    if not LOCK.is_file():
        return [f"{LOCK.name} is missing; qt-ci.yml installs from it"]
    lock_text = LOCK.read_text(encoding="utf-8")
    digest = hashlib.sha256(LOCK.read_bytes()).hexdigest()

    pinned = {m.group("name").lower().replace("_", "-"): m.group("version")
              for m in PINNED.finditer(lock_text)}
    if not pinned:
        problems.append(f"{LOCK.name} pins nothing")

    # Every requirement must carry hashes, or --require-hashes fails on the runner.
    for name in sorted(pinned):
        pattern = re.compile(
            rf"^{re.escape(name)}==[^\n]*\n(?:\s+--hash=sha256:[0-9a-f]{{64}}[^\n]*\n)+",
            re.M | re.I)
        if not pattern.search(lock_text):
            problems.append(f"{LOCK.name}: {name} carries no --hash entries")

    # The workflow's published digest must be this lock.
    steps = [s for s in ((load_yaml(WORKFLOW).get("jobs") or {}).get("qt") or {}).get("steps") or []
             if isinstance(s, dict)]
    declared = None
    for step in steps:
        if str(step.get("name")) == STEP:
            declared = str((step.get("env") or {}).get("LOCK_SHA256") or "")
    if declared is None:
        problems.append(f"qt-ci.yml has no {STEP!r} step")
    elif declared != digest:
        problems.append(
            f"qt-ci.yml publishes LOCK_SHA256 {declared[:12] or '<empty>'}… but "
            f"{LOCK.name} hashes to {digest[:12]}…; the workflow would refuse the "
            "lock it fetches")

    # The catalog must record the same closure and the same versions.
    tools = {str(entry.get("id")): entry for entry in (strict_load(TOOLS).get("tools") or [])}
    for tool_id in ("aqtinstall", "py7zr"):
        entry = tools.get(tool_id)
        if entry is None:
            problems.append(f"catalog/tools.yml does not register {tool_id}, which qt-ci.yml runs")
            continue
        if str(entry.get("lock_sha256")) != digest:
            problems.append(
                f"catalog/tools.yml records {tool_id} lock_sha256 "
                f"{str(entry.get('lock_sha256'))[:12]}…, but {LOCK.name} hashes to {digest[:12]}…")
        recorded = str(entry.get("pin") or entry.get("current_version") or "")
        if pinned.get(tool_id) != recorded:
            problems.append(
                f"catalog/tools.yml pins {tool_id} at {recorded!r}, but {LOCK.name} "
                f"locks {pinned.get(tool_id)!r}")
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_qt_toolchain_lock: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("check_qt_toolchain_lock: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
