# The `pull_request_target` / pwn-request class

The single most dangerous mistake in GitHub Actions is running **untrusted fork
code with a privileged token**. This is the "pwn request" class. This doc
explains the trust boundary, the modern default that blocks it, and safe
patterns.

## The vulnerability

`pull_request` runs a forked PR with a **read-only** token in the fork's
context — safe by default. `pull_request_target` (and `workflow_run`) instead run
in the **base repository's** context with **write** access to secrets and the
`GITHUB_TOKEN`. If such a privileged workflow **checks out and executes the
fork's code**, an attacker's PR runs with your write token and secrets — they can
exfiltrate secrets, push to branches, or poison caches.

```yaml
# DANGEROUS — do not do this
on: pull_request_target      # privileged context + write token
jobs:
  build:
    steps:
      - uses: actions/checkout@<sha>
        with:
          ref: ${{ github.event.pull_request.head.sha }}  # attacker's code
      - run: make            # runs attacker code with your secrets
```

Template injection is the sibling risk: interpolating untrusted
`${{ github.event.pull_request.title }}` (or body, branch name) directly into a
`run:` script lets an attacker inject shell commands. zizmor flags this (see
[06 Security scanning](../06-security-scanning.md#zizmor)).

## The modern default — checkout v7 refuses fork code

`actions/checkout` **v7 refuses to check out fork-PR code in
`pull_request_target` and `workflow_run` by default.** The opt-out is an explicit
input:

```yaml
- uses: actions/checkout@<full-sha>   # v7
  with:
    allow-unsafe-pr-checkout: true    # DELIBERATE risk — you own the consequences
```

Treat `allow-unsafe-pr-checkout: true` as a loaded gun: only in a
fully-understood, isolated design. Note this default **only blocks the checkout
action** — raw `git fetch`/`git checkout` or `gh pr checkout` of fork code in a
privileged event is still on you to avoid.

## The rule

> **Never check out untrusted fork code in a privileged event
> (`pull_request_target`, `workflow_run`).**

If you need code-dependent processing of a fork PR, do the untrusted work in a
plain `pull_request` job (read-only token, no secrets) and hand only trusted,
sanitized data to any privileged follow-up.

## Cache poisoning trust boundary

Caches are shared mutable state. A job running from an untrusted trigger could
write a poisoned cache that a later trusted job restores. GitHub now issues a
**read-only cache token** for untrusted triggers (2026-06-26, see
[watchlist-2026.md](../watchlist-2026.md)), but the principle stands: do not trust
cache contents produced by untrusted events, and never cache secrets.

## Safe patterns

| Need | Safe approach |
| --- | --- |
| Label / comment on a fork PR | `pull_request_target` **without** checking out fork code — use only event metadata, treat all fields as untrusted (no interpolation into `run:`) |
| Build/test fork code | `pull_request` (read-only token, no secrets) |
| Two-phase: untrusted build → trusted deploy | Untrusted work in `pull_request`; pass artifacts to a separate trusted `workflow_run` that does **not** re-checkout fork code |
| Use event text in a script | Assign to an `env:` var, then reference `"$VAR"` — never inline `${{ ... }}` into `run:` |
| Minimize blast radius | `permissions: {}` at top; grant the least per job; require approval for first-time contributors' workflow runs |

## Checklist

- [ ] No `checkout` of fork code under `pull_request_target` / `workflow_run`
- [ ] `allow-unsafe-pr-checkout` is **absent** (or a documented, isolated exception)
- [ ] No untrusted `${{ ... }}` interpolated into `run:` (use `env:` indirection)
- [ ] `permissions: {}` default; least privilege per job
- [ ] No secrets exposed to jobs that touch untrusted input
- [ ] zizmor runs on the repo's own workflows (catches these patterns)

---
Last verified: 2026-07-04
