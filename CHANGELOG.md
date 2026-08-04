# Changelog

## [Unreleased]

### Added

- **Personal-account consumer tier.** A repository owned by a *personal* GitHub
  account (not an organization) inherits the private-free posture but cannot
  reach an org-level self-hosted runner group — it needs a **repo-level**
  runner registration and a caller that routes every job to that label. New
  [docs/18-personal-account-tier.md](docs/18-personal-account-tier.md) records
  the runner-registration procedure (org-runner vs repo-runner reachability is a
  platform gate, not a setting), the inversion against [02 private-free], and
  the **trigger caveat**: cross-owner reusable workflows do not resolve jobs for
  `push` events to the default branch of a personal-account repo (verified
  empirically — `pull_request` works, `push` hangs in `pending` with zero jobs).
  New [examples/personal/security-selfhosted.yml](examples/personal/security-selfhosted.yml)
  is the private-free stack (gitleaks, actionlint, zizmor-no-SARIF) with a
  `runner:` input on every call and `pull_request`-only triggers. No catalog or
  workflow file changed — the capability set is identical to private-free; only
  the runner and trigger differ.

## [0.13.3] - 2026-08-03

### Added

- **`cross-platform-smoke.yml` grew an `install_command` input.** It was the
  only reusable that runs a caller command across an OS matrix without any way
  to install that command's dependencies first — `private-static.yml` has had
  `install_command` all along. Callers worked around it by chaining the
  installer onto `linux_command` and `macos_command` separately, which
  duplicates the install in every override and reports a broken install as a
  smoke failure. The new step runs before the smoke command on every OS in the
  matrix, is skipped when empty, and takes its value through `env` like every
  other caller-supplied string here. It is deliberately not per-OS: a caller
  needing genuinely different install steps should branch inside its command.

### Fixed

- **`pr-hygiene.yml`'s `pr-title` job never declared the `pull-requests: read`
  it needs.** `amannn/action-semantic-pull-request` fetches the pull request it
  validates through `GET /repos/{owner}/{repo}/pulls/{number}`, so the job needs
  `pull-requests: read`; the neighbouring `labeler` job correctly declares
  `pull-requests: write` and this one was missed. Every run failed with
  `Resource not accessible by integration`, observed on `github-device-sync`.

  A caller cannot grant a reusable more than the reusable declares, so no
  consumer could work around it — the caller in `github-device-sync` already
  declared `pull-requests: write` and still failed. This is the same defect
  class as the `zizmor-sarif.yml` `actions: read` fix in `0.13.2`.

  The failure had previously been read as a Dependabot-token problem and worked
  around by skipping Dependabot pull requests; that workaround hid a bug that
  affected every pull request. Reusable, catalog, and the caller example now
  declare the scope.

### Security

- **`checkout_ref` delegated its own safety rule to prose.**
  `private-static.yml` and `cross-platform-smoke.yml` are the only two
  reusables that let the caller choose the checked-out commit. That is correct
  on `pull_request`, where the job runs with a read-only token and no secrets,
  and unsafe on a privileged event such as `pull_request_target` or
  `workflow_run`, where the job holds the caller's write token and secrets and
  the checkout would execute untrusted code with them. The rule existed only as
  a sentence in the risk notes and in three dismissed code-scanning alerts —
  nothing enforced it, and nothing stopped a consumer from getting it wrong.

  Both workflows now open with a fail-closed guard step. A reusable workflow
  inherits the caller's `github` context, so `github.event_name` is the event
  that triggered the *calling* run; the guard refuses to proceed when a
  privileged event (`pull_request_target`, `workflow_run`, `issue_comment`,
  `issues`, `discussion`, `discussion_comment`) supplies a non-empty
  `checkout_ref`. It is the first step in the job, has no opt-out input, and
  reads both values through the environment, so no step runs before the
  refusal. A privileged caller that supplies no `checkout_ref` is untouched —
  the default checkout of the base repository stays legitimate.

  New `scripts/check_privileged_ref_guard.py` (wired into `validate_all` as
  `privileged-ref-guard`) discovers every workflow exposing `checkout_ref`,
  asserts the guard is the first step of every checking-out job, and then
  **executes** the extracted guard body against the full privileged/safe event
  matrix — so the contract is proven by behaviour, not by pattern matching. A
  future reusable that adds `checkout_ref` without the guard fails the gate.

### Documentation

- **Eight files told agents `main` was squash-merge-only; it has not been.**
  The declared ruleset `.github/rulesets/branch-main.json` sets
  `"allowed_merge_methods": ["merge"]`, and the live repository settings agree
  (`allow_squash_merge: false`, `allow_rebase_merge: false`,
  `allow_merge_commit: true`) — merge commits are the only permitted method,
  matching the estate-wide atomic-commit policy. `README.md`, `SECURITY.md`,
  `AGENTS.md`, `.claude/CLAUDE.md`, `docs/08-governance-rulesets.md`, and the
  `nddev-change-flow` / `nddev-release-flow` skills all still described the
  opposite, sending every agent that read them toward a merge method the
  repository rejects. Corrected in the authored sources and remirrored into
  `.claude/skills/`.

## [0.13.2] - 2026-08-01

### Fixed

- **`zizmor-sarif.yml` never declared the `actions: read` its SARIF upload
  needs.** `github/codeql-action/upload-sarif` reads the workflow run, so it
  requires `actions: read`; `public-codeql.yml` — the other SARIF uploader here —
  declares it, and this one did not. The incomplete set had propagated into
  `catalog/capabilities.yml` and all four examples that call it. Consumers saw
  the scan succeed and the upload fail with `Resource not accessible by
  integration`; observed on `github-device-sync`, red since adoption. Reusable,
  catalog, examples and this repository's own `ci.yml` caller now declare the
  same set.

  A caller cannot grant a reusable less than the reusable declares, so the token
  comes from the *called* workflow: a consumer cannot work around this by adding
  the permission to its own caller — it needs a release carrying the fix.


### Added

- **`public-scorecard.yml` was the only reusable without a copy-paste example.**
  `examples/public-oss/scorecard.yml` covered the JSON variant only, so the
  SARIF-uploading variant — the one that needs `security-events: write` and
  turns Scorecard findings into persistent code-scanning alerts — had no
  validated caller. Adds `examples/public-oss/scorecard-sarif.yml`, including
  the reason to pick one variant over the other and the shared trigger
  constraint. Every reusable now has an example.


## [0.13.1] - 2026-08-01

### Fixed

