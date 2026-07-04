#!/usr/bin/env python3
"""Validate the machine-readable capability catalog under `catalog/`.

Enforces the uniform capability schema so `catalog/` stays a trustworthy source
of truth that `docs/` mirror. Requires PyYAML.
"""
from __future__ import annotations

import sys
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_DIR = REPO_ROOT / "catalog"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
EXAMPLES_DIR = REPO_ROOT / "examples"
SCHEMA_FILE = CATALOG_DIR / "schema" / "capability.schema.yaml"

CAP_FIELDS = {
    "id", "name", "cluster", "status",
    "public_oss", "private_free", "private_paid",
    "workflow", "example", "required_permissions", "required_settings",
    "risks", "deprecations", "last_verified", "sources",
}
VALID_STATUS = {"ga", "preview", "deprecated", "retiring", "planned"}
VALID_TIER_AVAIL = {"free", "paid", "unavailable", "conditional"}
VALID_PRIVATE_PAID = {"available", "unavailable", "conditional"}
VALID_CLUSTERS = {
    "actions-core", "runners", "security-scanning", "supply-chain",
    "governance", "releases-packages", "deployments", "observability",
    "community-dx", "external-tools", "ai-agentic",
}
PIN_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[^@\\s]+)?@[0-9a-f]{40}(?:@sha256:[0-9a-f]{64})?$")
CONTAINER_PIN_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+:[^\\s@]+@sha256:[0-9a-f]{64}$")


def _load(name: str, problems: list[str]):
    path = CATALOG_DIR / name
    if not path.is_file():
        problems.append(f"missing catalog file: {name}")
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        problems.append(f"{name}: invalid YAML: {exc}")
        return None


def check() -> list[str]:
    problems: list[str] = []
    if not CATALOG_DIR.is_dir():
        return [f"missing catalog directory: {CATALOG_DIR}"]
    if not SCHEMA_FILE.is_file():
        problems.append(f"missing machine-readable schema file: {SCHEMA_FILE.relative_to(REPO_ROOT)}")

    caps_doc = _load("capabilities.yml", problems)
    if isinstance(caps_doc, dict):
        caps = caps_doc.get("capabilities", [])
        seen_ids: set[str] = set()
        workflows_in_catalog: set[str] = set()
        examples_in_catalog: set[str] = set()
        for cap in caps:
            if not isinstance(cap, dict):
                problems.append("capabilities: entry is not a mapping")
                continue
            cid = cap.get("id", "<no-id>")
            missing = CAP_FIELDS - set(cap.keys())
            extra = set(cap.keys()) - CAP_FIELDS
            if missing:
                problems.append(f"capability `{cid}`: missing fields {sorted(missing)}")
            if extra:
                problems.append(f"capability `{cid}`: unexpected fields {sorted(extra)}")
            if cid in seen_ids:
                problems.append(f"capability `{cid}`: duplicate id")
            seen_ids.add(cid)
            if cap.get("cluster") not in VALID_CLUSTERS:
                problems.append(f"capability `{cid}`: invalid cluster {cap.get('cluster')!r}")
            if cap.get("status") not in VALID_STATUS:
                problems.append(f"capability `{cid}`: invalid status {cap.get('status')!r}")
            if cap.get("public_oss") not in VALID_TIER_AVAIL:
                problems.append(f"capability `{cid}`: invalid public_oss {cap.get('public_oss')!r}")
            if cap.get("private_free") not in VALID_TIER_AVAIL:
                problems.append(f"capability `{cid}`: invalid private_free {cap.get('private_free')!r}")
            if cap.get("private_paid") not in VALID_PRIVATE_PAID:
                problems.append(f"capability `{cid}`: invalid private_paid {cap.get('private_paid')!r}")
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
            sources = cap.get("sources", [])
            if not sources:
                problems.append(f"capability `{cid}`: sources must be non-empty")
            for source in sources:
                if not isinstance(source, str) or not source.startswith("https://"):
                    problems.append(f"capability `{cid}`: source is not an https URL: {source!r}")
        workflow_files = {
            f".github/workflows/{path.name}"
            for path in WORKFLOWS_DIR.glob("*.yml")
            if path.name not in {"ci.yml", "release.yml"}
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
            "examples/private-paid-ghas/security.yml",
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
                if not (REPO_ROOT / used_by).exists():
                    problems.append(f"tool `{tid}`: used_by path does not exist: {used_by}")
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
