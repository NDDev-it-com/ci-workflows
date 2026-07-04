#!/usr/bin/env python3
"""Validate the ruleset JSON specs under `.github/rulesets/` against the shape
accepted by `POST /repos/{owner}/{repo}/rulesets`. This is a static shape check,
not a live GitHub state check.
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
        if doc.get("enforcement") not in VALID_ENFORCEMENT:
            problems.append(f"{name}: `enforcement` must be one of {sorted(VALID_ENFORCEMENT)}")

        for actor in doc.get("bypass_actors", []) or []:
            if actor.get("bypass_mode") not in VALID_BYPASS_MODES:
                problems.append(f"{name}: bypass_actor bypass_mode must be one of {sorted(VALID_BYPASS_MODES)}")

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