- **Five reusables were self-applied but still recorded as `unverified`.** When
  `codeql.yml`, `gitleaks.yml`, `dependency-review.yml`, and `scorecard.yml` were
  added as self workflows calling their reusables through relative refs, the
  runtime-coverage ledger was never updated to match — so the repository was
  proving these workflows on every push while the ledger claimed no observed run
  existed. Promoted to `runtime-proven` against runs that executed the current
  bytes: `public-codeql.yml`, `secret-scan.yml`, `public-scorecard-json.yml`,
  `zizmor-sarif.yml`, `public-dependency-review.yml`. Runtime-proven entries go
  from one to six.

  Nothing was promoted on estate evidence, although consumer repositories did run
  several of these today: every such run executed an older pinned revision, and a
  proof is only valid for the bytes it exercised. That tension is structural — a
  dependency bump invalidates a proof — which is why sustainable coverage comes
  from self-calling fixtures rather than from opportunistically harvesting
  consumer runs.

### Added

- **New skill `ci-consumer-adoption`.** The skill set covered authoring and
  operating the library but nothing about wiring a *consumer* repository onto
  it, which is where the two observed failure shapes live: a repository that
  looks configured but still bills, and a repository routed to hardware its jobs
  cannot use. Covers tier selection from entitlements rather than visibility
  alone, pinning to a released tag by full SHA, runner routing by visibility,
  the two managed scans no workflow file can reach, and proving the routing from
  a completed run's `runner_name` instead of a saved setting.

### Changed

- `ci-cost-performance` gains the visibility-routing rule and its corollaries:
  self-hosting pays only where minutes are metered, moving public work onto own
  hardware buys a fork-PR execution path rather than a saving, platform-scheduled
  scans carry their own runner control, there is no spillover from a busy
  self-hosted label to a hosted runner, and an isolated self-hosted runner is
  unprivileged so system-path installs fail there.

## [0.13.0] - 2026-08-01

### Added

- **GitHub Code Quality is now a modelled tier instead of an unattached price
  tag.** The product existed in the ledger as `github-code-quality-transition`
  and nowhere else: no capability, no tier doc, no mention in the tier tables —
  so the catalog priced a product it never told adopters how to place. It gets
  `catalog/capabilities.yml` entry `github-code-quality` and a tier doc,
  `docs/16-code-quality.md`.

  It is deliberately **not** folded into the public tier. Re-verification
  against the billing docs on 2026-08-01 established that visibility does not
  gate the licence: a public repository is billed the same per-active-committer
  rate as a private one, and being public only removes the Actions-minutes
  component. That contradicted `docs/01-public-oss-free.md`, which promised the
  "entire security and supply-chain suite for free" — a claim that would have
  been false for any adopter who enabled Code Quality on a public repo. The
  three-tier model sorts by visibility and plan; this product obeys neither, so
  it is documented as an orthogonal fourth tier and **excluded** from both free
  tiers, with the free maintainability substitutes (`coverage-gate.yml`,
  `docs-quality.yml`, `pr-hygiene.yml`, zizmor, the language packs) named
  explicitly.

  Two further billing facts are now recorded because they invert the usual
  cost-control instinct: committers are counted **once per organization**, so
  enabling one repository already bills the whole active-committer set and a
  "few paid repos, many free repos" split saves nothing unless the committer
  sets actually differ; and the licence is independent of Code Security and
  Secret Protection, so GHAS does not include it and holding both means paying
  two products to drive one CodeQL engine.

  The capability carries `workflow: null` and `example: null`, which is the
  honest shape rather than a gap: Code Quality has no Action, no `workflow_call`
  entrypoint, and no REST or GraphQL API, so enablement is UI-only and cannot be
  pinned by SHA, asserted, or drift-checked from CI. For the same reason the
  merge gate — ruleset rule "Require code quality results", severity threshold,
  check `CodeQL - Code Quality` — is documented as a UI procedure and **not**
  encoded in `.github/rulesets/`: those specs are shaped for
  `POST /repos/{owner}/{repo}/rulesets` and the rule-type identifier for this
  rule is undocumented. `AGENTS.md` records the gate so the next contributor does
  not re-derive it, replacing a stale instruction to "refresh that fact" on a
  date that has passed.

- **The library described GitHub's price list, not this estate's receipts.**
  Every tier doc reasoned from what GitHub charges a hypothetical adopter, so a
  private NDDev repository was configured as if it were on the free plan while
  the organization was already paying for Enterprise Cloud, Code Security,
  Secret Protection, and Code Quality. `docs/17-nddev-tier.md` records the
  verified entitlements and the advice that consequently does not apply.

  The concrete loss this closes: `docs/02-private-free.md` routes private
  releases to `release-supply-chain-free.yml` because Artifact Attestations
  require Enterprise Cloud on private repos. This estate **has** Enterprise
  Cloud, so all 26 private repositories were emitting `slsa_build_level: null`
  and discarding provenance that was already bought. They can use the attested
  `release-supply-chain.yml`.

  Also recorded, because it inverts the usual cost instinct: these products bill
  per active committer counted **once per organization**, so with one committer
  the estate pays the same whether one repository or fifty are enabled — partial
  coverage would have cost identically and protected less. `examples/nddev/`
  joins the aggregate-example allowlist in `validate_catalog.py`, alongside the
  three existing per-tier security suites.

  The doc is explicit about what is *absent* too: Copilot Autofix is unavailable
  (Copilot Business provisioned, zero seats assigned), and SHA pinning is
  unenforced at both org and enterprise (`sha_pinning_required: false`) — flagged
  rather than recommended blindly, since enabling it org-wide would break any
  repository still pinning actions by tag.

### Fixed

- **A grouped action bump could not land on its own.** Dependabot updates the
  `uses:` pins inside the workflows but knows nothing about `catalog/tools.yml`,
  so `validate_catalog.py` failed on seven tools whose catalog pin no longer
  matched the workflow that used it, and `validate_runtime_coverage.py` failed
  because two workflow files changed after the run that proved them. Catalog
  pins and `current_version` synced for `attest`, `checkout`, `setup-python`,
  `setup-go`, `setup-dotnet`, `labeler`, and `markdownlint-cli2-action`.
  `actionlint.yml` is re-proven against the CI run that executed the new bytes —
  this repository's own `ci.yml` calls it through a relative ref, so the proof is
  real. `release-supply-chain.yml` is downgraded to `static-only`: nothing in
  this repository's CI calls it, so no run has executed the new bytes, and the
  ledger's rule is to downgrade rather than carry a stale proof. The next real
  release re-proves it.

