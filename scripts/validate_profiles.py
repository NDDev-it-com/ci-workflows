#!/usr/bin/env python3
"""Consistency gate for the operating-profile model.

`catalog/profiles.yml` declares the modes this library supports as independent
axes rather than a three-tier line. This validator enforces that a declared
profile is internally coherent and agrees with the other catalogs, so the prose
in docs/16 and docs/17 cannot drift away from it the way it did before the model
existed.

The rules that matter are the ones that encode a real failure already observed:

* a fixed-cost profile may not permit AI credits or Actions overage — the $80
  envelope was breached in July by exactly those two lines;
* attestations on a private or internal repository require Enterprise Cloud, and
  Code Quality requires Team or Enterprise — plan gates, not visibility gates;
* every entitlement a profile claims must be unlockable by a capability that
  exists in `catalog/capabilities.yml`;
* every product fact a profile cites must exist and must not be deprecated;
* all eight C/S/Q combinations must be present, so no repository is unplaceable.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from _strict_yaml import strict_load

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILES = REPO_ROOT / "catalog" / "profiles.yml"
CAPABILITIES = REPO_ROOT / "catalog" / "capabilities.yml"
PRODUCT_FACTS = REPO_ROOT / "catalog" / "product-facts.yml"
SCHEMA = "nddev-ci-operating-profiles/v1"

REQUIRED_CONTROLS = {
    "codeql_mode", "code_quality_ai", "coverage_mode", "runner_mode",
    "governance_mode", "enforcement", "release_provenance",
}
ENTITLEMENT_KEYS = ("code_security", "secret_protection", "code_quality")
# Plan gates that are NOT visibility gates. Both were mis-stated in prose at
# some point, which is why they are asserted here rather than described.
ATTESTATION_PRIVATE_PLANS = {"enterprise-cloud"}
CODE_QUALITY_PLANS = {"team", "enterprise-cloud"}


def _load(path: Path) -> Any:
    return strict_load(path)


def validate_profiles(doc: Any, capability_ids: set[str], fact_ids: set[str],
                      deprecated_facts: set[str]) -> list[str]:
    problems: list[str] = []
    if not isinstance(doc, dict):
        return ["profiles: top-level document must be a mapping"]
    if doc.get("schema") != SCHEMA:
        problems.append(f"profiles: schema must be {SCHEMA!r}")

    axes = doc.get("axes")
    if not isinstance(axes, dict):
        return problems + ["profiles: `axes` must be a mapping"]
    control_axes = axes.get("controls") or {}
    allowed: dict[str, set[str]] = {
        name: {str(v) for v in (spec or {}).get("values") or []}
        for name, spec in control_axes.items()
    }
    visibilities = {str(v) for v in (axes.get("visibility") or {}).get("values") or []}
    plans = {str(v) for v in (axes.get("base_plan") or {}).get("values") or []}

    # Every entitlement axis must name capabilities that actually exist, or the
    # model claims to unlock something this library cannot deliver.
    for name, spec in (axes.get("entitlements") or {}).items():
        for cap in (spec or {}).get("unlocks") or []:
            if cap not in capability_ids:
                problems.append(
                    f"profiles: entitlement {name!r} unlocks unknown capability {cap!r}"
                )

    matrix = doc.get("entitlement_matrix")
    if not isinstance(matrix, list):
        problems.append("profiles: `entitlement_matrix` must be a list")
        matrix = []
    seen_masks = set()
    for entry in matrix:
        if not isinstance(entry, dict):
            problems.append("profiles: entitlement_matrix entry is not a mapping")
            continue
        mask = str(entry.get("mask"))
        seen_masks.add(mask)
        if len(mask) != 3 or set(mask) - {"0", "1"}:
            problems.append(f"profiles: mask {mask!r} must be three binary digits (C/S/Q)")
            continue
        # The mask and the booleans are two spellings of one fact; if they can
        # disagree, the table stops being usable as a lookup.
        for digit, key in zip(mask, ENTITLEMENT_KEYS):
            if bool(entry.get(key)) != (digit == "1"):
                problems.append(
                    f"profiles: mask {mask!r} disagrees with {key}={entry.get(key)!r}"
                )
        for cap in entry.get("fallbacks") or []:
            if cap not in capability_ids:
                problems.append(f"profiles: mask {mask!r} names unknown fallback {cap!r}")
    missing_masks = {f"{c}{s}{q}" for c in "01" for s in "01" for q in "01"} - seen_masks
    if missing_masks:
        problems.append(
            "profiles: entitlement_matrix is missing combinations "
            f"{sorted(missing_masks)} — every repository must be placeable"
        )

    profiles = doc.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        return problems + ["profiles: `profiles` must be a non-empty list"]

    ids: list[str] = []
    for profile in profiles:
        if not isinstance(profile, dict):
            problems.append("profiles: profile entry is not a mapping")
            continue
        pid = str(profile.get("id"))
        ids.append(pid)
        where = f"profile {pid!r}"

        doc_path = profile.get("doc")
        if not doc_path or not (REPO_ROOT / str(doc_path)).is_file():
            problems.append(f"{where}: doc {doc_path!r} does not exist")

        selectors = profile.get("selectors") or {}
        sel_vis = {str(v) for v in selectors.get("visibility") or []}
        sel_plans = {str(v) for v in selectors.get("base_plan") or []}
        if not sel_vis or sel_vis - visibilities:
            problems.append(f"{where}: invalid visibility selector {sorted(sel_vis)}")
        if not sel_plans or sel_plans - plans:
            problems.append(f"{where}: invalid base_plan selector {sorted(sel_plans)}")

        ent = profile.get("entitlements") or {}
        missing = set(ENTITLEMENT_KEYS) - set(ent)
        if missing:
            problems.append(f"{where}: entitlements missing {sorted(missing)}")
        mask = str(profile.get("entitlement_mask"))
        expected = "".join("1" if ent.get(k) else "0" for k in ENTITLEMENT_KEYS)
        if mask != expected:
            problems.append(
                f"{where}: entitlement_mask {mask!r} does not match entitlements ({expected!r})"
            )
        elif mask not in seen_masks:
            problems.append(f"{where}: mask {mask!r} has no entitlement_matrix row")

        controls = profile.get("controls") or {}
        for key in sorted(REQUIRED_CONTROLS - set(controls)):
            problems.append(f"{where}: missing control {key!r}")
        for key, value in controls.items():
            if key in allowed and str(value) not in allowed[key]:
                problems.append(
                    f"{where}: control {key}={value!r} is not one of {sorted(allowed[key])}"
                )

        # Plan gates.
        if ent.get("code_quality") and not (sel_plans & CODE_QUALITY_PLANS):
            problems.append(
                f"{where}: code_quality requires a Team or Enterprise Cloud plan"
            )
        if (controls.get("release_provenance") == "attestations"
                and sel_vis & {"private", "internal"}
                and not (sel_plans & ATTESTATION_PRIVATE_PLANS)):
            problems.append(
                f"{where}: attestations on private/internal repositories require "
                "Enterprise Cloud — this is a plan gate, not a GHAS one"
            )
        # An advanced CodeQL setup has to be delivered by a workflow this
        # library actually ships, or the mode is undeliverable.
        if controls.get("codeql_mode") == "advanced" and "codeql-code-scanning" not in capability_ids:
            problems.append(f"{where}: codeql_mode 'advanced' has no delivering capability")
        if ent.get("code_security") is False and controls.get("codeql_mode") != "none":
            if sel_vis & {"private", "internal"}:
                problems.append(
                    f"{where}: private CodeQL requires code_security; set codeql_mode 'none'"
                )

        cost = profile.get("cost") or {}
        for fact in cost.get("product_facts") or []:
            if fact not in fact_ids:
                problems.append(f"{where}: cites unknown product fact {fact!r}")
            elif fact in deprecated_facts:
                problems.append(f"{where}: cites deprecated product fact {fact!r}")

        fixed = cost.get("fixed_usd")
        if fixed is None:
            problems.append(f"{where}: cost.fixed_usd is required")
        elif fixed:
            lines = cost.get("fixed_lines") or []
            total = sum(float(l.get("usd", 0)) for l in lines if isinstance(l, dict))
            if not lines:
                problems.append(f"{where}: fixed_usd {fixed} needs itemised fixed_lines")
            elif abs(total - float(fixed)) > 1e-6:
                problems.append(
                    f"{where}: fixed_lines sum to {total:g}, not fixed_usd {fixed:g}"
                )
            # A fixed envelope that permits metered spend is not fixed. Both
            # guards below correspond to lines that actually breached it.
            guards = cost.get("guards") or {}
            if guards.get("allow_ai_credits") is not False:
                problems.append(
                    f"{where}: a fixed-cost profile must set guards.allow_ai_credits: false"
                )
            if guards.get("allow_actions_overage") is not False:
                problems.append(
                    f"{where}: a fixed-cost profile must set guards.allow_actions_overage: false"
                )
            if controls.get("code_quality_ai") != "disabled":
                problems.append(
                    f"{where}: a fixed-cost profile must set code_quality_ai: disabled — "
                    "AI credits are metered with no included allowance"
                )

        # Untrusted fork code must not reach a trusted persistent runner.
        if (sel_vis & {"public"}
                and controls.get("runner_mode") == "self-hosted-persistent"):
            problems.append(
                f"{where}: a public profile may not use self-hosted-persistent runners — "
                "pull_request executes untrusted fork code"
            )

    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        problems.append(f"profiles: duplicate profile ids {duplicates}")
    return problems


def _fixture_tests() -> list[str]:
    """Regression fixtures for the rules above, so they cannot rot silently."""
    problems: list[str] = []
    caps = {"codeql-code-scanning", "native-secret-scanning", "github-code-quality",
            "dependency-review", "code-scanning-sarif-upload",
            "secret-scanning-push-protection", "gitleaks-secret-scan"}
    facts = {"fact-a"}

    def base_matrix() -> list[dict]:
        rows = []
        for c in "01":
            for s in "01":
                for q in "01":
                    rows.append({
                        "mask": f"{c}{s}{q}",
                        "code_security": c == "1",
                        "secret_protection": s == "1",
                        "code_quality": q == "1",
                        "posture": "x", "fallbacks": [],
                    })
        return rows

    def doc(profile: dict, matrix: list[dict] | None = None) -> dict:
        return {
            "schema": SCHEMA,
            "axes": {
                "visibility": {"values": ["public", "private", "internal"]},
                "base_plan": {"values": ["free", "pro", "team", "enterprise-cloud"]},
                "entitlements": {
                    "code_security": {"values": [True, False], "unlocks": ["codeql-code-scanning"]},
                },
                "controls": {
                    "codeql_mode": {"values": ["none", "default", "advanced"]},
                    "code_quality_ai": {"values": ["disabled", "on_push"]},
                    "coverage_mode": {"values": ["off", "report", "gated"]},
                    "runner_mode": {"values": ["github-hosted-standard",
                                               "self-hosted-ephemeral",
                                               "self-hosted-persistent"]},
                    "governance_mode": {"values": ["solo-agent", "team-strict", "regulated"]},
                    "enforcement": {"values": ["report", "evaluate", "active"]},
                    "release_provenance": {"values": ["checksums", "attestations"]},
                },
            },
            "entitlement_matrix": base_matrix() if matrix is None else matrix,
            "profiles": [profile],
        }

    good = {
        "id": "p", "doc": "README.md",
        "selectors": {"visibility": ["private"], "base_plan": ["enterprise-cloud"]},
        "entitlements": {"code_security": True, "secret_protection": True, "code_quality": True},
        "entitlement_mask": "111",
        "controls": {"codeql_mode": "default", "code_quality_ai": "disabled",
                     "coverage_mode": "gated", "runner_mode": "self-hosted-persistent",
                     "governance_mode": "solo-agent", "enforcement": "active",
                     "release_provenance": "attestations"},
        "cost": {"fixed_usd": 80,
                 "fixed_lines": [{"line": "a", "usd": 21}, {"line": "b", "usd": 30},
                                 {"line": "c", "usd": 19}, {"line": "d", "usd": 10}],
                 "product_facts": ["fact-a"],
                 "guards": {"allow_ai_credits": False, "allow_actions_overage": False}},
    }

    def run(profile: dict, matrix: list[dict] | None = None) -> list[str]:
        return validate_profiles(doc(profile, matrix), caps, facts, set())

    def expect_fail(label: str, profile: dict, matrix: list[dict] | None = None) -> None:
        if not run(profile, matrix):
            problems.append(f"profiles fixture {label} should fail")

    if run(good):
        problems.append("profiles fixture valid should pass")
    expect_fail("mask-mismatch", {**good, "entitlement_mask": "110"})
    expect_fail("fixed-lines-sum", {**good, "cost": {**good["cost"],
                                                     "fixed_lines": [{"line": "a", "usd": 1}]}})
    expect_fail("ai-credits-allowed", {**good, "cost": {**good["cost"],
                                                        "guards": {"allow_ai_credits": True,
                                                                   "allow_actions_overage": False}}})
    expect_fail("ai-on-in-fixed-profile",
                {**good, "controls": {**good["controls"], "code_quality_ai": "on_push"}})
    expect_fail("attestations-without-ghec",
                {**good, "selectors": {"visibility": ["private"], "base_plan": ["team"]}})
    expect_fail("code-quality-without-team-plan",
                {**good, "selectors": {"visibility": ["private"], "base_plan": ["free"]}})
    expect_fail("public-on-persistent-self-hosted",
                {**good, "selectors": {"visibility": ["public"], "base_plan": ["enterprise-cloud"]}})
    expect_fail("private-codeql-without-code-security",
                {**good,
                 "entitlements": {"code_security": False, "secret_protection": True,
                                  "code_quality": True},
                 "entitlement_mask": "011"})
    expect_fail("unknown-fact", {**good, "cost": {**good["cost"], "product_facts": ["nope"]}})
    expect_fail("missing-control",
                {**good, "controls": {k: v for k, v in good["controls"].items()
                                      if k != "enforcement"}})
    expect_fail("missing-mask-row", good, base_matrix()[:-1])
    return problems


def check() -> list[str]:
    if not PROFILES.is_file():
        return [f"missing {PROFILES.relative_to(REPO_ROOT)}"]
    caps_doc = _load(CAPABILITIES) or {}
    capability_ids = {str(c.get("id")) for c in caps_doc.get("capabilities") or []}
    facts_doc = _load(PRODUCT_FACTS) or {}
    facts = facts_doc.get("facts") or []
    fact_ids = {str(f.get("id")) for f in facts}
    deprecated = {str(f.get("id")) for f in facts if f.get("status") == "deprecated"}
    problems = validate_profiles(_load(PROFILES), capability_ids, fact_ids, deprecated)
    return problems + _fixture_tests()


def main() -> int:
    problems = check()
    if problems:
        print("validate_profiles: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    doc = _load(PROFILES)
    print(f"validate_profiles: OK ({len(doc.get('profiles') or [])} profiles, "
          f"{len(doc.get('entitlement_matrix') or [])} entitlement combinations)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
