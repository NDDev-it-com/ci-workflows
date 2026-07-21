---
name: nddev-repo-orientation
description: Orient an agent on the ci-workflows repository in a single read — its catalog-as-source-of-truth architecture, the non-negotiable contracts, the validation gate, and which skill or file to reach for each task. Invoke first when you start work in this repository.
license: AGPL-3.0-or-later
compatibility: Codex and Agent Skills compatible; OpenCode discovers .agents/skills. Generate .claude/skills mirrors for Claude Code.
metadata:
  version: 1.0.0
  owner: NDDev
  status: proposed
  reviewed_at: '2026-07-12'
---

# ci-workflows — repository orientation

Read this first when you start work in `ci-workflows`. It gives you the
mental model, the rules you cannot break, and a router to the right skill or
file for whatever you were asked to do. It is a map, not a source of truth —
whenever a specific fact matters, follow the pointer to the authoritative file
rather than trusting a number quoted here.

## What this repository is

A library of **reusable GitHub Actions workflows** plus a **machine-readable
capability catalog**. The product is `.github/workflows/*.yml`:

- `ci.yml` and `release.yml` are *self* workflows — they run this repository's
  own CI and release.
- Every other workflow is `on: workflow_call` — consumed by other repositories
  that pin it to a full commit SHA.

Consumers pin these workflows as dependencies, so every change is a supply-chain
change for someone else. That is why the discipline below is strict and
fail-closed.

## The one rule: the catalog is the source of truth

`catalog/*.yml` is authoritative. `docs/` mirrors it and is partly generated —
**never treat prose docs as truth, and never hand-edit `docs/generated/*`** (a
CI drift check rejects hand edits). The catalog files:

- `capabilities.yml` — every capability: tier availability, its workflow,
  required permissions/settings, risks, sources, and optional `product_facts`
  links.
- `tools.yml` — every external action / CLI / container: its pin (full SHA for
  actions), `used_by` list, and version.
- `product-facts.yml` — the **only** home for volatile plan/price/quota facts;
  each fact is dated (`verified_at` / `expires_after`) and expires closed.
- `runtime-coverage.yml` — the honesty ledger: whether each reusable workflow is
  proven by a live run, stood in for by a validator, or not yet verified.
- `deprecations.yml` — deprecation records.
- `schema/capability.schema.yaml` — the machine-readable capability schema.

## Mental model

```
      authored                    enforced by                  generated
  catalog/*.yml  ───────────►  scripts/validate_*.py  ───────►  docs/generated/*
      │                        + scripts/check_*.py                   │
      │                        (aggregated by validate_all = ci-gate) │
      ▼                                                               ▼
  .github/workflows/*.yml                                     README + docs/00–15
  .agents/skills/*  ──sync_skills.py──►  .claude/skills/*  (byte-identical mirror)
```

Change flows one way: edit the workflow or script, update the catalog (the
source of truth), regenerate docs, sync the prose and examples, add a changelog
entry, run the gate, open a PR. The full checklist is the **`nddev-change-flow`**
skill.

## Where things live

| You want… | Look in |
| --- | --- |
| The workflows (the product) | `.github/workflows/*.yml` |
| The source of truth | `catalog/*.yml` |
| What a validator enforces | `scripts/validate_*.py`, `scripts/check_*.py` |
| Caller examples | `examples/**` |
| Human docs (mirror of the catalog) | `README.md`, `docs/00`–`docs/15` |
| Generated docs (never hand-edit) | `docs/generated/*` |
| Portable domain doctrine | `.agents/skills/ci-*`, `.agents/skills/github-actions-*` |
| How to operate this repo | `.agents/skills/nddev-*` (these skills) |
| Agent instructions | `.claude/CLAUDE.md` (Claude), `AGENTS.md` (Codex) |

## Contracts you must not break

The authoritative list is the "Contracts Claude must not break" section of
`.claude/CLAUDE.md`. The headlines:

- **Paired variants stay byte-parallel.** `release-supply-chain.yml` ↔
  `release-supply-chain-free.yml`; `benchmark.yml` ↔ `benchmark-compare.yml`.
  Edit one side, mirror the other, or `check_release_supply_chain.py` /
  `check_benchmark_contract.py` fail.
- **Fail-closed everywhere.** `monorepo-changed-paths.yml` rejects wildcard
  filters and unresolvable bases; an uncertain push base goes conservative
  all-true, never silent all-false.
- **Tier truth.** GitHub Artifact Attestations need GitHub Enterprise Cloud on
  private/internal repos; private-free releases use the attestation-free
  variant (`contents: write` only).
- **Runtime-coverage proof integrity.** A `runtime-proven` record needs a
  repo-scoped Actions run URL **plus** a `proven_digest` (sha256 of the
  workflow file). Editing a proven workflow fails the gate until you re-prove
  or downgrade — the "static-only dance" (see `nddev-change-flow`).
- **Runtime bundle subset.** `release-supply-chain*.yml` refuse `runtime_paths`
  outside `archive_paths`, so the source SBOM covers everything shipped.
- **Security invariants.** Full-SHA action pins with `# vX.Y.Z` comments;
  `permissions: {}` top-level + least-privilege jobs; `timeout-minutes`
  everywhere; `persist-credentials: false`; no `${{ ... }}` inside `run:` (env
  indirection only); embedded Python via `python3 -I`.

## The gate

One sequence reproduces what the required `ci-gate` check runs:

```bash
python3 -m pip install --require-hashes -r requirements-ci.txt   # PyYAML only
python3 scripts/validate_all.py        # the full validator aggregate
actionlint
zizmor --persona regular --min-severity low .github/workflows
python3 scripts/generate_docs.py --check
```

Many validators execute real fixtures (temporary Git repos, extracted embedded
Python programs), so a failure message usually names the exact broken contract.

## Task router

- **Change or add a workflow / catalog entry / doc / action pin** → skill
  `nddev-change-flow`.
- **Cut or verify a release** → skill `nddev-release-flow`.
- **Understand a CI topic** (authoring, security, cost, free-tier, provenance,
  failure triage, runtime testing, inventory) → the domain skills `ci-*` /
  `github-actions-*`.
- **Just diagnose a red gate** → run `validate_all.py`; the failing check names
  the contract; open the matching `scripts/check_*.py` and read its fixtures.

## First moves for a fresh session

1. Read `.claude/CLAUDE.md` (or `AGENTS.md`) end to end.
2. Skim `catalog/capabilities.yml` to see the capability surface.
3. Run the gate to confirm a green baseline before you touch anything.
4. Only then edit — and follow `nddev-change-flow` so you touch every layer the
   catalog-driven pipeline expects.
