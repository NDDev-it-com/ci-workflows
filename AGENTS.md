# nddev-ci-workflows — agent instructions

Reusable GitHub Actions workflow library plus a machine-readable capability
catalog. `.github/workflows/` holds two self workflows (`ci.yml`,
`release.yml`) and the reusable `on: workflow_call` product files that other
repositories pin by full commit SHA. Docs under `docs/` are human mirrors;
`examples/` are copy-paste callers validated by CI.

## Source of truth

- `catalog/capabilities.yml`, `catalog/tools.yml`, `catalog/deprecations.yml`
  are the machine-readable source of truth. Edit the catalog first, docs
  second.
- `docs/generated/*` is generated — never edit by hand. After a catalog or
  workflow change run `python3 scripts/generate_docs.py`; CI fails on drift.
- Tier claims (public / private-free / private-paid) must match the real
  GitHub billing contract. Known plan gate: GitHub Artifact Attestations are
  public-only on Free/Pro/Team plans; private/internal repositories require
  GitHub Enterprise Cloud (GHAS/Code Security does not unlock them).

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
