# Code Quality tier — paid per active committer; the public rate is disputed

GitHub Code Quality is a **maintainability** product: it runs CodeQL quality
queries (not only security queries) and reports findings, quality scores, and
history, with optional AI-assisted detection and Copilot Autofix. It went GA and
became billable on **2026-07-20**.

It gets its own tier because it **breaks the visibility rule the other three
tiers are built on**.

## Why this is a separate tier

The [three-tier model](00-overview.md#the-three-tier-model) sorts capabilities by
repository visibility and plan: public is free, private-free is the zero-cost
subset, private-paid unlocks the rest through GHAS. Code Quality obeys none of
that:

| Assumption that holds for CodeQL / GHAS | What Code Quality actually does |
| --- | --- |
| Public repositories get it free | **Disputed — see below.** Do not compile a public per-committer cost either way |
| A paid GHAS licence unlocks it | **No.** The licence is independent of Code Security and Secret Protection |
| Cost scales with the repositories you enable | **No.** Committers are counted **once per organization** |

Being public certainly saves the **Actions-minutes** component: scans run as
Actions workflows, and standard runners are unmetered on public repositories.

<a id="public-rate-dispute"></a>
> **The public per-committer rate is unresolved between GitHub's own sources.**
> [github.com/features/code-quality](https://github.com/features/code-quality)
> states "Public repositories: $0 per committer + usage-based billing for
> AI-powered work". The
> [billing documentation](https://docs.github.com/en/billing/concepts/product-billing/github-code-quality)
> states only that "each active committer uses one Code Quality license", with no
> visibility exemption and no rate. Neither reading may be hard-coded: the
> `github-code-quality-transition` fact carries the dispute explicitly and the
> public rate stays **account-observed** until NDDev Licensing/Billing or an
> invoice settles it. What is *not* disputed: the $10 private rate, the
> Team/Enterprise plan gate, and the once-per-organization committer count.

The consequence for cost control is blunt: **enabling Code Quality on one
repository already bills your entire active-committer set.** Splitting an estate
into "a few Code Quality repos and many free repos" saves nothing unless the
people who commit to the paid repos are a strictly smaller group than the people
who commit anywhere. Scope the tier by **who commits**, not by how many repos.

Live price, plan, and committer-counting rules are in the fact ledger, not in
this prose: [`github-code-quality-transition`](generated/free-tier-matrix.md).

## What the free tiers do instead

Both free tiers **exclude** Code Quality and get their maintainability signal
from workflows in this library, which cost nothing beyond Actions minutes:

| Need | Free substitute | Tier |
| --- | --- | --- |
| Security-focused static analysis | `public-codeql.yml` | [01 Public OSS](01-public-oss-free.md) (free on public) |
| Actions static analysis | `zizmor-sarif.yml` / `zizmor-no-sarif.yml` | both |
| Coverage threshold gate | `coverage-gate.yml` | both |
| Lint / type / build packs | the language packs in [15 Language & quality packs](15-language-and-quality-packs.md) | both |
| Docs quality | `docs-quality.yml` | both |
| PR hygiene | `pr-hygiene.yml` | both |

Those are not a feature-equivalent replacement — they do not produce Code
Quality's maintainability scores or its history — but they keep the free tiers
genuinely free.

## Enabling the tier

Code Quality is a **platform feature, not a reusable workflow.** This library
ships no caller for it, and there is nothing to pin by SHA: it has no Action and
no `workflow_call` entrypoint, which is why its catalog entry carries
`workflow: null` and `example: null`.

**It does, however, have a REST API**, so its state *is* assertable and
drift-checkable — just not from this library. That belongs to the estate
reconciler (GDS), not to a reusable-workflow catalogue:

| Endpoint | Use |
| --- | --- |
| `GET /repos/{owner}/{repo}/code-quality/setup` | read desired-vs-observed setup |
| `PATCH /repos/{owner}/{repo}/code-quality/setup` | enable/disable, change languages or runner |
| `GET /repos/{owner}/{repo}/code-quality/findings` | list findings |
| `GET /repos/{owner}/{repo}/code-quality/findings/{finding_number}` | one finding |

The setup object carries `state` (`configured` / `not-configured`), `runner_type`
(`standard` / `labeled`), `runner_label`, `languages` (csharp, go, java-kotlin,
javascript-typescript, python, ruby) and `ai_findings_option` (`disabled` /
`on_push`). A plain `repo`-scoped token reads it. See
[docs.github.com REST — Code Quality](https://docs.github.com/en/rest/code-quality/code-quality).

> Check-name warning: Code Quality and CodeQL **default setup** both execute as
> `dynamic/github-code-scanning/codeql` and both emit check runs named
> `Analyze (<language>)`. Only the *run* name distinguishes them — `Code Quality:
> Push on main` versus `Push on main`. A repository with both enabled for the same
> language produces two check runs with an identical name, so a required status
> check on `Analyze (<language>)` cannot tell maintainability from security.
> Resolve the owner through the two setup endpoints, never through the name.

The UI path below is still the fastest way to do it by hand.

1. **Enterprise** — an enterprise owner must allow Code Quality at the
   enterprise level, or the org setting has no effect.
2. **Organization** — Settings → Security → **Code quality** → **Repository
   access**. This dropdown *is* the tier boundary:
   - `No repositories` — the whole org stays in the free tiers.
   - `Selected repositories` — the Code Quality tier; pick them explicitly.
   - `All repositories` — every repo joins the paid tier, including public ones.
   Optionally set **Enforce access** so repository admins cannot opt themselves
   back in.
3. **Repository** — Settings → Security → **Code quality** → *Enable code
   quality*, then choose analysed languages and runner type. Actions must be
   enabled on the repo.

Prefer `Selected repositories` + `Enforce access`: `All repositories` silently
pulls every public repo into a paid product.

> The NDDev estate runs `All repositories` + `Enforce access` on purpose. That is
> not a contradiction of the advice above — it follows from the same arithmetic:
> the licence bills once per active committer, so at one committer the fiftieth
> repository costs exactly what the first one did. Apply the cautious default
> whenever the committer count is greater than one, or when "every public repo"
> would mean repos you do not control. See
> [17 NDDev tier](17-nddev-tier.md#cost-envelope).

<a id="ai-findings"></a>
## AI findings are a second, separately metered product

The repository page carries **two** switches, and only the first is covered by
the $10 licence:

| Switch | Billing |
| --- | --- |
| **Code Quality analysis** — CodeQL quality queries | included in the per-committer licence; unmetered |
| **AI findings** — AI-generated findings on push | **metered separately: AI credits, with no included allowance** |

Every AI-credit line in the billing API shows `discountAmount: 0.00` — nothing is
bundled. Observed rate: **$0.01 per credit**, and a single mid-sized repository
burned **774.9 credits in roughly twelve days** — about **$19/month for one
repository**, i.e. nearly twice the licence that covers the whole organization.

Two consequences worth stating plainly:

- **A product budget cannot fence this off.** A Code Quality budget must leave
  at least $10 of headroom for the licence, and AI credits accrue into that same
  headroom before any hard stop trips. The per-repository switch is the only
  real control.
- **The switch is absent where CodeQL finds no supported language.** Those
  repositories render *"No CodeQL supported languages to scan in this
  repository"* and cannot generate AI credits at all — a stronger guarantee than
  the switch being off, and not something to "fix".

Leave **AI findings off** unless the credit spend has been sized against the
licence for that specific repository.

## Using it as a merge gate

Enablement only produces findings. To make it block a bad merge, add the ruleset
rule on the target branch:

- Repository or org ruleset → **Branch rules** → **Require code quality
  results**.
- **Severity** selects the lowest severity that must be resolved before merge:
  `Errors`, `Warnings and higher`, `Notes and higher`, or `All`.
- The check that must report success is **`CodeQL - Code Quality`**.

The rule also blocks merges while analysis is **still running** or when it
**failed** — including failure caused by exhausted Actions minutes. On a private
repo with a tight minutes budget that turns a billing problem into a merge
outage; start at `Errors` and widen once the lane is proven.

> The REST ruleset rule-type identifier for this rule is not documented, so the
> repo's [`.github/rulesets/`](../.github/rulesets/) specs — which are shaped for
> `POST /repos/{owner}/{repo}/rulesets` and validated by
> `scripts/check_rulesets.py` — do not encode it. Configure this rule in the UI
> and treat the JSON specs as covering only the API-expressible rules. See
> [08 Governance & rulesets](08-governance-rulesets.md).

## Relationship to GHAS

Code Quality is **not** part of GitHub Advanced Security. A repository can hold
any combination of Code Security, Secret Protection, and Code Quality licences;
buying [03 Private-paid / GHAS](03-private-paid-ghas.md) does not include it, and
buying Code Quality does not unlock CodeQL *security* scanning on a private repo.

Both run CodeQL, so on a private repo with both licences you are paying two
products to drive one engine over the same code for different query suites, and
both consume Actions minutes.

## Turning the tier off

Set organization **Repository access** to `No repositories`, or toggle the
repository switch off. Scans and the billing they generate stop immediately;
usage already accrued in the current cycle still bills. Findings, scores, and
history are retained and return if you re-enable — disabling is not data loss.

---
Last verified: 2026-08-01
