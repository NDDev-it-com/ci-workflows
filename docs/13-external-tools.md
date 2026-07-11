# External tools

The library composes best-in-class open-source tools rather than reinventing
them. This is the reference table: what each does, which tier it fits, and which
workflow uses it. All are free/OSS and pinned (SHA for actions, digest for
container images, checksum for downloaded binaries).

| Tool | Does | Tier | Used by |
| --- | --- | --- | --- |
| **actionlint** | Lints workflow YAML: syntax, expression typos, deprecations | Both | `actionlint.yml` |
| **zizmor** | GitHub Actions security static analysis (template injection, cred persistence, excessive perms, impostor refs) | Both | `zizmor-sarif.yml`, `zizmor-no-sarif.yml` |
| **gitleaks** | Secret detection across working tree + full git history | Both | `secret-scan.yml` |
| **trivy** | Vulnerability + misconfig scanning for containers, images, IaC, and deps | Both | `container-ci.yml` |
| **syft** | SBOM generation (SPDX / CycloneDX) — checksum-pinned CLI archive | Both | `release-supply-chain.yml` |
| **grype** | Vulnerability scanning of SBOMs / images | Both | `container-ci.yml` (optional) |
| **osv-scanner** | Dependency vulnerabilities from the OSV database across lockfiles | Both | `private-static.yml` command |
| **semgrep** | Multi-language SAST with custom rules | Both | `private-static.yml` command |
| **shellcheck** | Shell script linting | Both | language/`docs-ci.yml` steps |
| **hadolint** | Dockerfile linting | Both | `container-ci.yml` |
| **pre-commit** | Local + CI hook runner aggregating many linters | Both | `private-static.yml` command |
| **renovate** | Alternative dependency updater (Dependabot is the default here) | Both | optional (repo uses Dependabot) |

## Notes per tool

- **actionlint** — downloaded pinned and **checksum-verified**
  (`actionlint_sha256`), not run as an unpinned action.
- **zizmor** — installed at a pinned version; `regular` persona by default,
  `pedantic`/`auditor` available. Split into SARIF/no-SARIF callers for the
  public vs private-free tiers (see [06 Security scanning](06-security-scanning.md#zizmor)).
- **gitleaks** — run from a **digest-pinned** container image with `--redact`
  so matched secrets are never printed.
- **trivy / grype / hadolint** — the container lane's scanners; trivy also
  covers IaC and dependencies. Emit SARIF for upload on public/GHAS.
- **syft** — version 1.46.0 is downloaded directly for Linux AMD64/ARM64 and
  verified against a pinned byte size and SHA-256 before producing SPDX-JSON;
  its output feeds the SBOM attestation (see
  [07 Supply chain](07-supply-chain-slsa-sbom-attestations.md#generating-the-sbom)).
- **osv-scanner / semgrep** — drop into `private-static.yml` as the `command`
  for zero-cost private SAST/dependency scanning.
- **renovate vs Dependabot** — this repo uses **Dependabot** (weekly, grouped,
  with a cooldown, see `.github/dependabot.yml`); renovate is listed as the
  common alternative if you need its extra flexibility.

## Pinning discipline

| Kind | Pin by | Bumped by |
| --- | --- | --- |
| GitHub Action | full commit SHA + version comment | Dependabot |
| Container image | `name:tag@sha256:...` digest | Dependabot / manual |
| Downloaded binary | version + SHA256 checksum verify | manual |

---
Last verified: 2026-07-10
