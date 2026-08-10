# ADR 0002: Operating modes are compiled, not described

Status: Accepted

Date: 2026-08-10

## Context

The library described tiers as a line from free to paid: public OSS,
private-free, private-paid. Capabilities carried three matching columns.

That model cannot express the estate it serves. Visibility, base plan and the
three paid add-ons (Code Security, Secret Protection, Code Quality) vary
independently, and most repositories sit in a combination the three tiers cannot
name — a private repository holding only Code Quality is neither "private-free"
nor "private-paid". Two further modes existed in prose only: the fixed-cost
NDDev tier and the personal-account tier.

So a mode could be stated only in a document, and a document is exactly what
nothing validates. The $80 envelope drifted in three separate ways before this
was noticed.

## Decision

- `catalog/profiles.yml` declares the axes as **independent**: visibility, base
  plan, three entitlement booleans, and seven operational controls
  (`codeql_mode`, `code_quality_ai`, `coverage_mode`, `runner_mode`,
  `governance_mode`, `enforcement`, `release_provenance`).
- All eight Code Security / Secret Protection / Code Quality combinations are
  enumerated, each with its posture and free fallbacks, so no repository is
  unplaceable.
- Named profiles compose those axes. Four exist: `public-free-standalone`,
  `private-free-max`, `public-enterprise-max`,
  `enterprise-full-private-fixed80`.
- `scripts/validate_profiles.py` enforces coherence, and its rules encode
  failures that actually happened rather than generic schema checks: itemised
  fixed cost lines must sum to the declared total; a fixed-cost profile may not
  permit AI credits or Actions overage; attestations on private repositories and
  Code Quality are **plan** gates, not visibility gates; a public profile may not
  use persistent self-hosted runners.
- `scripts/resolve_profile.py` turns a repository's shape into its profile and
  the exact capability set, split into run / conditional / unavailable with the
  free substitute for everything the mode does not entitle. A mode that cannot
  be resolved is a description, not a selection.
- The three tiers in `docs/00` are demoted to a reading aid.

## Consequences

- Adding a mode means adding a profile, not writing a document.
- Resolution must gate per entitlement, not per tier column. `private_paid`
  marks the whole Advanced Security tier `available`, so reading it whenever any
  add-on is held told a Secret-Protection-only repository it could run CodeQL.
  Code Security and Secret Protection do not imply each other, and Code Quality
  implies neither.
- A `free` value is never gated: CodeQL and secret scanning stay available on
  public repositories whatever add-ons are held. The first attempt at the gate
  above removed them, which is why an invariant now asserts it.
- The model is not yet consumed by the estate reconciler. It is published for
  GDS to pin by version and digest; that bundle does not exist yet.