- **The catalog recorded four action pins that no workflow used.** `setup-node`,
  `setup-java`, `setup-swift`, and `checkov-action` had drifted a version behind
  the SHA their `used_by` workflows actually reference — `setup-swift` by a full
  major (`v2.4.0` recorded, `v3` shipped). `validate_catalog.py` checked only the
  pin's *shape* and that `used_by` paths existed, never that the pin matched
  reality, so the gate stayed green while the declared source of truth was wrong
  in four places. Pins synced and `validate_catalog.py` now fails when a
  catalog pin does not appear verbatim in each of its `used_by` workflows.
- **`sql-ci.yml` declared a `python_version` input that nothing read.** It was
  the only never-read input across all reusables; the workflow has no
  `setup-python` step at all and provisions Python through `setup-uv`. A caller
  passing it got a silently ignored value. Input removed and the header comment
  corrected from "pinned setup-python" to "pinned setup-uv".
- `docs/12-community-dx.md` listed five community-health files as still missing;
  all five have shipped. Only the optional `.github/FUNDING.yml` remains absent.

### Added

- **Self-application of the public OSS security suite.** This repository shipped
  CodeQL, OSSF Scorecard, Dependency Review, and gitleaks to the estate while
  consuming none of them itself; it self-applied only `actionlint`, `zizmor`,
  and `release-supply-chain`. New self workflows `codeql.yml`, `gitleaks.yml`,
  `dependency-review.yml`, and `scorecard.yml` call the matching reusables
  through relative refs, with triggers taken from this repository's own
  `examples/public-oss/` shapes.

### Fixed

- **`SELF_WORKFLOWS` was duplicated as a literal in three places.**
  `_workflow_yaml.py` held the named constant while `validate_catalog.py` and
  `generate_docs.py` each hardcoded `{"ci.yml", "release.yml"}` again. Both now
  import it. With the constant honoured in only one of the three,
  `validate_all.py` passed while `docs/generated/workflow-inventory.md` listed
  the new self workflows as `MISSING` instead of `internal` — a green gate over
  wrong generated output.

- **Pinned tools installed into `/usr/local/bin`, which no correctly isolated
  self-hosted runner allows.** `actionlint.yml` and `osv-scan.yml` placed their
  checksum-verified binaries in a system path. That works on GitHub-hosted
  runners, where the job user may write there, and fails outright on a
  self-hosted runner whose account is unprivileged:
  `install: cannot create regular file '/usr/local/bin/actionlint': Permission denied`.
  Found by routing a real private-repository job to a self-hosted runner. The
  privilege is not incidental — a runner that *can* write to system paths shares
  mutable state between jobs — so the destination moved rather than the runner's
  permissions: both now install into `"${RUNNER_TEMP}/bin"` and prepend it to
  `GITHUB_PATH`, which is writable on hosted and self-hosted alike and is torn
  down with the job. Checksum verification is unchanged. `cpp-ci.yml` still uses
  `sudo apt-get`; that is a different class (system packages, not one pinned
  binary) and remains hosted-only.

### Documentation

- **No documented rule for which repositories run where.** Private-repository
  minutes are metered and public ones are free, so the cost-optimal routing is
  private → self-hosted, public → GitHub-hosted. `docs/05-runners.md` gains
  `Routing by visibility` with that rule, the fork-PR reasoning that makes a
  self-hosted runner on a public repository a security defect rather than a
  saving, and an explicit statement that **this repository is public** and must
  never route itself to self-hosted or ship a self-hosted default in
  `examples/`.
- **Two runner settings are invisible to workflow files.** CodeQL *default
  setup* and *Code Quality* scans are scheduled by GitHub, not by a workflow,
  and each carries its own runner control. Missing either leaves a repository
  consuming metered minutes while every caller says otherwise. Both are now
  documented with the exact API call and UI path.
- **AI findings were undocumented.** `docs/16-code-quality.md` gains an
  `AI findings` section: they are metered separately from the per-committer
  licence with **no included allowance** (`discountAmount: 0.00` on every
  billing line, $0.01/credit), and one repository burned 774.9 credits in about
  twelve days — roughly twice the licence that covers a whole organization. Also
  records why a product budget cannot fence this off, and that the switch is
  absent entirely where CodeQL finds no supported language.
- `docs/17-nddev-tier.md` gains the verified per-line cost envelope and a runner
  routing summary, and corrects a stale claim: `sha_pinning_required` is now
  **true** at both org and enterprise level, not false.
- New caller example `examples/nddev/security-private-selfhosted.yml` — the
  nddev suite with every job pinned to a self-hosted label.

## [0.12.0] - 2026-07-21

### Changed

- **Repository renamed `nddev-ci-workflows` → `ci-workflows`.** Every active
  and identity surface now uses the new coordinate: release `package_name`,
  all `examples/**` reusable `uses:` refs, README/docs/skills, and the two
  gate-coupled slugs (`check_examples.py` `USES_RE`, `validate_runtime_coverage.py`
  `REPO_SLUG` + `runtime-coverage.yml` run URLs). Consumers must repin reusable
  `uses:` references to `NDDev-it-com/ci-workflows/…` (GitHub does not redirect
  `uses:` across a rename).
- Pin previously-mutable uv/bun tool versions: `semgrep-ci` `semgrep_version`
  default `1.170.0`, `sql-ci` `sqlfluff_version` default `4.2.2`, and the
  `web-ci` default `lint_command` now pins `stylelint@17.14.1` +
  `htmlhint@1.9.2`. Empty/bare versions previously floated to the latest
  release at run time.

### Added

- `check_tool_pinning` validator (wired into `validate_all`): rejects empty
  uv/bun tool-version inputs and bare `uvx`/`bunx <tool>` invocations, keeping
  tool versions as reproducible as the full-SHA action pins.

## [0.11.3] - 2026-07-21

### Changed

- Bump pinned GitHub Actions (Dependabot): setup-node v6->v7, setup-java
  v5.5->v5.6, checkov-action v12.3112->v12.3114, setup-swift v2.4->v3.
- Downgrade iac-scan runtime-coverage to `unverified` after the checkov-action
  byte change (re-run the reusable to restore runtime-proven).

## [0.11.2] - 2026-07-21

### Changed

- Bump pinned uv `0.11.29` -> `0.11.30` across the setup-uv workflows and examples.
- Refresh the `github-code-quality-transition` product fact: the GA/paid
  transition completed 2026-07-20 as scheduled; re-verified 2026-07-21.

