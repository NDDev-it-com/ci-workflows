#!/usr/bin/env python3
"""Compile fail-closed runtime evidence lanes and render caller outputs/summary."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from _strict_yaml import strict_load
from _workflow_yaml import get_on

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG = REPO_ROOT / "catalog" / "evidence-orchestration.yml"
SCHEMA = REPO_ROOT / "catalog" / "schema" / "evidence-orchestration.schema.yaml"
LEVELS = ("fast", "pr-required", "full", "release")
HOST_CAPABILITIES = {"reboot", "gui-session", "ssh-network", "system-hardening"}
LANE_KEYS = {
    "id", "title", "workflow", "handoff", "minimum_level", "platforms",
    "operating_systems", "architectures", "profiles", "risks_any",
    "changes_any", "release", "environment_class", "host_capabilities",
    "evidence_class",
}


def load_contract(path: Path = CATALOG) -> tuple[dict[str, Any], list[str]]:
    doc = strict_load(path)
    problems: list[str] = []
    if not isinstance(doc, dict):
        return {}, [f"{path}: top level must be a mapping"]
    expected = {
        "schema", "levels", "platforms", "operating_systems", "architectures",
        "profiles", "risks", "changes", "environment_classes",
        "evidence_classes", "timing_policy", "lanes",
    }
    if set(doc) != expected:
        problems.append(f"{path}: unexpected or missing top-level keys")
    if doc.get("schema") != "nddev-ci-evidence-orchestration/v1":
        problems.append(f"{path}: unsupported schema")
    if tuple(doc.get("levels") or []) != LEVELS:
        problems.append(f"{path}: levels must be {list(LEVELS)} in order")
    if doc.get("timing_policy") != "observe-only":
        problems.append(f"{path}: timing_policy must be observe-only")
    evidence = doc.get("evidence_classes") or {}
    if set(evidence) != {"operational", "durable"}:
        problems.append(f"{path}: evidence classes must be operational/durable")
    elif [evidence[x].get("intended_downstream_retention_days") for x in
          ("operational", "durable")] != [7, 30]:
        problems.append(f"{path}: downstream semantic retention mapping must be 7/30")

    dimensions = {
        "platforms": set(doc.get("platforms") or []),
        "operating_systems": set(doc.get("operating_systems") or []),
        "architectures": set(doc.get("architectures") or []),
        "profiles": set(doc.get("profiles") or []),
        "risks_any": set(doc.get("risks") or []),
        "changes_any": set(doc.get("changes") or []),
    }
    for field, values in dimensions.items():
        raw = doc.get(field if field not in {"risks_any", "changes_any"} else
                      {"risks_any": "risks", "changes_any": "changes"}[field])
        if not isinstance(raw, list) or not raw or len(raw) != len(values):
            problems.append(f"{path}: {field} vocabulary must be a non-empty unique list")
    if set(doc.get("environment_classes") or []) != {
        "standard-hosted-vm", "native-disposable-host"
    }:
        problems.append(f"{path}: invalid environment_classes vocabulary")
    ids: list[str] = []
    for lane in doc.get("lanes") or []:
        if not isinstance(lane, dict):
            problems.append(f"{path}: every lane must be a mapping")
            continue
        lane_id = str(lane.get("id"))
        ids.append(lane_id)
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", lane_id):
            problems.append(f"{path}: invalid lane id {lane_id!r}")
        if not isinstance(lane.get("title"), str) or not lane["title"].strip():
            problems.append(f"{path}: lane {lane_id!r} needs a title")
        if set(lane) != LANE_KEYS:
            problems.append(f"{path}: lane {lane_id!r} has invalid keys")
        for field, allowed in dimensions.items():
            values = lane.get(field)
            if not isinstance(values, list) or len(values) != len(set(values)):
                problems.append(f"{path}: lane {lane_id!r} has invalid {field}")
            elif set(values) - allowed:
                problems.append(f"{path}: lane {lane_id!r} has unknown {field}")
        workflow, handoff = lane.get("workflow"), lane.get("handoff")
        if (workflow is None) == (handoff is None):
            problems.append(f"{path}: lane {lane_id!r} needs exactly one workflow/handoff")
        if workflow and not (REPO_ROOT / str(workflow)).is_file():
            problems.append(f"{path}: lane {lane_id!r} references missing workflow")
        elif workflow:
            triggers = get_on(strict_load(REPO_ROOT / str(workflow)))
            if not isinstance(triggers, dict) or "workflow_call" not in triggers:
                problems.append(
                    f"{path}: lane {lane_id!r} must reuse a workflow_call workflow"
                )
        native = lane.get("environment_class") == "native-disposable-host"
        if lane.get("environment_class") not in set(doc.get("environment_classes") or []):
            problems.append(f"{path}: lane {lane_id!r} has invalid environment_class")
        host_values = lane.get("host_capabilities")
        if not isinstance(host_values, list) or len(host_values) != len(set(host_values)) \
                or set(host_values) - HOST_CAPABILITIES:
            problems.append(f"{path}: lane {lane_id!r} has invalid host_capabilities")
        if native != bool(lane.get("host_capabilities")) or native != bool(handoff):
            problems.append(f"{path}: lane {lane_id!r} has incoherent host contract")
        if lane.get("minimum_level") not in LEVELS:
            problems.append(f"{path}: lane {lane_id!r} has invalid minimum_level")
        if lane.get("evidence_class") not in evidence:
            problems.append(f"{path}: lane {lane_id!r} has invalid evidence_class")
        if lane.get("release") not in {"forbidden", "allowed", "required"}:
            problems.append(f"{path}: lane {lane_id!r} has invalid release policy")
    if len(ids) != len(set(ids)):
        problems.append(f"{path}: duplicate lane ids")
    return doc, problems


def compile_plan(doc: dict[str, Any], *, level: str, platform: str, os_name: str,
                 arch: str, profile: str, risks: set[str], changes: set[str],
                 release: bool, host_capabilities: set[str]) -> dict[str, Any]:
    values = {
        "level": (level, set(doc["levels"])), "platform": (platform, set(doc["platforms"])),
        "os": (os_name, set(doc["operating_systems"])),
        "arch": (arch, set(doc["architectures"])),
        "profile": (profile, set(doc["profiles"])),
    }
    for name, (value, allowed) in values.items():
        if value not in allowed:
            raise ValueError(f"unknown {name} {value!r}; allowed: {sorted(allowed)}")
    for name, got, allowed in (("risk", risks, set(doc["risks"])),
                               ("change", changes, set(doc["changes"]))):
        if got - allowed:
            raise ValueError(f"unknown {name} values {sorted(got - allowed)}")
    if host_capabilities - HOST_CAPABILITIES:
        raise ValueError(f"unknown host capabilities {sorted(host_capabilities-HOST_CAPABILITIES)}")

    selected, skipped = [], []
    requested_rank = LEVELS.index(level)
    for lane in doc["lanes"]:
        reasons: list[str] = []
        if LEVELS.index(lane["minimum_level"]) > requested_rank:
            reasons.append(f"requires level {lane['minimum_level']}")
        if platform not in lane["platforms"]: reasons.append("platform mismatch")
        if os_name not in lane["operating_systems"]: reasons.append("OS mismatch")
        if arch not in lane["architectures"]: reasons.append("architecture mismatch")
        if profile not in lane["profiles"]: reasons.append("profile mismatch")
        if lane["risks_any"] and not risks.intersection(lane["risks_any"]):
            reasons.append("risk selector did not match")
        if lane["changes_any"] and not changes.intersection(lane["changes_any"]):
            reasons.append("change selector did not match")
        if lane["release"] == "required" and not release: reasons.append("release event required")
        if lane["release"] == "forbidden" and release: reasons.append("release event forbidden")
        missing_host = set(lane["host_capabilities"]) - host_capabilities
        if missing_host: reasons.append(f"missing host capabilities: {', '.join(sorted(missing_host))}")
        row = dict(lane)
        row["reason"] = "; ".join(reasons) if reasons else "all selectors matched"
        (skipped if reasons else selected).append(row)
    if not selected:
        raise ValueError("request selected zero lanes; refusing an all-skipped evidence plan")
    return {"request": {"level": level, "platform": platform, "os": os_name,
            "arch": arch, "profile": profile, "risks": sorted(risks),
            "changes": sorted(changes), "release": release,
            "host_capabilities": sorted(host_capabilities)},
            "timing_policy": "observe-only", "selected": selected, "skipped": skipped}


def render_summary(plan: dict[str, Any]) -> str:
    req = plan["request"]
    lines = ["### Evidence orchestration plan", "",
             f"Request: `{json.dumps(req, sort_keys=True)}`", "",
             "Timing is telemetry only; elapsed duration never selects, skips, cancels, or fails a lane.", "",
             "| Lane | Decision | Environment | Evidence class | Reason |", "| --- | --- | --- | --- | --- |"]
    for decision in ("selected", "skipped"):
        for lane in plan[decision]:
            lines.append(f"| `{lane['id']}` | {decision} | `{lane['environment_class']}` | `{lane['evidence_class']}` | {lane['reason']} |")
    return "\n".join(lines) + "\n"


def _write_github(plan: dict[str, Any], summary: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        selected = plan["selected"]
        values = {"plan_json": json.dumps(plan, separators=(",", ":")),
                  "selected_lane_ids": json.dumps([x["id"] for x in selected]),
                  "selected_workflows": json.dumps([x["workflow"] for x in selected if x["workflow"]]),
                  "host_handoffs": json.dumps([x for x in selected if x["handoff"]])}
        with open(output, "a", encoding="utf-8") as handle:
            for key, value in values.items(): handle.write(f"{key}={value}\n")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle: handle.write(summary)


def check() -> list[str]:
    doc, problems = load_contract()
    if not SCHEMA.is_file(): problems.append(f"missing schema {SCHEMA}")
    if problems: return problems
    positive = [
        ({"level":"fast","platform":"github-actions","os_name":"ubuntu","arch":"x64","profile":"public","risks":set(),"changes":set(),"release":False,"host_capabilities":set()}, {"static-contract"}),
        ({"level":"pr-required","platform":"github-actions","os_name":"ubuntu","arch":"x64","profile":"public","risks":{"code"},"changes":{"workflows"},"release":False,"host_capabilities":set()}, {"static-contract","actionlint"}),
        ({"level":"full","platform":"github-actions","os_name":"macos","arch":"arm64","profile":"public","risks":{"real-platform"},"changes":{"source"},"release":False,"host_capabilities":set()}, {"macos-runtime-smoke"}),
        ({"level":"full","platform":"openobserve-fleet","os_name":"macos","arch":"arm64","profile":"enterprise","risks":{"real-platform"},"changes":{"source"},"release":False,"host_capabilities":{"reboot","gui-session","ssh-network","system-hardening"}}, {"macos-native-host"}),
        ({"level":"release","platform":"github-actions","os_name":"ubuntu","arch":"x64","profile":"private-no-addons","risks":{"release"},"changes":{"release"},"release":True,"host_capabilities":set()}, {"static-contract","release-free"}),
    ]
    for args, expected in positive:
        try: got = {x["id"] for x in compile_plan(doc, **args)["selected"]}
        except ValueError as exc: problems.append(f"positive probe rejected: {exc}"); continue
        if got != expected: problems.append(f"positive probe selected {sorted(got)}, expected {sorted(expected)}")
    base = {"level":"full","platform":"openobserve-fleet","os_name":"macos","arch":"arm64","profile":"enterprise","risks":{"real-platform"},"changes":{"source"},"release":False,"host_capabilities":set()}
    negatives = [dict(base), {**base,"level":"unknown"}, {**base,"platform":"unknown"},
                 {**base,"os_name":"windows"}, {**base,"arch":"riscv64"},
                 {**base,"profile":"unknown"}, {**base,"risks":{"unknown"}},
                 {**base,"changes":{"unknown"}},
                 {**base,"host_capabilities":{"unknown"}}]
    for args in negatives:
        try: compile_plan(doc, **args)
        except ValueError: continue
        problems.append(f"negative probe unexpectedly accepted {args}")
    return problems


def csv_set(value: str) -> set[str]: return {x.strip() for x in value.split(",") if x.strip()}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--level", choices=LEVELS); p.add_argument("--platform")
    p.add_argument("--os", dest="os_name"); p.add_argument("--arch"); p.add_argument("--profile")
    p.add_argument("--risks", default=""); p.add_argument("--changes", default="")
    p.add_argument("--release", action="store_true"); p.add_argument("--host-capabilities", default="")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    if not all((args.level, args.platform, args.os_name, args.arch, args.profile)):
        problems = check()
        if problems:
            for problem in problems: print(f"evidence-orchestration: {problem}", file=sys.stderr)
            return 1
        print("compile_evidence_plan: OK"); return 0
    doc, problems = load_contract()
    if problems:
        for problem in problems: print(problem, file=sys.stderr)
        return 2
    try:
        plan = compile_plan(doc, level=args.level, platform=args.platform,
            os_name=args.os_name, arch=args.arch, profile=args.profile,
            risks=csv_set(args.risks), changes=csv_set(args.changes), release=args.release,
            host_capabilities=csv_set(args.host_capabilities))
    except ValueError as exc: print(f"evidence plan rejected: {exc}", file=sys.stderr); return 2
    summary = render_summary(plan); _write_github(plan, summary)
    print(json.dumps(plan, indent=2) if args.json else summary, end="")
    return 0


if __name__ == "__main__": raise SystemExit(main())
