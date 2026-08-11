# NDDev estate tier — everything the organization already pays for

The other four tier docs describe what GitHub *offers* at a given visibility and
plan. This one describes what the **NDDev-it-com organization actually owns**,
so that a repository in this estate stops being configured as if it were on the
free plan.

Which products the organization holds. Licence counts, repository inventory and
observed spend are account state, not library facts, and live in the control
plane rather than here — see the note at the end of this document.

| Product | Licences | Consequence for this library |
| --- | --- | --- |
| **Enterprise Cloud** | held | Artifact Attestations work on **private** repos |
| **Code Security** | held | CodeQL + SARIF upload legal on private |
| **Secret Protection** | held | Native secret scanning on private (push protection deliberately off) |
| **Code Quality** | held | Maintainability scans + PR gate — see [16](16-code-quality.md) |

Platform side is already applied: the org security configuration
**`nddev-config`** (`enforcement: enforced`) is attached to every repository in
the organization and is the default for new ones. It enables GHAS, secret scanning, validity
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
  observed when the stock `GitHub recommended` configuration attached to the
  public repositories without an advanced setup and failed on every repository
  already running `codeql.yml`.
  Code scanning is therefore enabled per repository instead.

  **Coverage is tracked in the control plane, not here.** Repositories fall into
  three groups: default setup, their own CodeQL workflow, and an empty language
  list. The last group is
  not a gap — they are submodule parents holding only Shell and Dockerfile, so
  CodeQL has nothing to analyse. Note that such a record still *reads* as "code
  scanning on" while scanning nothing, so count languages, not state.

  Four traps in the default-setup REST API, all learned by hitting them:

  - **The REST enum has no `rust`, but the product does.** `PATCH` accepts only
    `actions, c-cpp, csharp, go, java-kotlin, javascript-typescript, python,
    ruby, swift`. Yet CodeQL Rust support left public preview and went
    **generally available for default setup** in October 2025. Verified
    2026-08-10 on this account: the enum rejects `rust`, and `GET` does not
    offer it as available on `nddev-web`, `captcha` or `rldyour-chatgpt`,
    all three of which contain Rust. So the gap is this account's API surface
    lagging the documented GA, not a product limitation — treat Rust coverage as
    **pending and retryable**, not impossible, and re-probe the enum before
    reaching for a substitute.
  - **`GET` returns *available* languages when `not-configured` and *configured*
    languages when `configured`**, and it echoes the legacy aliases `javascript`
    and `typescript` which the `PATCH` enum then rejects. Filter the read-back
    through the accepted set before writing it again.
  - **The setup run is atomic**: one language that needs a build (`swift`,
    `java-kotlin`, `ruby`) fails the run and GitHub silently reverts the whole
    configuration. The `PATCH` still returned a `run_id`, so success has to be
    read from the run's per-job conclusions, not the response.
  - **Omitting `runner_type` resets it to `standard`.** A `PATCH` that only
    changes languages will move a private repository off the fleet and onto
    metered GitHub-hosted runners without saying so. Always send
    `runner_type`/`runner_label` with every write.

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

Private repositories take the same suite with every job pinned to the
self-hosted fleet:
[`examples/nddev/security-private-selfhosted.yml`](../examples/nddev/security-private-selfhosted.yml).
The coverage is identical — only the `runner` inputs differ — so a repository
changing visibility switches example, not posture.

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
  is assigned. That is a per-seat paid product, and the Code Quality licence does
  not include it.
- **SAML SSO, IP allow list, SSH certificate authorities.** None configured at
  org or enterprise level.

**Enforced SHA pinning is now on.** Both org and enterprise report
`sha_pinning_required: true`, so the platform rejects tag-referenced actions
estate-wide, not just in this library. `scripts/check_pinned_actions.py` remains
the pre-merge gate; the platform setting is the backstop for repositories that
do not run it.

## Cost note that governs tier choice

Every paid product here — Code Security, Secret Protection, Code Quality — bills
per **active committer**, counted **once per organization**, not per repository.
With a single active committer the estate pays the same whether one repository or
every repository is enabled. That is why `nddev-config` is attached to all of
them rather than a chosen subset: partial coverage would have cost exactly the
same and protected less. Re-evaluate that reasoning the moment a second
committer joins.

