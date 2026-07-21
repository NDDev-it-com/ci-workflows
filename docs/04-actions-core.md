# Actions core — reusable workflows, permissions, and orchestration

This doc covers the GitHub Actions primitives the library is built on: reusable
workflows, event triggers that matter for orchestration, the permissions model
(including the reusable-caller cap gotcha), concurrency, matrix, cache,
artifacts, and environments.

## Reusable workflows (`workflow_call`)

A reusable workflow declares `on: workflow_call` and is invoked from a caller
job via `uses:`. This library ships reusables; consumers write thin callers.

```yaml
# reusable (in this library)
on:
  workflow_call:
    inputs:
      runner: { type: string, default: 'ubuntu-latest' }
    secrets:
      token: { required: false }
```

```yaml
# caller (in your repo)
jobs:
  lint:
    permissions: { contents: read }
    uses: NDDev-it-com/ci-workflows/.github/workflows/actionlint.yml@<full-sha>
```

Rules that matter:

- A caller references a reusable at the **job** level with `uses:` — it cannot
  add `steps` to that job.
- Pin the reference by **full commit SHA**.
- Secrets are not inherited automatically; pass them explicitly or use
  `secrets: inherit`.
- Reusable nesting is limited (a caller chain has a maximum depth), so keep
  composition shallow.

This repo's own `ci.yml` enforces a contract: every shipped reusable must
declare `on: workflow_call`.

<a id="reusable-caller-permissions-cap"></a>
## Permissions — least privilege and the caller cap gotcha

Set `permissions: {}` at the top of every workflow and grant the minimum per
job. The default `GITHUB_TOKEN` should have no more scope than a job needs.

**The gotcha:** a caller cannot grant a reusable *more* permission than the
caller job itself has, and the caller job **must grant every permission the
reusable job declares**. `GITHUB_TOKEN` permissions can only be *reduced* down
the call chain, never expanded. If the reusable's job declares
`security-events: write` but the caller job omits it, the run **fails at
startup** — before any step executes — with a permissions error.

```yaml
# CORRECT — caller grants what the reusable needs
jobs:
  codeql:
    permissions:
      actions: read
      contents: read
      security-events: write   # required by public-codeql.yml
    uses: NDDev-it-com/ci-workflows/.github/workflows/public-codeql.yml@<full-sha>
```

Each reusable in this library documents its required permissions in its header;
mirror them in the caller job. Common mappings:

| Reusable | Caller job must grant |
| --- | --- |
| `public-codeql.yml` | `actions: read`, `contents: read`, `security-events: write` |
| `zizmor-sarif.yml` | `contents: read`, `security-events: write` |
| `public-scorecard.yml` | `security-events: write`, `id-token: write`, `contents: read`, `actions: read` |
| `public-scorecard-json.yml` | `id-token: write`, `contents: read`, `actions: read` |
| `public-dependency-review.yml` | `contents: read`, `pull-requests: write` |
| `release-supply-chain.yml` | `contents: write`, `id-token: write`, `attestations: write`, `artifact-metadata: write` |
| lint / smoke / static | `contents: read` |

## Event triggers for orchestration

- **`workflow_run`** — triggers a workflow after another completes. Runs in the
  base-repo context with write token access, so it is a privileged event: never
  check out untrusted fork code in it (see
  [security/pull-request-target.md](security/pull-request-target.md)).
- **`merge_group`** — fires for the **merge queue**. A queue builds a temporary
  candidate branch combining queued PRs and runs required checks against it
  before merging, preventing "green PR, red main" races. Required status checks
  for the queue are configured in rulesets/branch protection.
- **`pull_request` vs `pull_request_target`** — `pull_request` runs with a
  read-only token in the fork context; `pull_request_target` runs privileged in
  the base context. Prefer `pull_request`.

## Concurrency

Cancel superseded runs and serialize releases with a `concurrency` group.

```yaml
concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true     # false for releases — never cancel a publish
```

## Matrix

Fan out across dimensions. Use `fail-fast: false` when you want every leg's
result even if one fails (as in the CodeQL language matrix and the OS smoke
matrix).

```yaml
strategy:
  fail-fast: false
  matrix:
    os: ${{ fromJSON(inputs.os_list) }}
```

## Cache

`actions/cache` speeds up dependency installs. Two cautions:

- Cache keys are a trust boundary — a poisoned cache from an untrusted trigger
  can affect later runs. GitHub now issues a **read-only cache token** for
  untrusted triggers (2026-06-26) — see [watchlist-2026.md](watchlist-2026.md).
- Never cache secrets or credentials.

## Step-level parallel execution

GitHub introduced step-level parallel execution in public preview on
2026-06-25 (`background`, `wait`, `wait-all`, `cancel`, and `parallel`). Treat it
as a performance and ergonomics feature, not a default for canonical templates:

- keep reusable workflows sequential unless parallelism materially reduces wall
  clock time;
- avoid shared mutable files between parallel steps;
- document artifact/cache/log ordering assumptions before adopting it.

The catalog entry is `step-level-parallel-execution`.

## Artifacts

`actions/upload-artifact` / `download-artifact` move files between jobs and
persist build output. Set `retention-days` deliberately. Release artifacts in
this library are attested (see
[07 Supply chain](07-supply-chain-slsa-sbom-attestations.md)) and short-retained
because the immutable Release is the durable store.

## Environments

Environments gate deployment jobs with protection rules (required reviewers,
wait timers, branch/tag restrictions) and scope secrets/variables to a named
stage. Covered in [10 Deployments & environments](10-deployments-environments.md).

---
Last verified: 2026-07-04
