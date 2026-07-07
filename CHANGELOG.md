# Changelog

## [Unreleased]

## [0.3.0] - 2026-07-08

### Added

- Language packs: Dart/Flutter, C/C++, Qt, Kotlin/Android, Swift, R, HTML/CSS,
  and SQL reusable workflows (joining Python, Node, Go, Rust, Java, .NET,
  container, and Terraform).
- Quality gates: `coverage-gate` (Codecov/Coveralls), `docs-quality`
  (lychee/typos/markdownlint), and `pr-hygiene`
  (commitlint/PR-title/labeler/stale).
- Free SAST/SCA/IaC for every tier including private-free: Semgrep OSS,
  OSV-Scanner, Grype, hadolint, and Checkov (all gate-only, no security-events).
- Advanced testing: `mutation-testing`, `fuzzing` (cargo-fuzz), and `benchmark`
  (github-action-benchmark regression alert).
- Level-3 opt-in caller examples: AI code review (Claude Code Action) and
  release automation (release-please).
- `docs/15-language-and-quality-packs.md` and `examples/` subdirectories
  (`languages/`, `quality/`, `security/`, `testing/`, `level3/`).

### Changed

- Catalog grows to 67 capabilities and 38 pinned tools; every new third-party
  action is SHA-pinned with a version comment and verified against its
  `action.yml` input contract.
- `terraform-ci` documents `terraform_version` pinning for reproducible CI.
- Generated docs re-dated to 2026-07-08.

## [0.2.4] - 2026-07-04

### Added

- Machine-readable catalog schema under `catalog/schema/`.
- Catalog-derived generated docs under `docs/generated/`, checked by
  `scripts/generate_docs.py --check` through `scripts/validate_all.py`.
- Example workflow validator for copy-paste caller snippets, including
  private-free least privilege and Scorecard trigger constraints.
- Markdown local-link and merge-queue compatibility validators.
- First-class July 2026 catalog entries for merge queue, step-level parallel
  execution, hosted-runner governance controls, RHEL larger-runner images,
  license-compliance preview, npm trusted publishing, and PyPI trusted
  publishing.
- npm/PyPI trusted-publishing examples and `scripts/export_repo_sbom.sh`.
- Review reconciliation document under `docs/audit/`.

### Changed

- Strengthened catalog validation for workflow/example coverage, source URLs,
  tool pin shape, duplicate IDs, and stale materialized-workflow risk text.
- Updated runners, Actions core, rulesets, releases/packages, supply-chain, and
  watchlist docs for July 2026 platform facts.
- Fixed SBOM attestation verification docs to verify the released artifact with
  the SPDX predicate type.

## [0.2.3] - 2026-07-04

### Added

- `cross-platform-smoke.yml` now supports OS-specific command overrides
  (`linux_command`, `macos_command`, `windows_command`) while preserving the
  default `command` fallback.

### Changed

- `public-scorecard-json.yml` now defaults `publish_results` to `false`.
  Reusable workflow callers keep Scorecard as a JSON artifact/check signal by
  default, avoiding OpenSSF Scorecard webapp workflow-shape verification
  failures.

## [0.2.2] - 2026-07-04

### Added

- `public-dependency-review.yml` now exposes `vulnerability_check` and
  `allow_licenses`, preserving stricter adapter-local Dependency Review
  semantics during migration to reusable workflows.

## [0.2.1] - 2026-07-04

### Added

- `public-scorecard-json.yml` for Scorecard JSON artifact mode without
  `security-events: write`, matching estate policy where Scorecard is a
  project-health signal rather than a code-scanning alert source.
- Checkout controls (`checkout_ref`, `fetch_depth`, `submodules`) and setup hooks
  for `private-static.yml` and `cross-platform-smoke.yml`, so private/root
  callers can preserve PR refs and submodule validation.
