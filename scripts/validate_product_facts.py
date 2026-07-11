#!/usr/bin/env python3
"""Freshness gate for the volatile product-fact ledger.

`catalog/capabilities.yml` owns stable capability identity; external plan,
price, and quota facts change on the provider's schedule, not ours. This
validator makes that volatility CI-visible: it fails when a fact is past its
`expires_after` date, when two facts about the same product/plan/visibility
disagree without an explicit supersession, when a capability references a
fact id that does not exist, or when the schema is malformed. It is the reason
a stale tier claim turns the build red instead of silently misleading
adopters.

The core validation is parameterized by an as-of date so its own regression
fixtures are deterministic; `check()` (invoked by validate_all) runs it against
today.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER = REPO_ROOT / "catalog" / "product-facts.yml"
CAPABILITIES = REPO_ROOT / "catalog" / "capabilities.yml"

SCHEMA = "nddev-ci-free-tier-facts/v1"
ID_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MODELS = {
    "public-unmetered", "recurring-quota", "credit-quota", "application-grant",
    "zero-license-self-hosted", "zero-license-control-plane", "trial-only",
    "paid-only", "plan-gated", "add-on-gated", "included-feature",
    "scheduled-paid-transition", "retiring", "resource-quota",
    "build-count-quota", "shutdown",
}
STATUSES = {"official", "vendor-verified", "conditional", "deprecated",
            "unknown", "conflict"}
AUTHORITIES = {"primary", "secondary", "community", "vendor"}
# A fact the catalog's tier claims structurally depend on: its silent removal
# would let a known plan transition slip through unmonitored.
REQUIRED_FACT_IDS = {
    "github-attestations-private",
    "github-code-quality-transition",
}
REQUIRED_FACT_KEYS = {
    "id", "provider", "product", "surface", "repository_visibility", "plans",
    "model", "allowance", "conditions", "payment_method", "overage", "status",
    "source_authority", "verified_at", "expires_after", "source_urls", "notes",
}


def _iso(value: object) -> dt.date | None:
    if value is None:
        return None
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


def validate_ledger(data: object, as_of: dt.date) -> list[str]:
    """Validate a parsed ledger document as of a fixed date."""
    problems: list[str] = []
    if not isinstance(data, dict):
        return ["product-facts: top-level document must be a mapping"]
    if data.get("schema") != SCHEMA:
        problems.append(f"product-facts: schema must be {SCHEMA!r}")
    refresh = data.get("default_refresh_days")
    if not isinstance(refresh, int) or refresh <= 0:
        problems.append("product-facts: default_refresh_days must be a positive int")

    facts = data.get("facts")
    if not isinstance(facts, list) or not facts:
        return problems + ["product-facts: `facts` must be a non-empty list"]

    ids: list[str] = []
    groups: dict[tuple, list[dict]] = {}
    for index, fact in enumerate(facts):
        where = f"facts[{index}]"
        if not isinstance(fact, dict):
            problems.append(f"{where}: entry is not a mapping")
            continue
        fid = fact.get("id")
        ids.append(str(fid))
        where = f"fact {fid!r}"
        missing = REQUIRED_FACT_KEYS - set(fact.keys())
        extra = set(fact.keys()) - REQUIRED_FACT_KEYS - {"supersedes", "conflicts_with"}
        if missing:
            problems.append(f"{where}: missing fields {sorted(missing)}")
        if extra:
            problems.append(f"{where}: unexpected fields {sorted(extra)}")
        if not isinstance(fid, str) or ID_RE.fullmatch(fid) is None:
            problems.append(f"{where}: id must be kebab-case")
        if fact.get("model") not in MODELS:
            problems.append(f"{where}: invalid model {fact.get('model')!r}")
        if fact.get("status") not in STATUSES:
            problems.append(f"{where}: invalid status {fact.get('status')!r}")
        if fact.get("source_authority") not in AUTHORITIES:
            problems.append(f"{where}: invalid source_authority {fact.get('source_authority')!r}")
        try:
            verified = _iso(fact.get("verified_at"))
            expiry = _iso(fact.get("expires_after"))
        except (ValueError, TypeError) as exc:
            problems.append(f"{where}: bad date: {exc}")
            verified = expiry = None
        # Allow a one-day skew so an author whose local clock/timezone is ahead
        # of the CI runner does not trip this; still catches gross future dates.
        if verified is not None and verified > as_of + dt.timedelta(days=1):
            problems.append(f"{where}: verified_at {verified} is in the future")
        # A deprecated/terminal fact (a shut-down service) records history that
        # will not change, so it is exempt from the expiry requirement. Every
        # live fact must carry a future expiry and go stale on schedule.
        deprecated = fact.get("status") == "deprecated"
        if expiry is None:
            if not deprecated:
                problems.append(f"{where}: expires_after is required for a live fact")
        elif expiry < as_of and not deprecated:
            problems.append(
                f"{where}: EXPIRED on {expiry} (as of {as_of}); re-verify against "
                "source_urls and bump verified_at/expires_after"
            )
        urls = fact.get("source_urls") or []
        if not urls:
            problems.append(f"{where}: at least one source URL is required")
        for url in urls:
            parsed = urlparse(str(url))
            if parsed.scheme != "https" or not parsed.netloc:
                problems.append(f"{where}: source URL is not https: {url!r}")
        allowance = fact.get("allowance")
        if not isinstance(allowance, dict) or not allowance.get("unit") or not allowance.get("period"):
            problems.append(f"{where}: allowance must set unit and period")
        for link_field in ("supersedes", "conflicts_with"):
            target = fact.get(link_field)
            if target is not None and not isinstance(target, str):
                problems.append(f"{where}: {link_field} must be a fact id string")
        if isinstance(fid, str):
            key = (
                fact.get("provider"),
                fact.get("product"),
                frozenset(fact.get("repository_visibility") or []),
                frozenset(fact.get("plans") or []),
            )
            groups.setdefault(key, []).append(fact)

    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        problems.append(f"product-facts: duplicate fact ids {dupes}")

    id_set = set(ids)
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        for link_field in ("supersedes", "conflicts_with"):
            target = fact.get(link_field)
            if isinstance(target, str) and target not in id_set:
                problems.append(
                    f"fact {fact.get('id')!r}: {link_field} references unknown "
                    f"fact {target!r}"
                )

    # Two facts describing the same product for the same plan+visibility must
    # not disagree unless one explicitly supersedes or conflicts with the other.
    for key, members in groups.items():
        if len(members) < 2:
            continue
        signatures = {
            (m.get("model"), m.get("payment_method"),
             (m.get("allowance") or {}).get("value"),
             (m.get("allowance") or {}).get("unit"))
            for m in members
        }
        linked = any(m.get("supersedes") or m.get("conflicts_with") for m in members)
        if len(signatures) > 1 and not linked:
            provider, product = key[0], key[1]
            problems.append(
                f"product-facts: conflicting facts for {provider}/{product} on the "
                f"same plan+visibility disagree without supersedes/conflicts_with: "
                f"{sorted(str(m.get('id')) for m in members)}"
            )

    for required in sorted(REQUIRED_FACT_IDS):
        if required not in id_set:
            problems.append(
                f"product-facts: required anchor fact {required!r} is missing "
                "(a known plan gate/transition must stay tracked)"
            )
    return problems


def _capability_references(ledger_ids: set[str]) -> list[str]:
    problems: list[str] = []
    if not CAPABILITIES.is_file():
        return problems
    doc = yaml.safe_load(CAPABILITIES.read_text(encoding="utf-8"))
    for cap in (doc or {}).get("capabilities", []):
        if not isinstance(cap, dict):
            continue
        refs = cap.get("product_facts")
        if refs is None:
            continue
        if not isinstance(refs, list) or not refs:
            problems.append(
                f"capability {cap.get('id')!r}: product_facts must be a non-empty list"
            )
            continue
        for ref in refs:
            if ref not in ledger_ids:
                problems.append(
                    f"capability {cap.get('id')!r}: product_facts references unknown "
                    f"fact {ref!r}"
                )
    return problems


def _fixture_tests() -> list[str]:
    """Prove the validator catches the failure classes it exists to catch."""
    problems: list[str] = []
    base = {
        "id": "example-fact", "provider": "GitHub", "product": "Actions",
        "surface": "hosted-ci", "repository_visibility": ["public"],
        "plans": ["Free"], "model": "public-unmetered",
        "allowance": {"value": None, "unit": "minutes", "period": "month",
                      "multipliers": {}},
        "conditions": [], "payment_method": "not-required", "overage": "n/a",
        "status": "official", "source_authority": "primary",
        "verified_at": "2026-07-01", "expires_after": "2026-08-01",
        "source_urls": ["https://docs.github.com/x"], "notes": [],
    }

    def ledger(*facts: dict) -> dict:
        return {"schema": SCHEMA, "generated_at_utc": "2026-07-11T00:00:00Z",
                "default_refresh_days": 30, "facts": list(facts)}

    as_of = dt.date(2026, 7, 12)
    anchors = [
        {**base, "id": "github-attestations-private"},
        {**base, "id": "github-code-quality-transition"},
    ]

    def expect(label: str, doc: dict, should_pass: bool) -> None:
        found = validate_ledger(doc, as_of)
        # Ignore missing-anchor noise so each fixture isolates its own class.
        found = [p for p in found if "required anchor fact" not in p]
        if should_pass and found:
            problems.append(f"product-facts fixture {label} should pass: {found}")
        if not should_pass and not found:
            problems.append(f"product-facts fixture {label} should have failed")

    expect("valid", ledger(*anchors), True)
    expect("expired", ledger(*anchors, {**base, "id": "stale",
           "expires_after": "2026-07-01"}), False)
    expect("verified-in-future", ledger(*anchors, {**base, "id": "future",
           "verified_at": "2026-09-01"}), False)
    expect("bad-model", ledger(*anchors, {**base, "id": "badmodel",
           "model": "make-believe"}), False)
    expect("non-https-source", ledger(*anchors, {**base, "id": "http",
           "source_urls": ["http://insecure/x"]}), False)
    expect("duplicate-id", ledger(*anchors, {**base, "id": "dup"},
           {**base, "id": "dup"}), False)
    expect("orphan-supersedes", ledger(*anchors, {**base, "id": "orphan",
           "supersedes": "does-not-exist"}), False)
    conflict_a = {**base, "id": "conflict-a", "product": "ConflictProduct"}
    conflict_b = {**base, "id": "conflict-b", "product": "ConflictProduct",
                  "model": "paid-only", "payment_method": "required"}
    expect("conflict", ledger(*anchors, conflict_a, conflict_b), False)
    resolved_b = {**conflict_b, "id": "conflict-b2",
                  "supersedes": "conflict-a"}
    expect("conflict-resolved-by-supersedes",
           ledger(*anchors, conflict_a, resolved_b), True)
    # Missing required anchor is itself an error (checked without the filter).
    if not any("required anchor fact" in p
               for p in validate_ledger(ledger(base), as_of)):
        problems.append("product-facts fixture missing-anchor should have failed")
    return problems


def check() -> list[str]:
    if not LEDGER.is_file():
        return [f"missing product-fact ledger: {LEDGER.relative_to(REPO_ROOT)}"]
    try:
        data = yaml.safe_load(LEDGER.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [f"product-facts: invalid YAML: {exc}"]
    problems = validate_ledger(data, dt.date.today())
    ledger_ids = {
        str(f.get("id")) for f in (data or {}).get("facts", []) if isinstance(f, dict)
    }
    problems += _capability_references(ledger_ids)
    problems += _fixture_tests()
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("validate_product_facts: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("validate_product_facts: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
