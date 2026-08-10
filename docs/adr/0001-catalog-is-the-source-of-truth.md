# ADR 0001: The catalog is the source of truth, docs are a projection

Status: Accepted

Date: 2026-08-10

## Context

This library publishes reusable workflows that other repositories pin by commit
SHA, plus prose describing which of them to use at which tier. For most of its
life the prose *was* the model: `docs/00`–`docs/18` explained tiers, costs and
prerequisites, and `catalog/capabilities.yml` carried three availability columns
alongside.

Prose cannot be validated. It drifted, repeatedly and silently, and the drift
was only found by reading external sources by hand: the tier documentation named
a cost control that cannot stop usage, claimed a product had no REST API when it
has four endpoints, stated a public price GitHub's own sources disagree about,
and reported code-scanning coverage figures that had moved.

None of those were careless. Each was true when written. The defect is
structural: a claim with no validator has no expiry, and nothing makes its
author revisit it.

This ADR is written retroactively. The catalog-first arrangement predates it;
what is new is stating it as a decision so later work does not quietly reverse
it.

## Decision

- `catalog/*.yml` is the only authority. `capabilities.yml`, `tools.yml`,
  `product-facts.yml`, `runtime-coverage.yml` and `profiles.yml` each own one
  concern and are validated by a named script in `validate_all.py`.
- `docs/generated/*` is rendered from the catalog and a drift check rejects
  hand edits.
- Hand-written docs may **reference** a catalog entry; they may not **restate**
  one. Where prose and a generated artifact disagree, the generated artifact is
  correct — it is validated and the prose is not, and `docs/00` says so in those
  words.
- Every volatile external fact carries `verified_at` / `expires_after` and fails
  the gate when it expires, so a stale claim becomes a build failure rather than
  a quiet lie.

## Consequences

- Correcting a fact means editing the catalog and regenerating; a doc-only fix
  will be reverted by the next generation.
- Expiries must be staggered. Seeding the ledger in one sitting gave 38 of 41
  facts the same `expires_after`, which would have failed the gate in a single
  block. Refresh cost has to be amortised, not synchronised.
- The gate now fails for reasons unrelated to the change in hand — an expired
  fact blocks an unrelated PR. That is the intended trade: the alternative is a
  claim nobody revisits.
