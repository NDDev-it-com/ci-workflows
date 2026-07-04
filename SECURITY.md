# Security Policy

## Reporting a vulnerability

Report suspected vulnerabilities privately via GitHub Security Advisories:
https://github.com/NDDev-it-com/nddev-ci-workflows/security/advisories/new

Do not open public issues for security reports. You will receive an initial
response as soon as reasonably possible.

## Consuming these workflows securely

- **Always pin by full commit SHA**, never by tag or branch:
  `uses: NDDev-it-com/nddev-ci-workflows/.github/workflows/<name>.yml@<40-char-sha>`.
  Tags are mutable; a full SHA is immutable. Dependabot can bump the pinned SHA.
- Grant the calling job only the permissions the reusable declares it needs.
- Treat the private free tier (`enable_harden_runner: false`,
  `upload_sarif: false`) as the correct choice for private repositories, where
  code scanning, native secret scanning, and harden-runner are paid features.

## Posture of this repository

- Every third-party action is pinned to a full commit SHA with a version comment.
- Every workflow declares least-privilege `permissions`, `concurrency`, and a
  `timeout-minutes`.
- `ci.yml` runs static validators (`scripts/validate_all.py`), `actionlint`, and
  `zizmor` (regular persona, SARIF) against this repository's own workflows on
  every push and pull request; `ci-gate` aggregates them.
- `main` is protected by a repository ruleset (`.github/rulesets/branch-main.json`):
  signed commits, required review + code-owner review, linear history, no
  force-push or deletion, and the `ci-gate` status check. Release tags are
  protected by `.github/rulesets/tag-semver.json`.
- Releases are tag-driven and immutable, and ship an SPDX SBOM, SHA256SUMS, a
  build-provenance attestation, and an SBOM attestation (SLSA v1.0 Build L3,
  built inside the reusable `release-supply-chain.yml`). Verify with
  `scripts/verify_attestations.sh`.
