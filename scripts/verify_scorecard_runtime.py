#!/usr/bin/env python3
"""Verify a live default-branch Scorecard SARIF run through GitHub APIs.

This is deliberately not part of the offline gate. It turns provider state into
an immutable receipt only after checking the caller run, reusable provenance,
required step conclusions, and accepted Code Scanning analysis independently.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _strict_yaml import strict_load  # noqa: E402
from _workflow_yaml import REPO_ROOT  # noqa: E402
from check_scorecard_evidence_contract import verify_proof  # noqa: E402


def fail(message: str) -> None:
    print(f"verify_scorecard_runtime: {message}", file=sys.stderr)
    raise SystemExit(1)


def api(endpoint: str) -> Any:
    result = subprocess.run(
        ["gh", "api", endpoint], cwd=REPO_ROOT, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode != 0:
        fail(f"GitHub API {endpoint!r} failed: {result.stderr.strip()}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        fail(f"GitHub API {endpoint!r} returned invalid JSON: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--repo", default="NDDev-it-com/ci-workflows")
    args = parser.parse_args()

    contract = strict_load(REPO_ROOT / "catalog" / "scorecard-evidence.yml")
    consumer = contract["designated_consumer"]
    if args.repo != consumer["repository"]:
        fail(f"{args.repo!r} is not the designated consumer {consumer['repository']!r}")
    repository = api(f"repos/{args.repo}")
    if repository.get("private") is not False or repository.get("fork") is not False:
        fail("designated consumer is not a public non-fork repository")
    if repository.get("default_branch") != consumer["default_branch"]:
        fail("designated consumer default branch drifted from the contract")

    run = api(f"repos/{args.repo}/actions/runs/{args.run_id}")
    expected_ref = f"refs/heads/{consumer['default_branch']}"
    expected_reusable = (
        f"{args.repo}/{consumer['reusable_workflow']}@{run.get('head_sha')}"
    )
    run_expected = {
        "event": "push",
        "head_branch": consumer["default_branch"],
        "path": consumer["caller_workflow"],
        "conclusion": "success",
    }
    for key, value in run_expected.items():
        if run.get(key) != value:
            fail(f"run {key} is {run.get(key)!r}, expected {value!r}")
    if run.get("head_repository", {}).get("full_name") != args.repo:
        fail("run head repository is not the designated consumer")
    referenced = run.get("referenced_workflows") or []
    exact_refs = [item for item in referenced if item.get("path") == expected_reusable]
    if len(exact_refs) != 1 or exact_refs[0].get("sha") != run.get("head_sha"):
        fail("run did not load the local SARIF reusable from its exact caller SHA")

    jobs = api(f"repos/{args.repo}/actions/runs/{args.run_id}/jobs").get("jobs") or []
    matching_jobs = [job for job in jobs if job.get("name") == "scorecard / OSSF Scorecard (publish)"]
    if len(matching_jobs) != 1:
        fail(f"expected one Scorecard SARIF job, found {len(matching_jobs)}")
    job = matching_jobs[0]
    if job.get("conclusion") != "success":
        fail(f"Scorecard SARIF job concluded {job.get('conclusion')!r}")
    steps = {step.get("name"): step.get("conclusion") for step in job.get("steps") or []}
    required_steps = {
        "Validate public default-branch contract": "success",
        "Run analysis": "success",
        "Upload artifact": "success",
        "Upload SARIF to code scanning": "success",
    }
    for name, conclusion in required_steps.items():
        if steps.get(name) != conclusion:
            fail(f"required step {name!r} concluded {steps.get(name)!r}, expected success")
    analysis_only_jobs = [
        candidate for candidate in jobs
        if candidate.get("name") == "analysis-only / OSSF Scorecard (analysis only)"
    ]
    if len(analysis_only_jobs) != 1:
        fail(f"expected one analysis-only job, found {len(analysis_only_jobs)}")
    analysis_only_job = analysis_only_jobs[0]
    if analysis_only_job.get("conclusion") != "success":
        fail(f"analysis-only job concluded {analysis_only_job.get('conclusion')!r}")
    analysis_only_steps = {
        step.get("name"): step.get("conclusion")
        for step in analysis_only_job.get("steps") or []
    }
    if analysis_only_steps.get("Run analysis") != "success":
        fail("analysis-only Scorecard step did not execute successfully")
    forbidden_runtime_steps = {"Upload artifact", "Upload SARIF to code scanning"}
    if forbidden_runtime_steps & set(analysis_only_steps):
        fail("analysis-only job unexpectedly contains a publication step")

    analyses = api(f"repos/{args.repo}/code-scanning/analyses?per_page=100")
    candidates = [
        item for item in analyses
        if item.get("ref") == expected_ref
        and item.get("commit_sha") == run.get("head_sha")
        and item.get("category") == consumer["sarif_category"]
        and item.get("tool", {}).get("name") == consumer["sarif_tool"]
        and item.get("analysis_key") == f"{consumer['caller_workflow']}:scorecard"
        and not item.get("error")
        and str(item.get("created_at", "")) >= str(run.get("run_started_at", ""))
    ]
    if len(candidates) != 1:
        fail(f"expected one accepted exact Scorecard analysis, found {len(candidates)}")
    analysis = candidates[0]
    reusable_path = REPO_ROOT / consumer["reusable_workflow"]
    digest = hashlib.sha256(reusable_path.read_bytes()).hexdigest()
    proof = {
        "repository": args.repo,
        "caller_sha": run["head_sha"],
        "caller_ref": expected_ref,
        "caller_workflow": consumer["caller_workflow"],
        "event": run["event"],
        "run_id": run["id"],
        "run_url": run["html_url"],
        "job_id": job["id"],
        "job_url": f"{run['html_url']}/job/{job['id']}",
        "analysis_only_job_id": analysis_only_job["id"],
        "analysis_only_job_url": f"{run['html_url']}/job/{analysis_only_job['id']}",
        "analysis_only_step": analysis_only_steps["Run analysis"],
        "analysis_step": steps["Run analysis"],
        "upload_step": steps["Upload SARIF to code scanning"],
        "reusable_sha": exact_refs[0]["sha"],
        "reusable_digest": digest,
        "reusable_workflow": consumer["reusable_workflow"],
        "analysis_id": analysis["id"],
        "analysis_url": analysis["url"],
        "analysis_key": analysis["analysis_key"],
        "analysis_ref": analysis["ref"],
        "analysis_commit_sha": analysis["commit_sha"],
        "analysis_category": analysis["category"],
        "analysis_tool": analysis["tool"]["name"],
        "run_started_at": run["run_started_at"],
        "analysis_created_at": analysis["created_at"],
    }
    problems = verify_proof(proof, consumer)
    if problems:
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        fail("constructed proof failed the canonical contract")
    print(yaml.safe_dump({"proof": proof}, sort_keys=False).rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
