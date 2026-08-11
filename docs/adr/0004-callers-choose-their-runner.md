# ADR 0004: The caller chooses its runner, never the library

Status: Accepted

Date: 2026-08-10

## Context

A cost optimisation gave 39 of 46 reusable workflows `inputs.runner.default:
'amsterdam'` — the NDDev private self-hosted label — inside a **public** library
that external repositories consume.

A default is a property of the pinned commit, not of the caller. Two failure
modes follow, and neither leaves a diff in the consuming repository:

- outside this estate the label resolves to nothing, so the job queues against a
  runner that will never appear;
- inside it, on a public repository, `pull_request` executes untrusted fork code,
  and inheriting the default routes that code onto a trusted persistent fleet.

`check_workflow_contracts.py` already enforced explicit hosted runners — but only
for this repository's own self-calls. Nothing extended the rule to the surface
published to consumers, and 36 example jobs plus eight callers in a public
consumer repository inherited the estate label. That consumer was safe only
because it pinned an older commit whose default was still hosted; a routine
Dependabot bump would have flipped it.

## Decision

- Every example outside `examples/nddev/` states its runner explicitly, and
  `check_examples.py` fails any that leaves a non-hosted default implicit. It
  resolves the referenced reusable's actual default rather than pattern-matching.
- `examples/nddev/` is exempt: it is estate-specific by name and may name the
  fleet.
- Consuming repositories carry the rule in their own instruction docs, because
  the library cannot enforce anything in a repository it does not own.
- `github-actions-security` gains the doctrine: audit the runner a caller
  *inherits*, not only the one it declares, and diff `inputs.runner.default`
  across the two commits when reviewing a pin bump.

## Consequences

- The estate default was left in place at the time. Flipping it would have
  silently moved ~10 private callers onto metered hosted runners, which is a cost
  decision the library may not make for its consumers, so the rule closed the
  exposure at the caller and the generic contract stayed wrong-by-default.

  **Superseded 2026-08-12: the fleet no longer exists.** The estate moved to its
  own GitHub App for CI and the `amsterdam` label was retired. That voids the
  objection — there is nothing to move those callers *off*, and a default naming
  a retired label is not merely wrong-by-default but broken: the first failure
  mode above, a job queuing forever against a runner that will never appear, is
  now what every caller relying on the default actually gets. All 39 defaults
  moved to `ubuntu-latest`.

  The decision itself is unchanged and is the reason the migration was one edit:
  because callers were already required to name their runner, no example and no
  consumer that followed the rule depended on the default at all.
- A public repository on a persistent self-hosted fleet stays out of policy
  regardless of this rule. Making that safe needs ephemeral runners or fork-PR
  approval for all external contributors, neither of which this library controls.
- The same trap exists in the platform API: a `PATCH` to code-scanning default
  setup that omits `runner_type` resets it to `standard`, silently moving a
  private repository off the fleet. Send the field on every write.
