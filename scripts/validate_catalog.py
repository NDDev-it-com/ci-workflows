#!/usr/bin/env python3
"""Validate the machine-readable capability catalog under `catalog/`.

Enforces the uniform capability schema so `catalog/` stays a trustworthy source
of truth that `docs/` mirror. Requires PyYAML.

The per-entry shape — required keys, allowed keys, enums and string patterns —
is asserted by executing `catalog/schema/capability.schema.yaml` rather than by
a second copy of those rules in Python. Both used to exist and disagreed: the
schema forbade `runtime_requirements`, which two capabilities declare, while
this file allowed it, and neither noticed that `last_verified` had drifted to
`datetime.date` in seven entries because nothing ever ran the schema's pattern.
What stays here is everything a schema cannot express — that a `workflow:` path
is really on disk, that a tool pin matches the bytes the workflow uses, that
every reusable has an entry at all.
"""
from __future__ import annotations

import sys
import re
from pathlib import Path

import yaml

from ci_workflows_tools import _json_schema

from ci_workflows_tools._strict_yaml import strict_load

from ci_workflows_tools._workflow_yaml import SELF_WORKFLOWS

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_DIR = REPO_ROOT / "catalog"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
EXAMPLES_DIR = REPO_ROOT / "examples"
SCHEMA_FILE = CATALOG_DIR / "schema" / "capability.schema.yaml"

PIN_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[^@\\s]+)?@[0-9a-f]{40}(?:@sha256:[0-9a-f]{64})?$")
CONTAINER_PIN_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+:[^\\s@]+@sha256:[0-9a-f]{64}$")


def _load(name: str, problems: list[str]):
    path = CATALOG_DIR / name
    if not path.is_file():
        problems.append(f"missing catalog file: {name}")
        return None
    try:
        return strict_load(path)
    except yaml.YAMLError as exc:
        problems.append(f"{name}: invalid YAML: {exc}")
        return None


