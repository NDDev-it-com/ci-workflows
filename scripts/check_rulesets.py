#!/usr/bin/env python3
"""Validate the ruleset JSON specs under `.github/rulesets/` against the shape
accepted by `POST /repos/{owner}/{repo}/rulesets`. This is a static shape check,
not a live GitHub state check.

Shape is not the same as force, and this check used to assert only shape.
`enforcement` was validated against an enum that accepts `disabled`, so the
default-branch ruleset could have been switched off entirely and this gate would
still have been green while the required `ci-gate` context protected nothing.
Tag validation was a single boolean — "a tag ruleset exists" — even though the
consumer-adoption skill tells every consumer that tags in this library are
immutable, a promise that rests on three specific rules none of which were
checked. Both are now asserted, and a ruleset that deliberately runs below
`active` has to say so here with a reason.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RULESETS_DIR = REPO_ROOT / ".github" / "rulesets"

VALID_TARGETS = {"branch", "tag", "push"}
VALID_ENFORCEMENT = {"active", "evaluate", "disabled"}
VALID_BYPASS_MODES = {"always", "pull_request"}

# A branch or tag ruleset carries a security property, so it must actually be
# enforced. Anything weaker is a deliberate choice that belongs here, in the
# diff, rather than in a JSON field nobody re-reads.
ENFORCED_TARGETS = {"branch", "tag"}
NON_ACTIVE_ENFORCEMENT_REASONS = {
    "push-hygiene.json": (
        "Advisory by intent: it restricts committing build output, which is "
        "hygiene rather than a trust boundary, and `evaluate` reports the "
        "violation without blocking an unrelated push."
    ),
}

# What "immutable release tags" actually requires. `deletion` and
# `non_fast_forward` alone still allow a tag to be moved; `update` is the rule
# that forbids repointing it, and `required_signatures` is what makes the
# release-promotion gate's signed-tag payload meaningful.
REQUIRED_TAG_RULES = {"deletion", "non_fast_forward", "update", "required_signatures"}

# Bypass actors are real holes in the properties above. Keeping the expected set
# here means adding one shows up as a validator change, not as a silent edit to
# a JSON file. Actor id 5 is the repository-admin role: this is a solo-maintained
# repository, and `docs/08` records the trade-off.
EXPECTED_BYPASS_ACTORS = {
    "branch-main.json": {(5, "RepositoryRole", "always")},
    "tag-semver.json": {(5, "RepositoryRole", "always")},
    "push-hygiene.json": {(5, "RepositoryRole", "always")},
}


def check() -> list[str]:
    problems: list[str] = []
    if not RULESETS_DIR.is_dir():
        return [f"missing rulesets directory: {RULESETS_DIR}"]

    files = sorted(RULESETS_DIR.glob("*.json"))
    if not files:
        problems.append("no ruleset JSON files found")

    saw_branch_default = False
    saw_tag = False

    for path in files:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"{path.name}: invalid JSON: {exc}")
            continue

        name = path.name
        if not doc.get("name"):
            problems.append(f"{name}: missing `name`")
        target = doc.get("target")
        if target not in VALID_TARGETS:
            problems.append(f"{name}: `target` must be one of {sorted(VALID_TARGETS)}")
        enforcement = doc.get("enforcement")
        if enforcement not in VALID_ENFORCEMENT:
            problems.append(f"{name}: `enforcement` must be one of {sorted(VALID_ENFORCEMENT)}")
        elif enforcement != "active":
            reason = NON_ACTIVE_ENFORCEMENT_REASONS.get(name)
            if target in ENFORCED_TARGETS:
                problems.append(
                    f"{name}: a {target} ruleset must be `enforcement: active`; "
                    f"{enforcement!r} enforces nothing"
                )
            elif not reason:
                problems.append(
                    f"{name}: `enforcement: {enforcement}` enforces nothing and has "
                    "no recorded reason in check_rulesets.py"
                )
        elif name in NON_ACTIVE_ENFORCEMENT_REASONS:
            problems.append(
                f"{name}: is `active` but still carries a non-active enforcement "
                "reason in check_rulesets.py; drop the stale exemption"
            )

        for actor in doc.get("bypass_actors", []) or []:
            if actor.get("bypass_mode") not in VALID_BYPASS_MODES:
                problems.append(f"{name}: bypass_actor bypass_mode must be one of {sorted(VALID_BYPASS_MODES)}")
        if name in EXPECTED_BYPASS_ACTORS:
            declared = {
                (actor.get("actor_id"), actor.get("actor_type"), actor.get("bypass_mode"))
                for actor in doc.get("bypass_actors", []) or []
            }
            if declared != EXPECTED_BYPASS_ACTORS[name]:
                problems.append(
                    f"{name}: bypass actors changed to {sorted(map(str, declared))}; "
                    "update EXPECTED_BYPASS_ACTORS in check_rulesets.py so the "
                    "change is reviewed rather than inherited"
                )

        rules = doc.get("rules")
        if not isinstance(rules, list) or not rules:
            problems.append(f"{name}: `rules` must be a non-empty list")
            rules = []
        for rule in rules:
            if not isinstance(rule, dict) or "type" not in rule:
                problems.append(f"{name}: each rule needs a `type`")

        rule_types = {r.get("type") for r in rules if isinstance(r, dict)}

        if target == "branch":
            include = (doc.get("conditions", {}).get("ref_name", {}) or {}).get("include", [])
            if "~DEFAULT_BRANCH" in include or "~ALL" in include:
                saw_branch_default = True
                if "required_status_checks" in rule_types:
                    params = next(
                        (r.get("parameters", {}) for r in rules
                         if r.get("type") == "required_status_checks"), {})
                    contexts = {c.get("context") for c in params.get("required_status_checks", [])}
                    if "ci-gate" not in contexts:
                        problems.append(f"{name}: default-branch ruleset must require the `ci-gate` status check")
                else:
                    problems.append(f"{name}: default-branch ruleset must include a `required_status_checks` rule")
        if target == "tag":
            saw_tag = True
            missing_tag_rules = REQUIRED_TAG_RULES - rule_types
            if missing_tag_rules:
                problems.append(
                    f"{name}: tag ruleset is missing {sorted(missing_tag_rules)}; "
                    "the consumer-adoption skill promises immutable release tags "
                    "and those rules are what make that true"
                )

    if files and not saw_branch_default:
        problems.append("no ruleset protects the default branch (~DEFAULT_BRANCH)")
    if files and not saw_tag:
        problems.append("no ruleset protects release tags (target: tag)")
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_rulesets: FAIL", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print("check_rulesets: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
