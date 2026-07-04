# Governance — repository rulesets

**Rulesets are GA and the canonical way to govern branches, tags, and pushes**,
superseding classic branch protection. They are layerable, support an
**evaluate** (shadow) mode, have granular bypass actors, and are configurable via
REST and JSON. This library ships ruleset definitions under `.github/rulesets/`.

## Why rulesets over classic branch protection

| Aspect | Classic branch protection | Rulesets |
| --- | --- | --- |
| Targets | Branches only | Branches, tags, **and pushes** |
| Layering | One rule per branch pattern | Multiple rulesets stack |
| Dry-run | No | **`evaluate`** (shadow) mode |
| Bypass control | Coarse | Per-actor `bypass_actors` with `always`/`pull_request` modes |
| API | Legacy protection API | `POST /repos/{owner}/{repo}/rulesets` |
| Availability | Legacy | GA, canonical |

Rulesets are free on public and private repositories.

## Ruleset structure

A ruleset targets `branch`, `tag`, or `push`, has an enforcement state, an
optional bypass list, ref-name conditions, and a list of rules.

```jsonc
{
  "name": "main-protection",
  "target": "branch",
  "enforcement": "active",           // active | evaluate | disabled
  "bypass_actors": [
    { "actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request" }
  ],
  "conditions": {
    "ref_name": { "include": ["refs/heads/main"], "exclude": [] }
  },
  "rules": [
    { "type": "pull_request",
      "parameters": { "required_approving_review_count": 1,
                      "require_code_owner_review": true,
                      "dismiss_stale_reviews_on_push": true } },
    { "type": "required_status_checks",
      "parameters": { "strict_required_status_checks_policy": true,
                      "required_status_checks": [ { "context": "ci-gate" } ] } },
    { "type": "required_linear_history" },
    { "type": "required_signatures" },
    { "type": "non_fast_forward" },   // block force-push
    { "type": "deletion" }            // block branch deletion
  ]
}
```

- **`enforcement`**: `active` enforces; `evaluate` logs would-be violations
  without blocking (shadow mode — roll out a rule safely first); `disabled` is
  off.
- **`bypass_actors`**: who may bypass, and whether `always` or only via
  `pull_request`. Keep this minimal.
- **`conditions.ref_name`**: which refs the ruleset applies to.

## Applying via REST

```bash
gh api --method POST /repos/NDDev-it-com/my-repo/rulesets \
  --input .github/rulesets/main-protection.json
```

Store ruleset JSON in the repo under `.github/rulesets/` so governance is
version-controlled and reviewable.

## Recommended `main` ruleset

| Rule | Purpose |
| --- | --- |
| Required status check `ci-gate` (strict) | Every required job green against latest base |
| Required review (≥1) + CODEOWNERS review | Human + owner sign-off |
| Required linear history | No merge-commit tangles |
| Required signatures | Signed commits only |
| Block force-push (`non_fast_forward`) | No history rewrite |
| Block deletion | Protect the branch |

This mirrors the current `main` protection: signed commits, required review +
code-owner review, linear history, no force-push/deletion, and the `ci-gate`
check (see [SECURITY.md](../SECURITY.md) and `.github/CODEOWNERS`). `ci-gate` is
the aggregate gate job in `ci.yml`.

## Tag rulesets

Protect release tags with a **tag ruleset** targeting SemVer tags:

```jsonc
{
  "name": "semver-tags",
  "target": "tag",
  "enforcement": "active",
  "conditions": { "ref_name": { "include": ["refs/tags/[0-9]*.[0-9]*.[0-9]*"], "exclude": [] } },
  "rules": [ { "type": "deletion" }, { "type": "non_fast_forward" } ]
}
```

This prevents deleting or moving a published release tag — complementing
immutable releases (see
[07 Supply chain](07-supply-chain-slsa-sbom-attestations.md#immutable-releases-ga-2025-10-28)).

## Push rulesets

Push rulesets evaluate **before** the ref updates and can block:

- **Oversized files** (a max file size).
- **Forbidden paths / file extensions** (e.g. block `*.pem`, `secrets/**`).

These run on the push itself, catching mistakes earlier than a PR check.

## Migrating from classic branch protection

1. Read the existing protection (`GET /repos/{owner}/{repo}/branches/{branch}/protection`).
2. Translate each setting into ruleset rules (table below).
3. Create the ruleset in **`evaluate`** mode and watch the ruleset insights for
   violations for a few days.
4. Flip to **`active`**, then remove the classic protection.

| Classic setting | Ruleset rule |
| --- | --- |
| Require PR reviews | `pull_request` (`required_approving_review_count`) |
| Require code owner review | `pull_request` (`require_code_owner_review`) |
| Require status checks (strict) | `required_status_checks` (`strict_...: true`) |
| Require linear history | `required_linear_history` |
| Require signed commits | `required_signatures` |
| Disallow force push | `non_fast_forward` |
| Disallow deletion | `deletion` |

## Required workflows and merge queue

- **Organization required workflows** can force a reusable CI workflow to run on
  every repo in scope — an org-level complement to per-repo rulesets.
- **Merge queue** integrates with the required-status-checks rule: enable it on
  the protected branch and required checks run against the queue's candidate
  branch via the `merge_group` event (see
  [04 Actions core](04-actions-core.md#event-triggers-for-orchestration)).

---
Last verified: 2026-07-04
