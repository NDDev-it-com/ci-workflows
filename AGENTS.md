# nddev-ci-workflows — agent instructions

Reusable GitHub Actions workflow library plus a machine-readable capability
catalog. `.github/workflows/` holds two self workflows (`ci.yml`,
`release.yml`) and the reusable `on: workflow_call` product files that other
repositories pin by full commit SHA. Docs under `docs/` are human mirrors;
`examples/` are copy-paste callers validated by CI.

## Source of truth

- `catalog/capabilities.yml`, `catalog/tools.yml`, `catalog/deprecations.yml`
  are the machine-readable source of truth for capabilities and pins. Edit the
  catalog first, docs second.
- `catalog/product-facts.yml` is the single canonical source for volatile
  external plan/price/quota facts. Never hand-copy a tariff into prose; every
  live fact carries `verified_at`/`expires_after` and
  `scripts/validate_product_facts.py` fails CI once a fact expires. Capabilities
  link their tier claims to facts via the optional `product_facts` field. A
  companion `scripts/check_skills.py` guard fails CI if any `SKILL.md` hard-codes
  a quota figure (comma-grouped allowance, `<n> minutes`, or a storage size).
- `catalog/runtime-coverage.yml` is the honest runtime-evidence ledger for every
  reusable workflow (`runtime-proven` needs a repo-scoped `…/actions/runs/<id>`
  URL **and** a `proven_digest` = sha256 of the workflow file, which
  `validate_runtime_coverage.py` recomputes and matches; `static-only` names its
  validator; `unverified` is the default; `waived` needs owner/reason/expiry).
  Editing any proven workflow fails the gate on the digest mismatch — re-run and
  re-record, or drop to `static-only`, until a fresh run re-proves it. Never
  upgrade to `runtime-proven` without an observed `workflow_call` run.
- `docs/generated/*` is generated — never edit by hand. After a catalog,
  product-fact, or workflow change run `python3 scripts/generate_docs.py`; CI
  fails on drift.
- Tier claims (public / private-free / private-paid) must match the real
  GitHub billing contract. Known plan gate: GitHub Artifact Attestations are
  public-only on Free/Pro/Team plans; private/internal repositories require
  GitHub Enterprise Cloud (GHAS/Code Security does not unlock them). GitHub
  Code Quality becomes a paid product on 2026-07-20 — refresh that fact then.

## CI skills

`.agents/skills/` holds the project's authored skills (Codex and OpenCode
discover them); `.claude/skills/` is a generated, byte-identical mirror — never
edit it, run `python3 scripts/sync_skills.py` and let `scripts/check_skills.py`
(in validate_all) enforce parity, the fixed skill set, and the
no-hard-coded-quota guard. Two groups: eight portable CI/GitHub-Actions doctrine
skills (`ci-*`, `github-actions-*`), and three repo-operation skills for working
on this repo — `nddev-repo-orientation` (start here), `nddev-change-flow` (the
golden path), `nddev-release-flow` (releasing). Reach for
`ci-free-tier-planner` when choosing tiers (its data is
`catalog/product-facts.yml`), `ci-runtime-contract-testing` /
`ci-inventory-audit` when reasoning about coverage (data:
`catalog/runtime-coverage.yml`), `github-actions-authoring` /
`github-actions-security` when writing or reviewing workflow YAML, and
`ci-release-provenance` for the release chain. Skills carry doctrine only —
mutable facts stay in the catalogs above.

## Validation — run before every PR

```bash
python3 -m pip install --require-hashes -r requirements-ci.txt  # PyYAML
python3 scripts/validate_all.py
actionlint
zizmor --persona regular --min-severity low .github/workflows
```

`validate_all.py` aggregates every contract check and mirrors the required
`ci-gate` status. It executes behavior locks, not just lint: hermetic Git-DAG
fixtures for the monorepo router, byte-parity checks between paired workflow
variants, and runner-guard programs run against OS/architecture matrices.

## Paired-variant invariants (edit both sides or validators fail)

- `release-supply-chain.yml` (attested; public or private-GHEC) and
  `release-supply-chain-free.yml` (private-free) stay byte-identical
  step-for-step except the two attest steps, the permission set
  (`contents+id-token+attestations` vs `contents` only), and
  `slsa_build_level` (3 vs null) — `scripts/check_release_supply_chain.py`.
- `benchmark.yml` (publish lane: `contents: write`, `auto-push: true`) and
  `benchmark-compare.yml` (read-only lane: `contents: read`,
  `auto-push: false`) may differ only in that single `with:` key —
  `scripts/check_benchmark_contract.py`.
- `actionlint.yml` keeps its first-step Linux X64 runner guard —
  `scripts/check_actionlint_contract.py`.
- `monorepo-changed-paths.yml` is fail-closed: strict JSON filters (exact
  file paths or `/`-terminated directory prefixes; wildcards are an error),
  mandatory base resolution, conservative all-true on uncertain push bases —
  `scripts/check_monorepo_routing.py`.

## Hard rules for workflow changes (CI-enforced)

- Every third-party `uses:` pins a full 40-char commit SHA with a
  ` # vX.Y.Z` comment. No tags or branches.
- `permissions: {}` at top level; minimal per-job scopes; `timeout-minutes`
  on every job; `persist-credentials: false` on read-only checkouts.
- Never interpolate `${{ inputs.* }}` or `${{ github.event.* }}` inside
  `run:` — pass values through `env:`. Embedded Python must run as
  `python3 -I`.
- Tier separation is structural (separate workflow files), never a boolean
  toggle around a privileged action. `step-security/harden-runner` may
  appear only in the explicit public/GHAS allowlist inside
  `scripts/check_harden_runner_contract.py`, unconditional and first in the
  job.
- A new or changed workflow requires, in the same PR: catalog entry, tool
  `used_by` updates, regenerated docs, an example under `examples/`, and a
  `CHANGELOG.md` entry under `[Unreleased]`.

## Commits, PRs, releases

- Conventional Commits, subject under 100 chars; DCO sign-off (`-s`);
  cryptographic signature (`-S` — this checkout is configured for SSH
  signing); no `Co-Authored-By` trailers.
- `main` is PR-only: squash merges, required `ci-gate` status check, signed
  commits, linear history. Fill `.github/PULL_REQUEST_TEMPLATE.md`
  completely (threat-model note and permissions diff for workflow changes).
- Releases are tag-driven and immutable: `VERSION` must equal the tag as one
  LF-terminated line, `CHANGELOG.md` must contain exactly one matching
  `## [X.Y.Z]` heading, and `release.yml` publishes exactly five checksummed
  assets in a single `gh release create`. The maintainer cuts tags;
  never republish or clobber an existing release.