## [0.11.1] - 2026-07-20

Supersedes 0.11.0, whose tag was burned by an accidental immutable pre-release.
No functional change from 0.11.0.

## [0.11.0] - 2026-07-20

### Changed

- **BREAKING — uv and bun are now the only language/user-space package managers
  used by this library.** Every reusable workflow and self-CI step that
  previously shelled out to `pip`/`pipx`/`poetry` or `npm`/`npx`/`pnpm`/`yarn`
  now uses `astral-sh/setup-uv` (uv `0.11.30`) for Python and
  `oven-sh/setup-bun` (bun `1.3.14`) for JavaScript. Callers relying on the
  removed inputs or the old install/lint defaults must update their invocations:
  - `python-ci.yml`: `actions/setup-python` + pip is replaced by `setup-uv`
    (pinned via the new `uv_version` input, default `0.11.30`) with
    `enable-cache: true`; Python is provisioned with `uv python install`. The
    `install_command` default changes from `python -m pip install --upgrade pip`
    to `uv sync --frozen`. The pip-specific `cache` and `cache_dependency_path`
    inputs are removed (setup-uv caches automatically).
  - `node-ci.yml`: `actions/setup-node` + `npm ci` is replaced by `setup-bun`
    (new `bun_version` input, default `1.3.14`); the `install_command` default
    changes to `bun install --frozen-lockfile`. The `node_version`, `cache`, and
    `cache_dependency_path` inputs are removed.
  - `web-ci.yml`: `setup-node` is replaced by `setup-bun`; the default
    `lint_command` now runs `bunx stylelint … && bunx htmlhint …`. The
    `node_version`, `cache`, and `cache_dependency_path` inputs are removed in
    favor of `bun_version`.
  - `ci.yml`: validator dependencies install via `uv pip install --system
    --require-hashes -r requirements-ci.txt` (hash-pinning preserved). The
    Harden-Runner egress allowlist adds the uv download hosts.
  - `zizmor-sarif.yml`, `zizmor-no-sarif.yml`, `semgrep-ci.yml`, `sql-ci.yml`:
    the pinned tools now run ephemerally via `uvx tool@<version>` instead of a
    `pip install` step; the unpinned latest-install fallbacks are removed.

### Removed

- `pip`/`pipx`/`poetry` and `npm`/`npx` executable invocations from all
  `.github/workflows/*.yml`. Prose, input descriptions, and copy-paste examples
  that merely mention those managers are unchanged.

### Fixed

- Add an opt-in `fetch_depth` input to `go-ci.yml`, preserving the shallow
  default while allowing ancestry-aware validation to fetch pull-request merge
  parents with `fetch_depth: 0`.

### Changed

- Update the full-SHA-pinned Checkov action from `v12.1347.0` to
  `v12.3112.0`, including its bundled Checkov engine change from `2.0.930` to
  `3.3.6`. Record live `workflow_call` evidence from an isolated Terraform
  fixture that produced seven expected CKV findings while honoring
  `soft_fail: true`. The upstream action still references its engine image by
  the mutable `ghcr.io/bridgecrewio/checkov:3.3.6` tag; the outer action commit
  remains immutable, but that nested image is a documented residual
  supply-chain risk.

- Exclude `swift-actions/setup-swift` from the broad GitHub Actions Dependabot
  group so major Swift action updates receive a separate review and runtime
  consumer proof instead of blocking unrelated stable action updates.

- Make `private-static.yml` caller-provided install and validation command
  blocks fail on the first unsuccessful command, and enforce both fail-fast
  runners through the reusable-workflow contract validator.

## [0.10.0] - 2026-07-12

### Added

- **Three repository-operation skills for agents** under `.agents/skills/`
  (mirrored to `.claude/skills/`): `nddev-repo-orientation` (instant mental
  model, file map, contract index, and a task router), `nddev-change-flow` (the
  complete golden-path checklist, including paired-variant mirroring and the
  runtime-coverage "static-only dance"), and `nddev-release-flow` (version prep,
  the signed tag, the immutable-release verification checklist, and the
  post-release ledger re-promotion). They complement the eight portable
  CI/GitHub-Actions doctrine skills and route to the catalog and agent
  instructions as the source of truth rather than duplicating volatile facts.
  `EXPECTED_SKILLS` and the `AGENTS.md` / `.claude/CLAUDE.md` skill sections now
  describe the two groups.

### Changed

- Re-promote the `release-supply-chain.yml` runtime-coverage record to
  `runtime-proven` after the 0.9.0 release run
  (`…/actions/runs/29173277373` at `e27d4e3`) re-executed the current workflow
  live, recording the fresh run URL and `proven_digest`. Completes the honesty
  cycle opened when RVR-P2-011 edited the workflow and correctly dropped it to
  `static-only`.

## [0.9.0] - 2026-07-12

### Fixed

- **Sync the attested-release permission + Syft contract into every
  consumer-facing surface.** 0.8.1 added `artifact-metadata: write` to the
  attesting jobs and bumped Syft to 1.46.0 in the workflows and release
  validator, but the caller-facing docs, examples, and catalog still showed
  the old three-scope set and Syft 1.42.3. Because a caller's `GITHUB_TOKEN`
  permissions are the ceiling for a reusable workflow, a consumer copying the
  stale three-scope example under-scopes the attest step. Update the
  `release-supply-chain.yml` caller permissions in `README.md`,
  `examples/public-oss/release.yml`, and `docs/04`/`docs/09`; add
  `artifact-metadata: write` to the `artifact-attestations`,
  `slsa-build-provenance`, and attested `releases-packages` capabilities in
  `catalog/capabilities.yml`; correct the Syft version in `README.md`,
  `docs/07`, and `docs/13`; and add a 0.8.1 caller migration note. Contract-
  truth synchronization only — no workflow behavior change.

- **Remove volatile GitHub tariffs from the `ci-free-tier-planner` skill and
  guard against regression.** `.agents/skills/ci-free-tier-planner/SKILL.md`
  hard-coded plan quotas (Actions minute allowances, storage/cache sizes, and
  the attestation / dependency-review / secret-protection / environment plan
  gates), contradicting the project rule that volatile plan/price/quota facts
  live only in the freshness-enforced `catalog/product-facts.yml`. A product
  fact could expire and correctly redden the ledger while the skill still
  served the stale number. Rewrite section 4 to hold the durable procedure and
  reference the facts by id (`github-actions-*`, `github-attestations-*`,
  `github-dependency-review-*`, `github-secret-scanning-*`,
  `github-environments-*`, `github-code-quality-transition`) with fail-closed
  resolution, and add a `check_skills.py` guard (with self-test) that fails CI
  if any `SKILL.md` reintroduces a comma-grouped allowance, `<n> minutes`, or a
  storage-size figure. Regenerate the `.claude/skills` mirror. Found by an
  independent forensic review (RVR-P2-010).

