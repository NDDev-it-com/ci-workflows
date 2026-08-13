# ADR 0006: Compile evidence lanes; do not infer them from elapsed time

Status: Accepted

Date: 2026-08-13

## Context

Runtime coverage says what was observed, and runner routing says where a job may
run. Neither selects the evidence programme a concrete repository change owes.
The fixture workflows therefore encode policy by hand and cannot express native
host checks such as reboot, GUI/session, SSH/network, or system hardening.

## Decision

- `catalog/evidence-orchestration.yml` is the canonical lane inventory.
- `compile_evidence_plan.py` resolves level, platform, OS, architecture,
  profile, risk, change, release, and host capability before execution.
- Levels are cumulative: `fast`, `pr-required`, `full`, `release`.
- Unknown dimensions, missing native-host capabilities, and all-skipped plans
  fail closed.
- Workflow lanes reuse existing reusables. Native disposable-host lanes emit an
  explicit downstream handoff; they are not simulated on hosted runners.
- Timing is observe-only. Duration may be recorded, but never causes selection,
  skipping, cancellation, or failure.
- Retention is semantic: `operational` and `durable`. OpenObserve is intended to
  map them to 7 and 30 days. GitHub artifact retention remains independently
  governed and is not changed by this contract.

## Consequences

The compiler and generated ledger are static policy evidence, not proof that a
lane ran. Only `runtime-coverage.yml` and downstream run records can make that
claim. Existing fixture workflows remain evidence producers and are not made a
required pull-request check.
