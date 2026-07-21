#!/usr/bin/env python3
"""Completeness and honesty gate for the runtime-coverage ledger.

A green static gate (actionlint, zizmor, embedded-program validators) does not
prove that every published reusable workflow actually starts and behaves
correctly across its advertised events, tiers, runners, and permissions. This
validator does not try to prove that; it enforces that the repository is
HONEST about what is proven. Every reusable workflow must have exactly one
coverage record; `runtime-proven` requires a real Actions run in this repo plus
the sha256 of the workflow file at that run (so a later edit cannot silently
keep the proven label); `static-only` must name the validator that stands in
for a live run; `waived` needs an owner, reason, and unexpired date. It then reports the status counts so an unverified
surface can never masquerade as covered.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import sys
from pathlib import Path

import yaml

from _workflow_yaml import SELF_WORKFLOWS, WORKFLOWS_DIR

REPO_ROOT = Path(__file__).resolve().parent.parent
COVERAGE = REPO_ROOT / "catalog" / "runtime-coverage.yml"
SCHEMA = "nddev-ci-runtime-contract-coverage/v1"
VALID_STATUS = {
    "runtime-proven", "static-only", "unverified", "waived", "unsupported",
    "blocked",
}
# A runtime-proven record must cite a real Actions run in THIS repository — not
# an arbitrary https URL (the previous check accepted example.invalid, a docs
# page, or a foreign-repo run) — and must pin the sha256 of the workflow file
# as it was proven. The digest turns any later edit into an enforced, visible
# ledger change: a modified workflow can no longer keep a matching
# proven_digest, so it must be re-run and re-recorded (or downgraded) rather
# than silently masquerading as still-proven. The validator cannot fetch the
# run's tree, so it does not bind the run to the bytes — that stays a human
# review step — but staleness is no longer invisible.
REPO_SLUG = "NDDev-it-com/ci-workflows"
REPO_RUN_RE = re.compile(
    r"^https://github\.com/" + re.escape(REPO_SLUG) + r"/actions/runs/\d+$"
)
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def _file_digest(workflow: str) -> str | None:
    path = REPO_ROOT / workflow
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reusable_workflows() -> set[str]:
    return {
        f".github/workflows/{path.name}"
        for path in WORKFLOWS_DIR.glob("*.yml")
        if path.name not in SELF_WORKFLOWS
    }


def validate_coverage(data: object, reusables: set[str], as_of: dt.date,
                      digest_for=_file_digest) -> list[str]:
    problems: list[str] = []
    if not isinstance(data, dict):
        return ["runtime-coverage: top-level document must be a mapping"]
    if data.get("schema") != SCHEMA:
        problems.append(f"runtime-coverage: schema must be {SCHEMA!r}")
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        return problems + ["runtime-coverage: `entries` must be a non-empty list"]

    seen: list[str] = []
    for index, entry in enumerate(entries):
        where = f"entries[{index}]"
        if not isinstance(entry, dict):
            problems.append(f"{where}: entry is not a mapping")
            continue
        workflow = entry.get("workflow")
        seen.append(str(workflow))
        where = f"coverage {workflow!r}"
        status = entry.get("status")
        if status not in VALID_STATUS:
            problems.append(f"{where}: invalid status {status!r}")
        if status == "runtime-proven":
            run = entry.get("last_run")
            if not isinstance(run, str) or not REPO_RUN_RE.match(run):
                problems.append(
                    f"{where}: runtime-proven last_run must be a "
                    f"https://github.com/{REPO_SLUG}/actions/runs/<id> URL, "
                    f"got {run!r}"
                )
            proven = entry.get("proven_digest")
            if not isinstance(proven, str) or not DIGEST_RE.match(proven):
                problems.append(
                    f"{where}: runtime-proven requires proven_digest — the "
                    "sha256 of the workflow file at the proving run"
                )
            else:
                actual = digest_for(str(workflow))
                if actual is None:
                    problems.append(
                        f"{where}: cannot read workflow to verify proven_digest"
                    )
                elif actual != proven:
                    problems.append(
                        f"{where}: workflow changed since it was proven "
                        f"(proven_digest {proven[:12]}… != current "
                        f"{actual[:12]}…) — re-run the reusable and update "
                        "proven_digest, or downgrade to static-only"
                    )
        if status == "static-only":
            validator = entry.get("validator")
            if not validator or not (REPO_ROOT / str(validator)).is_file():
                problems.append(
                    f"{where}: static-only must name an existing validator script"
                )
        if status == "waived":
            waiver = entry.get("waiver")
            if not isinstance(waiver, dict) or not all(
                waiver.get(field) for field in ("owner", "reason", "expires_after")
            ):
                problems.append(
                    f"{where}: waived requires waiver.owner/reason/expires_after"
                )
            else:
                try:
                    expiry = dt.date.fromisoformat(str(waiver["expires_after"]))
                except ValueError:
                    problems.append(f"{where}: waiver.expires_after is not a date")
                else:
                    if expiry < as_of:
                        problems.append(
                            f"{where}: waiver EXPIRED on {expiry}; re-test the "
                            "workflow or renew the waiver"
                        )

    if len(seen) != len(set(seen)):
        dupes = sorted({w for w in seen if seen.count(w) > 1})
        problems.append(f"runtime-coverage: duplicate workflow records {dupes}")

    missing = reusables - set(seen)
    extra = set(seen) - reusables
    if missing:
        problems.append(
            f"runtime-coverage: reusable workflows without a coverage record: "
            f"{sorted(missing)}"
        )
    if extra:
        problems.append(
            f"runtime-coverage: coverage records for unknown/removed workflows: "
            f"{sorted(extra)}"
        )
    return problems


def _fixture_tests() -> list[str]:
    problems: list[str] = []
    reusables = {".github/workflows/a.yml", ".github/workflows/b.yml"}
    as_of = dt.date(2026, 7, 12)
    good_url = f"https://github.com/{REPO_SLUG}/actions/runs/29167958787"
    digest_a, digest_b = "a" * 64, "b" * 64
    stub = {".github/workflows/a.yml": digest_a,
            ".github/workflows/b.yml": digest_b}.get

    def cov(*entries: dict) -> dict:
        return {"schema": SCHEMA, "entries": list(entries)}

    def run(cov_doc: dict) -> list[str]:
        return validate_coverage(cov_doc, reusables, as_of, digest_for=stub)

    proven = {"workflow": ".github/workflows/a.yml", "status": "runtime-proven",
              "last_run": good_url, "proven_digest": digest_a, "waiver": None}
    unverified_b = {"workflow": ".github/workflows/b.yml", "status": "unverified",
                    "last_run": None, "waiver": None}

    if run(cov(proven, unverified_b)):
        problems.append("runtime-coverage fixture valid should pass")
    if not run(cov(proven)):
        problems.append("runtime-coverage fixture missing-workflow should fail")
    if not run(cov({**proven, "last_run": None}, unverified_b)):
        problems.append("runtime-coverage fixture proven-without-run should fail")
    foreign = {**proven, "last_run": "https://github.com/other/repo/actions/runs/1"}
    if not run(cov(foreign, unverified_b)):
        problems.append("runtime-coverage fixture foreign-run-url should fail")
    docs_url = {**proven, "last_run": "https://docs.github.com/actions"}
    if not run(cov(docs_url, unverified_b)):
        problems.append("runtime-coverage fixture non-run-url should fail")
    no_digest = {k: v for k, v in proven.items() if k != "proven_digest"}
    if not run(cov(no_digest, unverified_b)):
        problems.append("runtime-coverage fixture proven-without-digest should fail")
    if not run(cov({**proven, "proven_digest": "c" * 64}, unverified_b)):
        problems.append("runtime-coverage fixture stale-digest should fail")
    expired_waiver = {"workflow": ".github/workflows/b.yml", "status": "waived",
                      "waiver": {"owner": "x", "reason": "y",
                                 "expires_after": "2026-01-01"}}
    if not run(cov(proven, expired_waiver)):
        problems.append("runtime-coverage fixture expired-waiver should fail")
    extra = {"workflow": ".github/workflows/ghost.yml", "status": "unverified"}
    if not run(cov(proven, unverified_b, extra)):
        problems.append("runtime-coverage fixture orphan-record should fail")
    return problems


def check() -> list[str]:
    if not COVERAGE.is_file():
        return [f"missing runtime-coverage ledger: {COVERAGE.relative_to(REPO_ROOT)}"]
    try:
        data = yaml.safe_load(COVERAGE.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [f"runtime-coverage: invalid YAML: {exc}"]
    problems = validate_coverage(data, _reusable_workflows(), dt.date.today())
    problems += _fixture_tests()
    return problems


def _counts(data: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in data.get("entries", []):
        if isinstance(entry, dict):
            status = str(entry.get("status"))
            counts[status] = counts.get(status, 0) + 1
    return counts


def main() -> int:
    problems = check()
    if problems:
        print("validate_runtime_coverage: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    data = yaml.safe_load(COVERAGE.read_text(encoding="utf-8"))
    print(f"validate_runtime_coverage: OK {_counts(data)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