- **Harden the runtime-coverage honesty gate against weak and stale proofs.**
  `validate_runtime_coverage.py` accepted any `https` URL for a
  `runtime-proven` record (its own fixture used `example.invalid`), so a docs
  page or a foreign-repo run would have passed, and it never noticed that the
  `release-supply-chain.yml` record still pointed at a 0.7.0 run
  (`…/29165402032` at `eda8ff7`) taken two edits before the current file.
  Require `last_run` to be a
  `github.com/NDDev-it-com/nddev-ci-workflows/actions/runs/<id>` URL and add a
  `proven_digest` (sha256 of the workflow file at the proving run) that the
  validator recomputes and matches, so any later edit to a proven workflow
  reddens CI until it is re-run and re-recorded (or downgraded) instead of
  silently keeping the label. Repoint all three runtime-proven records to runs
  that provably executed the current bytes (actionlint / zizmor-sarif → the
  `ci.yml` run `…/29172553315`; release-supply-chain → the 0.8.1 release run
  `…/29167958787` at `8b8e3ea`) and record each digest. Fixtures now cover
  foreign-URL, non-run-URL, missing-digest, and stale-digest. Found by an
  independent forensic review (RVR-P2-009).

- **Bound the optional runtime bundle to the SBOM-covered source archive
  (RVR-P2-011).** `release-supply-chain.yml` and its byte-parallel free twin
  attach an optional second `runtime_paths` bundle that received a
  build-provenance attestation but no SBOM — and because `runtime_paths` was
  validated independently of `archive_paths`, it could ship tracked files the
  Syft scan of the source payload never saw. Enforce `runtime_paths ⊆
  archive_paths` inside the deterministic-bundle program (both variants,
  byte-identically) so every file in the runtime bundle is also in the source
  archive that `sbom.spdx.json` inventories — the source SBOM is now provably a
  superset of everything the release ships. Add a `check_release_supply_chain.py`
  fixture (the runtime-bundle program was previously the one embedded program
  with no hermetic test) covering subset-accepted and outside-archive / absolute
  / unmatched / empty-archive-refused. The `release-supply-chain.yml`
  runtime-coverage record drops to `static-only` (its contract validator stands
  in) until the next release re-proves it live. Found by an independent forensic
  review.

### Changed

- **Catalog tool inventory + currency (`catalog/tools.yml`).** Add the seven
  in-use actions that were absent from the catalog — `actions/setup-node`,
  `actions/setup-go`, `actions-rust-lang/setup-rust-toolchain`,
  `actions/setup-dotnet`, `actions/setup-java`, `hashicorp/setup-terraform`,
  and `aquasecurity/trivy-action` — and correct `github/codeql-action`'s
  `used_by` (it also runs in `zizmor-sarif.yml` and `public-scorecard.yml`).
  Bump drifted pins to latest across the workflows and catalog in lockstep:
  codeql-action v4.36.3→v4.37.0, lychee-action v2.8.0→v2.9.0, labeler
  v6.1.0→v6.2.0, stale v10.3.0→v10.4.0, setup-java v5.4.0→v5.5.0, and the
  documented semgrep CLI version v1.168.0→v1.169.0. All remain full-SHA pinned
  with `# vX.Y.Z` comments; no workflow behavior change.

## [0.8.1] - 2026-07-11

### Fixed

- **Grant `artifact-metadata: write` to the attesting release jobs.**
  `actions/attest@v4.1.1` documents `id-token: write` + `attestations: write`
  + `artifact-metadata: write` as its required permission set; the release
  jobs in `release-supply-chain.yml` and `release.yml` were missing
  `artifact-metadata: write`, so the action's artifact-storage-record step
  ran without its scope (the Sigstore signing/attestation itself still
  succeeds, which is why past releases passed). Add the scope to both jobs and
  to the release validator's exact attested-permission assertion. The
  attestation-free variant is unaffected (it has no attest steps). Found by a
  deep review against the `actions/attest` README at the pinned tag.

### Changed

- Relabel the release provenance claim from "SLSA v1.0" to "SLSA v1" in the
  workflow header, README, and SECURITY.md. slsa.dev has retired v1.0 (v1.2 is
  current); the reusable-workflow → Build L3 mechanism is unchanged across
  v1.1/v1.2, so only the version label needed correcting.
- Bump the checksum-pinned Syft SBOM generator from 1.42.3 to 1.46.0 (latest)
  in both `release-supply-chain.yml` and `release-supply-chain-free.yml`, with
  the release validator's `SYFT_PINS` and `catalog/tools.yml` updated in
  lockstep (new Linux amd64/arm64 archive sizes and SHA-256s verified against
  the upstream `syft_1.46.0_checksums.txt`). Syft is a manually pinned binary
  outside Dependabot's reach, so it had drifted four minor versions behind;
  this is a currency/best-practice pass, not a contract change — the SPDX-JSON
  output and every archive/SBOM/manifest/checksum invariant are unchanged.

## [0.8.0] - 2026-07-12

### Added

- **Runtime contract coverage ledger (`catalog/runtime-coverage.yml`).** A
  green static gate does not prove every published reusable workflow starts
  and behaves correctly across its advertised events, tiers, runners, and
  permissions. The repository now keeps an honest coverage record for all 42
  reusable workflows: `runtime-proven` (a real observed `workflow_call` run —
  currently the three the repo dogfoods, `actionlint`/`zizmor-sarif` via its
  own CI and `release-supply-chain` via its own release, each with a run URL),
  `static-only` (an executable embedded-program validator stands in for a live
  run), or `unverified` (no observed run — the honest default for the other
  35), plus `waived` with owner/reason/expiry.
  `scripts/validate_runtime_coverage.py` (wired into `validate_all`) enforces
  one record per reusable workflow, requires a run URL for `runtime-proven`, a
  named validator for `static-only`, and an unexpired waiver for `waived`, and
  reports the status counts so an unverified surface cannot masquerade as
  covered. (RVR-P2-007)

