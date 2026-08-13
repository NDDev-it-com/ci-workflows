# Observability and analytics

## Evidence orchestration

Runtime evidence selection is compiled from
[`catalog/evidence-orchestration.yml`](../catalog/evidence-orchestration.yml),
not inferred from job duration or copied fixture lists. The request names its
level (`fast`, `pr-required`, `full`, or `release`), platform, OS,
architecture, operating profile, risk, changed surface, release state, and any
real-host capabilities. Unknown or all-skipped combinations fail closed.

The generated [evidence orchestration ledger](generated/evidence-orchestration.md)
shows every lane and its current evidence boundary. Workflow lanes call existing
reusables. Native disposable-host lanes are explicit downstream handoffs for
reboot, GUI/session, SSH/network, and system-hardening evidence; hosted CI is
not allowed to simulate those claims.

Timing is telemetry only. It may be logged to compare runs, but elapsed duration
never selects, skips, cancels, or fails a lane. The catalog's `operational` and
`durable` evidence classes are intended for OpenObserve retention of 7 and 30
days respectively. They do not set GitHub artifact or log retention, which is a
separate repository/organization/enterprise policy.

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