<a id="cost-envelope"></a>
## The fixed-cost envelope

This estate is the `enterprise-full-private-fixed80` profile. The four fixed
lines, its guards and every other mode are declared in `catalog/profiles.yml`
and rendered to
[the generated profile matrix](generated/profile-matrix.md) — read the amounts
there, not here. `scripts/validate_profiles.py` checks that the itemised lines
sum to the declared total and that a fixed-cost profile cannot permit AI credits
or Actions overage, so the two cannot drift apart.

The licence mix and the amount are declared in `catalog/profiles.yml` and
validated against it; the invoice that confirms them is account state and lives
in the control plane. Read the amounts from the generated matrix, never from
this paragraph.

Everything else is metered and deliberately driven to zero:

| Metered line | Control |
| --- | --- |
| Actions minutes | $0 hard-stop budget at **org and enterprise**; private jobs routed to self-hosted |
| Actions **storage** | budgets do **not** block storage — controlled by 1-day artifact/log retention with the org maximum also pinned to 1 |
| **AI credits** | dedicated **AI credits budget**, $0, stop-usage on — see below |
| Codespaces, Packages, Git LFS, Models, Sandbox, Spark | $0 hard-stop budgets at both levels |

Three facts worth carrying:

- **A budget on a license-based product cannot stop anything.** The Code Quality
  budget is scoped by *license count*, and the edit form says so outright:
  "Stop usage when budget limit is reached — **Not available for license-based
  products**". The budgets *list* still renders `Stop usage: Yes` for it, exactly
  like the metered budgets where the stop does work. Set at 0 licences against 1
  legitimately consumed, it also reads `Over budget` permanently, so its alert
  carries no signal.
- **AI credits have their own budget type, and that one works.** The "New budget"
  flow offers **"AI credits budget — set a budget for all SKUs that consume AI
  credits"** alongside product- and SKU-level. It is metered, so stop-usage
  applies. Created at enterprise scope at **$0 with stop-usage**, it caps every
  AI-credit source at once — which matters, because `ai_findings_option:
  disabled` on every repository did **not** stop the line: credits still
  accrued under product *Code Quality*, and Copilot Autofix
  ("suggest fixes for CodeQL alerts using AI") remains `On` at repository level.
  Do not treat the per-repository AI toggle as the control.
  Budgets are not retroactive: "usage before budget creation isn't counted in the
  current billing cycle".
- **Seat count is the one thing no budget bounds.** A second active committer
  adds two more Advanced Security licences before anyone writes a workflow — the
  single largest step change available to this envelope. Org membership,
  outside-collaborator invitation, and enterprise member purchasing are all
  closed for that reason.

<a id="runner-routing"></a>
## Runner routing in this estate

Private repositories run on the estate's self-hosted fleet; public repositories
stay on GitHub-hosted runners, where minutes are free and self-hosted would be a
security defect. Mechanics, the two settings that a workflow file cannot reach,
and the reason this public repository never routes itself to self-hosted:
[05 Runners → Routing by visibility](05-runners.md#visibility-routing).

The invariant is that every private repository with a configured default setup
runs on `runner_type: labeled` and every public one on `standard`; the current
per-repository tally is control-plane state. Re-verify after any change to
code-scanning setup — omitting `runner_type` from a `PATCH` silently resets it
to `standard`, which moves private scanning onto metered runners.

<a id="included-minutes"></a>
### The included-minutes pool is the live risk to this envelope

Routing private work to the fleet is what keeps Actions at zero, and the routing
is only as good as its last write. The included pool has been observed emptying
well before month end when routing slips.

What happens then is not an overspend — the Actions budget is $0 with
stop-usage, so **Actions halt**. The envelope holds and CI stops. That is the
intended trade, but it is worth stating plainly, because "the bill stayed inside
the envelope" and "CI ran all month" are not the same claim. Read the current
meter in the control plane; a figure copied into this document is stale the day
after it is written.

Anything that adds a scheduled or per-PR job to a **private** repository draws on
this pool. Check the meter before adding one.

---
Last verified: 2026-08-10
