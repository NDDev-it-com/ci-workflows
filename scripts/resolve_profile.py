#!/usr/bin/env python3
"""Resolve a repository's operating profile and the programme it should run.

`catalog/profiles.yml` says what a mode *is* — entitlements, controls, cost.
It does not say what you *run* in it, and a mode you cannot turn into a set of
workflows is a description rather than a selection. This closes that: give it a
repository's shape and it returns the profile, the workflows available in that
mode, and the free substitute for every capability the mode does not entitle.

    python3 scripts/resolve_profile.py --visibility private --plan enterprise-cloud \
        --code-security --secret-protection --code-quality
    python3 scripts/resolve_profile.py --profile public-free-standalone

Which tier column applies is derived, not guessed: public repositories read
`public_oss`; private and internal ones read `private_paid` when any add-on is
held and `private_free` otherwise. A capability whose column says `paid` is only
included when the entitlement that unlocks it is actually on, so the two public
profiles — which share a tier column but differ in entitlements — resolve to
different programmes.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILES = REPO_ROOT / "catalog" / "profiles.yml"
CAPABILITIES = REPO_ROOT / "catalog" / "capabilities.yml"

ENTITLEMENT_KEYS = ("code_security", "secret_protection", "code_quality")
# Availability values that mean "you can run this in this mode".
INCLUDED = {"free", "available"}
CONDITIONAL = {"conditional"}


def _load(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# `private_paid` in the catalog means "private repository on a paid **Advanced
# Security** plan". Code Quality is a separate product on its own licence and
# does not put a repository in that tier: a private repo holding only Code
# Quality still cannot run CodeQL, dependency review or native secret scanning.
GHAS_ENTITLEMENTS = ("code_security", "secret_protection")


def tier_column(visibility: str, entitlements: dict[str, bool]) -> str:
    """The capability column that governs this repository."""
    if visibility == "public":
        return "public_oss"
    return ("private_paid" if any(entitlements.get(k) for k in GHAS_ENTITLEMENTS)
            else "private_free")


def _unlock_map(profiles_doc: dict[str, Any]) -> dict[str, str]:
    """capability id -> the entitlement that unlocks it."""
    out: dict[str, str] = {}
    for name, spec in ((profiles_doc.get("axes") or {}).get("entitlements") or {}).items():
        for cap in (spec or {}).get("unlocks") or []:
            out[str(cap)] = str(name)
    return out


def resolve(profiles_doc: dict[str, Any], capabilities: list[dict[str, Any]],
            profile: dict[str, Any]) -> dict[str, Any]:
    visibility = (profile.get("selectors") or {}).get("visibility", ["public"])[0]
    entitlements = profile.get("entitlements") or {}
    column = tier_column(visibility, entitlements)
    unlocks = _unlock_map(profiles_doc)
    mask = str(profile.get("entitlement_mask"))
    fallbacks: list[str] = []
    for row in profiles_doc.get("entitlement_matrix") or []:
        if str(row.get("mask")) == mask:
            fallbacks = [str(f) for f in row.get("fallbacks") or []]

    included, conditional, excluded = [], [], []
    for cap in capabilities:
        cid = str(cap.get("id"))
        value = str(cap.get(column))
        gate = unlocks.get(cid)
        entry = (cid, cap.get("workflow"))
        # Where an entitlement is actually required, hold the capability to it.
        # Two distinct cases, and conflating them is wrong in both directions:
        #   * `paid` in any column means the capability costs an add-on, so it
        #     needs the entitlement that unlocks it (Code Quality on public).
        #   * `private_paid` is the Advanced Security tier column, so its
        #     `available` presupposes an add-on — but not necessarily the same
        #     one. Secret Protection does not unlock CodeQL, and Code Security
        #     does not unlock native secret scanning.
        # A `free` value never needs a gate: CodeQL and secret scanning are free
        # on public repositories no matter which add-ons are held.
        needs_entitlement = value == "paid" or (column == "private_paid" and gate is not None)
        if needs_entitlement:
            (included if gate and entitlements.get(gate) else excluded).append(entry)
        elif value == "paid":
            # Priced as paid with no declared unlock: not resolvable as included.
            excluded.append(entry)
        elif value in INCLUDED:
            included.append((cid, cap.get("workflow")))
        elif value in CONDITIONAL:
            conditional.append((cid, cap.get("workflow")))
        else:
            excluded.append((cid, cap.get("workflow")))

    def shape(pairs: list[tuple[str, Any]]) -> list[dict[str, Any]]:
        return [{"capability": c, "workflow": w} for c, w in sorted(pairs)]

    return {
        "profile": profile.get("id"),
        "name": profile.get("name"),
        "tier_column": column,
        "visibility": visibility,
        "base_plan": (profile.get("selectors") or {}).get("base_plan", []),
        "entitlements": {k: bool(entitlements.get(k)) for k in ENTITLEMENT_KEYS},
        "entitlement_mask": mask,
        "controls": profile.get("controls") or {},
        "cost": profile.get("cost") or {},
        "included": shape(included),
        "conditional": shape(conditional),
        "excluded": shape(excluded),
        "free_fallbacks": fallbacks,
    }


def select(profiles_doc: dict[str, Any], visibility: str, plan: str,
           entitlements: dict[str, bool]) -> dict[str, Any] | None:
    """The declared profile matching a repository's shape, if one exists."""
    mask = "".join("1" if entitlements.get(k) else "0" for k in ENTITLEMENT_KEYS)
    for profile in profiles_doc.get("profiles") or []:
        sel = profile.get("selectors") or {}
        if visibility not in (sel.get("visibility") or []):
            continue
        if plan not in (sel.get("base_plan") or []):
            continue
        if str(profile.get("entitlement_mask")) != mask:
            continue
        return profile
    return None


