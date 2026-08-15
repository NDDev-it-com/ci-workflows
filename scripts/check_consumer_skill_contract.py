#!/usr/bin/env python3
"""The consumer skill's first command must run in a consumer's checkout.

`ci-consumer-adoption` says "This is the *caller* side" and then opened with

    .venv/bin/python -I -B scripts/check_python_execution_contract.py \\
        --launch resolve_profile.py -- ...

which are paths inside *this* repository. An agent following the skill in a
consumer repository got `No such file or directory` before making its first
decision. Worse, the skill also requires pinning to a released tag, and
`scripts/resolve_profile.py` does not exist in the newest release -- so the two
instructions could not both be obeyed. Both copies of the skill carried it
identically, which is mirror parity working exactly as designed and saying
nothing about whether the thing being mirrored is true.

Two properties, split by the repository's own tier rule. Whether the opening
block establishes the paths it uses is a property of the tree, so it blocks.
Whether the newest release carries the resolver is a property of the refs -- the
same reason `check_release_ledger` reconciles headings in `core` and tags in the
advisory sweep -- so it is advisory, and it is the half that will rot: the caveat
has to be *removed* once a release carries the resolver, which nobody would
otherwise notice.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from ci_workflows_tools.check_python_execution_contract import clean_environment

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / ".agents/skills/ci-consumer-adoption/SKILL.md"
RESOLVER = "scripts/resolve_profile.py"
LOCAL_PATHS = (".venv/", "scripts/")
FENCE = re.compile(r"```bash\n(.*?)```", re.S)
SEMVER_TAG = re.compile(r"^\d+\.\d+\.\d+$")


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, env=clean_environment({"PATH": "/usr/bin:/bin"}),
        capture_output=True, text=True, check=False, timeout=60)


def _newest_release() -> str | None:
    listed = _git("tag", "--list", "--sort=-v:refname")
    if listed.returncode != 0:
        return None
    for tag in listed.stdout.split():
        if SEMVER_TAG.fullmatch(tag):
            return tag
    return None


def check() -> list[str]:
    """Blocking: the opening block must establish what it uses."""
    if not SKILL.is_file():
        return [f"{SKILL.relative_to(REPO_ROOT)} is missing"]
    text = SKILL.read_text(encoding="utf-8")
    problems: list[str] = []

    blocks = FENCE.findall(text)
    if not blocks:
        return ["ci-consumer-adoption declares no command block"]
    first = blocks[0]
    uses_local = [path for path in LOCAL_PATHS if path in first]
    if uses_local:
        establishes = "git clone" in first and re.search(r"^\s*cd\s+\S+", first, re.M)
        if not establishes:
            problems.append(
                "ci-consumer-adoption's first command block uses "
                f"{', '.join(uses_local)} without checking the library out first; "
                "a consumer repository does not contain those paths")

    return problems


def check_release_claim() -> list[str]:
    """Advisory: what the skill says about the newest release must be true."""
    if not SKILL.is_file():
        return [f"{SKILL.relative_to(REPO_ROOT)} is missing"]
    text = SKILL.read_text(encoding="utf-8")
    problems: list[str] = []
    newest = _newest_release()
    if newest is None:
        return ["cannot list SemVer tags to check what the newest release contains; "
                "fetch tags before reconciling the skill against the releases"]
    shipped = _git("cat-file", "-e", f"{newest}:{RESOLVER}").returncode == 0
    # The claim is prose and wraps, sometimes inside a shell comment, so match it
    # against the text with line breaks and comment markers folded away.
    flowed = re.sub(r"\s*\n\s*#?\s*", " ", text)
    claims_absent = re.search(
        rf"{re.escape(RESOLVER.split('/')[-1])}[^.]*does not exist in {re.escape(newest)}",
        flowed) is not None
    if shipped and claims_absent:
        problems.append(
            f"ci-consumer-adoption says {RESOLVER} does not exist in {newest}, but "
            "that release contains it; point the skill at the tag and drop the caveat")
    if not shipped and not claims_absent:
        problems.append(
            f"{RESOLVER} is not in {newest}, the newest release, but the skill does "
            "not say so — it also tells the reader to pin to a released tag, so the "
            "two instructions cannot both be obeyed without the caveat")
    return problems


def main() -> int:
    problems = check() + check_release_claim()
    if problems:
        print("check_consumer_skill_contract: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("check_consumer_skill_contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
