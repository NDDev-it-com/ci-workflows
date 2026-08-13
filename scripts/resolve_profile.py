#!/usr/bin/env python3
"""Resolve a repository's operating profile and the programme it should run.

`catalog/profiles.yml` says what a mode *is* — entitlements, controls, cost.
It does not say what you *run* in it, and a mode you cannot turn into a set of
workflows is a description rather than a selection. This closes that: give it a
repository's shape and it returns the profile, the workflows available in that
mode, and the free substitute for every capability the mode does not entitle.

    .venv/bin/python -I -B scripts/check_python_execution_contract.py --launch resolve_profile.py -- --visibility private --plan enterprise-cloud \
        --code-security --secret-protection --code-quality
    .venv/bin/python -I -B scripts/check_python_execution_contract.py --launch resolve_profile.py -- --profile public-free-standalone

Availability is resolved per capability, not by moving the whole repository to
a `private_paid` column when it buys one add-on. Code Security, Secret Protection
and Code Quality are independent products; Enterprise Cloud separately unlocks
private attestations. This prevents one purchase from silently enabling another
product's workflows.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

from ci_workflows_tools._strict_yaml import strict_load

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILES = REPO_ROOT / "catalog" / "profiles.yml"
CAPABILITIES = REPO_ROOT / "catalog" / "capabilities.yml"

ENTITLEMENT_KEYS = ("code_security", "secret_protection", "code_quality")
# Availability values that mean "you can run this in this mode".
INCLUDED = {"free", "available"}
CONDITIONAL = {"conditional"}


def _load(path: Path) -> Any:
    return strict_load(path)


# `private_paid` in the catalog means "private repository on a paid **Advanced
# Security** plan". Code Quality is a separate product on its own licence and
# does not put a repository in that tier: a private repo holding only Code
# Quality still cannot run CodeQL, dependency review or native secret scanning.
GHAS_ENTITLEMENTS = ("code_security", "secret_protection")


def tier_column(visibility: str, entitlements: dict[str, bool]) -> str:
    """The summary column for display; private paid shapes are capability-mixed."""
    if visibility == "public":
        return "public_oss"
    return ("private_mixed" if any(entitlements.get(k) for k in GHAS_ENTITLEMENTS)
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
    base_plan = str(((profile.get("selectors") or {}).get("base_plan") or [""])[0])
    plan_unlocks = {
        str(cap)
        for cap in ((_derivation(profiles_doc).get("plan_unlocks") or {}).get(base_plan) or [])
    }
    capability_plan_gates = {
        str(cid): {str(plan) for plan in plans}
        for cid, plans in (_derivation(profiles_doc).get("capability_plan_gates") or {}).items()
    }
    for cap in capabilities:
        cid = str(cap.get("id"))
        gate = unlocks.get(cid)
        plan_gate = capability_plan_gates.get(cid)
        if visibility != "public" and plan_gate and base_plan not in plan_gate:
            value = "unavailable"
        elif visibility == "public":
            value = str(cap.get("public_oss"))
        elif plan_gate or (gate and entitlements.get(gate)):
            value = str(cap.get("private_paid"))
        elif cid in plan_unlocks:
            value = str(cap.get("private_paid"))
        else:
            value = str(cap.get("private_free"))
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
        needs_entitlement = value == "paid"
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

    def workflows(pairs: list[tuple[str, Any]]) -> list[str]:
        return sorted({str(w) for _, w in pairs if w})

    controls = profile.get("controls") or {}
    run_workflows = workflows(included)
    conditional_workflows = workflows(conditional)
    unavailable_workflows = workflows(excluded)

    # SBOM/release capabilities share two structural workflow variants. The
    # capability catalog names the attested implementation, but the operating
    # programme must select exactly one variant from the plan gate rather than
    # handing a private Free/Pro/Team consumer the GHEC-only workflow.
    release_workflow = (
        ".github/workflows/release-supply-chain.yml"
        if controls.get("release_provenance") == "attestations"
        else ".github/workflows/release-supply-chain-free.yml"
    )
    for candidate in (
        ".github/workflows/release-supply-chain.yml",
        ".github/workflows/release-supply-chain-free.yml",
    ):
        for collection in (run_workflows, conditional_workflows, unavailable_workflows):
            while candidate in collection:
                collection.remove(candidate)
    run_workflows.append(release_workflow)
    run_workflows.sort()

    runner_mode = str(controls.get("runner_mode") or "")
    runner_contract = {
        "mode": runner_mode,
        "caller_must_set_runner": visibility != "public",
        "managed_scanners_must_be_routed_separately": visibility != "public",
        "larger_runners_allowed": False,
        "actions_budget": (
            "stop-paid-usage-required"
            if controls.get("compute_billing") == "private-hosted-bounded"
            else "not-applicable"
        ),
    }

    return {
        "profile": profile.get("id"),
        "name": profile.get("name"),
        "source": "derived" if profile.get("_derived") else "preset",
        "derivation": profile.get("_derivation") or [],
        "undetermined_controls": profile.get("_undetermined") or [],
        "tier_column": column,
        "visibility": visibility,
        "base_plan": (profile.get("selectors") or {}).get("base_plan", []),
        "entitlements": {k: bool(entitlements.get(k)) for k in ENTITLEMENT_KEYS},
        "entitlement_mask": mask,
        "controls": controls,
        "cost": profile.get("cost") or {},
        "included": shape(included),
        "conditional": shape(conditional),
        "excluded": shape(excluded),
        "free_fallbacks": fallbacks,
        "programme": {
            "run_workflows": run_workflows,
            "conditional_workflows": conditional_workflows,
            "unavailable_workflows": unavailable_workflows,
            "release_workflow": release_workflow,
            "runner_contract": runner_contract,
        },
    }


def select(profiles_doc: dict[str, Any], visibility: str, plan: str,
           entitlements: dict[str, bool]) -> dict[str, Any] | None:
    """The declared *preset* matching a repository's shape, if one exists.

    A preset is ergonomics — a name, a rationale, and a costed envelope. Its
    absence never means the shape is unsupported; see ``synthesize``.
    """
    mask = mask_of(entitlements)
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


def mask_of(entitlements: dict[str, bool]) -> str:
    return "".join("1" if entitlements.get(k) else "0" for k in ENTITLEMENT_KEYS)


def _derivation(profiles_doc: dict[str, Any]) -> dict[str, Any]:
    return profiles_doc.get("derivation") or {}


def invalid_reason(profiles_doc: dict[str, Any], visibility: str, plan: str,
                   entitlements: dict[str, bool]) -> str | None:
    """Why this shape cannot exist, or None if it can.

    Only a real product or repository-shape gate makes a shape invalid.
    Visibility matters because internal repositories exist only on Enterprise
    Cloud and because public Code Security/Secret Protection surfaces do not
    require purchasing their private-repository products.
    """
    gates = _derivation(profiles_doc).get("plan_gates") or {}
    labels = {
        "code_security": "Code Security",
        "secret_protection": "Secret Protection",
        "code_quality": "Code Quality",
    }
    # Public repositories receive the public security surfaces without buying
    # Code Security or Secret Protection. The entitlement bits still distinguish
    # named governance programmes there, so their private purchase gates do not
    # invalidate a public shape. Code Quality remains a separately licensed
    # organization product on public repositories too.
    for entitlement, label in labels.items():
        if visibility == "public" and entitlement != "code_quality":
            continue
        plans = [str(p) for p in gates.get(entitlement) or []]
        if entitlements.get(entitlement) and plans and plan not in plans:
            return (f"{label} requires a {' or '.join(plans)} plan; "
                    f"this shape declares {plan}")
    if visibility == "internal" and plan != "enterprise-cloud":
        return "internal repositories require GitHub Enterprise Cloud"
    if mask_of(entitlements) not in {
        str(row.get("mask")) for row in profiles_doc.get("entitlement_matrix") or []
    }:
        return f"entitlement mask {mask_of(entitlements)} is not in the entitlement matrix"
    return None


def synthesize(profiles_doc: dict[str, Any], capabilities: list[dict[str, Any]],
               visibility: str, plan: str,
               entitlements: dict[str, bool]) -> dict[str, Any]:
    """Build a profile for a valid shape that no preset names.

    The controls come from ``derivation`` in the catalog, not from this file, so
    the rule stays reviewable where the rest of the model lives. Controls the
    axes do not determine are left out rather than guessed.
    """
    spec = _derivation(profiles_doc)
    mask = mask_of(entitlements)
    controls: dict[str, Any] = dict(spec.get("default_controls") or {})
    trace: list[str] = []

    column = tier_column(visibility, entitlements)
    trace.append(f"tier column {column} from visibility={visibility}, mask={mask}")

    # Cost routing is a visibility decision, not an entitlement side effect.
    # The old derivation defaulted every unnamed shape to GitHub-hosted runners.
    # On private/internal repositories that silently opts the consumer into a
    # metered SKU once its included quota is exhausted. Derived modes therefore
    # fail safe to a zero-GitHub-meter route; a consumer that intentionally wants
    # to spend its included hosted quota must make that override in its caller.
    if visibility == "public":
        controls["compute_billing"] = "public-standard-unmetered"
        controls["runner_mode"] = "github-hosted-standard"
    else:
        controls["compute_billing"] = "private-self-hosted"
        controls["runner_mode"] = "self-hosted-ephemeral"
    controls["license_billing"] = (
        "selected-addons" if any(entitlements.values()) else "no-paid-addons"
    )
    trace.append(
        f"compute_billing={controls['compute_billing']}, "
        f"license_billing={controls['license_billing']}, "
        f"runner_mode={controls['runner_mode']} "
        f"from visibility={visibility}; add-ons never select a metered runner"
    )

    # codeql_mode: on where CodeQL actually resolves in this mode.
    codeql_free = any(
        str(c.get("id")) == "codeql-code-scanning"
        and str(c.get("public_oss" if visibility == "public" else "private_free")) == "free"
        for c in capabilities
    )
    codeql_on = codeql_free or (visibility != "public" and entitlements.get("code_security"))
    controls["codeql_mode"] = "default" if codeql_on else "none"
    trace.append(
        f"codeql_mode={controls['codeql_mode']} because CodeQL is "
        f"{'resolvable' if codeql_on else 'not entitled'} in this mode"
    )

    # release_provenance: attestations only where the plan permits them.
    att_plans = [str(p) for p in (spec.get("plan_gates") or {}).get("private_attestations") or []]
    attest_ok = visibility == "public" or plan in att_plans
    controls["release_provenance"] = "attestations" if attest_ok else "checksums"
    trace.append(
        f"release_provenance={controls['release_provenance']} because artifact "
        f"attestations on {visibility} repositories "
        + ("are unrestricted" if visibility == "public" else f"require {' or '.join(att_plans)}")
    )

    undetermined = [str(k) for k in spec.get("undetermined") or []]
    if undetermined:
        trace.append(
            "left unset (the axes do not determine them): " + ", ".join(undetermined)
        )

    posture, fallbacks = "", []
    for row in profiles_doc.get("entitlement_matrix") or []:
        if str(row.get("mask")) == mask:
            posture = str(row.get("posture") or "")
            fallbacks = [str(f) for f in row.get("fallbacks") or []]

    return {
        "id": f"derived:{visibility}/{plan}/{mask}",
        "name": f"Derived mode — {visibility}, {plan}, mask {mask}",
        "selectors": {"visibility": [visibility], "base_plan": [plan]},
        "entitlements": dict(entitlements),
        "entitlement_mask": mask,
        "controls": controls,
        # No cost is compiled for a derived mode. A costed envelope is a decision
        # somebody made and verified against billing, not something to infer.
        "cost": {},
        "rationale": posture,
        "_derived": True,
        "_derivation": trace,
        "_undetermined": undetermined,
        "_fallbacks": fallbacks,
    }


def resolve_shape(profiles_doc: dict[str, Any], capabilities: list[dict[str, Any]],
                  visibility: str, plan: str,
                  entitlements: dict[str, bool],
                  private_compute: str = "self-hosted") -> dict[str, Any]:
    """Resolve any repository shape: preset if one exists, derived otherwise.

    Raises ``ValueError`` only for a shape a plan gate forbids.
    """
    if private_compute not in {"self-hosted", "github-hosted"}:
        raise ValueError(f"unknown private compute policy {private_compute!r}")
    if visibility == "public" and private_compute != "self-hosted":
        raise ValueError("--private-compute applies only to private/internal repositories")

    reason = invalid_reason(profiles_doc, visibility, plan, entitlements)
    if reason is not None:
        raise ValueError(reason)
    profile = select(profiles_doc, visibility, plan, entitlements)
    if profile is None:
        profile = synthesize(profiles_doc, capabilities, visibility, plan, entitlements)
    else:
        # Presets may cover several plans/visibilities. Resolution must use the
        # concrete selected shape, not the first item in the preset selector;
        # otherwise private Pro can accidentally inherit Free plan gates.
        profile = copy.deepcopy(profile)
        profile["selectors"] = {"visibility": [visibility], "base_plan": [plan]}
    result = resolve(profiles_doc, capabilities, profile)
    if visibility in {"private", "internal"} and private_compute == "github-hosted":
        result["controls"]["compute_billing"] = "private-hosted-bounded"
        result["controls"]["runner_mode"] = "github-hosted-standard"
        result["cost"] = dict(result.get("cost") or {})
        metered = list(result["cost"].get("metered_lines") or [])
        if "actions-minutes" not in metered:
            metered.append("actions-minutes")
        result["cost"]["metered_lines"] = metered
        result["programme"]["runner_contract"]["mode"] = "github-hosted-standard"
        result["programme"]["runner_contract"]["actions_budget"] = \
            "stop-paid-usage-required"
        result["derivation"] = list(result.get("derivation") or []) + [
            "explicit private_compute=github-hosted opt-in: included allowance is "
            "bounded and overage is billable"
        ]
    return result


def _render(result: dict[str, Any]) -> str:
    lines = [
        f"profile: {result['profile']}  ({result['name']})",
        f"  source:       {result['source']}",
        f"  shape:        {result['visibility']} / {', '.join(result['base_plan'])} / mask {result['entitlement_mask']}",
        f"  tier column:  {result['tier_column']}",
        "  controls:",
    ]
    for key, value in result["controls"].items():
        lines.append(f"    {key}: {value}")
    if result["visibility"] in {"private", "internal"}:
        if result["controls"].get("compute_billing") == "private-self-hosted":
            lines.append("  cost guard:    pass a self-hosted runner label in every caller")
            lines.append("                 and route CodeQL default setup / Code Quality separately")
        elif result["controls"].get("runner_mode") == "github-hosted-standard":
            lines.append("  cost warning:  private hosted minutes are metered after the plan allowance")
            lines.append("  cost guard:    set an Actions budget with Stop paid usage enabled")
    for key in result.get("undetermined_controls") or []:
        lines.append(f"    {key}: (unset — the axes do not determine this; choose it)")
    cost = result["cost"]
    if result["source"] == "derived":
        lines.append("  fixed cost:   not compiled for a derived mode")
    else:
        fixed = cost.get("fixed_usd")
        lines.append(f"  fixed cost:   {'free' if not fixed else f'${fixed:g}/month'}")
    if cost.get("metered_lines"):
        lines.append(f"  metered:      {', '.join(cost['metered_lines'])}")
    if result.get("derivation"):
        lines.append("  derivation:")
        for step in result["derivation"]:
            lines.append(f"    - {step}")

    programme = result["programme"]
    lines.append("\ncompiled workflow programme:")
    lines.append(f"  release:      {programme['release_workflow']}")
    lines.append(
        "  runner:       " + str(programme["runner_contract"]["mode"])
        + (" (caller must set it explicitly)"
           if programme["runner_contract"]["caller_must_set_runner"] else "")
    )
    lines.append(f"  run now:      {len(programme['run_workflows'])} unique workflows")
    lines.append(f"  conditional:  {len(programme['conditional_workflows'])} unique workflows")

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
        programme = result.get("programme") or {}
        run_workflows = programme.get("run_workflows") or []
        release_workflow = programme.get("release_workflow")
        if release_workflow not in run_workflows:
            problems.append(f"resolve-profile: {pid} programme omits its release workflow")
        if ({".github/workflows/release-supply-chain.yml",
             ".github/workflows/release-supply-chain-free.yml"} <= set(run_workflows)):
            problems.append(f"resolve-profile: {pid} programme selects both release variants")
        if len(run_workflows) != len(set(run_workflows)):
            problems.append(f"resolve-profile: {pid} programme contains duplicate workflows")
        controls = result.get("controls") or {}
        visibility = result.get("visibility")
        if visibility in {"private", "internal"}:
            if controls.get("compute_billing") == "private-self-hosted" \
                    and not str(controls.get("runner_mode", "")).startswith("self-hosted-"):
                problems.append(
                    f"resolve-profile: {pid} promises zero GitHub Actions meter but "
                    f"selects runner_mode={controls.get('runner_mode')!r}"
                )
        # Round-trip: a profile must be reachable from the shape it declares.
        sel = profile.get("selectors") or {}
        back = select(profiles_doc, sel["visibility"][0], sel["base_plan"][0],
                      profile.get("entitlements") or {})
        if back is None or str(back.get("id")) != pid:
            problems.append(
                f"resolve-profile: {pid} is not selectable from its own selectors"
            )

    # Holding every add-on must resolve the capabilities those add-ons promise.
    # It does not make a private repository eligible for public-only Scorecard,
    # merge queue, or paid larger-runner previews, so "nothing excluded" would
    # itself be an entitlement leak.
    full = resolved.get("enterprise-full-private-fixed80")
    if full:
        runnable = {r["capability"] for key in ("included", "conditional")
                    for r in full[key]}
        promised = {"codeql-code-scanning", "dependency-review",
                    "native-secret-scanning", "github-code-quality",
                    "artifact-attestations", "slsa-build-provenance"}
        if promised - runnable:
            problems.append(
                "resolve-profile: the full paid profile does not resolve "
                f"{sorted(promised - runnable)}"
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
        return {x["capability"] for key in ("included", "conditional") for x in r[key]}

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

    # TOTALITY. Every shape a plan gate does not forbid must resolve. This is
    # the invariant the model claimed and did not hold: presets named 13 of the
    # 96 shapes and the resolver refused the other 83, so a supported customer
    # state was unresolvable for a naming reason. Exhaustive rather than
    # sampled, because the failures were spread across the space.
    axes = profiles_doc.get("axes") or {}
    visibilities = [str(v) for v in (axes.get("visibility") or {}).get("values") or []]
    plans = [str(p) for p in (axes.get("base_plan") or {}).get("values") or []]
    if not visibilities or not plans:
        problems.append("resolve-profile: axes declare no visibility/base_plan values")
    unresolved: list[str] = []
    inconsistent: list[str] = []
    for visibility in visibilities:
        for plan in plans:
            for bits in range(8):
                ents = {
                    key: bool(bits & (1 << (2 - index)))
                    for index, key in enumerate(ENTITLEMENT_KEYS)
                }
                shape_id = f"{visibility}/{plan}/{mask_of(ents)}"
                if invalid_reason(profiles_doc, visibility, plan, ents) is not None:
                    # Forbidden by a plan gate: refusing is the correct answer,
                    # but it must be a *stated* refusal, not a lookup miss.
                    continue
                try:
                    result = resolve_shape(profiles_doc, capabilities, visibility,
                                           plan, ents)
                except ValueError as exc:
                    unresolved.append(f"{shape_id}: {exc}")
                    continue
                if not result["included"]:
                    unresolved.append(f"{shape_id}: resolves to an empty programme")
                    continue
                # Determinism: the same shape must resolve identically twice.
                again = resolve_shape(profiles_doc, capabilities, visibility, plan, ents)
                if again != result:
                    inconsistent.append(shape_id)
    if unresolved:
        problems.append(
            f"resolve-profile: {len(unresolved)} valid shape(s) do not resolve — "
            "presets must not decide validity; first: " + unresolved[0]
        )
    if inconsistent:
        problems.append(
            f"resolve-profile: resolution is not deterministic for {inconsistent[:3]}"
        )

    # A shape a plan gate forbids must be refused with a reason, never silently
    # resolved: Code Quality on Free/Pro is not a mode anyone can buy.
    forbidden = {"code_security": False, "secret_protection": False, "code_quality": True}
    if invalid_reason(profiles_doc, "private", "pro", forbidden) is None:
        problems.append(
            "resolve-profile: Code Quality on a Pro plan resolved — the "
            "plan gate in catalog/profiles.yml is not being applied"
        )
    for entitlement, label in (
        ("code_security", "Code Security"),
        ("secret_protection", "Secret Protection"),
    ):
        ent = {"code_security": False, "secret_protection": False,
               "code_quality": False}
        ent[entitlement] = True
        if invalid_reason(profiles_doc, "private", "pro", ent) is None:
            problems.append(
                f"resolve-profile: {label} on private Pro resolved despite its "
                "Team/Enterprise Cloud purchase gate"
            )
    if invalid_reason(
        profiles_doc, "internal", "team",
        {"code_security": False, "secret_protection": False, "code_quality": False},
    ) is None:
        problems.append(
            "resolve-profile: an internal repository resolved outside Enterprise Cloud"
        )

    no_addons = {"code_security": False, "secret_protection": False,
                 "code_quality": False}
    private_free = resolve_shape(
        profiles_doc, capabilities, "private", "free", no_addons
    )
    private_pro = resolve_shape(
        profiles_doc, capabilities, "private", "pro", no_addons
    )
    enterprise_no_addons = resolve_shape(
        profiles_doc, capabilities, "private", "enterprise-cloud", no_addons
    )
    def runnable(result: dict[str, Any]) -> set[str]:
        return {row["capability"] for bucket in ("included", "conditional")
                for row in result[bucket]}
    if "rulesets" in runnable(private_free) or "rulesets" not in runnable(private_pro):
        problems.append(
            "resolve-profile: private rulesets must be unavailable on Free and "
            "available from Pro"
        )
    if "merge-queue" in runnable(private_pro) \
            or "merge-queue" not in runnable(enterprise_no_addons):
        problems.append(
            "resolve-profile: private merge queue must resolve only on Enterprise Cloud"
        )
    if any(cid.startswith("ossf-scorecard") for cid in runnable(enterprise_no_addons)):
        problems.append(
            "resolve-profile: public-only Scorecard workflow leaked into a private programme"
        )
    team_code_security = resolve_shape(
        profiles_doc, capabilities, "private", "team",
        {"code_security": True, "secret_protection": False,
         "code_quality": False},
    )
    leaked_licences = {"harden-runner", "license-compliance-preview"} \
        & runnable(team_code_security)
    if leaked_licences:
        problems.append(
            "resolve-profile: Code Security leaked separately licensed or "
            f"Enterprise-only capabilities {sorted(leaked_licences)}"
        )

    # A derived mode must never invent a costed envelope; a cost is a verified
    # decision, and the $80 drift is exactly what happens when one is inferred.
    try:
        derived = resolve_shape(profiles_doc, capabilities, "private", "team",
                                {"code_security": False, "secret_protection": True,
                                 "code_quality": False})
    except ValueError as exc:
        # A broken resolver must be reported, not raised: validate_all collects
        # problems from every check and a crash here would hide the rest.
        return problems + [f"resolve-profile: an unnamed valid shape raised: {exc}"]
    if derived["source"] != "derived":
        problems.append("resolve-profile: an unnamed shape did not report source=derived")
    if derived["cost"]:
        problems.append(
            "resolve-profile: a derived mode compiled a cost — cost is a verified "
            "decision, not something to infer from the axes"
        )
    if derived["controls"].get("compute_billing") != "private-self-hosted":
        problems.append(
            "resolve-profile: a derived private mode must fail safe to "
            "private-self-hosted compute"
        )
    if not str(derived["controls"].get("runner_mode", "")).startswith("self-hosted-"):
        problems.append(
            "resolve-profile: a derived private zero-meter mode must use self-hosted compute"
        )
    if not derived["derivation"]:
        problems.append("resolve-profile: a derived mode carries no derivation trace")

    hosted = resolve_shape(
        profiles_doc, capabilities, "private", "team",
        {"code_security": False, "secret_protection": True, "code_quality": False},
        "github-hosted",
    )
    if hosted["controls"].get("compute_billing") != "private-hosted-bounded" \
            or hosted["controls"].get("runner_mode") != "github-hosted-standard":
        problems.append(
            "resolve-profile: explicit private hosted opt-in does not select the "
            "private-hosted-bounded contract"
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
    parser.add_argument(
        "--private-compute",
        choices=["self-hosted", "github-hosted"],
        default="self-hosted",
        help=("private/internal only: self-hosted guarantees zero GitHub Actions "
              "compute meter; github-hosted explicitly accepts quota and overage"),
    )
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
        try:
            result = resolve_shape(profiles_doc, capabilities, args.visibility,
                                   args.plan, entitlements, args.private_compute)
        except ValueError as exc:
            print(
                f"{args.visibility}/{args.plan}/mask "
                f"{mask_of(entitlements)} is not a valid shape: {exc}",
                file=sys.stderr,
            )
            return 2
        print(json.dumps(result, indent=2) if args.json else _render(result))
        return 0

    result = resolve(profiles_doc, capabilities, profile)
    print(json.dumps(result, indent=2) if args.json else _render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
