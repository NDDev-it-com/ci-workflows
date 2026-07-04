# Observability and analytics

CI is only trustworthy if you can see how it behaves over time. This doc covers
Actions performance metrics, job summaries, failure/queue signals, and audit log
streaming.

## Actions performance metrics

The organization and repository **Actions → Performance / Usage metrics** views
report, per workflow and job:

- Total runs, success/failure counts, and **failure rate**.
- **Queue (wait) time** before a job starts on a runner.
- **Run duration** and minute consumption by runner type.

Watch failure rate for flaky jobs and queue time for runner-capacity pressure
(especially on private repos with limited concurrency or self-hosted fleets, see
[05 Runners](05-runners.md)).

## Job summaries (`$GITHUB_STEP_SUMMARY`)

Write Markdown to `$GITHUB_STEP_SUMMARY` to render a rich summary on the run
page — far more useful than scrolling logs.

```bash
{
  echo "## Validation summary"
  echo "| Check | Result |"
  echo "| --- | --- |"
  echo "| lint | ✅ |"
  echo "| tests | ✅ 128 passed |"
} >> "$GITHUB_STEP_SUMMARY"
```

Use summaries for release manifests, scan counts, coverage, and gate results so
the outcome is visible without opening step logs.

## Failure rate and queue time in practice

| Signal | What it tells you | Action |
| --- | --- | --- |
| Rising failure rate on one job | Flaky test or drifting dependency | Quarantine/fix; check Dependabot PRs |
| High queue time | Runner starvation / concurrency limits | Add runners, trim matrix, tune `concurrency` |
| Long duration growth | Cache misses, larger builds | Review cache keys, split jobs |

## Audit log and event streaming

The **audit log** records administrative and security-relevant events (ruleset
changes, secret creation, permission changes, workflow runs on protected refs).
Organizations can enable **audit log streaming** to an external SIEM
(e.g. object storage or a log platform) for retention and alerting beyond the
in-app window.

Pair audit streaming with:

- Ruleset change events (see [08 Governance & rulesets](08-governance-rulesets.md)).
- Security alert events from code/secret scanning (see
  [06 Security scanning](06-security-scanning.md)).

Together these give a durable, queryable record of who changed governance and
what CI did on protected branches.

---
Last verified: 2026-07-04
