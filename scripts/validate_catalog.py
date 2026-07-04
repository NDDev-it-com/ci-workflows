#!/usr/bin/env python3
"""Validate the machine-readable capability catalog under `catalog/`.

Enforces the uniform capability schema so `catalog/` stays a trustworthy source
of truth that `docs/` mirror. Requires PyYAML.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_DIR = REPO_ROOT / "catalog"

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

    caps_doc = _load("capabilities.yml", problems)
    if isinstance(caps_doc, dict):
        caps = caps_doc.get("capabilities", [])
        seen_ids: set[str] = set()
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
            if wf and not (REPO_ROOT / wf).exists():
                problems.append(f"capability `{cid}`: workflow path does not exist: {wf}")
    else:
        problems.append("capabilities.yml: missing top-level `capabilities:` list")

    for extra_file in ("tools.yml", "deprecations.yml"):
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
