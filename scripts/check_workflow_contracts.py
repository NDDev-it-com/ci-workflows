#!/usr/bin/env python3
"""Reusable-workflow contract: every workflow except the self workflows
(`ci.yml`, `release.yml`) must be reusable (`on: workflow_call`). The self
workflows must NOT be reusable, and `ci.yml` must expose the `ci-gate` job that
branch protection requires as a status check. Caller-provided command runners
must also fail on the first failing command instead of returning the status of
only the final command. The Go pack's history-depth input remains a typed,
backward-compatible pass-through to checkout.
The private-free workflows used on persistent self-hosted fleets must also
isolate ambient global Git configuration before checkout so runner-owned
Authorization headers cannot combine with actions/checkout's scoped token.
"""
from __future__ import annotations

import re
import shlex
import sys

from _runners import is_standard_hosted
from _workflow_yaml import SELF_WORKFLOWS, get_on, is_reusable, load_yaml, workflow_files


def check() -> list[str]:
    problems: list[str] = []
    for path in workflow_files():
        doc = load_yaml(path)
        reusable = is_reusable(doc)
        if path.name in SELF_WORKFLOWS:
            if reusable:
                problems.append(f"{path.name}: self workflow must not be `on: workflow_call`")
        elif not reusable:
            problems.append(f"{path.name}: reusable workflow missing `on: workflow_call`")

    isolated_checkout_workflows = {
        "actionlint.yml",
        "cross-platform-smoke.yml",
        "private-static.yml",
        "public-codeql.yml",
        "secret-scan.yml",
        "zizmor-no-sarif.yml",
    }
    expected_isolation = """set -euo pipefail
umask 077
isolated_config="$RUNNER_TEMP/nddev-ci-global.gitconfig"
: > "$isolated_config"
printf 'GIT_CONFIG_GLOBAL=%s\\n' "$isolated_config" >> "$GITHUB_ENV"
"""
    workflow_root = workflow_files()[0].parent
    for filename in sorted(isolated_checkout_workflows):
        workflow = load_yaml(workflow_root / filename)
        jobs = workflow.get("jobs", {}) or {}
        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                continue
            steps = job.get("steps", []) or []
            checkout_indexes = [
                index
                for index, step in enumerate(steps)
                if isinstance(step, dict)
                and str(step.get("uses", "")).startswith("actions/checkout@")
            ]
            if not checkout_indexes:
                continue
            isolation_indexes = [
                index
                for index, step in enumerate(steps)
                if isinstance(step, dict)
                and step.get("name") == "Isolate global Git config"
                and step.get("shell") == "bash"
                and step.get("run") == expected_isolation
            ]
            if len(isolation_indexes) != 1 or isolation_indexes[0] >= min(
                checkout_indexes
            ):
                problems.append(
                    f"{filename}: job {job_name!r} must run the canonical global "
                    "Git-config isolation exactly once before checkout"
                )

    # This repository is public. Every local reusable call that exposes a
    # runner selector must choose a standard hosted runner explicitly; relying
    # on the reusable's private-consumer default can route public PR code to the
    # private self-hosted fleet when that default changes or remains stale.
    #
    # "Standard hosted", not the literal string `ubuntu-latest`. The rule used
    # to demand that one label, which enforced the property by accident and
    # forbade `macos-latest` — a standard hosted runner, unmetered on public
    # repositories exactly like ubuntu. That made `swift-ci.yml`, whose whole
    # purpose is macOS, impossible to call from this repository's own fixture
    # estate. What matters is that the choice is explicit and lands on a runner
    # every account resolves and nobody is billed for; _runners.py holds that
    # definition, shared with check_examples.py.
    for filename in sorted(SELF_WORKFLOWS):
        caller = load_yaml(workflow_root / filename)
        for job_name, job in (caller.get("jobs", {}) or {}).items():
            if not isinstance(job, dict):
                continue
            use = str(job.get("uses", ""))
            prefix = "./.github/workflows/"
            if not use.startswith(prefix):
                continue
            reusable_path = workflow_root / use.removeprefix(prefix)
            reusable = load_yaml(reusable_path)
            reusable_on = get_on(reusable)
            call = (
                reusable_on.get("workflow_call", {})
                if isinstance(reusable_on, dict)
                else {}
            )
            inputs = call.get("inputs", {}) if isinstance(call, dict) else {}
            if not isinstance(inputs, dict) or "runner" not in inputs:
                continue
            with_values = job.get("with", {}) or {}
            chosen = with_values.get("runner") if isinstance(with_values, dict) else None
            if chosen is None:
                problems.append(
                    f"{filename}: public self-call job {job_name!r} must select a "
                    "standard hosted runner explicitly — inheriting the reusable's "
                    "default can route public pull-request code to a private fleet"
                )
            elif not is_standard_hosted(chosen):
                problems.append(
                    f"{filename}: public self-call job {job_name!r} selects "
                    f"{chosen!r}, which is not a standard hosted runner. Standard "
                    "runners are unmetered on public repositories in all three "
                    "operating systems; larger runners are billed there from the "
                    "first minute, and a self-hosted label makes a forked pull "
                    "request remote code execution on that hardware"
                )

    ci = load_yaml((workflow_files()[0].parent / "ci.yml"))
    jobs = ci.get("jobs", {}) or {}
    if "ci-gate" not in jobs:
        problems.append("ci.yml: missing required `ci-gate` job (branch-protection status check)")

    go_ci = load_yaml((workflow_files()[0].parent / "go-ci.yml"))
    go_on = get_on(go_ci)
    go_call = go_on.get("workflow_call", {}) if isinstance(go_on, dict) else {}
    go_inputs = go_call.get("inputs", {}) if isinstance(go_call, dict) else {}
    fetch_depth = go_inputs.get("fetch_depth", {}) if isinstance(go_inputs, dict) else {}
    if not isinstance(fetch_depth, dict) or (
        fetch_depth.get("type") != "number" or fetch_depth.get("default") != 1
    ):
        problems.append(
            "go-ci.yml: fetch_depth must remain a number with the "
            "backward-compatible default 1"
        )
    cache = go_inputs.get("cache", {}) if isinstance(go_inputs, dict) else {}
    if not isinstance(cache, dict) or (
        cache.get("type") != "boolean" or cache.get("default") is not True
    ):
        problems.append(
            "go-ci.yml: cache must remain a boolean with the "
            "backward-compatible default true"
        )
    go_steps = go_ci.get("jobs", {}).get("go", {}).get("steps", [])
    checkout = next(
        (
            step
            for step in go_steps
            if isinstance(step, dict) and step.get("name") == "Checkout"
        ),
        {},
    )
    checkout_with = checkout.get("with", {})
    actual_depth = (
        checkout_with.get("fetch-depth")
        if isinstance(checkout_with, dict)
        else None
    )
    if actual_depth != "${{ inputs.fetch_depth }}":
        problems.append(
            "go-ci.yml: Checkout must pass fetch_depth through to actions/checkout"
        )
    setup_go = next(
        (
            step
            for step in go_steps
            if isinstance(step, dict) and step.get("name") == "Set up Go"
        ),
        {},
    )
    setup_go_with = setup_go.get("with", {})
    actual_cache = (
        setup_go_with.get("cache")
        if isinstance(setup_go_with, dict)
        else None
    )
    if actual_cache != "${{ inputs.cache }}":
        problems.append(
            "go-ci.yml: Set up Go must pass cache through to actions/setup-go"
        )

    private_static = load_yaml((workflow_files()[0].parent / "private-static.yml"))
    static_steps = private_static.get("jobs", {}).get("static", {}).get("steps", [])
    steps_by_name = {step.get("name"): step for step in static_steps if isinstance(step, dict)}
    fail_fast_commands = {
        "Run install command": 'bash -euo pipefail -c "$INSTALL_COMMAND"',
        "Run validation": 'bash -euo pipefail -c "$VALIDATION_COMMAND"',
    }
    for name, expected in fail_fast_commands.items():
        actual = steps_by_name.get(name, {}).get("run")
        if actual != expected:
            problems.append(
                f"private-static.yml: {name!r} must use the fail-fast runner {expected!r}"
            )

    # The fail-fast contract above was written for private-static.yml alone
    # while 47 other caller-command sites across 23 workflows ran plain
    # `bash -c "$CMD"`. That inner shell inherits nothing from the step's
    # shell, so a caller passing `lint; test` or `build | tee log` got exit 0
    # from a failing first command — the reusable reported success for a build
    # that did not succeed. The rule is the same everywhere a caller's command
    # is executed, so it is enforced everywhere.
    problems += _fail_fast_caller_commands()
    problems += _balanced_caller_commands()
    problems += _runner_selftest()
    return problems


