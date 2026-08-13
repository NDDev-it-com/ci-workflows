#!/usr/bin/env python3
"""Fail-closed contract for event-correct Scorecard SARIF runtime evidence."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from copy import deepcopy
from typing import Any

from _strict_yaml import strict_load
from _workflow_yaml import REPO_ROOT, WORKFLOWS_DIR, get_on, load_yaml
from check_harden_runner_contract import HARDENED_WORKFLOWS, HARDEN_RUNNER

CONTRACT_PATH = REPO_ROOT / "catalog" / "scorecard-evidence.yml"
CALLER_PATH = WORKFLOWS_DIR / "scorecard.yml"
REUSABLE_PATH = WORKFLOWS_DIR / "public-scorecard.yml"
ANALYSIS_REUSABLE_PATH = WORKFLOWS_DIR / "public-scorecard-analysis.yml"
EXPECTED_CONSUMER = {
    "repository": "NDDev-it-com/ci-workflows",
    "visibility": "public",
    "default_branch": "main",
    "caller_workflow": ".github/workflows/scorecard.yml",
    "reusable_workflow": ".github/workflows/public-scorecard.yml",
    "analysis_reusable_workflow": ".github/workflows/public-scorecard-analysis.yml",
    "supported_events": ["push", "schedule"],
    "runner": "ubuntu-latest",
    "publish_results": True,
    "sarif_category": "ossf-scorecard",
    "sarif_tool": "Scorecard",
    "required_permissions": {
        "actions": "read",
        "contents": "read",
        "id-token": "write",
        "security-events": "write",
    },
    "analysis_only_permissions": {
        "actions": "read",
        "contents": "read",
    },
}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_MATRIX = [{
    "identity": "analysis-only",
    "workflow": ".github/workflows/public-scorecard-analysis.yml",
    "public_execution_tier": "conditional-public-oss",
    "private_execution_tier": "unsupported",
    "runner_class": "github-hosted-standard",
    "capability": "sarif-analysis-no-publication",
    "permissions": {"actions": "read", "contents": "read"},
    "harden_runner": {
        "required": True, "pin": HARDEN_RUNNER,
        "egress_policy": "audit", "position": "first",
    },
    "allowed_callers": {
        "visibility": "public", "repository_kind": "non-fork",
        "events": ["push", "schedule"], "ref": "actual-default-branch",
        "runner": "ubuntu-latest",
    },
    "evidence_obligations": [
        "job-and-analysis-step-success", "no-oidc-or-write-permission",
        "no-artifact-or-sarif-upload-step", "exact-caller-and-reusable-sha",
    ],
}, {
    "identity": "publish",
    "workflow": ".github/workflows/public-scorecard.yml",
    "public_execution_tier": "public-oss",
    "private_execution_tier": "unsupported",
    "runner_class": "github-hosted-standard",
    "capability": "scorecard-publication-and-sarif-upload",
    "permissions": {
        "actions": "read", "contents": "read", "id-token": "write",
        "security-events": "write",
    },
    "harden_runner": {
        "required": True, "pin": HARDEN_RUNNER,
        "egress_policy": "audit", "position": "first",
    },
    "allowed_callers": {
        "visibility": "public", "repository_kind": "non-fork",
        "events": ["push", "schedule"], "ref": "actual-default-branch",
        "runner": "ubuntu-latest",
    },
    "evidence_obligations": [
        "analysis-and-upload-steps-success", "exact-caller-and-reusable-sha",
        "accepted-code-scanning-analysis", "exact-ref-sha-tool-and-category",
    ],
}]
EXPECTED_ATTEMPTS = [{
    "attempt": 1,
    "classification": "product-failure",
    "caller_sha": "1c5545457b36d6875a43695902fca66a02136a18",
    "run_id": 31662081168,
    "run_url": "https://github.com/NDDev-it-com/ci-workflows/actions/runs/31662081168",
    "conclusion": "startup_failure",
    "reason": (
        "Nested scorecard job requested id-token: write while its "
        "publish_results:false caller allowed id-token: none."
    ),
}, {
    "attempt": 2,
    "classification": "product-failure",
    "caller_sha": "d1d5376da29bb2c494498630e04c5454287575a4",
    "run_id": 31662731064,
    "run_url": "https://github.com/NDDev-it-com/ci-workflows/actions/runs/31662731064",
    "conclusion": "startup_failure",
    "reason": (
        "GitHub preflight validated the skipped publish job before if and "
        "rejected its write permissions for the read-only caller."
    ),
}, {
    "attempt": 3,
    "classification": "contract-test-failure",
    "base_sha": "d1d5376da29bb2c494498630e04c5454287575a4",
    "issue_receipt": (
        "https://github.com/NDDev-it-com/ci-workflows/issues/128"
        "#issuecomment-5275483568"
    ),
    "command": "python3 scripts/validate_all.py --tier core",
    "failed_contract": "harden-runner-contract",
    "reason": (
        "The physical public analysis entrypoint was absent from the exact "
        "Harden-Runner public/GHAS allowlist."
    ),
}]


def _steps(workflow: dict[str, Any], job_id: str) -> dict[str, dict[str, Any]]:
    raw = workflow.get("jobs", {}).get(job_id, {}).get("steps", [])
    return {str(step.get("name")): step for step in raw if isinstance(step, dict)}


def _embedded_guard(step: dict[str, Any]) -> str:
    lines = str(step.get("run", "")).splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == "python3 -I <<'PY'"]
    if len(starts) != 1:
        raise ValueError(f"expected one isolated Python heredoc, found {len(starts)}")
    start = starts[0] + 1
    end = next(i for i in range(start, len(lines)) if lines[i] == "PY")
    return "\n".join(lines[start:end]) + "\n"


def _run_guard(program: str, **overrides: str) -> int:
    env = {
        **os.environ,
        "SCORECARD_EVENT_NAME": "push",
        "SCORECARD_REF": "refs/heads/main",
        "SCORECARD_DEFAULT_BRANCH": "main",
        "SCORECARD_REPOSITORY_PRIVATE": "false",
        "SCORECARD_REPOSITORY_FORK": "false",
        "SCORECARD_SERVER_URL": "https://github.com",
        "SCORECARD_SARIF_CATEGORY": "ossf-scorecard",
        **overrides,
    }
    return subprocess.run(
        [sys.executable, "-I", "-"], input=program, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    ).returncode


def _caller_contract_problems(caller: dict[str, Any], consumer: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    events = get_on(caller)
    if not isinstance(events, dict) or set(events) != {"push", "schedule"}:
        problems.append("canonical Scorecard consumer must trigger only on push and schedule")
    elif events.get("push", {}).get("branches") != ["main"]:
        problems.append("canonical Scorecard consumer push must target only its default branch main")
    if caller.get("permissions") != {}:
        problems.append("canonical Scorecard consumer must deny permissions at top level")
    concurrency = caller.get("concurrency", {})
    if concurrency.get("cancel-in-progress") is not False:
        problems.append("canonical Scorecard evidence must preserve the first run rather than cancel it")
    jobs = caller.get("jobs", {})
    expected = {
        "analysis-only": (
            consumer["analysis_only_permissions"],
            "./.github/workflows/public-scorecard-analysis.yml",
            {"runner": "ubuntu-latest", "sarif_category": "ossf-scorecard"},
        ),
        "scorecard": (
            consumer["required_permissions"],
            "./.github/workflows/public-scorecard.yml",
            {"runner": "ubuntu-latest", "publish_results": True,
             "sarif_category": "ossf-scorecard"},
        ),
    }
    if set(jobs) != set(expected):
        problems.append("canonical consumer must contain exactly analysis-only and publish jobs")
    for job_id, (permissions, entrypoint, inputs) in expected.items():
        job = jobs.get(job_id, {})
        if job.get("uses") != entrypoint:
            problems.append(f"canonical {job_id} consumer must call its physical entrypoint")
        if "if" in job:
            problems.append(f"canonical {job_id} must not hide an entrypoint behind job if")
        if job.get("permissions") != permissions:
            problems.append(f"canonical {job_id} permissions drifted from its exact mode")
        if job.get("with") != inputs:
            problems.append(f"canonical {job_id} inputs must select its exact boolean mode")
    analysis_permissions = jobs.get("analysis-only", {}).get("permissions", {})
    if {"id-token", "security-events"} & set(analysis_permissions):
        problems.append("analysis-only caller must not grant OIDC or Code Scanning writes")
    return problems


def verify_proof(proof: Any, consumer: dict[str, Any]) -> list[str]:
    """Validate an immutable post-merge API receipt; synthetic self-tests use this too."""
    if proof is None:
        return []
    if not isinstance(proof, dict):
        return ["scorecard proof must be null or a mapping"]
    required = {
        "repository", "caller_sha", "caller_ref", "caller_workflow", "event",
        "run_id", "run_url", "job_id", "job_url", "analysis_only_job_id",
        "analysis_only_job_url", "analysis_only_step", "analysis_step",
        "upload_step", "reusable_sha", "reusable_digest", "reusable_workflow",
        "analysis_reusable_sha", "analysis_reusable_digest",
        "analysis_reusable_workflow",
        "analysis_id", "analysis_url", "analysis_key", "analysis_ref",
        "analysis_commit_sha", "analysis_category", "analysis_tool",
        "run_started_at", "analysis_created_at",
    }
    missing = required - set(proof)
    extra = set(proof) - required
    problems: list[str] = []
    if missing:
        problems.append(f"scorecard proof missing fields {sorted(missing)}")
    if extra:
        problems.append(f"scorecard proof has unexpected fields {sorted(extra)}")
    if missing:
        return problems
    expected = {
        "repository": consumer["repository"],
        "caller_ref": f"refs/heads/{consumer['default_branch']}",
        "caller_workflow": consumer["caller_workflow"],
        "event": "push",
        "analysis_only_step": "success",
        "analysis_step": "success",
        "upload_step": "success",
        "reusable_workflow": consumer["reusable_workflow"],
        "analysis_reusable_workflow": consumer["analysis_reusable_workflow"],
        "analysis_ref": f"refs/heads/{consumer['default_branch']}",
        "analysis_category": consumer["sarif_category"],
        "analysis_tool": consumer["sarif_tool"],
        "analysis_key": f"{consumer['caller_workflow']}:scorecard",
    }
    for key, value in expected.items():
        if proof.get(key) != value:
            problems.append(f"scorecard proof {key} is {proof.get(key)!r}, expected {value!r}")
    if not SHA_RE.fullmatch(str(proof.get("caller_sha", ""))):
        problems.append("scorecard proof caller_sha must be a full commit SHA")
    if proof.get("analysis_commit_sha") != proof.get("caller_sha"):
        problems.append("Scorecard analysis commit does not equal caller default-branch SHA")
    if proof.get("reusable_sha") != proof.get("caller_sha"):
        problems.append("local reusable was not loaded from the exact caller commit")
    if proof.get("analysis_reusable_sha") != proof.get("caller_sha"):
        problems.append("analysis reusable was not loaded from the exact caller commit")
    if not DIGEST_RE.fullmatch(str(proof.get("reusable_digest", ""))):
        problems.append("scorecard proof reusable_digest must be a lowercase SHA-256")
    if not DIGEST_RE.fullmatch(str(proof.get("analysis_reusable_digest", ""))):
        problems.append("scorecard proof analysis_reusable_digest must be a lowercase SHA-256")
    for key in ("run_id", "job_id", "analysis_only_job_id", "analysis_id"):
        if not isinstance(proof.get(key), int) or proof[key] <= 0:
            problems.append(f"scorecard proof {key} must be a positive integer")
    for key in ("run_url", "job_url", "analysis_only_job_url", "analysis_url"):
        allowed_prefixes = ("https://github.com/", "https://api.github.com/")
        if not str(proof.get(key, "")).startswith(allowed_prefixes):
            problems.append(f"scorecard proof {key} must be an immutable GitHub URL")
    if str(proof.get("analysis_created_at", "")) < str(proof.get("run_started_at", "")):
        problems.append("Scorecard analysis predates the caller run")
    return problems


def _proof_selftests(consumer: dict[str, Any]) -> list[str]:
    base = {
        "repository": consumer["repository"],
        "caller_sha": "a" * 40,
        "caller_ref": "refs/heads/main",
        "caller_workflow": consumer["caller_workflow"],
        "event": "push",
        "run_id": 1,
        "run_url": "https://github.com/NDDev-it-com/ci-workflows/actions/runs/1",
        "job_id": 2,
        "job_url": "https://github.com/NDDev-it-com/ci-workflows/actions/runs/1/job/2",
        "analysis_only_job_id": 4,
        "analysis_only_job_url": "https://github.com/NDDev-it-com/ci-workflows/actions/runs/1/job/4",
        "analysis_only_step": "success",
        "analysis_step": "success",
        "upload_step": "success",
        "reusable_sha": "a" * 40,
        "reusable_digest": "b" * 64,
        "reusable_workflow": consumer["reusable_workflow"],
        "analysis_reusable_sha": "a" * 40,
        "analysis_reusable_digest": "d" * 64,
        "analysis_reusable_workflow": consumer["analysis_reusable_workflow"],
        "analysis_id": 3,
        "analysis_url": "https://github.com/NDDev-it-com/ci-workflows/security/code-scanning/tools/Scorecard/status/",
        "analysis_key": ".github/workflows/scorecard.yml:scorecard",
        "analysis_ref": "refs/heads/main",
        "analysis_commit_sha": "a" * 40,
        "analysis_category": "ossf-scorecard",
        "analysis_tool": "Scorecard",
        "run_started_at": "2026-08-13T00:00:00Z",
        "analysis_created_at": "2026-08-13T00:01:00Z",
    }
    if verify_proof(base, consumer):
        return ["scorecard proof self-test rejected the valid receipt"]
    mutations = {
        "non-default-ref": {"caller_ref": "refs/heads/fixtures/test"},
        "private-or-nondesignated": {"repository": "NDDev-it-com/other"},
        "skipped-analysis": {"analysis_step": "skipped"},
        "skipped-analysis-only": {"analysis_only_step": "skipped"},
        "skipped-upload": {"upload_step": "skipped"},
        "unpinned-reusable": {"reusable_sha": "main"},
        "wrong-sha": {"analysis_commit_sha": "c" * 40},
        "wrong-category": {"analysis_category": "default"},
        "wrong-tool": {"analysis_tool": "CodeQL"},
        "json-only": {"reusable_workflow": ".github/workflows/public-scorecard-json.yml"},
        "wrong-analysis-entrypoint": {"analysis_reusable_workflow": ".github/workflows/public-scorecard.yml"},
    }
    problems: list[str] = []
    for label, values in mutations.items():
        candidate = deepcopy(base)
        candidate.update(values)
        if not verify_proof(candidate, consumer):
            problems.append(f"scorecard proof self-test accepted {label}")
    return problems


def _matrix_contract_problems(matrix: Any) -> list[str]:
    return [] if matrix == EXPECTED_MATRIX else ["Scorecard entrypoint tier/permission/hardening matrix drifted"]


def _matrix_selftests() -> list[str]:
    mutations = {
        "analysis-overgrant": (0, "permissions", {"actions": "read", "contents": "read", "id-token": "write"}),
        "analysis-private": (0, "private_execution_tier", "private-paid"),
        "analysis-fleet": (0, "runner_class", "self-hosted-fleet"),
        "analysis-no-hardening": (0, "harden_runner", {"required": False}),
        "publish-undergrant": (1, "permissions", {"actions": "read", "contents": "read"}),
        "publish-wrong-tier": (1, "public_execution_tier", "private-free"),
        "wildcard-entrypoint": (1, "workflow", ".github/workflows/public-scorecard*.yml"),
    }
    problems: list[str] = []
    for label, (index, key, value) in mutations.items():
        candidate = deepcopy(EXPECTED_MATRIX)
        candidate[index][key] = value
        if not _matrix_contract_problems(candidate):
            problems.append(f"Scorecard matrix self-test accepted {label}")
    return problems


def check() -> list[str]:
    problems: list[str] = []
    contract = strict_load(CONTRACT_PATH)
    if contract.get("schema") != "nddev-ci-scorecard-evidence/v1":
        problems.append("scorecard evidence catalog has an unknown schema")
    problems += _matrix_contract_problems(contract.get("entrypoint_matrix"))
    problems += _matrix_selftests()
    matrix_workflows = {row["workflow"].rsplit("/", 1)[-1] for row in EXPECTED_MATRIX}
    if not matrix_workflows <= HARDENED_WORKFLOWS:
        problems.append("Scorecard public entrypoints are not exact Harden-Runner allowlist members")
    if any("*" in name for name in HARDENED_WORKFLOWS):
        problems.append("Harden-Runner allowlist must enumerate exact workflow filenames")
    if contract.get("attempts") != EXPECTED_ATTEMPTS:
        problems.append("Scorecard preserved product-failure receipts drifted")
    consumer = contract.get("designated_consumer")
    if consumer != EXPECTED_CONSUMER:
        problems.append("scorecard evidence consumer must be the exact owned public default-branch contract")
        consumer = EXPECTED_CONSUMER

    capabilities = strict_load(REPO_ROOT / "catalog" / "capabilities.yml").get("capabilities", [])
    scorecard_tiers = {
        row.get("id"): (row.get("public_oss"), row.get("private_free"), row.get("private_paid"))
        for row in capabilities if str(row.get("id", "")).startswith("ossf-scorecard")
    }
    if scorecard_tiers.get("ossf-scorecard") != ("free", "unavailable", "unavailable"):
        problems.append("Scorecard publish entrypoint tier classification drifted")
    if scorecard_tiers.get("ossf-scorecard-analysis") != ("conditional", "unavailable", "unavailable"):
        problems.append("Scorecard analysis alternative tier classification drifted")

    caller = load_yaml(CALLER_PATH)
    problems += _caller_contract_problems(caller, consumer)
    missing_security_events = deepcopy(caller)
    del missing_security_events["jobs"]["scorecard"]["permissions"]["security-events"]
    if not _caller_contract_problems(missing_security_events, consumer):
        problems.append("Scorecard caller self-test accepted missing security-events permission")
    missing_oidc = deepcopy(caller)
    del missing_oidc["jobs"]["scorecard"]["permissions"]["id-token"]
    if not _caller_contract_problems(missing_oidc, consumer):
        problems.append("Scorecard caller self-test accepted missing publish OIDC permission")
    json_only_caller = deepcopy(caller)
    json_only_caller["jobs"]["scorecard"]["uses"] = "./.github/workflows/public-scorecard-json.yml"
    if not _caller_contract_problems(json_only_caller, consumer):
        problems.append("Scorecard caller self-test accepted the JSON-only reusable")
    overgranted_caller = deepcopy(caller)
    overgranted_caller["jobs"]["analysis-only"]["permissions"]["id-token"] = "write"
    if not _caller_contract_problems(overgranted_caller, consumer):
        problems.append("Scorecard caller self-test accepted analysis-only OIDC overgrant")
    analysis_write_caller = deepcopy(caller)
    analysis_write_caller["jobs"]["analysis-only"]["permissions"]["security-events"] = "write"
    if not _caller_contract_problems(analysis_write_caller, consumer):
        problems.append("Scorecard caller self-test accepted analysis-only SARIF write")
    hidden_publish_caller = deepcopy(caller)
    hidden_publish_caller["jobs"]["scorecard"]["if"] = "${{ false }}"
    if not _caller_contract_problems(hidden_publish_caller, consumer):
        problems.append("Scorecard caller self-test accepted hidden conditional publish")
    dual_publish_caller = deepcopy(caller)
    dual_publish_caller["jobs"]["analysis-only"]["uses"] = "./.github/workflows/public-scorecard.yml"
    if not _caller_contract_problems(dual_publish_caller, consumer):
        problems.append("Scorecard caller self-test accepted dual publish entrypoints")
    reusable = load_yaml(REUSABLE_PATH)
    analysis_reusable = load_yaml(ANALYSIS_REUSABLE_PATH)
    reusable_call = get_on(reusable).get("workflow_call", {})
    analysis_call = get_on(analysis_reusable).get("workflow_call", {})
    publish_input = reusable_call.get("inputs", {}).get("publish_results", {})
    if publish_input != {
        "description": "Publish results to the OpenSSF Scorecard API (public repos).",
        "type": "boolean", "default": True,
    }:
        problems.append("publish_results must remain an exact typed boolean with its compatible default")
    expected_analysis_inputs = {
        key: deepcopy(value) for key, value in reusable_call.get("inputs", {}).items()
        if key not in {"publish_results", "upload_sarif_on_forks"}
    }
    if analysis_call.get("inputs") != expected_analysis_inputs:
        problems.append("analysis entrypoint inputs drifted from the common compatible API")
    if {"publish_results", "upload_sarif_on_forks"} & set(analysis_call.get("inputs", {})):
        problems.append("analysis entrypoint must expose no publication-mode inputs")
    if reusable_call.get("outputs", {}).get("sarif_id", {}).get("value") != "${{ jobs.scorecard.outputs.sarif_id }}":
        problems.append("public-scorecard must expose the SARIF upload identifier")
    jobs = reusable.get("jobs", {})
    analysis_jobs = analysis_reusable.get("jobs", {})
    if set(jobs) != {"scorecard"} or set(analysis_jobs) != {"scorecard"}:
        problems.append("each Scorecard entrypoint must physically contain exactly one job")
    publish_job = jobs.get("scorecard", {})
    analysis_job = analysis_jobs.get("scorecard", {})
    if "if" in publish_job or "if" in analysis_job:
        problems.append("physical Scorecard entrypoint jobs must never use conditional mode selection")
    if analysis_job.get("permissions") != consumer["analysis_only_permissions"]:
        problems.append("analysis-only reusable must request only contents/actions read")
    if {"id-token", "security-events"} & set(analysis_job.get("permissions", {})):
        problems.append("analysis-only reusable must never request OIDC or Code Scanning writes")
    if publish_job.get("permissions") != consumer["required_permissions"]:
        problems.append("publish reusable must request the exact proven publication permissions")
    if publish_job.get("outputs", {}).get("sarif_id") != "${{ steps.upload-sarif.outputs.sarif-id }}":
        problems.append("publish job must bind sarif_id to the upload-sarif output")
    steps = _steps(reusable, "scorecard")
    analysis_steps = _steps(analysis_reusable, "scorecard")
    required_steps = {
        "Harden runner", "Validate public default-branch contract", "Run analysis",
        "Upload artifact", "Upload SARIF to code scanning",
    }
    if not required_steps <= steps.keys():
        problems.append(f"public-scorecard is missing required evidence steps {sorted(required_steps - steps.keys())}")
        return problems
    if "Upload SARIF to code scanning" in analysis_steps:
        problems.append("analysis-only mode must not contain a SARIF upload step")
    forbidden_analysis_steps = {"Upload artifact", "Upload SARIF to code scanning"}
    if forbidden_analysis_steps & set(analysis_steps):
        problems.append("analysis-only mode must not publish SARIF as an artifact or Code Scanning analysis")
    for mode, mode_steps in (("analysis", analysis_steps), ("publish", steps)):
        harden = mode_steps.get("Harden runner", {})
        if harden.get("uses") != HARDEN_RUNNER or harden.get("with") != {"egress-policy": "audit"}:
            problems.append(f"Scorecard {mode} hardening pin/config drifted")
        if list(mode_steps)[0] != "Harden runner" or "if" in harden:
            problems.append(f"Scorecard {mode} hardening must be unconditional and first")
    common_names = list(analysis_steps)
    publish_common_names = [name for name in steps if name not in {
        "Validate publish entrypoint", "Upload artifact", "Upload SARIF to code scanning",
    }]
    if common_names != publish_common_names:
        problems.append("Scorecard mode common-step order drifted")
    for name in common_names:
        analysis_step = deepcopy(analysis_steps[name])
        publish_step = deepcopy(steps[name])
        if name == "Run analysis":
            if analysis_step.get("with", {}).get("publish_results") is not False:
                problems.append("analysis entrypoint must hardcode publish_results: false")
            analysis_step["with"]["publish_results"] = "${{ inputs.publish_results }}"
        if analysis_step != publish_step:
            problems.append(f"Scorecard physical entrypoint common step {name!r} drifted")
    for field in ("runs-on", "timeout-minutes"):
        if analysis_job.get(field) != publish_job.get(field):
            problems.append(f"Scorecard mode {field} drifted")
    step_order = list(steps)
    if step_order[0] != "Harden runner" or not (
        step_order.index("Validate public default-branch contract")
        < step_order.index("Checkout") < step_order.index("Run analysis")
    ):
        problems.append("Scorecard hardening and event guard must run before checkout or analysis")
    try:
        guard = _embedded_guard(steps["Validate public default-branch contract"])
    except (ValueError, StopIteration) as exc:
        problems.append(f"Scorecard guard extraction failed: {exc}")
    else:
        for event in ("push", "schedule"):
            if _run_guard(guard, SCORECARD_EVENT_NAME=event) != 0:
                problems.append(f"Scorecard guard rejected supported {event} default-branch event")
        invalid = {
            "non-default-ref": {"SCORECARD_REF": "refs/heads/fixtures/test"},
            "private": {"SCORECARD_REPOSITORY_PRIVATE": "true"},
            "fork": {"SCORECARD_REPOSITORY_FORK": "true"},
            "pull-request": {"SCORECARD_EVENT_NAME": "pull_request"},
            "workflow-dispatch": {"SCORECARD_EVENT_NAME": "workflow_dispatch"},
            "ghes": {"SCORECARD_SERVER_URL": "https://github.example.com"},
            "wrong-category-shape": {"SCORECARD_SARIF_CATEGORY": "Scorecard SARIF"},
        }
        for label, values in invalid.items():
            if _run_guard(guard, **values) == 0:
                problems.append(f"Scorecard guard accepted unsupported {label}")

    analysis = steps["Run analysis"]
    if analysis.get("uses") != "ossf/scorecard-action@2d1146689b8cda280b9bc96326124645441f03bc":
        problems.append("Scorecard analysis action must retain the immutable v2.4.4 pin")
    if analysis.get("with", {}).get("results_format") != "sarif":
        problems.append("public-scorecard analysis must produce SARIF, not JSON-only evidence")
    upload = steps["Upload SARIF to code scanning"]
    if upload.get("id") != "upload-sarif":
        problems.append("Scorecard SARIF upload must expose its documented output")
    if upload.get("uses") != "github/codeql-action/upload-sarif@d1ba80a13dd99fba24a470575428917156a28b43":
        problems.append("Scorecard upload-sarif action must retain the immutable v4.37.5 pin")
    if upload.get("with", {}).get("category") != "${{ inputs.sarif_category }}":
        problems.append("Scorecard SARIF upload must use the caller-visible deterministic category")
    if upload.get("continue-on-error") or analysis.get("continue-on-error"):
        problems.append("Scorecard analysis/upload failures must never be hidden")
    problems += verify_proof(contract.get("proof"), consumer)
    problems += _proof_selftests(consumer)
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_scorecard_evidence_contract: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("check_scorecard_evidence_contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
