#!/usr/bin/env python3
"""Reusable workflows must pin the uv/bun tools they run.

`uvx`/`bunx` resolve an unversioned tool name to the registry's *latest*
release at run time, so an empty version input or a bare `uvx <tool>` /
`bunx <tool>` silently floats the tool across runs — the same class of
non-reproducibility this repo already forbids for actions (full-SHA pins).
This check enforces that every tool executed through `uvx`/`bunx` is pinned:
either an explicit `@<version>` in the command, or a `${VAR:+@$VAR}`
conditional whose backing `workflow_call` version input has a non-empty
default.

Deliberately narrow: this library is multi-ecosystem, and language toolchains
are provisioned by their own setup actions with caller-owned commands. The
contract enforced here is only that uv/bun *tool versions* are reproducible;
it does not police pip/npm/caller commands.
"""
from __future__ import annotations

import re
import sys
from typing import Any

from _workflow_yaml import get_on, load_yaml, workflow_files

# `${VAR:+@$VAR}` / `${VAR:+@${VAR}}` — a conditional "@version" that expands to
# nothing (→ latest) when VAR is empty.
COND_PIN_RE = re.compile(r"\$\{(\w+):\+@\$\{?(\w+)\}?\}")
# `${{ inputs.name }}` binding inside an env value.
INPUT_BIND_RE = re.compile(r"\$\{\{\s*inputs\.([A-Za-z0-9_]+)\s*\}\}")
# `uvx`/`bunx <flags...> <tool-token>`; not preceded by a path/word char.
RUNNER_RE = re.compile(r"(?<![\w./-])(uvx|bunx)\s+((?:-{1,2}[\w-]+\s+)*)(\S+)")


def _inputs(doc: dict[str, Any]) -> dict[str, Any]:
    on = get_on(doc)
    if not isinstance(on, dict):
        return {}
    call = on.get("workflow_call") or {}
    inputs = call.get("inputs") if isinstance(call, dict) else None
    return inputs if isinstance(inputs, dict) else {}


def _iter_steps(doc: dict[str, Any]):
    for job in (doc.get("jobs", {}) or {}).values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps", []) or []:
            if isinstance(step, dict):
                yield step


def _env_to_input(doc: dict[str, Any]) -> dict[str, str]:
    """Map a shell ENV var to the input it is bound to, across every env scope."""
    mapping: dict[str, str] = {}
    scopes: list[Any] = [doc.get("env", {})]
    for job in (doc.get("jobs", {}) or {}).values():
        if isinstance(job, dict):
            scopes.append(job.get("env", {}))
    for step in _iter_steps(doc):
        scopes.append(step.get("env", {}))
    for env in scopes:
        if not isinstance(env, dict):
            continue
        for var, val in env.items():
            m = INPUT_BIND_RE.search(str(val))
            if m:
                mapping[str(var)] = m.group(1)
    return mapping


def check() -> list[str]:
    problems: list[str] = []
    for path in workflow_files():
        doc = load_yaml(path)
        if not isinstance(doc, dict):
            continue
        name = path.name
        inputs = _inputs(doc)
        env_map = _env_to_input(doc)

        # The only shell text policed: run bodies + string input defaults.
        snippets: list[str] = []
        for step in _iter_steps(doc):
            run = step.get("run")
            if isinstance(run, str):
                snippets.append(run)
        for spec in inputs.values():
            if isinstance(spec, dict) and isinstance(spec.get("default"), str):
                snippets.append(spec["default"])
        text = "\n".join(snippets)

        # Rule A: `${VAR:+@$VAR}` requires a non-empty backing input default.
        for m in COND_PIN_RE.finditer(text):
            var = m.group(1)
            input_name = env_map.get(var)
            if input_name is None:
                problems.append(
                    f"{name}: `${{{var}:+@...}}` tool-version pin is not bound to "
                    f"a workflow_call input, so its pinning cannot be proven"
                )
                continue
            spec = inputs.get(input_name, {})
            default = spec.get("default") if isinstance(spec, dict) else None
            if not isinstance(default, str) or default == "":
                problems.append(
                    f"{name}: input `{input_name}` feeds a uv/bun tool-version "
                    f"pin but its default is empty — an empty version resolves "
                    f"to the latest release (mutable); set an explicit default"
                )

        # Rule B: bare `uvx <tool>` / `bunx <tool>` with no @version.
        for m in RUNNER_RE.finditer(text):
            runner, tool = m.group(1), m.group(3).strip().strip("'\"")
            if tool.startswith("$") or "${" in tool:
                continue  # shell-var driven (covered by Rule A / explicit @$VAR)
            if "@" in tool:
                continue  # explicit @version
            problems.append(
                f"{name}: `{runner} {tool}` is unpinned — it floats to the "
                f"latest release; add an explicit `@<version>`"
            )
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_tool_pinning: FAIL", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print("check_tool_pinning: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