- **Product-fact freshness gate (`catalog/product-facts.yml`).** External
  plan, price, and quota facts change on the provider's schedule, not ours,
  so the catalog now separates volatile product facts from stable capability
  identity. Each live fact carries `verified_at`/`expires_after` plus source
  authority and optional `supersedes`/`conflicts_with`;
  `scripts/validate_product_facts.py` (wired into `validate_all`) fails CI when
  a live fact is expired, when facts about the same product/plan/visibility
  disagree without a supersession, when a `product_facts` capability reference
  is unknown, or when a required anchor fact is dropped. Deprecated facts
  (shut-down services) are exempt from expiry. Tier-sensitive capabilities
  (`artifact-attestations`, `slsa-build-provenance`, `release-supply-chain`,
  `release-supply-chain-free`) now reference their backing facts via the new
  optional `product_facts` field. `docs/generated/free-tier-matrix.md` is
  generated from the ledger so no tariff is hand-copied. The GitHub Code
  Quality commercial transition (GA 2026-07-20) is tracked with
  `expires_after: 2026-07-20` so CI turns red on the day it must be
  re-verified. (RVR-P2-006)

- **CI skills package (`.agents/skills/`).** Eight authored CI/GitHub-Actions
  skills — inventory audit, workflow authoring, workflow security, free-tier
  planning, failure triage, release provenance, cost/performance, and runtime
  contract testing. `.agents/skills/` is the single authored source (Codex and
  OpenCode); `.claude/skills/` is a generated byte-identical mirror produced by
  `scripts/sync_skills.py` and enforced by `scripts/check_skills.py` (in
  `validate_all`) via frontmatter, fixed-set, and mirror-hash-parity checks.
  Skills hold doctrine only — their mutable data stays in `catalog/`
  (product-facts, runtime-coverage). AGENTS.md and `.claude/CLAUDE.md` route to
  them; the release archive now includes `.agents`. The delivered package's
  duplicate fact/coverage validators and data were dropped in favour of the
  repository-canonical equivalents so there is a single CI truth.

## [0.7.0] - 2026-07-12

### Added

- **`release-supply-chain.yml` optional `runtime_paths`.** When set, the
  workflow builds a second deterministic, minimal runtime bundle from the
  selected tracked paths (reproducible tar assembled from Git blobs; executable
  bits preserved; symlinks and non-regular entries rejected), includes it in
  the release manifest, `SHA256SUMS`, and the single immutable release-create
  call, and attests its build provenance alongside the source archive. Empty
  (default) leaves every existing asset, checksum, and attestation
  byte-for-byte unchanged, so current callers are unaffected. (RVR-P3-001)

### Fixed

- **`monorepo-changed-paths` rejects `pull_request_target`.** Under that
  privileged event GitHub checks out the base branch rather than the PR, so
  the git-diff router saw none of the proposed changes and returned a green
  all-false — silently skipping every gated test, scan, build, or migration.
  The router now hard-fails on `pull_request_target` (before any base
  resolution, and regardless of an explicit `base_ref`) with a message
  pointing callers to `pull_request`; checking out fork code to work around
  it is unsafe and intentionally not offered. `check_monorepo_routing.py`
  gains negative fixtures proving both the payload-base and explicit-base
  forms fail closed. (RVR-P2-005)

## [0.6.0] - 2026-07-11

### Added

- `release-supply-chain-free.yml`: the identical closed release pipeline
  (deterministic tracked-source archive, exact-payload SPDX SBOM, canonical
  release notes, manifest, `SHA256SUMS`, one-shot immutable publish) without
  the GitHub attestation steps, requesting only `contents: write`. Its
  manifest records `slsa_build_level: null`. Copy-paste caller:
  `examples/release/private-free-release.yml`.
- Tracked agent instruction docs `AGENTS.md` (Codex-native) and
  `.claude/CLAUDE.md` (Claude Code-native), plus `.DS_Store` in `.gitignore`.

### Changed

- This repository's own release archive now includes `AGENTS.md` and
  `.claude/CLAUDE.md` alongside the other tracked contributor docs, so the
  published source archive is the complete library surface.

- `actionlint.yml` now states and enforces its real runner contract: the
  workflow installs the checksum-verified linux_amd64 binary, so a
  first-step guard rejects any runner that is not Linux X64 with a clear
  error before the download instead of failing halfway through install.
  `scripts/check_actionlint_contract.py` executes the guard against a
  supported/unsupported OS-architecture matrix via `validate_all`.
- **Breaking (`benchmark`):** the single dual-mode workflow is split into a
  publish lane and a read-only compare lane, because compare-only runs
  (`auto_push: false`) still granted `contents: write` and handed a
  write-capable `GITHUB_TOKEN` to the third-party benchmark action.
  `benchmark.yml` now always publishes history (`auto-push: true`,
  `contents: write`) and drops the `auto_push` input; `benchmark-compare.yml`
  is the new read-only lane (`contents: read`, `auto-push: false`) whose
  job-scoped token cannot write. `scripts/check_benchmark_contract.py` keeps
  the two lanes byte-parallel except for that single difference. Callers that
  passed `auto_push: false` switch to `benchmark-compare.yml`; callers on the
  default publish behavior keep `benchmark.yml` unchanged.
- **Breaking (`monorepo-changed-paths`):** the router is now fail-closed.
  `filters` is a strict JSON object of exact file paths or directory prefixes
  ending in `/`; wildcard patterns — previously matched via a
  boundary-crossing `startswith` heuristic, so `src*` also matched `src-old/`
  — now fail the run. An explicit `base_ref`, pull-request base, or
  `merge_group` base that cannot be resolved fails the run instead of
  silently reporting every group unchanged (the `git diff … || true`
  suppression is gone). Pull-request routing uses merge-base semantics,
  `merge_group` is handled as a first-class event, and a push without a
  usable previous tip (branch creation, force-push beyond reachable history)
  or any other event without `base_ref` conservatively reports every group
  as changed. `scripts/check_monorepo_routing.py` exercises the embedded
  program against a hermetic Git-DAG fixture matrix (invalid bases,
  zero/unreachable `before`, multi-commit pushes, prefix boundaries,
  renames, deletions, unusual filenames) via `validate_all`.

### Fixed

- Tier truth for GitHub Artifact Attestations: on the Free, Pro, and Team
  plans attestations are available to **public repositories only**; private
  and internal repositories require GitHub Enterprise Cloud (a plan gate that
  GHAS/Code Security does not unlock). `release-supply-chain.yml` therefore
  cannot complete on private Free/Pro/Team repositories — its unconditional
  attestation steps fail before the release is created. The catalog
  (`artifact-attestations`, `slsa-build-provenance`, `release-supply-chain`),
  README tier tables, and docs 01/02/03/07/09 now state the real plan
  boundary, and the private-free tier releases via
  `release-supply-chain-free.yml`. The release validator enforces byte-level
  step parity between the two variants (minus attestations), the free
  variant's `contents: write`-only permission set, and the absence of any
  attestation reference in the free variant.

