# Contributing

Thanks for helping harden the NDDev CI/CD supply chain. This repository ships
**reusable GitHub Actions workflows** consumed across the estate by full commit
SHA. A workflow here is a security-critical dependency for every caller, so the
bar for changes is deliberately high.

By contributing you agree to the [Code of Conduct](CODE_OF_CONDUCT.md) and to
license your contribution under [AGPL-3.0-or-later](LICENSE).

- **Security vulnerabilities are never contributions.** Do not open a public
  issue or PR. Report privately via GitHub Security Advisories — see
  [SECURITY.md](SECURITY.md).

## Ways to contribute

- **Propose a new reusable workflow or capability** — open a
  [Workflow request](https://github.com/NDDev-it-com/ci-workflows/issues/new?template=workflow_request.yml)
  first. Describe the capability, which tier(s) it targets
  (public / private-free / private-paid), the underlying tools, the motivation,
  and the security considerations. Agreeing on scope and tier before code avoids
  wasted work.
- **Report a bug** in an existing workflow — use the
  [Bug report](https://github.com/NDDev-it-com/ci-workflows/issues/new?template=bug_report.yml)
  form.
- **Flag a pinned tool/action update** — use the
  [Tool update](https://github.com/NDDev-it-com/ci-workflows/issues/new?template=tool_update.yml)
  form (Dependabot already batches most of these).
- **Propose a hardening improvement** — use the
  [Security hardening](https://github.com/NDDev-it-com/ci-workflows/issues/new?template=security_hardening.yml)
  form. This is for defense-in-depth ideas, not vulnerabilities.
- **Fix a docs gap** — use the
  [Docs gap](https://github.com/NDDev-it-com/ci-workflows/issues/new?template=docs_gap.yml)
  form.

## Non-negotiables for every workflow PR

These are enforced by review, the self-CI `ci-gate`, `actionlint`, and `zizmor`.
A PR that misses any of them will not be merged.

1. **Full-SHA action pins with version comments.** Every `uses:` of a
   third-party action pins a 40-character commit SHA followed by a version
   comment, e.g.:

   ```yaml
   uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0  # v7.0.0
   ```

   No tags, no branches, no floating major versions. Dependabot bumps the SHA.
2. **Least-privilege `permissions`.** Start from `permissions: {}` at the top
   level and grant only the exact scopes a job needs (e.g.
   `contents: read`, `security-events: write`). Never rely on the default token
   scope.
3. **`concurrency`** on every workflow, to cancel superseded runs, e.g.
   `group: <workflow>-${{ github.ref }}` with `cancel-in-progress: true`.
4. **`timeout-minutes`** on every job. No unbounded jobs.
5. **`persist-credentials: false`** on every read-only `actions/checkout`.
   Only opt in to credential persistence when a later step provably needs to
   push.
6. **No template injection.** Never interpolate `${{ inputs.* }}`,
   `${{ github.event.* }}`, or any other expression directly inside a `run:`
   block. Pass untrusted values through `env:` and reference them as shell
   variables:

   ```yaml
   - env:
       VERSION: ${{ inputs.version }}
     run: |
       set -euo pipefail
       echo "building $VERSION"
       bash -c 'do-something "$VERSION"'
   ```

   `zizmor` will flag `template-injection`; treat that as a hard failure.
7. **Separate paid and private-free contracts.** A workflow available to the
   private-free tier must not reference a paid action or GitHub feature. Split
   SARIF/no-SARIF workflows and public/GHAS runtime hardening at the file
   boundary; never try to disable an action with lifecycle hooks through a
   step-level boolean condition.
8. **Reusable contract.** Every workflow intended for callers must declare
   `on: workflow_call:` and document its inputs in a header comment. The self-CI
   contract job verifies this.
9. **Harden public/GHAS jobs explicitly.** Use
   `step-security/harden-runner` as the unconditional first step with an egress
   policy (`audit` by default, `block` where the endpoint set is known). Do not
   reference it from cross-tier or private-free workflows.

## Local checks

Run these before opening a PR (they mirror the self-CI `ci-gate`):

```bash
# Lint all workflow YAML
actionlint

# Workflow security analysis (regular persona, matches CI)
zizmor --persona regular --min-severity low .github/workflows

# Complete repository contract, catalog, example, and generated-doc checks
python3 scripts/validate_all.py
```

Install validator dependencies with the hash-locked file:

```bash
python3 -m pip install --require-hashes -r requirements-ci.txt
```

Install the tools locally with:

```bash
# actionlint (choose one)
brew install actionlint          # macOS
go install github.com/rhysd/actionlint/cmd/actionlint@latest

# zizmor
pipx install zizmor              # or: uv tool install zizmor
```

## Commits and pull requests

- **Conventional Commits.** Subject lines follow
  `type(scope): summary` (e.g. `feat(workflows): add sbom diff reusable`,
  `fix(zizmor): pin analysis to full sha`). Keep the subject under 100
  characters.
- **Sign off every commit (DCO).** Add a `Signed-off-by:` trailer with
  `git commit -s`, certifying the
  [Developer Certificate of Origin](https://developercertificate.org/).
- **Sign your commits.** `main` requires cryptographically signed commits
  (`git commit -S`, or `git config commit.gpgsign true`). Unsigned commits are
  rejected.
- **Sole authorship.** Do not add `Co-Authored-By:` trailers.
- Fill in the [pull request template](.github/PULL_REQUEST_TEMPLATE.md)
  completely, including the permissions diff and threat-model note when a change
  touches workflow behavior or token scopes.
- Update the README capability table (and `docs/` / `catalog/` where present)
  and add a `CHANGELOG.md` entry under `[Unreleased]`.

## Branch protection and CI

`main` is protected: signed commits, required review plus code-owner review,
linear history, no force-push or deletion, and the required `ci-gate` status
check. All workflow files are owned by [@rldyourmnd](https://github.com/rldyourmnd)
via [CODEOWNERS](.github/CODEOWNERS), so a maintainer review is always required.
Open PRs against `main` from a topic branch; the `ci-gate` check (contract +
actionlint + zizmor) must be green before merge.

## Releases

Releases are tag-driven (`MAJOR.MINOR.PATCH`) and publish an SPDX SBOM,
`SHA256SUMS`, and SLSA build-provenance attestations. Contributors do not tag
releases; the maintainer cuts them.