def check() -> list[str]:
    problems: list[str] = []
    if not CATALOG_DIR.is_dir():
        return [f"missing catalog directory: {CATALOG_DIR}"]
    problems += _json_schema.selftest()
    schema = None
    if not SCHEMA_FILE.is_file():
        problems.append(f"missing machine-readable schema file: {SCHEMA_FILE.relative_to(REPO_ROOT)}")
    else:
        try:
            schema = strict_load(SCHEMA_FILE)
        except yaml.YAMLError as exc:
            problems.append(f"capability.schema.yaml: invalid YAML: {exc}")

    caps_doc = _load("capabilities.yml", problems)
    if isinstance(caps_doc, dict):
        # Execute the published schema against the published catalog. This is
        # the whole assertion for per-entry shape; anything the schema can
        # express must live there and not be restated below.
        if schema is not None:
            problems += [
                f"capabilities.yml: {issue}"
                for issue in _json_schema.validate(caps_doc, schema)
            ]
        caps = caps_doc.get("capabilities", [])
        seen_ids: set[str] = set()
        workflows_in_catalog: set[str] = set()
        examples_in_catalog: set[str] = set()
        for cap in caps:
            if not isinstance(cap, dict):
                problems.append("capabilities: entry is not a mapping")
                continue
            cid = cap.get("id", "<no-id>")
            if cid in seen_ids:
                problems.append(f"capability `{cid}`: duplicate id")
            seen_ids.add(cid)
            wf = cap.get("workflow")
            if wf:
                workflows_in_catalog.add(wf)
                if not (REPO_ROOT / wf).exists():
                    problems.append(f"capability `{cid}`: workflow path does not exist: {wf}")
                stale_absence_claims = [
                    risk for risk in cap.get("risks", [])
                    if isinstance(risk, str) and "Workflow not yet present on disk" in risk
                ]
                if stale_absence_claims and (REPO_ROOT / wf).exists():
                    problems.append(f"capability `{cid}`: stale risk claims workflow is not present: {wf}")
            example = cap.get("example")
            if example:
                examples_in_catalog.add(example)
                if not (REPO_ROOT / example).exists():
                    problems.append(f"capability `{cid}`: example path does not exist: {example}")
        workflow_files = {
            f".github/workflows/{path.name}"
            for path in WORKFLOWS_DIR.glob("*.yml")
            if path.name not in SELF_WORKFLOWS
        }
        missing_workflows = workflow_files - workflows_in_catalog
        if missing_workflows:
            problems.append(f"catalog missing workflow capability entries: {sorted(missing_workflows)}")
        example_files = {
            str(path.relative_to(REPO_ROOT))
            for path in EXAMPLES_DIR.rglob("*.yml")
        }
        missing_examples = example_files - examples_in_catalog
        # Security-suite examples aggregate multiple capabilities; release examples
        # can map to release-supply-chain or trusted-publishing capabilities.
        allowed_aggregate_examples = {
            "examples/public-oss/security.yml",
            "examples/private-free/security.yml",
            "examples/private-free/security-selfhosted.yml",
            "examples/private-paid-ghas/security.yml",
            "examples/nddev/security.yml",
            "examples/nddev/security-private-selfhosted.yml",
            "examples/nddev/os-capability-routing.yml",
            "examples/personal/security-selfhosted.yml",
        }
        missing_examples -= allowed_aggregate_examples
        if missing_examples:
            problems.append(f"catalog missing example references: {sorted(missing_examples)}")
    else:
        problems.append("capabilities.yml: missing top-level `capabilities:` list")

    tools_doc = _load("tools.yml", problems)
    if isinstance(tools_doc, dict):
        seen_tool_ids: set[str] = set()
        for tool in tools_doc.get("tools", []):
            if not isinstance(tool, dict):
                problems.append("tools.yml: entry is not a mapping")
                continue
            tid = tool.get("id", "<no-id>")
            if tid in seen_tool_ids:
                problems.append(f"tool `{tid}`: duplicate id")
            seen_tool_ids.add(tid)
            pin = tool.get("pin")
            kind = tool.get("kind")
            if kind in {"action", "container"} and not pin:
                problems.append(f"tool `{tid}`: {kind} tool must record an immutable pin")
            if isinstance(pin, str):
                if "#" in pin:
                    problems.append(f"tool `{tid}`: pin value must not include comments: {pin}")
                if kind == "action" and not PIN_RE.match(pin):
                    problems.append(f"tool `{tid}`: action pin is not a full-SHA ref: {pin}")
                if kind == "container" and not CONTAINER_PIN_RE.match(pin):
                    problems.append(f"tool `{tid}`: container pin is not digest-pinned: {pin}")
            for used_by in tool.get("used_by", []):
                used_path = REPO_ROOT / used_by
                if not used_path.exists():
                    problems.append(f"tool `{tid}`: used_by path does not exist: {used_by}")
                    continue
                # The catalog is the declared source of truth for supply-chain
                # posture, so a pin it records must be the pin the workflow
                # actually uses. Checking only the pin's shape let four tools
                # drift a full version behind (setup-swift by a major) while
                # the gate stayed green.
                if kind != "action" or not isinstance(pin, str) or "@" not in pin:
                    continue
                action_ref, pinned_sha = pin.split("@", 1)
                actual = set(
                    re.findall(
                        rf"{re.escape(action_ref)}@([0-9a-f]{{40}})",
                        used_path.read_text(encoding="utf-8"),
                    )
                )
                for found in sorted(actual - {pinned_sha}):
                    problems.append(
                        f"tool `{tid}`: catalog pin {pinned_sha} does not match "
                        f"{found} used in {used_by}"
                    )
    elif tools_doc is not None:
        problems.append("tools.yml: expected a top-level mapping")

    for extra_file in ("deprecations.yml",):
        doc = _load(extra_file, problems)
        if doc is not None and not isinstance(doc, dict):
            problems.append(f"{extra_file}: expected a top-level mapping")
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("validate_catalog: FAIL", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print("validate_catalog: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
