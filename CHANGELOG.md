# Changelog

## [Unreleased]

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
