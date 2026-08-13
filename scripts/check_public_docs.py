#!/usr/bin/env python3
"""A public library must not publish account-observed estate state.

`docs/17` and `docs/18` carried a live operations report inside a public
reusable-workflow library: licence counts, repository inventory ("23 repos",
"attached to all 51 repositories", "36 on default setup, 8 on their own"), an
observed invoice total, accrued AI-credit spend to the cent, a metered-pool
reading with a projected exhaustion date, and a named private repository.

None of it was a secret, and that is exactly why it survived review. The defect
is the trust domain, not confidentiality: a consumer reads a public library for
stable contracts, and this told them what one particular organization's bill
looked like on one particular morning. Every figure was stale within days, each
one invited a refresh commit, and the tier docs became the fastest-rotting files
in a repository whose whole thesis is that unvalidated claims rot.

So the rule is structural. Durable statements stay — which products the estate
holds, why push protection is off, that a security configuration attaches
atomically, that a budget cannot stop a licence-based product. Countable account
state goes to the control plane.

Two patterns are rejected, chosen because both are unambiguously *observations*
rather than contracts:

* **inventory counts** — "N repositories", "N repos", "N active committers";
* **cent-precision currency** — an invoice or an accrual, never a list price.

A `$0` budget setting is a control, not an observation, and is allowed. List
prices are product facts and belong in `catalog/product-facts.yml`, which is
freshness-gated; this check does not police them, `validate_product_facts` does.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from _workflow_yaml import REPO_ROOT

# Everything a consumer reads. The catalog is excluded: product-facts.yml is the
# sanctioned home for dated external figures and has its own freshness gate.
PUBLIC_DOCS = ("README.md", "docs")

INVENTORY = re.compile(
    r"\b\d+\s+(?:repositor(?:y|ies)|repos)\b"
    r"|\b\d+\s+active\s+committers?\b"
    r"|\ball\s+\d+\s+(?:repositor(?:y|ies)|repos)\b",
    re.IGNORECASE,
)
# $12.34 — cents mean somebody read an invoice. $0 and $10 are settings/prices.
OBSERVED_SPEND = re.compile(r"\$\d[\d,]*\.\d{2}\b")

# Generated files render catalog rows and are checked by their own drift gate.
EXEMPT_DIRS = ("docs/generated",)


def _public_files() -> list[Path]:
    files: list[Path] = []
    for entry in PUBLIC_DOCS:
        path = REPO_ROOT / entry
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(sorted(path.rglob("*.md")))
    return [
        f for f in files
        if not any(str(f.relative_to(REPO_ROOT)).startswith(d) for d in EXEMPT_DIRS)
    ]


def check() -> list[str]:
    problems: list[str] = []
    for path in _public_files():
        rel = path.relative_to(REPO_ROOT)
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for pattern, label in (
                (INVENTORY, "an estate inventory count"),
                (OBSERVED_SPEND, "an observed spend figure"),
            ):
                hit = pattern.search(line)
                if hit:
                    problems.append(
                        f"{rel}:{lineno}: {label} ({hit.group(0)!r}) in a public "
                        "document — account state belongs in the control plane; "
                        "state the durable rule here instead"
                    )
    problems += _selftest()
    return problems


def _selftest() -> list[str]:
    """The patterns must catch real snapshots and leave contracts alone."""
    problems: list[str] = []
    must_flag = [
        "attached to all 51 repositories",
        "1 active committer, 23 repos",
        "36 repositories on default setup",
        "$1.31 still accrued in August",
        "billed at $21 + $49 + $10 = $80.00",
    ]
    must_pass = [
        "$0 hard-stop budget at org and enterprise",
        "the $10 Code Quality licence",          # a list price, owned by the ledger
        "a repository in this estate",
        "timeout-minutes: 30",
        "actions/checkout@3d3c42e5 # v7.0.1",
        "run 30702933166",
    ]
    for sample in must_flag:
        if not (INVENTORY.search(sample) or OBSERVED_SPEND.search(sample)):
            problems.append(f"check_public_docs self-test: missed {sample!r}")
    for sample in must_pass:
        if INVENTORY.search(sample) or OBSERVED_SPEND.search(sample):
            problems.append(f"check_public_docs self-test: false positive {sample!r}")
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_public_docs: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("check_public_docs: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
