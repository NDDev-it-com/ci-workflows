#!/usr/bin/env python3
"""Aggregate static validator for ci-workflows.

Runs every repository self-check and exits non-zero if any fails. This is the
single source of truth invoked by `ci.yml` and by contributors locally.

Checks:
  - pinned actions (full-SHA + version comment)
  - least-privilege permissions + timeouts
  - reusable-workflow contract
  - release supply-chain asset/archive/version contract
  - copy-paste example contract
  - Markdown local link health
  - merge_queue / merge_group trigger compatibility
  - ruleset JSON shape
  - capability catalog schema
  - generated docs drift
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_actionlint_contract
import check_benchmark_contract
import check_permissions
import check_pinned_actions
import check_tool_pinning
import check_release_supply_chain
import check_docs_links
import check_examples
import check_harden_runner_contract
import check_merge_group
import check_monorepo_routing
import check_rulesets
import check_skills
import check_workflow_contracts
import generate_docs
import validate_catalog
import validate_product_facts
import validate_runtime_coverage

CHECKS = [
    ("pinned-actions", check_pinned_actions.check),
    ("tool-pinning", check_tool_pinning.check),
    ("permissions", check_permissions.check),
    ("workflow-contracts", check_workflow_contracts.check),
    ("harden-runner-contract", check_harden_runner_contract.check),
    ("release-supply-chain", check_release_supply_chain.check),
    ("monorepo-routing", check_monorepo_routing.check),
    ("benchmark-contract", check_benchmark_contract.check),
    ("actionlint-contract", check_actionlint_contract.check),
    ("examples", check_examples.check),
    ("docs-links", check_docs_links.check),
    ("merge-group", check_merge_group.check),
    ("rulesets", check_rulesets.check),
    ("catalog", validate_catalog.check),
    ("product-facts", validate_product_facts.check),
    ("runtime-coverage", validate_runtime_coverage.check),
    ("skills", check_skills.check),
    ("generated-docs", generate_docs.check),
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