def _render(result: dict[str, Any]) -> str:
    lines = [
        f"profile: {result['profile']}  ({result['name']})",
        f"  shape:        {result['visibility']} / {', '.join(result['base_plan'])} / mask {result['entitlement_mask']}",
        f"  tier column:  {result['tier_column']}",
        "  controls:",
    ]
    for key, value in result["controls"].items():
        lines.append(f"    {key}: {value}")
    cost = result["cost"]
    fixed = cost.get("fixed_usd")
    lines.append(f"  fixed cost:   {'free' if not fixed else f'${fixed:g}/month'}")
    if cost.get("metered_lines"):
        lines.append(f"  metered:      {', '.join(cost['metered_lines'])}")

    def block(title: str, rows: list[dict[str, Any]]) -> None:
        lines.append(f"\n{title} ({len(rows)}):")
        for row in rows:
            wf = row["workflow"] or "-"
            lines.append(f"  {row['capability']:<38} {wf}")

    block("RUN in this mode", result["included"])
    if result["conditional"]:
        block("CONDITIONAL — check the capability's required_settings", result["conditional"])
    block("NOT available in this mode", result["excluded"])
    if result["free_fallbacks"]:
        lines.append("\nfree substitutes for what this mode does not entitle:")
        for f in result["free_fallbacks"]:
            lines.append(f"  {f}")
    return "\n".join(lines)


