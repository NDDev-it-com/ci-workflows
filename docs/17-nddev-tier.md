# NDDev estate tier — everything the organization already pays for

The other four tier docs describe what GitHub *offers* at a given visibility and
plan. This one describes what the **NDDev-it-com organization actually owns**,
so that a repository in this estate stops being configured as if it were on the
free plan.

Entitlements, verified 2026-08-01 against the enterprise licensing page:

| Product | Licences | Consequence for this library |
| --- | --- | --- |
| **Enterprise Cloud** | 1 consumed | Artifact Attestations work on **private** repos |
| **Code Security** | 1 active committer, 23 repos | CodeQL + SARIF upload legal on private |
| **Secret Protection** | 1 active committer, 26 repos | Native secret scanning on private (push protection deliberately off) |
| **Code Quality** | 1 consumed | Maintainability scans + PR gate — see [16](16-code-quality.md) |

Platform side is already applied: the org security configuration
**`nddev-config`** (`enforcement: enforced`) is attached to all 50 repositories
and is the default for new ones. It enables GHAS, secret scanning, validity
checks, non-provider patterns, Dependabot security updates, and private
vulnerability reporting.

Two settings are deliberately **not** in it, and both decisions are load-bearing:

- **`secret_scanning_push_protection: disabled`.** Push protection is the only
  control that stops a secret reaching the remote at all; with it off, detection
  is after the fact and the remedy is rotation, not prevention. It was turned off
  as an explicit velocity trade-off. Treat a secret-scanning alert here as an
  already-leaked credential.
- **`code_scanning_default_setup: not_set`.** Config attachment is atomic per
  repository: forcing default setup where an active CodeQL *advanced* setup
  exists fails the **whole** attachment, taking secret scanning down with it —
  observed exactly once, when the stock `GitHub recommended` configuration
  attached to 4 of 24 public repos and failed on the 20 running `codeql.yml`.
  Code scanning is therefore enabled per repository instead, which is why
  coverage is **50/50**: 30 repositories on default setup, 20 on their own
  CodeQL workflow.

## The correction this tier exists to make

[02 Private free](02-private-free.md) tells a private repository to release with
`release-supply-chain-free.yml`, because Artifact Attestations require GitHub
Enterprise Cloud on private and internal repos.

**That gate does not apply here — this estate has Enterprise Cloud.** Every one
of the 26 private repositories can use the attested `release-supply-chain.yml`
and get SLSA build provenance. Using the `-free` variant here throws away
provenance that is already paid for.

The same inversion applies across the board: in the generic model a private repo
is the *degraded* case. In this estate it is not. Private and public repositories
run the **same** callers — the difference is only who pays, and that is settled.

| Capability | Generic private-free | This estate |
| --- | --- | --- |
| CodeQL + SARIF | excluded (paid) | `public-codeql.yml`, `zizmor-sarif.yml` |
| Native secret scanning | gitleaks substitute | native, plus `secret-scan.yml` for history |
| Push protection | unavailable (paid) | licensed but **off** by choice — see above |
| Dependency review | excluded (paid) | `public-dependency-review.yml` |
| Release provenance | `release-supply-chain-free.yml` | **`release-supply-chain.yml`** (attested) |
| Maintainability | lint/coverage only | Code Quality + the free packs |

## Callers

Security suite: [`examples/nddev/security.yml`](../examples/nddev/security.yml).
It is the private-paid/GHAS suite plus `osv-scan.yml`, and it runs unchanged on
public repositories.

Release with provenance — on **private** repos too:

```yaml
jobs:
  publish:
    permissions:
      contents: write
      id-token: write
      attestations: write
      artifact-metadata: write
    uses: NDDev-it-com/ci-workflows/.github/workflows/release-supply-chain.yml@<full-sha>
```

The manifest records `slsa_build_level: 3` rather than the `null` that
`release-supply-chain-free.yml` writes. See
[07 Supply chain](07-supply-chain-slsa-sbom-attestations.md).

## What this estate does *not* have

- **Copilot Autofix.** Copilot Business is provisioned on the organization but
  **zero seats are assigned** (`seat_management_setting: unconfigured`), so
  Autofix on code scanning and Code Quality findings is unavailable until a seat
  is assigned. That is a per-seat paid product; the $10 Code Quality licence does
  not include it.
- **SAML SSO, IP allow list, SSH certificate authorities.** None configured at
  org or enterprise level.
- **Enforced SHA pinning.** Both org and enterprise report
  `sha_pinning_required: false`. This library enforces full-SHA pins on itself
  through `scripts/check_pinned_actions.py`, but the platform does not enforce it
  on other repositories in the estate. Turning it on org-wide would break any
  repository still referencing actions by tag — audit before enabling.

## Cost note that governs tier choice

Every paid product here — Code Security, Secret Protection, Code Quality — bills
per **active committer**, counted **once per organization**, not per repository.
With a single active committer the estate pays the same whether one repository or
all fifty are enabled. That is why `nddev-config` is attached to all 50 rather
than a chosen subset: partial coverage would have cost exactly the same and
protected less. Re-evaluate that reasoning the moment a second committer joins.

---
Last verified: 2026-08-01
