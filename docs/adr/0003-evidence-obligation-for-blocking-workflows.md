# ADR 0003: Absence of evidence is a failure for blocking workflows

Status: Accepted

Date: 2026-08-10

## Context

`catalog/runtime-coverage.yml` is an honest ledger: a workflow is
`runtime-proven` only with a real observed `workflow_call` run and a
`proven_digest` matching the current bytes, `partial-runtime` only when the live
run proves an explicit subset of jobs and the remainder stays typed debt,
`static-only` only when it names an executable validator, and `unverified`
otherwise.

Its honesty was the problem. The validator checked whether a *claimed* status was
self-consistent and never whether anyone had claimed anything, so `unverified`
was the default and unlimited. The ledger read 2 proven, 2 static-only and **42
unverified of 46 reusable workflows**, and `ci-gate` was green throughout. A
green check that answers "is what you claimed coherent?" renders identically to
one that answers "did this work?", and readers assume the second.

This is not theoretical. The library shipped a semantic defect static validation
could not catch — a called workflow cannot read the caller's `needs` context —
which is why that contract now takes a serialised `needs_json`.

## Decision

- Every record declares `criticality`: `release`, `security-blocking`,
  `required-gate` or `supporting`.
- For `release`, `security-blocking`, and `required-gate`, `unverified` is **rejected**. Those
  must be proven, `static-only` behind a validator that exists, or `waived` with
  a named owner and an unexpired date.
- Every non-proven row carries typed runtime debt: risk, barrier, required
  capability, and a repository issue handoff. Supporting status does not erase
  that debt or reduce the eventual evidence obligation.
- `partial-runtime` names each live-proven job. A skipped, failed, cancelled or
  missing job is not evidence, and a side-effecting caller is eligible only when
  its named observation/cleanup guards also succeed.
- The blocking families are pinned in `PINNED_CRITICALITY`, so relabelling a
  record `supporting` to escape the obligation is itself a gate failure rather
  than something only review can catch.
- A waiver is valid only for an objective external secret, licence, or real-host
  barrier, and also carries owner, reason, required capability, handoff and an
  expiry. Event setup, a large SDK, or fixture engineering are tracked as debt,
  not waived as impossibilities.

## Consequences

- The post-merge closure batch raised runtime proof to 35 of 46 and removed all
  legacy waivers. The remaining rows are visible in the generated closure
  ledger with typed risk and child-issue ownership.
- The obligation does not prove anything by itself. Only a successful,
  non-skipped top-level reusable caller job for the current digest is eligible.
  Failed, cancelled, skipped and missing callers or required guards fail the
  summary and emit repair context; a diagnostic retry cannot overwrite the
  first failure.
- Adding a reusable workflow to a blocking family now means editing
  `PINNED_CRITICALITY` too.
