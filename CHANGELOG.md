# Changelog

## [Unreleased]

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
