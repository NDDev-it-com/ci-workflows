---
name: ci-consumer-adoption
description: Wire a repository onto the ci-workflows reusable library correctly — pick the tier from visibility and entitlements, pin to a released tag, route the runner, and close the two scanner settings no workflow file can reach. Invoke when adopting, migrating, or auditing a consumer repository, not when editing the library itself.
license: AGPL-3.0-or-later
compatibility: Codex and Agent Skills compatible; OpenCode discovers .agents/skills. Generate .claude/skills mirrors for Claude Code.
metadata:
  version: 1.0.0
  owner: NDDev
  status: proposed
  reviewed_at: '2026-08-01'
---

# Adopting ci-workflows in a consumer repository

This is the *caller* side. For work inside the library itself use
`nddev-repo-flow`.

Adoption is four decisions, in order. Getting them out of order is what produces
the two failure shapes seen in practice: a repository that looks configured but
still bills, and a repository that is routed to hardware its jobs cannot use.

## Start by resolving the mode

Do not choose a tier by reading prose. Resolve it:

```bash
.venv/bin/python -I -B scripts/check_python_execution_contract.py --launch resolve_profile.py -- --visibility private --plan enterprise-cloud \
    --code-security --secret-protection --code-quality
```

It returns the matching profile, its controls (CodeQL mode, runner class,
enforcement, release provenance), the fixed and metered cost lines, and the
capability/workflow set split into run / conditional / unavailable, with the
free substitute for everything the mode does not entitle. Adopt that set; the
sections below are how to wire it correctly.

## 1. Tier — from visibility *and* entitlements, never visibility alone

Pick the tier doc first; it decides which reusables are even legal to call:

| Situation | Doc |
| --- | --- |
| public repository | `docs/01-public-oss-free.md` |
| private, no paid security products | `docs/02-private-free.md` |
| private, Advanced Security held | `docs/03-private-paid-ghas.md` |
| an estate that already owns the paid products | `docs/17-nddev-tier.md` |
| Code Quality (orthogonal to all of the above) | `docs/16-code-quality.md` |

The trap: the generic model treats *private* as the degraded case, so a private
repository inside an estate that already pays for the paid products gets
configured down to the free tier and quietly discards capability that is already
bought — most visibly by releasing through `release-supply-chain-free.yml` when
`release-supply-chain.yml` would attest. Check entitlements before believing a
tier table. Prices and quotas live in `catalog/product-facts.yml`; never quote
them from memory or from a skill.

## 2. Pin — to a released tag, by full SHA

Reference reusables as `NDDev-it-com/ci-workflows/.github/workflows/<file>@<40-hex>`
with a trailing comment naming the release. Pin to a commit that a release tag
points at, not to whatever `main` happens to be: tags in this library are
immutable and protected, `main` is not, and an estate pinned to arbitrary commits
cannot answer "what version are we on".

Audit for drift across an estate by collecting the unique pinned SHAs per
repository. More than one distinct pin inside a single repository is always a
defect; several distinct pins across an estate means upgrades have been landing
per repository rather than per release.

The library was renamed once. A reference to the old name still resolves through
GitHub's rename redirect, which is not a dependency worth keeping — if the
redirect lapses or the old name is reclaimed, every caller stops resolving.
Repoint rather than rely on it.

## 3. Runner — by visibility, and it is not one setting

Minutes are free and unlimited on public repositories and metered on private
ones, so the cost-optimal routing is the inverse of "use our own hardware
everywhere":

- **public → GitHub-hosted.** A self-hosted runner reachable from a public
  repository is a remote-code-execution path: a forked pull request runs
  attacker-controlled code on your machine. This is a security defect, not a
  saving. Never ship a self-hosted label as a default in an example.
- **private → self-hosted label**, passed by the caller through the `runner`
  input.

Then close the two settings that **no workflow file can reach**, because GitHub
schedules them itself:

| Scan | Where the runner is chosen |
| --- | --- |
| CodeQL *default setup* | `PATCH /repos/{owner}/{repo}/code-scanning/default-setup` with `runner_type: labeled` |
| Code Quality | `PATCH /repos/{owner}/{repo}/code-quality/setup` with `runner_type: labeled`, `runner_label` — or repository settings → Code quality → *Labeled runner* |

Miss either and the repository keeps consuming metered minutes while every
caller in the tree claims otherwise. Full mechanics:
`docs/05-runners.md#visibility-routing`.

There is **no** automatic spillover from a self-hosted label to a hosted runner.
A job whose label is busy queues until a runner frees. Size the fleet so
queueing is rare; a "fallback" to hosted runners on a private repository would
silently reintroduce the metered minutes you just moved off.

## 4. Prove it on the runner you actually chose

A saved setting is not evidence. Two failure classes only appear on a real run:

- **Privilege.** Reusables that install a pinned tool must write somewhere the
  job user owns. A correctly isolated self-hosted runner is unprivileged, so a
  step that installs into a system path fails there while passing on hosted
  runners. If you hit this, fix the workflow's destination — granting the runner
  account write access to system paths trades isolation for convenience and
  makes every subsequent job share mutable state.
- **Toolchain.** Hosted images ship a large preinstalled toolchain; a
  self-hosted host ships whatever you put on it.

Verify by reading the job's `runner_name` and `runner_group_name` from the
completed run, not by re-reading the setting you just wrote.

## Cost controls that belong to the consumer, not the library

- **Code Quality AI findings are metered separately from the licence, with no
  included allowance.** Leave them off unless the credit burn has been sized for
  that specific repository. A product budget cannot fence them off, because the
  budget must leave headroom for the licence accruing under the same SKU — the
  per-repository switch is the only real control. Where CodeQL finds no
  supported language the switch is absent entirely, which is a stronger
  guarantee than "off" and is not a gap to fix.
- **Artifact retention drives storage spend and is not blocked by spend budgets.**
  Keep it short and purge accumulated artifacts; budgets stop compute, not
  storage.

## Checklist

1. Tier chosen from visibility **and** verified entitlements.
2. Every reusable reference pinned by full SHA to a released tag; one pin per repository.
3. No reference to the pre-rename library name.
4. `runner` input set on private callers; absent on public ones.
5. CodeQL default setup and Code Quality both routed for private repositories.
6. A completed run inspected for `runner_name`, not just a saved setting.
7. AI findings off unless deliberately sized.
8. Release caller matches entitlement — attested where the plan allows it.
