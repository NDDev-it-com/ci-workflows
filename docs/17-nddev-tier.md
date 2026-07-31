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
| **Secret Protection** | 1 active committer, 26 repos | Native secret scanning + push protection on private |
| **Code Quality** | 1 consumed | Maintainability scans + PR gate — see [16](16-code-quality.md) |

Platform side is already applied: the org security configuration
**`nddev-config`** (`enforcement: enforced`) is attached to all 50 repositories
and is the default for new ones. It enables GHAS, secret scanning, push
protection, validity checks, non-provider patterns, Dependabot security updates,
and private vulnerability reporting. It deliberately leaves
`code_scanning_default_setup: not_set` — code scanning stays the job of this
library's CodeQL workflows, and forcing default setup would collide with the
`codeql.yml` advanced setup already present in 20 repositories.

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
| Native secret scanning + push protection | gitleaks substitute | native, plus `secret-scan.yml` for history |
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
