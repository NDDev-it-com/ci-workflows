# ADR 0003: Absence of evidence is a failure for blocking workflows

Status: Accepted

Date: 2026-08-10

## Context

`catalog/runtime-coverage.yml` is an honest ledger: a workflow is
`runtime-proven` only with a real observed `workflow_call` run and a
`proven_digest` matching the current bytes, `static-only` only when it names an
executable validator, and `unverified` otherwise.

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
- For `release` and `security-blocking`, `unverified` is **rejected**. Those
  must be proven, `static-only` behind a validator that exists, or `waived` with
  a named owner and an unexpired date.
- `supporting` may rest at `unverified` indefinitely. That is the honest state
  for a benchmark helper, and the reason the tier exists.
- The blocking families are pinned in `PINNED_CRITICALITY`, so relabelling a
  record `supporting` to escape the obligation is itself a gate failure rather
  than something only review can catch.
- Waiver expiries are staggered, one per date.

## Consequences

- Thirteen workflows entered the obligation. Two moved to `static-only` behind
  `check_release_supply_chain.py`, which executes real fixtures; nine took dated
  waivers spread from 2026-09-15 to 2027-01-15.
- Those waivers expire, and when they do the gate goes red. That is the point:
  a waiver is a dated debt, unlike `unverified`, which never comes due.
- The obligation does not prove anything by itself. It converts silence into a
  decision — prove it, stand in for it, or own the exception with a date. The
  fixture estate that would supply real proof is still absent.
- Adding a reusable workflow to a blocking family now means editing
  `PINNED_CRITICALITY` too.