## [0.5.1] - 2026-07-10

### Security

- Materialize canonical release notes inside the closed release directory before
  the manifest and checksums are generated. The immutable downloadable notes
  asset now preserves release-note integrity even though GitHub permits the
  release title and body to be edited after publication.
- Require changelog-derived and explicit notes to be tracked, regular,
  non-symlink UTF-8 files with non-whitespace content, and refuse a pre-existing
  canonical output path.

### Fixed

- Publish `release-notes.md` as the fifth explicit immutable asset, declare it in
  `release-manifest.json`, cover it with `SHA256SUMS`, and use that exact file as
  the GitHub Release body in the same single create call.
- Extend the embedded-program validator with positive and adversarial fixtures
  for canonical notes, missing or undeclared assets, exact five-asset publish
  arguments, and checksum closure.

## [0.5.0] - 2026-07-10

### Security

- Build source archives from a normalized, literal Git-index expansion of the
  caller's selected paths. Empty, unmatched, absolute, traversing,
  non-normalized, duplicate, option-like, control-character, dirty-worktree,
  symlink, submodule, and other non-regular Git entries now fail closed.
- Feed GNU tar a sorted NUL-delimited tracked-file list with verbatim option
  handling and recursion disabled. Untracked directory contents and tar/pathspec
  injection can no longer enter a release archive.
- Validate strict numeric SemVer before the untrusted input can reach checkout,
  then check out the exact requested tag and revalidate its LF-terminated
  one-line `VERSION`, optional tracked changelog heading, tag context, safe
  package basename, source tag object, and peeled commit identity.
- Run every embedded Python release guard with isolated mode (`python3 -I`) so
  caller-controlled `PYTHONPATH`, site customization, or standard-library
  shadow modules cannot hijack release logic.
- Replace `anchore/sbom-action` with a direct Syft 1.42.3 binary download whose
  Linux AMD64/ARM64 archive size and SHA-256 are pinned in the workflow. No
  mutable remote installer executes in the privileged release job.

### Fixed

- Generate changelog-derived release notes in runner temporary storage and
  publish an explicit four-item asset array. `release-notes.md` is no longer an
  undeclared fifth immutable release asset omitted from the manifest and
  checksums.
- Match changelog headings literally and require exactly one version section;
  dotted versions can no longer behave as regular expressions or select an
  ambiguous duplicate section.
- Build the archive before SBOM generation, extract that exact archive into a
  private runner-temporary payload, and scan only that payload. The SPDX SBOM
  can no longer describe caller files that are absent from the source archive.
- Generate `release-manifest.json` and `SHA256SUMS` from explicit asset names,
  require the final directory to equal the manifest closure, and reject
  symlinked or non-regular release assets.
- Revalidate the remote tag object immediately before publication and record
  both the source tag object and peeled source commit in the release manifest.

### Added

- Add a `validate_all.py` release-supply-chain gate that extracts and executes
  the workflow's exact embedded guards against positive and adversarial
  fixtures for archive selection, extracted-payload closure, strict versions,
  isolated Python, pinned Syft architecture selection, exact publish arguments,
  asset closure, manifest contents, and checksum coverage.

### Changed

- Make the library's own custom source archive complete: workflows, rulesets,
  catalog, generated and authored docs, examples, validators, locked validation
  dependencies, community files, and the root ignore boundary are all selected
  from the exact tag's tracked state.
- Remove the former `sbom_source_path` input. Syft now always scans the exact
  extracted archive payload, and release runners are explicitly limited to
  Linux X64/ARM64 because the deterministic archive contract requires GNU tar.

### Migration

- Update callers pinned to an older release before adopting `0.5.0`: remove
  `sbom_source_path`, ensure `VERSION` is one LF-terminated numeric SemVer line,
  use only normalized tracked regular-file selections in `archive_paths`, keep
  an explicit `notes_file` tracked and regular, and select a Linux X64/ARM64
  runner. These intentionally incompatible contract changes require a minor
  release rather than a patch release.

## [0.4.0] - 2026-07-10

### Security

- Remove the unsafe `enable_harden_runner` step toggle. Harden-Runner's
  JavaScript `pre` and `post` hooks can execute even when the main step's `if`
  condition is false, so cross-tier and private-free workflows now contain no
  StepSecurity action reference.
- Add a fail-closed validator that restricts Harden-Runner to explicit
  public/GHAS workflows, requires it to be unconditional and first in its job,
  and rejects regressions to the legacy toggle contract.
- Update the remaining public/GHAS Harden-Runner references to v2.20.0 at the
  audited full commit SHA.
- Compile the validator dependency set with complete distribution hashes and
  require hash verification in self-CI.

### Changed

- Make the public/GHAS versus private-free billing boundary structural rather
  than caller-configured. This is a breaking input-contract change for callers
  that passed `enable_harden_runner`; remove that input when updating the pin.
- Migrate the SBOM attestation from the deprecated `actions/attest-sbom` to
  `actions/attest` (native SBOM mode via `sbom-path`, an identical interface).
  The SPDX predicate type and `scripts/verify_attestations.sh` verification are
  unchanged.

## [0.3.0] - 2026-07-08

### Added

- Language packs: Dart/Flutter, C/C++, Qt, Kotlin/Android, Swift, R, HTML/CSS,
  and SQL reusable workflows (joining Python, Node, Go, Rust, Java, .NET,
  container, and Terraform).
- Quality gates: `coverage-gate` (Codecov/Coveralls), `docs-quality`
  (lychee/typos/markdownlint), and `pr-hygiene`
  (commitlint/PR-title/labeler/stale).
- Free SAST/SCA/IaC for every tier including private-free: Semgrep OSS,
  OSV-Scanner, Grype, hadolint, and Checkov (all gate-only, no security-events).
- Advanced testing: `mutation-testing`, `fuzzing` (cargo-fuzz), and `benchmark`
  (github-action-benchmark regression alert).
- Level-3 opt-in caller examples: AI code review (Claude Code Action) and
  release automation (release-please).
- `docs/15-language-and-quality-packs.md` and `examples/` subdirectories
  (`languages/`, `quality/`, `security/`, `testing/`, `level3/`).

### Changed

