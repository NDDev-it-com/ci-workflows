#!/usr/bin/env python3
"""Aggregate static validator for ci-workflows.

Runs the repository self-checks and exits non-zero if any fails. Invoked by
`ci.yml` and by contributors locally.

Checks are grouped into three tiers, because coupling them was itself a defect:
one required job mixed product invariants with calendar-driven external facts,
so a third party's pricing page going stale made an unrelated workflow bugfix
unmergeable. A green check should mean "this change is sound", not "nobody's
tariff expired today".

  core       Blocking on every pull request. Parse integrity, action pins,
             permission/event/ref/runner trust, reusable API contracts,
             release-graph authorization, generated-doc drift, and the
             executable behaviour fixtures. All of these are properties of the
             tree in hand, so they can only fail because of the change.

  touched    Blocking, but scoped to what the change actually reaches. Product
             facts are checked for expiry only when the changed capability
             depends on them; a runtime-coverage waiver is checked for expiry
             only when its workflow was touched. Structural rules from both
             ledgers always run in `core`.

  scheduled  Advisory, on a timer, never blocking a pull request. The full
             calendar sweep of external facts and waivers, and the broad
             documentation link audit. Their failures are real work, but they
             are maintenance debt rather than a defect in someone's change.

Usage:
    python3 scripts/validate_all.py                     # everything (default)
    python3 scripts/validate_all.py --tier core         # what ci-gate blocks on
    python3 scripts/validate_all.py --tier touched --changed-from origin/main
    python3 scripts/validate_all.py --tier scheduled    # the advisory sweep
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _strict_yaml
import check_actionlint_contract
import check_benchmark_contract
import check_docs_links
import check_examples
import check_gate_contract
import check_harden_runner_contract
import check_merge_group
import check_monorepo_routing
import check_permissions
import check_public_docs
import check_runtime_requirements
import check_runner_routing
import check_side_effect_fixture_contract
import compile_evidence_plan
import check_pinned_actions
import check_privileged_ref_guard
import check_pr_hygiene_contract
import check_release_graph
import check_release_promotion_gate
import check_release_supply_chain
import check_rulesets
import check_skills
import check_tool_pinning
import check_tool_registry
import check_workflow_contracts
import generate_docs
import resolve_profile
import render_runtime_evidence
import validate_catalog
import validate_product_facts
import validate_profiles
import validate_runtime_coverage

REPO_ROOT = Path(__file__).resolve().parent.parent

# Blocking. Every one of these is a property of the tree, so it can only fail
# because of the change in hand.
CORE = [
    # Parse integrity first: every later check reads these files.
    ("strict-yaml", _strict_yaml.check),
    ("pinned-actions", check_pinned_actions.check),
    ("tool-pinning", check_tool_pinning.check),
    ("tool-registry", check_tool_registry.check),
    ("permissions", check_permissions.check),
    ("workflow-contracts", check_workflow_contracts.check),
    ("harden-runner-contract", check_harden_runner_contract.check),
    ("privileged-ref-guard", check_privileged_ref_guard.check),
    ("pr-hygiene-contract", check_pr_hygiene_contract.check),
    ("release-supply-chain", check_release_supply_chain.check),
    ("release-promotion-gate", check_release_promotion_gate.check),
    ("release-graph", check_release_graph.check),
    ("gate-contract", check_gate_contract.check),
    ("monorepo-routing", check_monorepo_routing.check),
    ("benchmark-contract", check_benchmark_contract.check),
    ("actionlint-contract", check_actionlint_contract.check),
    ("examples", check_examples.check),
    ("public-docs", check_public_docs.check),
    ("runtime-requirements", check_runtime_requirements.check),
    ("runner-routing", check_runner_routing.check),
    ("evidence-orchestration", compile_evidence_plan.check),
    ("runtime-evidence-summary", render_runtime_evidence.check),
    ("side-effect-fixture", check_side_effect_fixture_contract.check),
    ("merge-group", check_merge_group.check),
    ("rulesets", check_rulesets.check),
    ("catalog", validate_catalog.check),
    ("profiles", validate_profiles.check),
    ("profile-resolution", resolve_profile.check),
    ("skills", check_skills.check),
    ("generated-docs", generate_docs.check),
    # Ledger structure without the calendar: a malformed record is a defect in
    # the change; a waiver coming due is not.
    ("product-facts-structure", validate_product_facts.check_structural),
    ("runtime-coverage-structure", validate_runtime_coverage.check_structural),
]

# Blocking, scoped to the changed paths.
TOUCHED = [
    ("product-facts-touched", validate_product_facts.check_for_paths),
    ("runtime-coverage-touched", validate_runtime_coverage.check_for_paths),
]

# Advisory. Real work, but maintenance debt rather than a defect in a change.
SCHEDULED = [
    ("product-facts-calendar", validate_product_facts.check),
    ("runtime-coverage-calendar", validate_runtime_coverage.check),
    ("docs-links", check_docs_links.check),
]


def changed_paths(base: str | None, explicit: list[str]) -> set[str]:
    """Repository-relative paths this change touches."""
    if explicit:
        return set(explicit)
    if not base:
        return set()
    merge_base = subprocess.run(
        ["git", "merge-base", "HEAD", base],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    ref = merge_base.stdout.strip() if merge_base.returncode == 0 else base
    diff = subprocess.run(
        ["git", "diff", "--name-only", f"{ref}...HEAD"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    if diff.returncode != 0:
        # Fail closed. An unresolvable base means the change cannot be scoped,
        # so treat the whole tree as touched rather than checking nothing —
        # the same conservative rule the monorepo router uses.
        print(
            f"validate_all: cannot resolve changed paths against {base!r}; "
            "treating the whole tree as touched",
            file=sys.stderr,
        )
        return {
            str(path.relative_to(REPO_ROOT))
            for path in REPO_ROOT.rglob("*.yml")
            if ".git/" not in str(path)
        }
    return {line.strip() for line in diff.stdout.splitlines() if line.strip()}


def run(label: str, problems: list[str]) -> bool:
    if problems:
        print(f"[FAIL] {label}")
        for problem in problems:
            print(f"    - {problem}")
        return False
    print(f"[ OK ] {label}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--tier", choices=["all", "core", "touched", "scheduled"], default="all",
        help="which group to run (default: all)",
    )
    parser.add_argument(
        "--changed-from", metavar="REF",
        help="resolve changed paths against this ref (for --tier touched)",
    )
    parser.add_argument(
        "--changed", nargs="*", default=[], metavar="PATH",
        help="explicit changed paths, bypassing git",
    )
    args = parser.parse_args()

    ok = True
    if args.tier in ("all", "core"):
        for label, fn in CORE:
            ok &= run(label, fn())

    if args.tier in ("all", "touched"):
        paths = changed_paths(args.changed_from, args.changed)
        if args.tier == "touched" and not paths:
            print("[ -- ] touched: no changed paths resolved; nothing to scope")
        for label, fn in TOUCHED:
            ok &= run(label, fn(paths))

    if args.tier in ("all", "scheduled"):
        for label, fn in SCHEDULED:
            ok &= run(label, fn())

    if not ok:
        print(f"\nvalidate_all ({args.tier}): FAIL", file=sys.stderr)
        return 1
    print(f"\nvalidate_all ({args.tier}): OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
