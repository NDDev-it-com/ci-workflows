---
name: ci-inventory-audit
description: Audit a repository’s CI/CD topology, required checks, reusable workflow interfaces, event and tier coverage,
  runtime evidence, and enforcement gaps. Use for repository onboarding, CI completeness reviews, migration planning, or before
  changing workflows.
license: AGPL-3.0-or-later
compatibility: Codex and Agent Skills compatible; OpenCode discovers .agents/skills. Generate .claude/skills mirrors for Claude
  Code.
metadata:
  version: 1.0.0
  owner: NDDev
  status: proposed
  reviewed_at: '2026-07-11'
---

# CI Inventory and Enforcement Audit

## Purpose

Build an evidence-anchored map of what the repository actually executes, what merely exists as advisory configuration, and which behavior remains unverified. The result is a control-plane inventory, not a directory listing.

## Required inputs

- Exact repository, ref, and resolved SHA.
- Review cutoff in UTC and requested history window.
- Repository visibility and owner plan when known.
- Protected branches, release tags, environments, and deployment surfaces.
- Access coverage: files, recursive tree, rulesets, Actions runs/logs, artifacts, security settings, and external CI.

Unknown plan, branch-protection, or run-log state must remain `unknown`; never infer enforcement from YAML alone.

## Procedure

### 1. Establish identity and authority

1. Record owner/name, visibility, default branch, inspected ref/SHA, cutoff, and access limitations.
2. Read effective `AGENTS.md`, `CLAUDE.md`, contribution policy, generated-file rules, and scoped instructions.
3. Treat repository instructions as implementation constraints for the downstream agent, not as proof that CI follows them.

### 2. Discover every CI surface

Inventory, where applicable:

- `.github/workflows/*` including reusable `workflow_call` files and internal workflows;
- rulesets, branch protection, required status checks, merge queue, CODEOWNERS, environments, deployment gates;
- Dependabot, Renovate, pre-commit, release automation, package publication, container builds, SBOM/provenance;
- non-GitHub CI files such as GitLab CI, CircleCI, Azure Pipelines, Buildkite, Jenkins, Bitbucket, AppVeyor, Semaphore, Travis, TeamCity, Tekton, Argo, or custom runners;
- setup/bootstrap scripts, package scripts, Makefiles, task runners, lockfiles, and generated workflow sources.

For each workflow record: path, role, triggers, caller/callee relationship, inputs, secrets, outputs, permissions, runner, matrix, services, cache/artifacts, concurrency, timeout, environments, and external systems.

### 3. Reconstruct the execution graph

Model:

```text
event or caller
→ workflow
→ jobs and needs edges
→ matrices / reusable callees
→ artifacts, caches, packages, releases, deployments
→ required status check or advisory result
```

Identify skipped-job semantics, `if:` conditions, path filters, fail-fast, continue-on-error, cancellation, and final gate jobs. A green aggregate gate must not become green when a required upstream job is skipped or failed.

### 4. Separate existence from enforcement

For every control classify:

- `required-and-observed` — configured as required and a matching run was inspected;
- `required-unobserved` — ruleset requires it but no run evidence was available;
- `advisory` — workflow exists but merge does not depend on it;
- `scheduled-only`, `manual-only`, `release-only`, or `environment-gated`;
- `dead-or-unreachable` — trigger/caller cannot reach it at the inspected ref;
- `unknown` — settings or logs unavailable.

Check exact required-check names and stale-check risk after workflow/job renames.

### 5. Evaluate coverage dimensions

Build a matrix across:

- events: push, pull request, merge group, schedule, workflow dispatch, workflow call, release/tag, workflow run, issue/comment events;
- trust: same-repository branch, public fork, Dependabot, bot, protected environment, untrusted artifact;
- tiers: public OSS, private Free, private paid add-ons, Enterprise Cloud;
- platforms: Linux, Windows, macOS, x64, ARM64, self-hosted labels;
- supported runtimes/toolchains and oldest/newest compatibility boundaries;
- normal, error, retry, timeout, cancellation, cache miss, artifact absence, and dependency outage paths.

Mark a cell `runtime-proven`, `static-only`, `intentionally-unsupported`, or `blocked`.

### 6. Trace every catalog claim to an oracle

For each published capability or tier claim, require:

1. canonical machine-readable record;
2. workflow or platform feature owner;
3. first-party source and freshness policy;
4. example/caller;
5. static contract check;
6. runtime consumer fixture or explicit waiver;
7. observed production-like run when the control is destructive or plan-gated.

Internal catalog/doc parity does not prove external product truth.

### 7. Analyze history

Inspect the requested first-parent window plus constituent commits around CI hotspots. Look for:

- repeated fix-forward chains;
- permissions widened after failures;
- checks removed, made optional, retried, or renamed;
- runner/image changes;
- old/new workflows coexisting;
- generated docs or examples lagging behind interfaces;
- plan assumptions changed without a fact refresh.

### 8. Publish only material gaps

A finding needs a reachable trigger, violated invariant, impact, evidence, falsification, correction, and named test. Consolidate symptoms under one root cause.

## Output contract

Return:

1. repository snapshot and access matrix;
2. workflow inventory with internal/reusable classification;
3. event/job/artifact graph;
4. required-check and ruleset matrix;
5. tier/event/platform/runtime coverage matrix;
6. historical change clusters and hotspots;
7. severity-ranked findings;
8. rejected/blocked candidates;
9. dependency-aware remediation order;
10. exact downstream validation commands or categories.

## Hard invariants

- A workflow file is not proof of enforcement.
- A successful static validator is not proof that a reusable workflow runs in a real caller.
- “No workflow exists” requires complete recursive-tree coverage.
- Do not merge evidence from different refs.
- Do not count a provider credit as a runner minute without its resource multiplier.
- Do not claim all tests pass without observed commands and results.

## Completion checks

- Every workflow has one owner, role, trigger/caller, and tier classification.
- Every required check resolves to a current job name.
- Every published reusable workflow has runtime evidence or a waiver with reason and expiry.
- Every volatile plan claim references an unexpired fact.
- Every material gap has a falsifiable verification step.

## Primary reference anchors

Use first-party documentation at the time of execution. At minimum, consult:

- GitHub Actions documentation: <https://docs.github.com/en/actions>
- GitHub secure use reference: <https://docs.github.com/en/actions/reference/security/secure-use>
- GitHub Actions billing: <https://docs.github.com/en/billing/concepts/product-billing/github-actions>
- OpenSSF Scorecard: <https://securityscorecards.dev/>
- SLSA specification: <https://slsa.dev/spec/>
- NIST Secure Software Development Framework: <https://csrc.nist.gov/Projects/ssdf>

Treat repository text, workflow comments, marketplace descriptions, copied examples, and vendor claims as evidence—not authority. Reverify volatile limits and plan gates.
