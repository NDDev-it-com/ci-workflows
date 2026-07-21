# Private-free tier — zero-cost only

Private repositories on a free GitHub plan can still run a meaningful security
and supply-chain stack, but **only the capabilities that cost nothing**. This
doc lists exactly what is free on private, how to configure the library for it,
and — importantly — what is **excluded** because it is paid.

## Paid on private → excluded from this tier

These are free on public repositories but **require paid GitHub Advanced
Security** (or are otherwise billable) on private repositories. Do **not** enable
them in the private-free tier:

| Feature | Why excluded here | Where it lives |
| --- | --- | --- |
| CodeQL code scanning | Paid (GHAS) on private | [03 GHAS](03-private-paid-ghas.md) |
| Native secret scanning + push protection | Paid (Secret Protection) on private | [03 GHAS](03-private-paid-ghas.md) |
| Dependency review action | Paid (GHAS) on private | [03 GHAS](03-private-paid-ghas.md) |
| `step-security/harden-runner` | Paid on private repos | use a private-free workflow with no action reference |
| SARIF upload to code scanning | Requires code scanning (paid) | use the no-SARIF workflow variant |
| GitHub Artifact Attestations | Require GitHub Enterprise Cloud on private/internal (a plan gate — GHAS does not unlock it) | use `release-supply-chain-free.yml` (below) |

## The zero-cost private stack

| Capability | Workflow | Notes |
| --- | --- | --- |
| Workflow YAML lint | `actionlint.yml` | contains no paid action |
| Actions static analysis | `zizmor-no-sarif.yml` | fails on findings, no upload |
| Secret scanning (history-aware) | `secret-scan.yml` | gitleaks; contains no paid action |
| Static validation | `private-static.yml` | single Ubuntu job, no matrix/cache |
| Release supply chain (SBOM, checksums, no attestations) | `release-supply-chain-free.yml` | attestations require GHEC on private |
| Cross-platform smoke | `cross-platform-smoke.yml` | OS matrix |
| Cloud auth | OIDC | short-lived credentials, no stored secrets |

### Recommended caller

```yaml
# .github/workflows/security.yml  (private, free-minimal)
name: security
on:
  push: { branches: [main] }
  pull_request: { branches: [main] }
permissions: {}
jobs:
  secret-scan:
    permissions: { contents: read }
    uses: NDDev-it-com/ci-workflows/.github/workflows/secret-scan.yml@<full-sha>
  actionlint:
    permissions: { contents: read }
    uses: NDDev-it-com/ci-workflows/.github/workflows/actionlint.yml@<full-sha>
  zizmor:
    permissions: { contents: read }
    uses: NDDev-it-com/ci-workflows/.github/workflows/zizmor-no-sarif.yml@<full-sha>
  validate:
    permissions: { contents: read }
    uses: NDDev-it-com/ci-workflows/.github/workflows/private-static.yml@<full-sha>
    with:
      command: "python3 scripts/validate_all.py"
```

> `zizmor-no-sarif.yml` still **fails the job** when zizmor reports findings at
> or above `min_severity`; it just skips the (paid) SARIF upload. The
> public/GHAS tier uses `zizmor-sarif.yml` instead. See
> [06 Security scanning](06-security-scanning.md#zizmor).

## actionlint (`actionlint.yml`)

Lints workflow YAML for syntax errors, expression typos, and deprecated usage.
The binary is downloaded pinned and **checksum-verified** (`actionlint_sha256`).
Free everywhere. Its reusable workflow contains no Harden-Runner reference.
Linux X64 runners only: the workflow installs the linux_amd64 binary, and a
first-step guard rejects any other platform before the download.

## gitleaks (`secret-scan.yml`)

History-aware secret detection using a **digest-pinned** gitleaks container
image (`detect --redact --exit-code 1` over full git history via
`fetch-depth: 0`). Gitleaks is free on public and private. It is the
private-tier substitute for native secret scanning, which is paid.

## private-static (`private-static.yml`)

A deliberately minimal single Ubuntu job with **no matrix, no cache, no
artifacts** — the zero-cost validation lane. It runs a caller-provided `command`
(required input) with optional Python setup.

```yaml
jobs:
  validate:
    permissions: { contents: read }
    uses: NDDev-it-com/ci-workflows/.github/workflows/private-static.yml@<full-sha>
    with:
      command: "ruff check . && pyright ."
      timeout_minutes: 10
```

## Release supply chain without attestations (`release-supply-chain-free.yml`)

GitHub Artifact Attestations are **not available to private or internal
repositories on the Free, Pro, or Team plan** — they require GitHub Enterprise
Cloud. That is a plan gate, not a GHAS gate, so buying Code Security does not
unlock it either. `release-supply-chain.yml` would fail at its unconditional
attestation steps on such repositories, so the private-free tier calls
`release-supply-chain-free.yml`: the same deterministic tracked-source archive,
exact-payload SPDX SBOM, canonical release notes, manifest, and `SHA256SUMS`,
published as one immutable release — with no attestation actions and only
`contents: write`. The manifest records `slsa_build_level: null` because no
provenance is generated. Copy-paste caller:
[`examples/release/private-free-release.yml`](../examples/release/private-free-release.yml).
Details: [07 Supply chain](07-supply-chain-slsa-sbom-attestations.md).

## OIDC instead of stored secrets

Use OIDC to obtain short-lived cloud credentials (AWS/GCP/Azure) at run time
instead of storing long-lived keys as Actions secrets. This is free and is the
recommended posture for private repos — see
[10 Deployments & environments](10-deployments-environments.md#cloud-oidc).

## Cross-platform smoke (`cross-platform-smoke.yml`)

Runs a caller command across an OS matrix. On private repos, **Windows and macOS
minutes are billed at higher multipliers than Linux** (see
[05 Runners](05-runners.md#cost-model)). Trim `os_list` to `["ubuntu-latest"]`
to stay free-minimal, or accept the multiplier cost intentionally. Use
`linux_command`, `macos_command`, or `windows_command` when one platform needs a
lighter smoke than the default `command`.

## Self-hosted caveats

Self-hosted runners avoid GitHub minute billing but move trust and cost onto
your own infrastructure. **Never** attach self-hosted runners to a public repo
(forked PRs can execute arbitrary code on them). For private repos, isolate,
auto-scale (e.g. Actions Runner Controller), and treat egress carefully — see
[05 Runners](05-runners.md#self-hosted).

---
Last verified: 2026-07-11