def check() -> list[str]:
    """Invariants that keep resolution meaningful, for validate_all.

    A resolver that returns something for every input is not obviously working;
    these assert the properties that make the answer worth acting on.
    """
    problems: list[str] = []
    profiles_doc = _load(PROFILES)
    capabilities = (_load(CAPABILITIES) or {}).get("capabilities") or []
    if not capabilities:
        return ["resolve-profile: capability catalog is empty"]

    resolved: dict[str, dict[str, Any]] = {}
    for profile in profiles_doc.get("profiles") or []:
        pid = str(profile.get("id"))
        result = resolve(profiles_doc, capabilities, profile)
        resolved[pid] = result
        if not result["included"]:
            problems.append(f"resolve-profile: {pid} resolves to an empty programme")
        # Round-trip: a profile must be reachable from the shape it declares.
        sel = profile.get("selectors") or {}
        back = select(profiles_doc, sel["visibility"][0], sel["base_plan"][0],
                      profile.get("entitlements") or {})
        if back is None or str(back.get("id")) != pid:
            problems.append(
                f"resolve-profile: {pid} is not selectable from its own selectors"
            )

    # Holding every add-on must leave nothing unavailable; if it does, either a
    # capability is mis-tiered or an entitlement is missing an `unlocks` entry.
    full = resolved.get("enterprise-full-private-fixed80")
    if full and full["excluded"]:
        problems.append(
            "resolve-profile: the full paid profile excludes "
            f"{[r['capability'] for r in full['excluded']]} — mis-tiered capability "
            "or a missing entitlement `unlocks` entry"
        )
    # The zero-cost private profile must genuinely exclude the paid surface,
    # otherwise the free tier is being advertised as more than it is.
    free = resolved.get("private-free-max")
    if free and not free["excluded"]:
        problems.append("resolve-profile: private-free-max excludes nothing, which cannot be right")
    # Cross-entitlement leakage: holding one add-on must not resolve another's
    # capabilities. `private_paid` marks the whole Advanced Security tier
    # `available`, so a naive column read hands CodeQL to a repository that only
    # bought Secret Protection. Probed with synthetic shapes because no declared
    # profile occupies these masks.
    def probe(mask: str, ents: dict[str, bool]) -> set[str]:
        r = resolve(profiles_doc, capabilities,
                    {"id": f"probe-{mask}", "name": "probe",
                     "selectors": {"visibility": ["private"], "base_plan": ["team"]},
                     "entitlements": ents, "entitlement_mask": mask,
                     "controls": {}, "cost": {}})
        return {x["capability"] for x in r["included"]}

    sp_only = probe("010", {"code_security": False, "secret_protection": True,
                            "code_quality": False})
    if "codeql-code-scanning" in sp_only or "dependency-review" in sp_only:
        problems.append(
            "resolve-profile: Secret Protection alone resolves Code Security "
            "capabilities — the private_paid column is being read without its "
            "per-entitlement gate"
        )
    if "native-secret-scanning" not in sp_only:
        problems.append("resolve-profile: Secret Protection does not resolve native secret scanning")
    cq_only = probe("001", {"code_security": False, "secret_protection": False,
                            "code_quality": True})
    leaked = {"codeql-code-scanning", "dependency-review", "native-secret-scanning"} & cq_only
    if leaked:
        problems.append(
            f"resolve-profile: Code Quality alone resolves {sorted(leaked)} — "
            "Code Quality is a separate licence and unlocks none of the Advanced "
            "Security surface"
        )
    if "github-code-quality" not in cq_only:
        problems.append("resolve-profile: Code Quality does not resolve its own capability")
    # A public repository must keep the free surface regardless of add-ons.
    pub = resolved.get("public-free-standalone")
    if pub:
        free_on_public = {x["capability"] for x in pub["included"]}
        for cap in ("codeql-code-scanning", "native-secret-scanning"):
            if cap not in free_on_public:
                problems.append(
                    f"resolve-profile: {cap} is free on public repositories but the "
                    "zero-entitlement public profile excludes it"
                )

    # Two profiles sharing a tier column must still differ, or entitlements are
    # not actually influencing resolution.
    a, b = resolved.get("public-free-standalone"), resolved.get("public-enterprise-max")
    if a and b:
        if a["tier_column"] != b["tier_column"]:
            problems.append("resolve-profile: the public profiles should share a tier column")
        elif {r["capability"] for r in a["included"]} == {r["capability"] for r in b["included"]}:
            problems.append(
                "resolve-profile: the two public profiles resolve identically — "
                "entitlements are not affecting resolution"
            )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--profile", help="resolve a declared profile by id")
    parser.add_argument("--visibility", choices=["public", "private", "internal"])
    parser.add_argument("--plan", choices=["free", "pro", "team", "enterprise-cloud"])
    parser.add_argument("--code-security", action="store_true")
    parser.add_argument("--secret-protection", action="store_true")
    parser.add_argument("--code-quality", action="store_true")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    profiles_doc = _load(PROFILES)
    capabilities = (_load(CAPABILITIES) or {}).get("capabilities") or []

    if args.profile:
        profile = next((p for p in profiles_doc.get("profiles") or []
                        if str(p.get("id")) == args.profile), None)
        if profile is None:
            known = ", ".join(str(p.get("id")) for p in profiles_doc.get("profiles") or [])
            print(f"unknown profile {args.profile!r}; known: {known}", file=sys.stderr)
            return 2
    else:
        if not args.visibility or not args.plan:
            parser.error("give --profile, or both --visibility and --plan")
        entitlements = {
            "code_security": args.code_security,
            "secret_protection": args.secret_protection,
            "code_quality": args.code_quality,
        }
        profile = select(profiles_doc, args.visibility, args.plan, entitlements)
        if profile is None:
            mask = "".join("1" if entitlements[k] else "0" for k in ENTITLEMENT_KEYS)
            print(
                f"no declared profile matches {args.visibility}/{args.plan}/mask {mask}.\n"
                "That combination is valid — every mask is in the entitlement matrix — "
                "but no named profile covers it. Read the matrix row for the posture and "
                "its free fallbacks, or add a profile to catalog/profiles.yml.",
                file=sys.stderr,
            )
            return 1

    result = resolve(profiles_doc, capabilities, profile)
    print(json.dumps(result, indent=2) if args.json else _render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