- Adapter-migration extension inputs for shared workflows: `actionlint.yml`
  `post_command`, `secret-scan.yml` report/config/post-command options, and
  `public-codeql.yml` optional CodeQL config/autobuild/artifact output.

### Changed

- Public examples now default to `public-scorecard-json.yml`; SARIF Scorecard
  remains available through `public-scorecard.yml` for repositories that
  intentionally want code-scanning upload.

## [0.2.0] - 2026-07-04

### Added

- **CI/CD encyclopedia** under `docs/` (17 pages): public-OSS / private-free /
  private-paid tiers, Actions core, runners, security scanning, supply chain
  (SLSA/SBOM/attestations), governance/rulesets, releases, deployments,
  observability, community DX, external tools, AI/agentic workflows, a 2026
  watchlist, and `pull_request_target` hardening.
- **Machine-readable catalog** under `catalog/` (`capabilities.yml`,
  `tools.yml`, `deprecations.yml`) with a uniform, validated schema.
- **Language / use-case reusable packs**: `python-ci.yml`, `node-ci.yml`,
  `go-ci.yml`, `rust-ci.yml`, `java-ci.yml`, `dotnet-ci.yml`,
  `container-ci.yml` (Trivy), `terraform-ci.yml`, `docs-ci.yml`, and
  `monorepo-changed-paths.yml`.
- **Rulesets-first governance** under `.github/rulesets/` (branch, tag, push)
  mirroring live protection, plus a migration guide.
- **Static validators** (`scripts/validate_all.py` and friends) enforcing
  full-SHA pins, least-privilege permissions/timeouts, the reusable-workflow
  contract, ruleset shape, and the catalog schema — wired into `ci.yml`.
- **Community health kit**: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`,
  `SUPPORT.md`, a PR template, and issue forms.
- **Attestation verifier** `scripts/verify_attestations.sh`, plus `examples/`
  caller workflows for each tier and a `pip` Dependabot ecosystem.

### Changed

- **Release supply chain** now generates a real SPDX SBOM (Syft via
  `anchore/sbom-action`), attests the archive with
  `actions/attest-build-provenance` and the SBOM with `actions/attest-sbom`
  (SLSA v1.0 Build L3, produced inside the reusable workflow), and publishes an
  **immutable release in a single `gh release create`** call.
- **`zizmor.yml` split** into `zizmor-sarif.yml` (public / paid, uploads SARIF)
  and `zizmor-no-sarif.yml` (private-free, `contents: read` only — least
  privilege).
- **`ci.yml`** now runs `scripts/validate_all.py` as its contract gate.
- README rewritten around the three-tier positioning; SECURITY.md corrected.

### Removed

- `gh release upload --clobber` fallback: it fails against immutable releases
  (GA 2025-10-28). The workflow now fails fast if a release already exists.
- Combined `zizmor.yml` (replaced by the SARIF / no-SARIF split).

## [0.1.0] - 2026-07-04

### Added

- Initial reusable GitHub Actions CI/CD + supply-chain workflow library for the
  NDDev estate, split into two tiers.
- Public-only reusables (free on public repos): `public-codeql.yml`,
  `public-scorecard.yml`, `public-dependency-review.yml`.
- Dual-tier reusables (free on both; `enable_harden_runner`/`upload_sarif`
  toggles for the private free tier): `secret-scan.yml` (digest-pinned
  gitleaks), `actionlint.yml` (checksum-verified), `zizmor.yml`,
  `cross-platform-smoke.yml`, `release-supply-chain.yml`.
- Private free-minimal reusable: `private-static.yml`.
- Self-CI (`ci.yml`) dogfoods `actionlint` and `zizmor` on this repository and
  enforces a reusable-workflow contract; tag-driven `release.yml` publishes an
  attested SBOM/checksum bundle via `release-supply-chain.yml`.
- All third-party actions pinned to full commit SHAs; least-privilege
  `permissions`; concurrency and timeouts on every workflow.