- Catalog grows to 67 capabilities and 38 pinned tools; every new third-party
  action is SHA-pinned with a version comment and verified against its
  `action.yml` input contract.
- `terraform-ci` documents `terraform_version` pinning for reproducible CI.
- Generated docs re-dated to 2026-07-08.

## [0.2.4] - 2026-07-04

### Added

- Machine-readable catalog schema under `catalog/schema/`.
- Catalog-derived generated docs under `docs/generated/`, checked by
  `scripts/generate_docs.py --check` through `scripts/validate_all.py`.
- Example workflow validator for copy-paste caller snippets, including
  private-free least privilege and Scorecard trigger constraints.
- Markdown local-link and merge-queue compatibility validators.
- First-class July 2026 catalog entries for merge queue, step-level parallel
  execution, hosted-runner governance controls, RHEL larger-runner images,
  license-compliance preview, npm trusted publishing, and PyPI trusted
  publishing.
- npm/PyPI trusted-publishing examples and `scripts/export_repo_sbom.sh`.
- Review reconciliation document under `docs/audit/`.

### Changed

- Strengthened catalog validation for workflow/example coverage, source URLs,
  tool pin shape, duplicate IDs, and stale materialized-workflow risk text.
- Updated runners, Actions core, rulesets, releases/packages, supply-chain, and
  watchlist docs for July 2026 platform facts.
- Fixed SBOM attestation verification docs to verify the released artifact with
  the SPDX predicate type.

## [0.2.3] - 2026-07-04

### Added

- `cross-platform-smoke.yml` now supports OS-specific command overrides
  (`linux_command`, `macos_command`, `windows_command`) while preserving the
  default `command` fallback.

### Changed

- `public-scorecard-json.yml` now defaults `publish_results` to `false`.
  Reusable workflow callers keep Scorecard as a JSON artifact/check signal by
  default, avoiding OpenSSF Scorecard webapp workflow-shape verification
  failures.

## [0.2.2] - 2026-07-04

### Added

- `public-dependency-review.yml` now exposes `vulnerability_check` and
  `allow_licenses`, preserving stricter adapter-local Dependency Review
  semantics during migration to reusable workflows.

## [0.2.1] - 2026-07-04

### Added

- `public-scorecard-json.yml` for Scorecard JSON artifact mode without
  `security-events: write`, matching estate policy where Scorecard is a
  project-health signal rather than a code-scanning alert source.
- Checkout controls (`checkout_ref`, `fetch_depth`, `submodules`) and setup hooks
  for `private-static.yml` and `cross-platform-smoke.yml`, so private/root
  callers can preserve PR refs and submodule validation.
- Adapter-migration extension inputs for shared workflows: `actionlint.yml`
  `post_command`, `secret-scan.yml` report/config/post-command options, and
  `public-codeql.yml` optional CodeQL config/autobuild/artifact output.

### Changed

- Public examples now default to `public-scorecard-json.yml`; SARIF Scorecard
  remains available through `public-scorecard.yml` for repositories that
  intentionally want code-scanning upload.

## [0.2.0] - 2026-07-04

### Added

- **CI/CD encyclopedia** under `docs/` (17 pages): public-OSS / private-free /
  private-paid tiers, Actions core, runners, security scanning, supply chain
  (SLSA/SBOM/attestations), governance/rulesets, releases, deployments,
  observability, community DX, external tools, AI/agentic workflows, a 2026
  watchlist, and `pull_request_target` hardening.
- **Machine-readable catalog** under `catalog/` (`capabilities.yml`,
  `tools.yml`, `deprecations.yml`) with a uniform, validated schema.
- **Language / use-case reusable packs**: `python-ci.yml`, `node-ci.yml`,
  `go-ci.yml`, `rust-ci.yml`, `java-ci.yml`, `dotnet-ci.yml`,
  `container-ci.yml` (Trivy), `terraform-ci.yml`, `docs-ci.yml`, and
  `monorepo-changed-paths.yml`.
- **Rulesets-first governance** under `.github/rulesets/` (branch, tag, push)
  mirroring live protection, plus a migration guide.
- **Static validators** (`scripts/validate_all.py` and friends) enforcing
  full-SHA pins, least-privilege permissions/timeouts, the reusable-workflow
  contract, ruleset shape, and the catalog schema — wired into `ci.yml`.
- **Community health kit**: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`,
  `SUPPORT.md`, a PR template, and issue forms.
- **Attestation verifier** `scripts/verify_attestations.sh`, plus `examples/`
  caller workflows for each tier and a `pip` Dependabot ecosystem.

### Changed

- **Release supply chain** now generates a real SPDX SBOM (Syft via
  `anchore/sbom-action`), attests the archive with
  `actions/attest-build-provenance` and the SBOM with `actions/attest-sbom`
  (SLSA v1.0 Build L3, produced inside the reusable workflow), and publishes an
  **immutable release in a single `gh release create`** call.
- **`zizmor.yml` split** into `zizmor-sarif.yml` (public / paid, uploads SARIF)
  and `zizmor-no-sarif.yml` (private-free, `contents: read` only — least
  privilege).
- **`ci.yml`** now runs `scripts/validate_all.py` as its contract gate.
- README rewritten around the three-tier positioning; SECURITY.md corrected.

### Removed

- `gh release upload --clobber` fallback: it fails against immutable releases
  (GA 2025-10-28). The workflow now fails fast if a release already exists.
- Combined `zizmor.yml` (replaced by the SARIF / no-SARIF split).

## [0.1.0] - 2026-07-04

### Added

- Initial reusable GitHub Actions CI/CD + supply-chain workflow library for the
  NDDev estate, split into two tiers.
- Public-only reusables (free on public repos): `public-codeql.yml`,
  `public-scorecard.yml`, `public-dependency-review.yml`.
- Dual-tier reusables (free on both; `enable_harden_runner`/`upload_sarif`
  toggles for the private free tier): `secret-scan.yml` (digest-pinned
  gitleaks), `actionlint.yml` (checksum-verified), `zizmor.yml`,
  `cross-platform-smoke.yml`, `release-supply-chain.yml`.
- Private free-minimal reusable: `private-static.yml`.
- Self-CI (`ci.yml`) dogfoods `actionlint` and `zizmor` on this repository and
  enforces a reusable-workflow contract; tag-driven `release.yml` publishes an
  attested SBOM/checksum bundle via `release-supply-chain.yml`.
- All third-party actions pinned to full commit SHAs; least-privilege
  `permissions`; concurrency and timeouts on every workflow.
