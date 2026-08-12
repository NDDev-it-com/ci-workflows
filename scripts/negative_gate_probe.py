#!/usr/bin/env python3
"""Run a reusable's real gate step against a fixture and assert how it exits.

The fixture estate proves a workflow starts and passes on good input. That is
half a proof: a gate that never fails is not a gate. The obvious way to prove
the other half — call the reusable with a broken fixture and expect the job to
fail — is unavailable, because `continue-on-error` is rejected on a job that
calls a reusable with `uses:`. Every such expected failure would therefore turn
the whole run red, and a permanently red workflow is indistinguishable from a
broken one at a glance.

So this takes the same route `check_gate_contract.py` takes for gate.yml: read
the workflow, lift out the exact step that does the gating, and execute it
directly. Run inside an ordinary job, the exit code is just data, so the run
stays green while still exercising the bytes that ship.

What is executed is the step's own `run:` text with its own `env:` block, with
`${{ inputs.X }}` resolved from values supplied on the command line. Nothing is
paraphrased: if someone edits the step, this runs the edited step, and if
someone renames it this fails loudly rather than silently testing nothing.

Both directions run in one invocation, and that is deliberate rather than
convenient. The first version took a single `--expect fail`, and the very first
local run reported "gate refused as required" when the real reason was
`terraform: command not found` — exit 127. A missing tool is indistinguishable
from a working gate if you only ever look at the failing side. So:

* `--bad` must make the step exit non-zero — the claim the estate could not
  make before;
* `--good` must make the same step exit zero — the control that proves the
  probe can tell the two apart at all.

Exit 127 is rejected outright in either direction, because "there was no
command to run" is never evidence about a gate.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _strict_yaml import strict_load  # noqa: E402

INPUT_EXPR = re.compile(r"\$\{\{\s*inputs\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
OTHER_EXPR = re.compile(r"\$\{\{(.+?)\}\}")


def _resolve(value: str, inputs: dict[str, str]) -> str:
    """Substitute `${{ inputs.X }}` from `inputs`; refuse anything else."""
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in inputs:
            raise SystemExit(
                f"negative_gate_probe: step needs input {name!r}, not supplied. "
                f"Pass --input {name}=<value>."
            )
        return inputs[name]

    resolved = INPUT_EXPR.sub(replace, value)
    leftover = OTHER_EXPR.search(resolved)
    if leftover:
        # runner.os, matrix.*, secrets.* and friends cannot be reproduced here.
        # Guessing at them would make the probe test something other than the
        # workflow, so it stops instead.
        raise SystemExit(
            f"negative_gate_probe: cannot resolve expression "
            f"'${{{{{leftover.group(1)}}}}}' outside a runner"
        )
    return resolved


def declared_defaults(workflow: Path) -> dict[str, str]:
    """The reusable's own `workflow_call` input defaults.

    Unsupplied inputs fall back to these rather than being repeated on the
    command line. hadolint pins both a version and a sha256; copying them into
    a caller would create a second place to update and a silent way for the
    probe to test a different binary than the workflow ships.
    """
    document = strict_load(workflow)
    triggers = document.get(True) or document.get("on") or {}
    call = triggers.get("workflow_call") or {} if isinstance(triggers, dict) else {}
    inputs = call.get("inputs") or {}
    return {
        name: str(spec.get("default"))
        for name, spec in inputs.items()
        if isinstance(spec, dict) and spec.get("default") is not None
    }


def find_step(workflow: Path, job_id: str, step_name: str) -> dict:
    document = strict_load(workflow)
    jobs = document.get("jobs") or {}
    if job_id not in jobs:
        raise SystemExit(
            f"negative_gate_probe: {workflow.name} has no job {job_id!r} "
            f"(has {sorted(jobs)})"
        )
    for step in jobs[job_id].get("steps") or []:
        if isinstance(step, dict) and step.get("name") == step_name:
            if "run" not in step:
                raise SystemExit(
                    f"negative_gate_probe: step {step_name!r} is a `uses:` step; "
                    "an action cannot be lifted out of its runner"
                )
            return step
    names = [s.get("name") for s in jobs[job_id].get("steps") or [] if isinstance(s, dict)]
    raise SystemExit(
        f"negative_gate_probe: {workflow.name} job {job_id!r} has no step "
        f"{step_name!r}. Steps present: {names}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--step", required=True)
    parser.add_argument("--bad", required=True,
                        help="Directory to run the rejecting case in.")
    parser.add_argument("--good", required=True,
                        help="Directory to run the accepting case in.")
    parser.add_argument(
        "--before", default=None, metavar="STEP",
        help="Step to run first, once, in --good. For gates whose tool an "
             "earlier step installs (hadolint downloads its own binary), so "
             "the probe exercises that step too instead of assuming it ran.",
    )
    parser.add_argument(
        "--bad-input", action="append", default=[], metavar="NAME=VALUE",
        help="Input override for the rejecting case. Some gates vary by input "
             "rather than by directory: hadolint takes a `dockerfile` path, so "
             "both cases run in the same tree.",
    )
    parser.add_argument(
        "--good-input", action="append", default=[], metavar="NAME=VALUE",
        help="Input override for the accepting case.",
    )
    parser.add_argument(
        "--input", action="append", default=[], metavar="NAME=VALUE",
        help="Value for a `${{ inputs.NAME }}` reference in the step's env.",
    )
    args = parser.parse_args()

    inputs = declared_defaults(Path(args.workflow))
    for item in args.input:
        name, _, value = item.partition("=")
        inputs[name] = value

    def parse(pairs: list[str]) -> dict[str, str]:
        out = {}
        for item in pairs:
            name, _, value = item.partition("=")
            out[name] = value
        return out

    step = find_step(Path(args.workflow), args.job, args.step)

    def env_for(overrides: dict[str, str]) -> dict[str, str]:
        merged = {**inputs, **overrides}
        env = dict(os.environ)
        for key, value in (step.get("env") or {}).items():
            env[key] = _resolve(str(value), merged)
        # Steps append to the job summary; give them somewhere harmless.
        env.setdefault("GITHUB_STEP_SUMMARY", os.devnull)
        return env

    def run_in(directory: str, body: str, env: dict[str, str]) -> int:
        completed = subprocess.run(
            ["bash", "-e", "-c", body], cwd=directory, env=env, check=False,
        )
        return completed.returncode

    label = f"{Path(args.workflow).name}:{args.step}"
    problems: list[str] = []

    if args.before:
        prior = find_step(Path(args.workflow), args.job, args.before)
        print(f"── {label}: preparing with step {args.before!r}")
        prior_env = dict(os.environ)
        for key, value in (prior.get("env") or {}).items():
            prior_env[key] = _resolve(str(value), inputs)
        prior_env.setdefault("GITHUB_STEP_SUMMARY", os.devnull)
        if run_in(args.good, prior["run"], prior_env) != 0:
            print(
                f"✗ {label}: preparatory step {args.before!r} failed, so nothing "
                "below proves anything about the gate.",
                file=sys.stderr,
            )
            return 1

    print(f"── {label}: must REJECT {args.bad}")
    bad_code = run_in(args.bad, step["run"], env_for(parse(args.bad_input)))
    print(f"── {label}: must ACCEPT {args.good}")
    good_code = run_in(args.good, step["run"], env_for(parse(args.good_input)))

    for code, where in ((bad_code, args.bad), (good_code, args.good)):
        if code == 127:
            problems.append(
                f"{label}: exit 127 in {where} — the command does not exist on "
                "this runner. That is a missing toolchain, not a verdict about "
                "the gate, and treating it as one is how a negative test rots "
                "into a no-op."
            )
    if not problems:
        if bad_code == 0:
            problems.append(
                f"{label}: ACCEPTED {args.bad}, a fixture built to break it. "
                "Either the fixture stopped being broken or the gate stopped "
                "gating; both make this lane worthless."
            )
        if good_code != 0:
            problems.append(
                f"{label}: REJECTED the clean fixture {args.good} "
                f"(exit {good_code}). Until this passes the probe cannot be "
                "trusted to tell good input from bad."
            )

    if problems:
        for problem in problems:
            print(f"✗ {problem}", file=sys.stderr)
        return 1
    print(f"✓ {label}: refused {args.bad} (exit {bad_code}), accepted {args.good}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
