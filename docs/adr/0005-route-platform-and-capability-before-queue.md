# ADR 0005: Route platform and machine capability before queueing

Status: Accepted

Date: 2026-08-13

## Context

GitHub chooses a runner from `runs-on` and does not spill a queued self-hosted
job onto a hosted runner. A wrong label is therefore not a slow fallback: the
job can wait forever, or reach a machine that lacks Docker and fail after it has
already consumed queue and provisioning capacity.

ADR 0004 correctly leaves the runner choice to the caller, and PR #117 added a
derived `container-runtime` requirement. The remaining contract was missing:
which operating systems a reusable supports, whether that portability was ever
observed live, and whether an operator class satisfies the workflow before the
caller commits the final label.

## Decision

- `catalog/workflow-routing.yml` lists every reusable exactly once with its
  supported OS set and machine requirements. It contains no private label.
- `catalog/runtime-coverage.yml` may attach `proven_os` only to a current
  `runtime-proven` record. Non-Linux portability is advertised only when every
  advertised non-Linux OS has live `workflow_call` evidence.
- Operator mappings translate `{platform, class}` into a concrete runner and
  backend. The NDDev example maps Linux fast/standard/integration to its private
  fleet, while macOS and Windows map directly to standard GitHub-hosted runners.
- `scripts/check_runner_routing.py` resolves the tuple before dispatch and fails
  closed for an unsupported OS, missing capability, unknown class, hosted/self-
  hosted mismatch, or public repository routed to self-hosted capacity.
- The compiled caller contains the final runner label directly. The resolver is
  an adoption and policy tool, not a routing job: adding a preliminary Actions
  job would itself enter a queue and could not protect that job from bad routing.

## Consequences

- Linux container work cannot use fast or standard capacity; it selects an
  integration route before GitHub sees the job.
- macOS and Windows never enter the Linux fleet queue. A future native macOS
  backend requires a new reviewed operator route and conformance evidence; it
  is not a conditional branch hidden inside the public library.
- Static validation proves the catalog and mapping are internally coherent. It
  does not prove fleet availability or a workflow's runtime behavior. Those
  claims remain in the runtime coverage ledger and in the owning fleet's issue.
