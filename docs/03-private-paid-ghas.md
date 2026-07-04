# Private-paid tier — GitHub Advanced Security (GHAS)

To run the full security suite on **private** repositories you need paid GitHub
Advanced Security, which since 2025 is sold as two products:

- **GitHub Code Security** — code scanning (CodeQL), dependency review, Copilot
  Autofix, security overview, delegated alert dismissal governance.
- **GitHub Secret Protection** — secret scanning, push protection, custom
  patterns, delegated bypass.

On **public** repositories all of this is free (see
[01 Public OSS free](01-public-oss-free.md)); this doc is specifically about
turning it on for private repos, where it is billed per active committer.

## What GHAS unlocks on private repos

| Capability | Product | Library workflow |
| --- | --- | --- |
| CodeQL code scanning | Code Security | `public-codeql.yml` |
| SARIF upload to code scanning | Code Security | `zizmor-sarif.yml`, any SARIF producer |
| Dependency review (PR gate) | Code Security | `public-dependency-review.yml` |
| Copilot Autofix for code scanning | Code Security | (native, on alerts) |
| Secret scanning + push protection | Secret Protection | repository setting |
| Custom secret patterns | Secret Protection | org/repo setting |
| Delegated bypass / delegated dismissal | both | org governance |

> The `public-*` naming reflects where these run **for free**. On a private repo
> with GHAS enabled they run identically — the workflow is the same, only the
> billing changes.

## Enabling on a private repo

1. Purchase/assign GHAS (Code Security and/or Secret Protection) at the org or
   enterprise level.
2. Enable **Code scanning**, **Dependency graph**, **Dependency review**, and
   **Secret scanning + push protection** under **Settings → Code security**.
3. Add the reusable callers you need, using the public-tier examples but keeping
   `enable_harden_runner` / SARIF upload **on** (they are now paid-for and
   supported).

```yaml
# private repo WITH GHAS — same callers as public
jobs:
  codeql:
    permissions:
      actions: read
      contents: read
      security-events: write
    uses: NDDev-it-com/nddev-ci-workflows/.github/workflows/public-codeql.yml@<full-sha>
    with:
      languages: '["python","actions"]'
  zizmor:
    permissions:
      contents: read
      security-events: write
    uses: NDDev-it-com/nddev-ci-workflows/.github/workflows/zizmor-sarif.yml@<full-sha>
  dependency-review:
    permissions:
      contents: read
      pull-requests: write
    uses: NDDev-it-com/nddev-ci-workflows/.github/workflows/public-dependency-review.yml@<full-sha>
```

## Copilot Autofix

For code scanning alerts (CodeQL and third-party SARIF), Copilot Autofix
proposes a fix as a suggested change on the pull request. It is included with
Code Security. Treat suggestions as review input, not as an auto-merge path — see
[14 AI / agentic workflows](14-ai-agentic-workflows.md#autofix).

## Delegated governance

GHAS supports **delegated alert dismissal** (code scanning) and **delegated
bypass** (push protection): a developer's request to dismiss an alert or bypass a
blocked secret is routed to a designated reviewer instead of being self-served.
Configure at the org level and pair with rulesets — see
[08 Governance & rulesets](08-governance-rulesets.md).

## When to stay in the free tier instead

If a repository can be public, publish it public and get everything for free. If
it must stay private and the budget is not there, run the zero-cost stack in
[02 Private free](02-private-free.md): gitleaks instead of native secret
scanning, `zizmor-no-sarif.yml` instead of SARIF-backed code scanning, and
`private-static.yml` for validation.

---
Last verified: 2026-07-04
