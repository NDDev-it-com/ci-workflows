---
name: nddev-change-flow
description: The complete golden-path checklist for any change to the nddev-ci-workflows repository — editing a workflow, catalog entry, action pin, doc, or skill — so you touch every layer the catalog-driven pipeline expects and leave the validation gate green. Invoke before you edit.
license: AGPL-3.0-or-later
compatibility: Codex and Agent Skills compatible; OpenCode discovers .agents/skills. Generate .claude/skills mirrors for Claude Code.
metadata:
  version: 1.0.0
  owner: NDDev
  status: proposed
  reviewed_at: '2026-07-12'
---

# Making a change to nddev-ci-workflows

Every change here is a supply-chain change for a downstream consumer, so the
repository is fail-closed and heavily validated. Follow the golden path so you
update every layer in step; skipping one usually shows up as a red `ci-gate`.
New to the repo? Read `nddev-repo-orientation` first.

## Golden path (do these in order)

1. **Edit** the workflow, script, or asset.
2. **Update the catalog** (`catalog/*.yml`) — it is the source of truth.
3. **Regenerate docs**: `python3 scripts/generate_docs.py`. `docs/generated/*`
   is generated output; hand edits fail the drift check.
4. **Sync the prose**: `README.md`, the tier docs `docs/00`–`docs/15`, and the
   matching caller example under `examples/`.
5. **If you touched a skill** under `.agents/skills/`, run
   `python3 scripts/sync_skills.py` to regenerate the `.claude/skills` mirror.
6. **Add a `CHANGELOG.md` entry** under `[Unreleased]`.
7. **Validate** (below), then open a PR. `main` is squash-merge-only behind the
   required `ci-gate` check.

## Editing a workflow — the security invariants

Any `.github/workflows/*.yml` edit must keep:

- `permissions: {}` at top level and least-privilege scopes per job.
- Every remote `uses:` pinned to a full 40-char commit SHA with a `# vX.Y.Z`
  comment (enforced by `check_pinned_actions.py`). If you add or bump an action,
  resolve the SHA with `gh api repos/OWNER/REPO/commits/<tag> --jq .sha`.
- `timeout-minutes` on every job; `concurrency` on new workflows.
- `persist-credentials: false` on read-only `actions/checkout` steps.
- **No** `${{ ... }}` interpolated inside `run:` — pass values through `env:` and
  reference shell variables, to keep template injection impossible.
- Embedded Python invoked with `python3 -I` (isolated mode).
- Harden-Runner only where `check_harden_runner_contract.py` allows it —
  unconditional, first step, never behind a boolean input.

### Paired variants

Two workflow pairs must stay byte-parallel except for a named difference:

- `release-supply-chain.yml` ↔ `release-supply-chain-free.yml` — differ only in
  the attest steps, permissions, and `slsa_build_level` (3 vs `null`).
- `benchmark.yml` ↔ `benchmark-compare.yml` — differ only in `auto-push` and
  permissions.

Edit one side and mirror the other, or `check_release_supply_chain.py` /
`check_benchmark_contract.py` fail. The release contract validator extracts the
embedded Python programs and runs them in hermetic temporary Git repos, so a
break points at the exact program.

## Updating the catalog

Pick the right file:

- **`capabilities.yml`** — add or change a capability record. Keep the uniform
  schema (`scripts/validate_catalog.py` checks required fields, valid
  cluster/status/tier values, existing workflow/example paths, https sources).
  Every reusable workflow needs a capability entry.
- **`tools.yml`** — add or bump an action/CLI/container. Action pins must be a
  full-SHA ref with no comment inside the pin string; keep `used_by` accurate to
  every workflow that runs the tool.
- **`product-facts.yml`** — the **only** place for a volatile plan/price/quota
  fact. Never hard-code such a number in a workflow comment, a doc, or a skill:
  `validate_product_facts.py` expires stale facts and a `check_skills.py` guard
  fails CI if a `SKILL.md` embeds a quota figure. Capabilities link facts via
  the optional `product_facts` field.
- **`runtime-coverage.yml`** — the honesty ledger (see the next section).

## The runtime-coverage "static-only dance"

`runtime-coverage.yml` records, per reusable workflow, whether it is
`runtime-proven` (a live run exercised it), `static-only` (a named validator
stands in), `unverified` (default), or `waived`.

A `runtime-proven` record carries a repo-scoped `…/actions/runs/<id>` URL **and**
a `proven_digest` = sha256 of the workflow file. `validate_runtime_coverage.py`
recomputes that digest and fails on a mismatch. Consequence:

> **Editing a `runtime-proven` workflow makes the gate red** — the recorded
> digest no longer matches the file.

Resolve it honestly, never by faking the digest:

1. In the **same** change, set that workflow's record to `status: static-only`
   with `validator:` pointing at the `scripts/check_*.py` that statically covers
   it (for the release workflows that is `scripts/check_release_supply_chain.py`).
   Drop `last_run` / `proven_digest`.
2. After a later live run exercises the new bytes (a release run, or the CI run
   that dogfoods `actionlint.yml` / `zizmor-sarif.yml`), re-promote to
   `runtime-proven`: record the run URL and the fresh
   `shasum -a 256 <workflow>` digest. `nddev-release-flow` covers the
   post-release re-promotion.

Never mark a workflow `runtime-proven` without an observed `workflow_call` run.

## Editing a skill

`.agents/skills/` is the authored source; `.claude/skills/` is a generated
byte-identical mirror. After any skill edit run `python3 scripts/sync_skills.py`.
`check_skills.py` enforces the frontmatter contract (kebab-case `name` equal to
the directory, a substantial `description`), a bounded line budget, the fixed
skill set (`EXPECTED_SKILLS` — update it when you add or remove a skill), mirror
byte-parity, and the no-hard-coded-quota guard. Skills hold durable doctrine
only; their mutable data lives in the catalog.

## Validate

```bash
python3 scripts/validate_all.py
actionlint
zizmor --persona regular --min-severity low .github/workflows
python3 scripts/generate_docs.py --check
git diff --check
```

`validate_all.py` aggregates the checks the required `ci-gate` runs, including:
`pinned-actions`, `permissions`, `workflow-contracts`, `harden-runner-contract`,
`release-supply-chain`, `monorepo-routing`, `benchmark-contract`,
`actionlint-contract`, `examples`, `docs-links`, `merge-group`, `rulesets`,
`catalog`, `product-facts`, `runtime-coverage`, `skills`, `generated-docs`.

## Common failures → fix

| Failure names… | Do |
| --- | --- |
| `generated-docs` drift | run `python3 scripts/generate_docs.py` and commit |
| `skills` mirror drift / set mismatch | run `sync_skills.py`; update `EXPECTED_SKILLS` |
| `catalog` unknown/missing path | fix `used_by` / `workflow` / `example` to a real file |
| `runtime-coverage` digest mismatch | do the static-only dance above |
| `release-supply-chain` parity | mirror the edit into the other variant |
| `product-facts` expired/conflict | refresh the dated fact; regenerate the free-tier matrix |
| `pinned-actions` | full-SHA pin + `# vX.Y.Z` comment |

## Commit, PR, merge

- Conventional Commits (< 100-char subject); sign off (`-s`, DCO) and sign
  (`-S`, SSH is configured in this checkout); no `Co-Authored-By`.
- Fill `.github/PULL_REQUEST_TEMPLATE.md` — the permissions diff and
  threat-model note are required for any workflow or permission change.
- Merge is squash-only after `ci-gate` is green.
