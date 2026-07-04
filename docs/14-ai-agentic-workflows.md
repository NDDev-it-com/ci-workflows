# AI and agentic workflows

GitHub's AI features can help with triage, summarization, and fixes — but they
are a **trust surface**. This doc states where AI is safe to use in CI, and one
hard retirement date you must design around.

## GitHub Agentic Workflows (public preview, 2026-06-11)

Agentic Workflows let an AI agent run inside a workflow. As of the 2026-06-11
public preview, they are designed defensively:

- **Read-only by default** — the agent cannot write to the repo unless you
  explicitly opt in.
- **Safe-outputs** — the agent proposes structured outputs (a comment, a draft
  issue) that a subsequent trusted step applies, rather than the agent mutating
  state directly.
- **Sandbox + firewall** — execution is sandboxed with restricted network
  egress.
- **Threat detection** — prompt-injection and abuse detection on inputs.

**Recommended use in this estate:** triage, summarization, docs-gap detection,
and read-only audits only. Do not grant an agentic workflow write permissions or
let it act on untrusted input from forked PRs. Treat its output as a suggestion
that a human or a trusted, least-privilege step reviews — the same trust boundary
as [pull_request_target](security/pull-request-target.md).

<a id="autofix"></a>
## Copilot Autofix

For **code scanning** alerts (CodeQL and third-party SARIF), Copilot Autofix
proposes a fix as a suggested change on the PR. It ships with GHAS Code Security
(free on public, paid on private — see [03 GHAS](03-private-paid-ghas.md)). Use
it as review input; a human still approves and merges.

## Copilot coding agent (paid / optional)

The Copilot coding agent can take an issue and open a PR autonomously. It is a
paid, optional capability. If adopted, gate its PRs behind the same rulesets,
required reviews, and CI as any contributor — no bypass actor, no auto-merge.

## Hard retirement — GitHub Models (2026-07-30)

> **GitHub Models is fully retired on 2026-07-30** (with brownouts on 07-16 and
> 07-23). **Do not build any CI around `models: read` or the GitHub Models
> inference API.** Any workflow depending on it will break.

If you need model inference in CI, call an external provider's API with a
short-lived, OIDC-obtained or narrowly-scoped credential — not GitHub Models.
This item is tracked in [watchlist-2026.md](watchlist-2026.md).

## Summary of what to use where

| Task | Use | Tier |
| --- | --- | --- |
| Triage / summarize / docs-gap / read-only audit | Agentic Workflows (read-only, sandboxed) | preview |
| Fix a code scanning alert | Copilot Autofix | GHAS |
| Autonomous PR from an issue | Copilot coding agent (gated) | paid/optional |
| Model inference in CI | External provider API — **not GitHub Models** | n/a |

---
Last verified: 2026-07-04
