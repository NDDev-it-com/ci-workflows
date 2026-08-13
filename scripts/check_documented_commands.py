#!/usr/bin/env python3
"""Documented tool commands must be the commands `ci-gate` actually runs.

Four places in this repository told a contributor how to run zizmor locally and
three of them were wrong, each in a different way. `AGENTS.md` and the
`nddev-repo-flow` skill named `--persona regular`; `ci.yml` passes
`--persona pedantic`, which adds `undocumented-permissions`, so following the
brief gave a clean local run and a red required check. `CONTRIBUTING.md`
carried a comment reading "regular persona, matches CI" directly above a
command using pedantic, ran an unpinned `zizmor` off `PATH` against this
repository's own "never a mutable version" rule, and omitted `GH_TOKEN` from
both of its invocations — the exact omission `AGENTS.md` documents as how three
`ref-version-mismatch` findings reached the default branch, because a tokenless
zizmor silently skips its online audits and reports "No findings".

Nothing tied prose to the workflow tree, so all four drifted independently.
The version, severity and persona are read from the workflow inputs and from
what `ci.yml` really passes; the documents are checked against that.
"""
from __future__ import annotations

import re
import sys
from typing import Any

from ci_workflows_tools._workflow_yaml import REPO_ROOT, WORKFLOWS_DIR, get_on, load_yaml

# Where a contributor is told to run something. Skills are checked in both the
# authored tree and its generated mirror, because a consumer of either one is
# equally misled.
DOCUMENTS = (
    "AGENTS.md",
    "CONTRIBUTING.md",
    "README.md",
    ".agents/skills/nddev-repo-flow/SKILL.md",
    ".claude/skills/nddev-repo-flow/SKILL.md",
    ".agents/skills/ci-consumer-adoption/SKILL.md",
    ".claude/skills/ci-consumer-adoption/SKILL.md",
)

# A command line, not prose about one. Prose says "run zizmor at the version
# zizmor-sarif.yml pins"; a command carries a flag or a pin.
ZIZMOR_INVOCATION = re.compile(r"zizmor@|zizmor\b[^\n]*--(?:persona|min-severity)")
ACTIONLINT_ASSET = re.compile(r"actionlint_(\d+\.\d+\.\d+)_linux_amd64\.tar\.gz")
ACTIONLINT_RELEASE = re.compile(r"actionlint/releases/download/v(\d+\.\d+\.\d+)/")
SHA256 = re.compile(r"\b([0-9a-f]{64})\b")


def _input_defaults(filename: str) -> dict[str, Any]:
    document = load_yaml(WORKFLOWS_DIR / filename)
    call = (get_on(document) or {}).get("workflow_call") or {}
    return {
        name: spec.get("default")
        for name, spec in (call.get("inputs") or {}).items()
        if isinstance(spec, dict)
    }


def _self_call_inputs(job: str) -> dict[str, Any]:
    document = load_yaml(WORKFLOWS_DIR / "ci.yml")
    return (document.get("jobs", {}).get(job, {}) or {}).get("with", {}) or {}


def check() -> list[str]:
    problems: list[str] = []
    zizmor_defaults = _input_defaults("zizmor-sarif.yml")
    actionlint_defaults = _input_defaults("actionlint.yml")
    gate_inputs = _self_call_inputs("zizmor")

    version = zizmor_defaults.get("zizmor_version")
    severity = zizmor_defaults.get("min_severity")
    # What the required check really runs: the caller's value wins over the
    # reusable's default, and the caller is the authority a contributor is
    # trying to reproduce.
    persona = gate_inputs.get("persona", zizmor_defaults.get("persona"))
    actionlint_version = actionlint_defaults.get("actionlint_version")
    actionlint_sha256 = actionlint_defaults.get("actionlint_sha256")
    for label, value in (
        ("zizmor_version", version), ("min_severity", severity), ("persona", persona),
        ("actionlint_version", actionlint_version), ("actionlint_sha256", actionlint_sha256),
    ):
        if not isinstance(value, str) or not value:
            problems.append(f"cannot resolve {label} from the workflow tree")
    if problems:
        return problems

    for relative in DOCUMENTS:
        path = REPO_ROOT / relative
        if not path.is_file():
            problems.append(f"documented-command surface is missing: {relative}")
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            where = f"{relative}:{number}"
            if ZIZMOR_INVOCATION.search(line):
                if f"zizmor@{version}" not in line:
                    problems.append(
                        f"{where}: zizmor must be pinned as `uvx zizmor@{version}`; "
                        "an unpinned binary off PATH is not what CI runs"
                    )
                if f"--persona {persona}" not in line:
                    problems.append(
                        f"{where}: zizmor persona must be {persona!r}, which is what "
                        "ci.yml passes to the required check"
                    )
                if f"--min-severity {severity}" not in line:
                    problems.append(f"{where}: zizmor must use --min-severity {severity}")
                if "GH_TOKEN" not in line:
                    problems.append(
                        f"{where}: zizmor needs GH_TOKEN; without one it silently "
                        "skips its online audits and reports a false 'No findings'"
                    )
            asset = ACTIONLINT_ASSET.search(line) or ACTIONLINT_RELEASE.search(line)
            if asset and asset.group(1) != actionlint_version:
                problems.append(
                    f"{where}: actionlint {asset.group(1)} does not match the "
                    f"workflow default {actionlint_version}"
                )
            if "actionlint" in line and "sha256sum" in line:
                digests = set(SHA256.findall(line))
                if digests and actionlint_sha256 not in digests:
                    problems.append(
                        f"{where}: actionlint checksum does not match the workflow "
                        f"default {actionlint_sha256}"
                    )
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_documented_commands: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("check_documented_commands: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
