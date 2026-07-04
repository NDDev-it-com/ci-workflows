# nddev-ci-workflows

A **July-2026 GitHub-native CI/CD, security, governance, and supply-chain
automation knowledge base plus reusable workflow library** for the NDDev estate.

It separates three billing realities — **public OSS**, **private-free**, and
**private-paid/GHAS** — ships SHA-pinned reusable workflows for each, and
documents every capability with its status, cost model, risk, and implementation
path in [`docs/`](docs/00-overview.md) and the machine-readable
[`catalog/`](catalog/README.md).

## Three tiers, by repository billing reality

| Tier | What you get | Notes |
| --- | --- | --- |
| **Public OSS** | The full free security suite: CodeQL, OSSF Scorecard, dependency review, native secret scanning, gitleaks, actionlint, zizmor (SARIF), harden-runner, SBOM + attestations. | Standard hosted runners and code scanning are free on public repos. |
| **Private-free** | Zero-cost only: actionlint, zizmor (no SARIF), gitleaks, private static validation, cross-platform smoke, SBOM + attestations, OIDC. | CodeQL, native secret scanning, dependency review, and harden-runner are **paid** on private repos and are excluded here. |
| **Private-paid / GHAS** | Everything in public, on private repos, via GitHub Code Security / Secret Protection. | Requires a paid plan. |

See [`docs/01-public-oss-free.md`](docs/01-public-oss-free.md),
[`docs/02-private-free.md`](docs/02-private-free.md), and
[`docs/03-private-paid-ghas.md`](docs/03-private-paid-ghas.md).

## Capability → workflow map

| Capability | Workflow | Public | Private-free | Private-paid |
| --- | --- | :---: | :---: | :---: |
| CodeQL code scanning | `public-codeql.yml` | ✅ | ❌ paid | ✅ |
| OSSF Scorecard | `public-scorecard.yml` | ✅ | ❌ | ✅ |
| Dependency Review | `public-dependency-review.yml` | ✅ | ❌ paid | ✅ |
| Gitleaks secret scan | `secret-scan.yml` | ✅ | ✅ | ✅ |
| actionlint | `actionlint.yml` | ✅ | ✅ | ✅ |
| zizmor (SARIF) | `zizmor-sarif.yml` | ✅ | ❌ (needs code scanning) | ✅ |
| zizmor (no SARIF) | `zizmor-no-sarif.yml` | ✅ | ✅ | ✅ |
| Cross-platform smoke | `cross-platform-smoke.yml` | ✅ | ✅ | ✅ |
| Release supply chain (SBOM + attest) | `release-supply-chain.yml` | ✅ | ✅ | ✅ |
| Lightweight static validation | `private-static.yml` | ✅ | ✅ | ✅ |
| Language CI packs | `python-ci.yml`, `node-ci.yml`, `go-ci.yml`, `rust-ci.yml`, `java-ci.yml`, `dotnet-ci.yml` | ✅ | ✅ | ✅ |
| Container image scan (Trivy) | `container-ci.yml` | ✅ | ✅ | ✅ |
| Terraform CI | `terraform-ci.yml` | ✅ | ✅ | ✅ |
| Docs CI | `docs-ci.yml` | ✅ | ✅ | ✅ |
| Monorepo changed-paths router | `monorepo-changed-paths.yml` | ✅ | ✅ | ✅ |

The machine-readable source of truth is [`catalog/capabilities.yml`](catalog/capabilities.yml).

## Usage

Always pin by **full commit SHA** (tags are mutable). Dependabot bumps the SHA.
A caller job **must grant every permission the reusable job declares**, or the
run fails at startup — see [`docs/04-actions-core.md`](docs/04-actions-core.md).

### Public repository

Security suite (push + PR):

```yaml
# .github/workflows/security.yml
name: security
on:
  push: { branches: [main] }
  pull_request: { branches: [main] }
permissions: {}
jobs:
  codeql:
    permissions: { actions: read, contents: read, security-events: write }
    uses: NDDev-it-com/nddev-ci-workflows/.github/workflows/public-codeql.yml@<sha>
    with:
      languages: '["python","actions"]'
  secret-scan:
    permissions: { contents: read }
    uses: NDDev-it-com/nddev-ci-workflows/.github/workflows/secret-scan.yml@<sha>
  actionlint:
    permissions: { contents: read }
    uses: NDDev-it-com/nddev-ci-workflows/.github/workflows/actionlint.yml@<sha>
  zizmor:
    permissions: { contents: read, security-events: write }
    uses: NDDev-it-com/nddev-ci-workflows/.github/workflows/zizmor-sarif.yml@<sha>
```

Dependency Review runs **on pull requests only**:

