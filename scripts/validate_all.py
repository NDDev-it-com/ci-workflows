#!/usr/bin/env python3
"""Aggregate static validator for nddev-ci-workflows.

Runs every repository self-check and exits non-zero if any fails. This is the
single source of truth invoked by `ci.yml` and by contributors locally.

Checks:
  - pinned actions (full-SHA + version comment)
  - least-privilege permissions + timeouts
  - reusable-workflow contract
  - ruleset JSON shape
  - capability catalog schema
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_permissions
import check_pinned_actions
import check_rulesets
import check_workflow_contracts
import validate_catalog

CHECKS = [
    ("pinned-actions", check_pinned_actions.check),
    ("permissions", check_permissions.check),
    ("workflow-contracts", check_workflow_contracts.check),
    ("rulesets", check_rulesets.check),
    ("catalog", validate_catalog.check),
]


def main() -> int:
    failed = False
    for label, fn in CHECKS:
        problems = fn()
        if problems:
            failed = True
            print(f"[FAIL] {label}")
            for p in problems:
                print(f"    - {p}")
        else:
            print(f"[ OK ] {label}")
    if failed:
        print("\nvalidate_all: FAIL", file=sys.stderr)
        return 1
    print("\nvalidate_all: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
