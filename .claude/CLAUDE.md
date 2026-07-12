# nddev-ci-workflows — Claude Code project memory

Reusable GitHub Actions workflow library + machine-readable capability
catalog. The product is `.github/workflows/*.yml` (`ci.yml` and `release.yml`
are self workflows; everything else is `on: workflow_call` consumed by
callers pinned to full commit SHAs). `docs/` mirrors the catalog; never treat
prose docs as the source of truth.

## Golden path for any change

1. Edit workflows/scripts.
2. Update `catalog/capabilities.yml` (and `catalog/tools.yml` `used_by` /
   pins) — the catalog is the source of truth. Volatile plan/price/quota facts
   live only in `catalog/product-facts.yml` (dated + expiring); runtime
   evidence lives only in `catalog/runtime-coverage.yml`.
3. `python3 scripts/generate_docs.py` — `docs/generated/*` (capability matrix,
   workflow inventory, free-tier matrix) is generated output; hand-edits fail
   the CI drift check.
4. Sync `README.md`, tier docs (`docs/00`–`docs/15`), and the matching
   caller example under `examples/`.
5. If you touched a skill, `python3 scripts/sync_skills.py` to regenerate the
   `.claude/skills` mirror from `.agents/skills`.
6. Add a `CHANGELOG.md` entry under `[Unreleased]`.
7. Validate (below), then PR — `main` is squash-merge-only behind the
   `ci-gate` check.

## CI skills

`.agents/skills/` is the authored source; `.claude/skills/` is a generated
byte-identical mirror (never hand-edit — run `scripts/sync_skills.py`;
`check_skills` in validate_all enforces parity, the fixed `EXPECTED_SKILLS`
set, and a guard against hard-coded quota figures). Two groups: **eight
portable CI/GitHub-Actions doctrine skills** (`ci-*`, `github-actions-*`),
published as product, and **three repo-operation skills** for agents working on
this repo — `nddev-repo-orientation` (start here), `nddev-change-flow` (the
golden path), `nddev-release-flow` (releasing). Skills hold doctrine only; their
mutable data is the catalogs (`ci-free-tier-planner` →
`catalog/product-facts.yml`, `ci-runtime-contract-testing` /
`ci-inventory-audit` → `catalog/runtime-coverage.yml`).

## Commands

```bash
python3 -m pip install --require-hashes -r requirements-ci.txt  # PyYAML only
python3 scripts/validate_all.py                                 # full gate
actionlint
zizmor --persona regular --min-severity low .github/workflows
python3 scripts/generate_docs.py --check                        # drift only
```

`validate_all.py` is the same aggregate the required `ci-gate` runs. Several
checks execute real fixtures (temporary git repos, extracted embedded Python
programs), so a failure message usually names the exact broken contract.

## Contracts Claude must not break

- **Paired variants stay byte-parallel.** `release-supply-chain.yml` ↔
  `release-supply-chain-free.yml` differ only in the attest steps,
  permissions, and `slsa_build_level` (3 vs null); `benchmark.yml` ↔
  `benchmark-compare.yml` differ only in `auto-push` and permissions. Edits
  to one side must be mirrored or `check_release_supply_chain.py` /
  `check_benchmark_contract.py` fail.
- **Tier truth.** GitHub Artifact Attestations: public repos on any plan;
  private/internal require GitHub Enterprise Cloud (not GHAS). Private-free
  releases use `release-supply-chain-free.yml` (`contents: write` only).
- **Fail-closed router.** `monorepo-changed-paths.yml` accepts only strict
  JSON filters (exact paths or `/`-terminated directory prefixes); wildcard
  patterns, unresolvable bases, and malformed groups must fail the run;
  uncertain push bases go conservative all-true — never silent all-false
  (`check_monorepo_routing.py` fixtures).
- **Runner honesty.** `actionlint.yml` guards Linux X64 as step one;
  `release-supply-chain*.yml` validate Linux X64/ARM64 before checkout.
- **Runtime-coverage proof integrity.** In `catalog/runtime-coverage.yml` a
  `runtime-proven` record needs a repo-scoped `…/actions/runs/<id>` URL **and**
  a `proven_digest` (sha256 of the workflow file) that
  `validate_runtime_coverage.py` recomputes and matches. Editing any proven
  workflow (`release-supply-chain.yml`, `actionlint.yml`, `zizmor-sarif.yml`)
  therefore fails the gate — the "static-only dance": re-run the reusable and
  update the digest, or drop the record to `static-only`, until the next run
  re-proves it. Never leave a stale run masquerading as proof.
- **Runtime bundle ⊆ source archive.** `release-supply-chain*.yml` refuse a
  `runtime_paths` selection outside `archive_paths`, so the Syft-scanned source
  SBOM stays a superset of everything the release ships. `release.yml` never
  sets `runtime_paths`, so that path is covered only by
  `check_release_supply_chain.py` fixtures (not the self-release).
- **Security invariants.** Full-SHA pins with `# vX.Y.Z` comments;
  `permissions: {}` top-level + least-privilege jobs; `timeout-minutes`
  everywhere; `persist-credentials: false`; no `${{ ... }}` inside `run:`
  (env indirection only); embedded Python via `python3 -I`; Harden-Runner
  only in the public/GHAS allowlist of `check_harden_runner_contract.py`,
  unconditional, first step — never behind a boolean input.

## Git and release etiquette

- Conventional Commits (<100-char subject), `git commit -s` (DCO) and `-S`
  (SSH signing is configured in this checkout), no `Co-Authored-By`.
- PRs fill `.github/PULL_REQUEST_TEMPLATE.md` (permissions diff +
  threat-model note for workflow changes); merge is squash-only after
  `ci-gate` is green.
- Release = maintainer pushes SemVer tag; `release.yml` validates
  byte-exact `VERSION`, a single matching `CHANGELOG.md` heading, then
  publishes five immutable checksummed assets in one create call. Never
  attempt `gh release upload --clobber`.

## Local-only context

- `.serena/` (Serena MCP memories) is intentionally gitignored — local
  developer tooling, not published catalog content.
- `AUDIT/` (when present) holds external review deliverables; keep it out of
  commits.