BARE_BASH_C = re.compile(r'\bbash -c "(\$\{?[A-Za-z_][A-Za-z0-9_]*\}?)"')
# Inputs whose value is handed to a shell by the reusable that receives it.
COMMAND_INPUT = re.compile(r"(^|_)commands?$")


def _balanced_caller_commands() -> list[str]:
    """A command passed to a reusable must be shell-parseable.

    An unbalanced quote in one of these is invisible to every check this
    repository had: the YAML is valid, so actionlint passes; the value is just a
    string, so no schema complains; and the failure surfaces only when a runner
    reaches `bash: unexpected EOF while looking for matching \"`. That is a
    real minute of CI and a confusing log to reach a typo. `shlex` settles it in
    microseconds.

    This checks parseability, not safety: these strings are caller-authored by
    design, and the reusables run them through `bash -euo pipefail -c` on
    purpose.
    """
    problems: list[str] = []
    for path in workflow_files():
        for job_name, job in (load_yaml(path).get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            for key, value in (job.get("with") or {}).items():
                if not isinstance(value, str) or not COMMAND_INPUT.search(str(key)):
                    continue
                try:
                    shlex.split(value)
                except ValueError as exc:
                    problems.append(
                        f"{path.name}: job {job_name!r} input {key!r} is not "
                        f"shell-parseable ({exc}): {value[:70]!r}"
                    )
    return problems


def _fail_fast_caller_commands() -> list[str]:
    """Any `bash -c "$VAR"` running a caller command must set -euo pipefail."""
    problems: list[str] = []
    for path in workflow_files():
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            match = BARE_BASH_C.search(line)
            if match:
                problems.append(
                    f"{path.name}:{lineno}: `bash -c \"{match.group(1)}\"` does not "
                    "fail fast; use `bash -euo pipefail -c` so a caller command "
                    "like `a; b` or `a | b` cannot report success after failing"
                )
    return problems


def _runner_selftest() -> list[str]:
    """The shared runner predicate must keep saying no to the expensive answers.

    Widening this rule from the literal `ubuntu-latest` to "standard hosted" is
    only safe while the three things it was protecting against still fail:
    a larger runner (hosted, but billed on public repositories from the first
    minute), a self-hosted fleet label (a forked pull request becomes remote
    code execution on that hardware), and a missing or non-string value.
    """
    expectations = {
        # standard hosted, all three operating systems, latest and pinned
        "ubuntu-latest": True, "macos-latest": True, "windows-latest": True,
        "ubuntu-24.04": True, "macos-14": True, "windows-2022": True,
        # larger runners: hosted, never free
        "ubuntu-latest-8-cores": False, "ubuntu-latest-4-cores": False,
        "macos-latest-large": False, "windows-latest-xlarge": False,
        # somebody's fleet
        "nddev-linux-fast": False, "nddev-linux-release": False,
        "self-hosted": False, "amsterdam": False,
        # nothing at all
        "": False,
    }
    problems = []
    for label, expected in expectations.items():
        if is_standard_hosted(label) is not expected:
            problems.append(
                f"_runners.is_standard_hosted({label!r}) is "
                f"{is_standard_hosted(label)}, expected {expected}"
            )
    for value in (None, 123, ["ubuntu-latest"]):
        if is_standard_hosted(value):
            problems.append(
                f"_runners.is_standard_hosted({value!r}) accepted a non-string"
            )
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_workflow_contracts: FAIL", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print("check_workflow_contracts: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
