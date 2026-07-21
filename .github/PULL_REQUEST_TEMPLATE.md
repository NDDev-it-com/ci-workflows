<!--
Thanks for contributing to ci-workflows.
Every workflow here is a full-SHA-pinned dependency for other repos, so please
complete this checklist. Security VULNERABILITIES must NOT be filed here — use a
private GitHub Security Advisory (see SECURITY.md).
-->

## Summary

<!-- What does this change do, and why? Link the issue it resolves (e.g. Closes #123). -->

## Type of change

- [ ] New reusable workflow / capability
- [ ] Fix to an existing workflow
- [ ] Pinned tool/action version bump
- [ ] Hardening / security posture improvement
- [ ] Docs only

## Threat-model note (required for workflow / permission changes)

<!--
For any change to workflow behavior, token scopes, egress, or which actions run:
what new trust or attack surface does this introduce, and how is it contained?
Write "N/A — docs only" if this PR changes no workflow behavior.
-->

## Permissions diff (required for workflow / permission changes)

<!--
Show the before/after `permissions:` for each affected job. Justify every scope
that is more than `contents: read`. Example:

  release-supply-chain (publish job):
  - contents: read  ->  contents: write   # create GitHub Release
  + id-token: write                        # SLSA provenance (OIDC)
  + attestations: write                    # attest SBOM + archive
-->

## Checklist

- [ ] All third-party actions pinned to a **full 40-char commit SHA** with a
      `# vX.Y.Z` version comment (no tags/branches).
- [ ] Least-privilege `permissions` (top-level `{}`, per-job minimal scopes).
- [ ] `concurrency` and `timeout-minutes` present on new/changed workflows/jobs.
- [ ] `persist-credentials: false` on all read-only `actions/checkout` steps.
- [ ] No `${{ inputs.* }}` / `${{ github.event.* }}` interpolated inside `run:`
      (passed via `env:` and referenced as shell variables).
- [ ] Paid public/GHAS actions are absent from private-free/cross-tier files;
      SARIF/no-SARIF behavior is split into explicit workflow contracts.
- [ ] `actionlint` passes locally.
- [ ] `zizmor --pedantic` passes locally (no `template-injection` or unpinned
      findings).
- [ ] README capability table and `docs/` / `catalog/` updated (if a workflow
      was added or changed).
- [ ] `CHANGELOG.md` updated under `[Unreleased]`.
- [ ] Commits are signed (`-S`) and signed off (`-s`, DCO); Conventional Commit
      messages.

## Tier impact

<!-- Which billing tiers does this affect? -->

- [ ] Public (free OSS suite)
- [ ] Private free tier (zero-cost only)
- [ ] Private paid tier (GHAS / harden-runner features)