```yaml
# .github/workflows/dependency-review.yml
name: dependency-review
on: { pull_request: { branches: [main] } }
permissions: {}
jobs:
  dependency-review:
    permissions: { contents: read, pull-requests: write }
    uses: NDDev-it-com/nddev-ci-workflows/.github/workflows/public-dependency-review.yml@<sha>
```

OSSF Scorecard runs **on push-to-default + schedule only** (`pull_request` is
experimental and unsupported by the action), so keep it in its own file:

```yaml
# .github/workflows/scorecard.yml
name: scorecard
on:
  push: { branches: [main] }
  schedule: [{ cron: "31 2 * * 1" }]
permissions: {}
jobs:
  scorecard:
    permissions: { security-events: write, id-token: write, contents: read, actions: read }
    uses: NDDev-it-com/nddev-ci-workflows/.github/workflows/public-scorecard.yml@<sha>
```

### Private repository (free-minimal)

```yaml
# .github/workflows/security.yml
name: security
on:
  push: { branches: [main] }
  pull_request: { branches: [main] }
permissions: {}
jobs:
  secret-scan:
    permissions: { contents: read }
    uses: NDDev-it-com/nddev-ci-workflows/.github/workflows/secret-scan.yml@<sha>
    with: { enable_harden_runner: false }
  actionlint:
    permissions: { contents: read }
    uses: NDDev-it-com/nddev-ci-workflows/.github/workflows/actionlint.yml@<sha>
    with: { enable_harden_runner: false }
  zizmor:
    permissions: { contents: read }   # no security-events: write — least privilege
    uses: NDDev-it-com/nddev-ci-workflows/.github/workflows/zizmor-no-sarif.yml@<sha>
  validate:
    permissions: { contents: read }
    uses: NDDev-it-com/nddev-ci-workflows/.github/workflows/private-static.yml@<sha>
    with:
      command: "python3 scripts/validate_all.py"
```

### Release (either tier)

```yaml
# .github/workflows/release.yml
name: release
on: { push: { tags: ["[0-9]+.[0-9]+.[0-9]+"] } }
permissions: {}
jobs:
  publish:
    permissions: { contents: write, id-token: write, attestations: write }
    uses: NDDev-it-com/nddev-ci-workflows/.github/workflows/release-supply-chain.yml@<sha>
    with:
      version: ${{ github.ref_name }}
      package_name: my-repo
      archive_paths: "README.md LICENSE VERSION CHANGELOG.md src"
```

The release is **immutable** and ships an SPDX SBOM, SHA256SUMS, a build-provenance
attestation, and an SBOM attestation (SLSA v1.0 Build L3). Verify with
[`scripts/verify_attestations.sh`](scripts/verify_attestations.sh). See
[`docs/07-supply-chain-slsa-sbom-attestations.md`](docs/07-supply-chain-slsa-sbom-attestations.md).

## Common inputs

- `runner` — runner label (default `ubuntu-latest`).
- `enable_harden_runner` — dual-tier hardening toggle (`true` public; `false` on
  private where harden-runner is paid).
- `upload_sarif` (zizmor) — split into `zizmor-sarif.yml` (uploads) and
  `zizmor-no-sarif.yml` (least privilege; no `security-events: write`).
- `egress_policy` — `audit` (default) or `block` for harden-runner.

Each workflow documents its full input set in its header comment.

## Governance

`main` and release tags are protected by **rulesets** in
[`.github/rulesets/`](.github/rulesets/) (signed commits, required review +
code-owner review, linear history, `ci-gate` status check, tag protection). See
[`docs/08-governance-rulesets.md`](docs/08-governance-rulesets.md) for the
rulesets-first model and a migration guide from classic branch protection.

## Repository map

```
docs/       CI/CD encyclopedia (public/private tiers, security, supply chain, governance, AI)
catalog/    machine-readable capability + tools + deprecations catalog
.github/
  workflows/   reusable workflows (the product)
  rulesets/    branch/tag/push ruleset specs
  ISSUE_TEMPLATE/  issue forms
scripts/    static validators (validate_all.py) + attestation verifier
examples/   copy-paste caller workflows per tier
```

## Conventions

- Third-party actions pinned to full commit SHAs with version comments.
- Least-privilege `permissions`, `concurrency`, and `timeout-minutes` everywhere.
- No `${{ inputs.* }}` inline in `run:` (passed via `env:` — zizmor
  template-injection hardening).
- Digest-pinned container images (gitleaks) and checksum-verified downloads
  (actionlint).

## License

[AGPL-3.0-or-later](LICENSE). Author: Danil Silantyev (github:rldyourmnd), CEO NDDev.

- Security policy: [SECURITY.md](SECURITY.md)
- Contributing: [CONTRIBUTING.md](CONTRIBUTING.md)
- Releases: https://github.com/NDDev-it-com/nddev-ci-workflows/releases
