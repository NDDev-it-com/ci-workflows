# Changelog

## [Unreleased]

- Add one hermetic Python execution boundary for every repository validator and
  generator. A machine-readable policy now pins the interpreter and PyYAML,
  inventories imports/resources/subprocess edges, strips ambient `PYTHON*`
  state at every generation, rejects shadow or unregistered tools, and keeps
  cold startup proof separate from semantic validation. Dependency imports are
  accepted only from a coherent active venv whose distribution/version matches
  the hash-pinned requirements policy; dependency subjects transition to the
  repository venv explicitly and enforce exact per-environment CPython patch
  identity across local and hosted layouts (#129).

- Make `public-scorecard.yml` fail closed outside a public default-branch
  push/schedule, assign a deterministic SARIF category, and expose the upload
  identifier. The repository's persistent Scorecard caller now exercises the
  SARIF path with least privilege, while a machine-readable ledger rejects
  JSON-only, skipped, wrong-ref, wrong-tool and wrong-analysis evidence (#128).
- Split Scorecard analysis-only and publication into exact mutually exclusive
  jobs. The analysis-only path cannot request OIDC or Code Scanning writes;
  publication retains only the permissions needed for provenance and SARIF.
- Physically separate the read-only Scorecard graph into
  `public-scorecard-analysis.yml`. GitHub validates every nested job's maximum
  permissions before evaluating job conditions, so separate reusable files are
  required to prevent a skipped publish job from invalidating a read-only call.
- Preserve Scorecard's three upstream SARIF run identities and verify their
  exact Code Scanning API category set. The upload category is a fallback, not
  an override when `runAutomationDetails.id` is already present.

- Add an explicit, fail-closed non-Docker Gitleaks mode for Linux X64. The
  existing digest-pinned container remains the default; binary execution binds
  version, platform, architecture, official asset size, and SHA-256, rejects
  unsafe archives, verifies the executable version, records timings, and proves
  cleanup without weakening finding/report/post-command semantics (#137).

### Fixed

- Add a side-effect-safe runtime fixture for benchmark and pull-request hygiene
  workflows. Disposable branch state and pull-request labels are observed,
  restored and guarded before evidence is eligible; skipped, failed or missing
  cleanup can no longer produce a runtime-proof claim. Release publishers and
  promotion remain explicitly blocked where honest proof needs external signing
  authority, protected environments or irreversible transparency-log writes.
- Make side-effect observers fail closed: label evidence now requires the `ci`
  label to be absent before the caller, and benchmark ref probes accept only an
  explicit HTTP 404 as absence rather than treating API/auth/network errors as
  missing state. The fixture-only label rule covers every PR so unrelated paths
  cannot turn a required evidence run into an expected no-match failure.
- Omit `configFile` entirely for an empty PR-hygiene commitlint configuration,
  preserving upstream default discovery; validate and pass a non-empty caller
  path exactly. Passing an empty key made cosmiconfig read the checkout
  directory and fail with `EISDIR`.

- Make runtime-fixture evidence fail closed when a claimed caller is failed,
  cancelled, skipped or missing; add live fixtures for six high-risk gates and
  scope cargo-deny to the same Rust working directory as audit and machete.
  Runtime coverage is now 35 of 46; every remaining gap has typed risk,
  capability and issue handoff, while waivers are limited to objective external
  secret, licensing or real-host barriers.

- Document the intentional ClusterFuzzLite rolling commit pin for pedantic
  zizmor. Upstream's only `v1` tag is older than the reviewed commit, so the two
  action steps narrowly suppress both tag/version audits without changing SHA
  or runtime behaviour.

### Changed

- Allow the runtime ledger to record `partial-runtime` evidence with an explicit
  list of proven jobs while retaining typed debt for every unexecuted lane.
  Static validation and skipped jobs remain ineligible as runtime proof.

- Make billing intent an explicit operating-profile control. Derived public
  modes select unmetered standard hosted runners; derived private/internal
  modes now fail safe to self-hosted compute instead of silently opting into
  metered GitHub-hosted minutes when an add-on is enabled.
- Resolve paid capabilities per entitlement instead of promoting an entire
  private repository into one `private_paid` bucket, and emit a deduplicated
  workflow programme with exactly one plan-correct release variant.
- Distinguish the private no-add-on feature posture from runner billing:
  self-hosted is the zero-GitHub-meter default, while hosted quota and overage
  require an explicit resolver opt-in.
- Split compute billing from licence billing so self-hosted Enterprise modes
  can honestly express both zero GitHub-hosted minutes and a fixed add-on
  envelope. Reject Code Security and Secret Protection on Free/Pro plans and
  non-Enterprise internal repositories according to GitHub's product gates.

### Added

- Add a fail-closed evidence-orchestration catalog and compiler. It selects
  cumulative `fast` / `pr-required` / `full` / `release` lanes from repository
  profile, risk, change, release, platform, OS, architecture and real-host
  requirements; reuses existing workflows; and emits explicit downstream
  handoffs for disposable native Ubuntu/macOS evidence. Timing is observe-only,
  while semantic operational/durable retention maps downstream to 7/30 days.

- **OS and machine-capability routing now fails before useful jobs enter a
  runner queue.** `catalog/workflow-routing.yml` declares the supported OS and
  derived machine requirements for every reusable without embedding private
  labels. `check_runner_routing.py` combines it with an operator mapping and
  rejects unsupported OS/class pairs, missing container capacity and public
  repositories targeting self-hosted backends. The NDDev mapping sends Linux
  fast/standard/integration to their explicit classes and keeps macOS/Windows
  on standard hosted runners. Runtime-proven OS remains a separate evidence
  field; static validation is not presented as a live run.

- **A workflow now states what it needs from the machine.** `required_permissions`
  answered what the token needs and `required_settings` what the repository
  needs; nothing answered what the *host* needs, so a caller choosing between
  self-hosted classes had to read the workflow and guess — and guessing wrong
  fails at runtime with a missing socket rather than anything naming the real
  problem.

  `runtime_requirements` in `catalog/capabilities.yml` states it, and the surface
  turns out to be small enough that knowing it is the useful part: **of 46
  reusables, 44 need nothing but a shell.** Two need a container runtime —
  `secret-scan`, whose gitleaks is a digest-pinned image, and `container-ci`,
  whose Trivy action shells out to Docker.

  `check_runtime_requirements.py` derives the requirement from the workflow and
  compares it with the catalog, so the two cannot drift in either direction: add
  `docker run` and the gate fails until the catalog says so; remove it and the
  gate fails too, because an overstated requirement pushes callers onto a
  scarcer class than they need.

  Deliberately **not** a `runner_class` input. An input would have to name a
  private label taxonomy inside a public library — the thing ADR 0004 forbids —
  and would sit beside `runner` as a second way to choose one machine. A
  requirement is durable; a class name belongs to whoever runs the fleet and
  changes when they do.

- **The negative gates now block the merge.** They were green and ran on every
  pull request, but nothing required them — a gate could stop refusing bad input
  and the merge would go through. `shell-gates` and `dockerfile-gate` now live
  in `ci.yml` and sit inside `ci-gate`'s `needs`, which is the required context.

  They live in `ci.yml` rather than a workflow of their own for two reasons that
  both come from this repository's own rules. A required context must be
  caller-native, so `ci-gate`'s `needs` has to be the run's real dependency graph
  with nothing crossing a workflow boundary. And they cannot be a called
  reusable, because a self workflow must not be `on: workflow_call` — everything
  that is becomes part of the product consumers pin by SHA, and this is internal.

  `runtime-negative.yml` is retired accordingly: keeping it would have meant two
  copies of the same probe list. The weekly standalone run goes with it, which is
  the one thing lost — `ci.yml` runs on every pull request and every push to
  `main`, so drift is caught on the next change rather than the next Sunday.

- **The gates are now proven to fail, not only to pass.** Everything the fixture
  estate did up to now showed that a reusable starts and succeeds on good input.
  That is half a proof: a gate that never fails is not a gate.

  `runtime-negative.yml` feeds six reusables a deliberately broken fixture — an
  unpinned Docker base, SQL the ansi dialect rejects, a misspelling, a false
  assertion in Go and in pytest, misaligned HCL — and asserts each one refuses
  it. All six refused on the first run.

  It does this **without a red run**. Calling the reusable and letting the job
  fail was the first design and was replaced: `continue-on-error` is rejected on
  a job that calls a reusable with `uses:`, so every expected failure turned the
  whole run red, and a permanently red workflow teaches people to stop reading
  the badge. Instead `scripts/negative_gate_probe.py` lifts the gating step out
  of the workflow — its own `run:` text and `env:` block, paraphrasing nothing —
  and executes it in an ordinary job where an exit code is just data.

  Every probe runs both directions, and the second half earned its place: the
  first local run reported "gate refused as required" when the real reason was
  `terraform: command not found`. Without the accepting case a missing toolchain
  is indistinguishable from a working gate, so exit 127 is now an error either
  way. The probe found two more of its own gaps on first contact with CI — a
  missing PyYAML and `$GITHUB_PATH` not carrying a downloaded binary between
  steps — and in both cases refused to report a verdict rather than inventing
  one.

  Seven gates covered, including `zizmor-no-sarif`, which is
  `security-blocking`: its rejecting fixture interpolates a pull-request title
  straight into a shell command and zizmor reports `template-injection` on it.
  The token reaches the probe through `env:`, never a command-line argument —
  putting a credential in an argument is the very pattern zizmor exists to
  catch.

  Two workflows have no lane and the reasons differ. `docs-quality`'s three
  gates are all `uses:` steps. `actionlint`'s step is a bare `actionlint -color`
  with no target and it resolves the git project root itself, so aiming it at a
  fixture would mean giving that fixture its own repository — and the probe runs
  the step as written rather than a convenient variant of it.

- **`benchmark-compare`, `r-ci` and `mutation-testing` are proven**, taking the
  ledger to 29 of 46 and leaving seven unverified.

  `benchmark-compare` became provable by exposing `external_data_json_path` on
  both benchmark lanes: with it set the action stores history in a file and no
  longer uses a Git branch, so the read-only twin stops failing on a `gh-pages`
  branch this repository has never had. `auto_push` is deliberately still not an
  input — `check_benchmark_contract.py` refuses that string in either file, and
  the refusal is right, because a caller-controllable auto-push would collapse
  the write lane and the read lane into one workflow with a dangerous toggle.

- **The estate is two workflow files.** `runtime-fixtures.yml` keeps the nine
  tree-level lanes; `runtime-fixtures-languages.yml` takes the language and
  tooling lanes. One 550-line file mixing "does the gate work" with "does Swift
  build" was already hard to read.

- **Nine reusables are now proven on all three operating systems.** Every
  reusable exposes a `runner` input — a promise that a consumer may choose their
  OS — and until now that promise had only ever been tested on Linux. Standard
  hosted runners are unmetered on public repositories in all three, so
  `go-ci`, `python-ci`, `node-ci`, `rust-ci`, `dotnet-ci`, `java-ci`,
  `terraform-ci`, `sql-ci` and `web-ci` now run on macOS and Windows in the
  fixture estate as well.

  The runner rule had to learn matrices first: it required a literal label, so
  `${{ matrix.os }}` read as "not a standard hosted runner" and three-OS
  coverage was structurally impossible. It now resolves the expression against
  the job's own `strategy.matrix` and checks every value, `include:` entries
  included, so a clean `os:` list cannot smuggle a fleet label past it.

- **Java, .NET and Swift joined the fixture estate**, taking the ledger to 26
  proven of 46. The Swift lane runs on `macos-latest` — a standard hosted
  runner, unmetered on public repositories, which is the whole reason the macOS
  fact was worth recording.

  Ten records remain unverified and every one states its reason. Two are
  structural: `benchmark.yml` cannot be proven without writing a `gh-pages`
  branch, and its read-only twin needs history only that write creates. The
  rest need SDKs (Android, Qt, Flutter, R) or harnesses (fuzzing, mutation
  testing) heavy enough to deserve their own change.

- **Twelve reusables now have a live run behind them.** Twenty-five of the
  forty-six sat `unverified`: every static check passed, but nothing had ever
  started them. `runtime-fixtures.yml` now calls twelve more as a consumer
  would, against ten dependency-free projects under `tests/fixtures/`. The
  ledger moves from 11 proven to 22.

  Dependency-free is the design constraint, not an economy: a fixture that
  downloads a package tree proves the network works, not that the workflow
  does. Each project was run locally against the same tool and the same pinned
  version the workflow uses before being wired in.

  Not everything can be proven here, and the records now say why rather than
  saying nothing. `benchmark.yml` hard-wires `auto-push: true`, so proving it
  would commit history to a `gh-pages` branch — a fixture estate must not
  change the repository it runs in. Its read-only twin fails on
  `couldn't find remote ref gh-pages`, which is a precondition rather than a
  defect: it fetches history only the writing twin can create.

### Fixed

- **This library said the `amsterdam` runner label had been retired. It has
  not.** ADR 0004 and `docs/05` both stated the label was dead and that any
  caller still inheriting it queued against a runner that would never appear.
  The fleet that owns those runners reports the opposite: they are
  online and carrying a large share of the estate's CI, `github-device-sync`'s
  own included. The counts stay in the control plane, where account state
  belongs.

  The decision those documents record is unaffected and unchanged — a public
  library must not ship a private label as anyone's default, because no consumer
  outside this estate can resolve one. What was wrong is the *reason* attached
  to it, and the tense. Saying the label is dead makes the danger sound
  historical; the live danger is the other one, that a public repository
  inheriting a private default runs fork-authored code on trusted hardware.

  The estate version ledger carried the mirror image of the same error — it
  claimed this module defaults `runner` to `amsterdam` across 38 workflows, when
  the string appears in no workflow here at all. Corrected in
  NDDev-it-com/github-device-sync#159.

- **A wrong reason in the ledger, corrected.** `benchmark.yml` was recorded as
  unprovable because `auto-push: true` would write a `gh-pages` branch. That was
  not the obstacle. The real one is permissions: its job declares
  `contents: write`, a reusable cannot request more than its caller grants, and
  calling it from a `contents: read` job produces a `startup_failure` with no
  jobs and no annotation. It stays unproven because granting the fixture estate
  a write-capable token would defeat the property the estate exists to have —
  a deliberate refusal, not an impossibility, and the record now says so.

  Worth keeping: a reusable demanding more permission than its caller grants
  fails the **whole run** before any job starts, and GitHub reports only "this
  run likely failed because of a workflow file issue". Neither the unique-call
  count nor the total-call count explained it; bisection did.

- **Twenty-six jobs were running PowerShell on Windows.** Twenty-two files
  declare `defaults: run: shell: bash` at workflow level, and then their jobs
  declare `defaults: run: working-directory:` — which *replaces* the
  workflow-level block rather than merging with it. Every one of those jobs
  silently lost the shell its own file declared three lines above.

  Linux hid it completely, because bash is the default there anyway. Windows
  did not: `python-ci` on `windows-latest` ran its steps under PowerShell,
  where a bash line continuation and `>>` are syntax errors and `${VAR}`
  expands to nothing — the job printed "(requested )" and then failed.

  The clue was already in the tree: `cross-platform-smoke.yml`, the one
  workflow written for three operating systems, sets `shell: bash` on every
  individual step instead of trusting the default. It was also the only Windows
  lane that passed.

  Every job-level `defaults.run` now pins the shell, and a validator refuses one
  that does not.

- **The self-call runner rule forbade a free runner.** It demanded the literal
  string `ubuntu-latest`, which enforced the property it cared about — a public
  caller chooses explicitly, never inherits a default that could route forked
  pull-request code to a private fleet — but enforced it by accident, and so
  banned `macos-latest`. That made `swift-ci.yml` impossible to call from this
  repository's own estate.

  The rule now requires an explicit *standard hosted* runner. Both halves still
  bite: omitting `runner` fails, and so does any larger runner or fleet label.
  `check_examples.py` had its own copy of these constants; both now import
  `_runners.py`, so the two checks cannot drift apart about what "hosted" and
  "standard" mean — which is how they came to disagree at all.

- **`python-ci.yml` ignored its own `python_version`.** The job ran
  `uv python install`, which downloaded the requested interpreter and then left
  it unused — the caller's install and test commands resolved `python` from
  `PATH` and got the runner's system Python. The step then printed
  "Python 3.13 tests passed" while pytest had run on 3.12, so the workflow
  asserted the one thing it had not done. `setup-uv` now receives
  `python-version` and `activate-environment`, and the summary reports the
  interpreter that actually executed.

- **`docs-quality.yml`'s `working_directory` scoped nothing.** All three lanes
  are `uses:` steps, and an action resolves path arguments against the
  workspace root whatever the job's default working-directory says. Pointed at
  one small tree, the lane scanned the whole repository. The three path inputs
  are now documented as repo-root-relative, on the input that misleads and on
  each path input.

  Both defects were found by the first fixture run and neither was reachable by
  static analysis, which is the argument for the estate in one sentence.

- **zizmor's stricter persona was advice rather than a control.** The catalog
  recorded "run pedantic locally for deeper manual audits" — a bar nothing
  enforced and nobody recorded. It is now what CI runs. Closing it cost ten
  comments: every granted permission states why it is granted.

### Fixed

- **The ledger held no macOS fact at all**, while this library defaults
  `swift-ci.yml` to `macos-latest` and `cross-platform-smoke.yml` to a matrix
  including macOS and Windows. Eighteen GitHub facts, zero of them covering the
  runners we hand consumers by default.

  Verified against two primary sources and recorded on
  `github-actions-public-standard`: **all three operating systems are standard on
  public repositories and free there** — `macos-latest` is listed under "Standard
  GitHub-hosted runners for public repositories", and "use of the standard
  GitHub-hosted runners is free and unlimited on public repositories". Larger
  runners stay billed even on public. On **private** repositories the multiplier
  is the part worth knowing: Linux $0.006/min, Windows 1.67x, macOS **10.33x** —
  a macOS lane that costs an OSS repository nothing eats ten times the quota
  behind the paywall.

  Worth recording how close this came to being wrong: a summary of the billing
  page asserted that *only Linux* standard runners are free on public
  repositories. The sentence it quoted said no such thing, and the runners
  reference contradicts it outright. The claim was taken from the primary wording
  rather than the summary — which is the entire reason this ledger requires
  `source_urls` instead of prose.

  Marked where it will actually be read: `docs/05` where routing is taught,
  `AGENTS.md` tier truth, and the `runner` input description of `swift-ci.yml`
  itself. Expiry staggered to 2026-10-30, away from the eight facts already on
  2026-10-09.

### Fixed

- **Hosted is not the same as free.** `docs/05` taught routing with the sentence
  "minutes are free and unlimited on public repositories" — true only for
  **standard** runners. Larger ones (`-N-cores`, `-large`, `-xlarge`) are billed
  from the first minute on public repositories too, and the standard allowance
  does not offset them, so a public repository reaching for
  `ubuntu-latest-8-cores` because "Actions is free on OSS" starts paying at once.
  The prose now says which, sourced to the two facts that own it, and
  `check_examples.py` rejects a larger runner in any example so this repository
  cannot ship the trap it warns about.

- **Public repositories must be on hosted runners, and the rule that said so had
  gone vacuous.** `check_examples.py` required an explicit `runner` only when the
  reusable's default was *non-hosted*. That was written when the default was
  `amsterdam`; the moment it became `ubuntu-latest` the check stopped firing
  anywhere, and thirteen example jobs across seven files had quietly gone back to
  inheriting — including the estate's **public** variant, which is exempt from the
  rule precisely so it *may* name the fleet.

  Nothing was broken today, because today's default is safe. That is the whole
  problem: the protection had become a bet on the current default rather than a
  contract, and the next default change would have moved every one of those jobs
  with no diff in any example.

  Two rules replace it, and both are negative-tested. An example must state its
  runner **whatever the current default is** — a default belongs to the pinned
  commit, not to the caller. And a non-hosted label is accepted only in a file
  whose own name declares a private target, because public repositories get free
  unmetered hosted minutes and a forked pull request on self-hosted hardware is
  remote code execution on it.

- **The estate fleet is ephemeral, and only two of its four classes have a
  host.** Reading `modules/github-actions` instead of inferring from a label
  produced three corrections:

  - `catalog/profiles.yml` recorded `runner_mode: self-hosted-persistent` for the
    estate profile. The fleet gives every job a fresh VM, runs it once and
    destroys it, and explicitly does not reuse a VM after that VM has executed
    workflow code. That is `self-hosted-ephemeral`, and the distinction is the
    one ADR 0004 named as the condition that would make a public fork safe on
    self-hosted hardware — so its consequence is updated rather than left saying
    the condition is unmet.

  - **Declared is not deployed.** The fleet publishes four scale-set classes;
    `nddev-linux-fast` and `nddev-linux-release` have no host, and the fleet's
    GARM holds one repository entity, so it serves `NDDev-it-com/github-actions`
    alone. No `nddev-*` label can take a job from any other estate repository
    until the organization entity is rolled out. The estate example now says so
    instead of reading as runnable.

  - The previous entry called the classes a routing fix. They are the *intended*
    routing; today they are aspirational for every repository but one. Naming a
    real label is not the same as naming a reachable one, and the failure mode is
    identical to the retired label's: the job queues rather than fails.

### Fixed

- **Corrected a claim I made about the estate's runners.** The previous entry
  said the `amsterdam` fleet "no longer exists" and that the estate had moved to
  GitHub-hosted runners. Only the first half is right: the **label** was retired,
  but the estate still runs its own fleet — reimplemented as a GitHub App in
  `modules/github-actions`, with a per-class taxonomy
  (`nddev-linux-standard`, `-integration`, `-fast`, `-release`).

  The change itself stands and every default remains `ubuntu-latest`, because the
  justification was wrong rather than the outcome. It is not "the estate went
  hosted". It is ADR 0004's original rule, unchanged: **a public library must not
  ship a private label as anyone's default**, because no consumer outside the
  estate can resolve one. `nddev-linux-standard` would be exactly as wrong a
  default as `amsterdam` was; an estate caller names its class explicitly, which
  is what the rule required all along.

  The estate example now names the real classes instead of a `<label>`
  placeholder, and the routing is not cosmetic: `secret-scan` runs gitleaks as a
  digest-pinned container, so it needs `nddev-linux-integration` (the class with
  a Docker daemon) while every other scanner uploads SARIF and belongs on
  `nddev-linux-standard` (repository-scoped credentials) rather than the
  credential-free `nddev-linux-fast`. Put the container job on the standard class
  and it fails at `docker run`; put the SARIF jobs on the fast class and they
  fail for want of a token.

  `catalog/profiles.yml` therefore keeps `runner_mode: self-hosted-persistent`
  on the two private profiles, and `docs/17` keeps its routing model: private
  work still runs on the estate's own runners and still bypasses the metered
  pool. ADR 0004 and `docs/05` are corrected to say the label was retired rather
  than the fleet.

### Fixed

- **The GDS projection no longer contradicts live governance.** For most of this
  repository's life `.gds/compiled-policy.json` declared `allow_squash_merge:
  true` and `allow_merge_commit: false` under `management: managed`, while the
  live repository is the opposite — managed *intent* disagreeing with reality, so
  a reconcile run would have flipped a governance model the ruleset, the
  instruction docs and the contributor guide all describe correctly.

  It was fixed where it belongs: a repository-tier override in the control plane
  (NDDev-it-com/github-device-sync#150), in the same shape as the one
  `github-actions` already carries, plus this module claiming it. The base policy
  stays squash-only for the rest of the estate. `gds compile policy` now resolves
  four sources and reports `allow_merge_commit: true`, matching the live API.

  Two properties of that system are recorded in `docs/08`, because both cost a CI
  round trip to learn: a policy source and its projections move in one commit
  (adding the override staled four generated files at once and failed
  `gds context` on a digest mismatch), and a module must never claim a profile
  whose source has not landed (`gds compile policy` fails closed with
  `GDS_POLICY_PROFILE_MISSING`).

  An earlier note in this changelog called the projection "wrong and fixable only
  upstream". The first half was right; the second was half-right — upstream is
  where the fix belongs, and it was reachable.

### Added

- **Caller commands must be shell-parseable, checked by `shlex`.** An unbalanced
  quote in a `command:` input was invisible to everything: the YAML is valid so
  actionlint passes, the value is just a string so no schema complains, and the
  failure surfaced only when a runner reached `bash: unexpected EOF while looking
  for matching "`. That cost a full CI round-trip to find a typo. Written after
  making exactly that mistake in the fixture estate.

### Changed

- **The `runner` default is `ubuntu-latest`; the `amsterdam` fleet is gone.**
  Thirty-nine reusables defaulted to a private self-hosted label. ADR 0004
  described exactly what that costs an external consumer — "the label resolves to
  nothing, so the job queues against a runner that will never appear" — and
  deliberately left the default alone, because flipping it would have moved ~10
  private callers onto metered hosted runners, a cost decision the library may
  not make for its consumers.

  That objection died with the fleet. The estate moved to its own GitHub App for
  CI and retired the label, so there is nothing left to move those callers off,
  and the default stopped being wrong-by-default and became broken: every caller
  inheriting it now queues forever. All 39 defaults are `ubuntu-latest`.

  The migration was one edit precisely because ADR 0004's rule held: callers were
  already required to name their runner, so no example and no compliant consumer
  depended on the default. A caller on its own fleet still names its label —
  and now must, since a hosted default meters silently.

  ADR 0004 records the supersession rather than being rewritten; `docs/05`
  carries the history, because "the default is safe today" is a fact with a date
  on it.

### Added

- **A consumer fixture estate, and it immediately found four defects static
  validation could not.** `runtime-fixtures.yml` calls nine reusables the way a
  consumer would. ADR 0003 named its absence as the reason 44 of 46 workflows
  were unproven; the first run proved seven and produced these:

  - **Three pin comments named the wrong release.** zizmor's `ref-version-mismatch`
    is an *online* audit. Run locally without a token it is skipped silently and
    zizmor prints "No findings"; CI has `GH_TOKEN`, so it runs. The pinned
    `cargo-deny-action` SHA is `v2.1.1`, not the `v2.0.11` its comment claimed —
    a different commit entirely — and both `clusterfuzzlite` comments were dated
    2024-09-19 against a commit from 2026-02-12. The new pin-comment rule checked
    the *format* and passed all three. Corrected, and `AGENTS.md` and the skill
    now require a token for local zizmor.

  - **`private-static.yml` provisioned no installer.** It sets up Python, then
    runs a caller-supplied `install_command` — with `pip` and `pipx` forbidden by
    estate policy and `uv` never installed, a caller following that policy had
    nothing to install with. The fixture failed on `uv: command not found`. Closed
    with an additive `setup_uv` input, default `false`, so every existing caller
    is byte-identical.

  - **The examples did not demonstrate the library's own headline rule.** Semgrep
    flagged ten `github-actions-mutable-action-tag` findings, all in `examples/`:
    third-party actions carried the `@<sha>` placeholder, which no scanner can
    distinguish from a mutable tag. `check_pinned_actions.py` enforces full-SHA
    pinning over `.github/workflows/` only. The four affected examples now pin
    real SHAs; `@<sha>` remains where it belongs, on the `ci-workflows` reference
    a consumer must choose for themselves.

  **Result after the fixes: 10/10 green, and nine reusables promoted to
  `runtime-proven`** against run 31535606661 — `actionlint`, `zizmor-no-sarif`,
  `secret-scan`, `private-static`, `monorepo-changed-paths`, `osv-scan`,
  `semgrep-ci`, `docs-ci` and `gate`. The ledger moves from 2 proven / 31
  unverified to **11 proven / 25 unverified**, and of the eighteen records in an
  obligated tier, eight are now proven by a real run rather than standing on a
  validator or a dated waiver. Seven waivers remain: `coverage-gate`,
  `grype-scan`, `iac-scan`, `pr-hygiene`, `public-codeql`, `rust-supply-chain`,
  `zizmor-sarif` — each needs a fixture this run does not provide (a container
  image, a pull-request context, SARIF upload permissions, a crate).

  `semgrep-ci` is proven in both directions: an earlier run of the same fixture
  exited 1 on ten real findings before they were fixed, so the gate is known to
  fire, not only to pass.

  The estate is deliberately not a required check and not on `pull_request` —
  evidence production is not merge gating. It triggers on a push to `fixtures/**`
  so a change can be proven before it merges, and weekly so evidence does not go
  stale as pins move.

### Fixed

- **CodeQL caught a cyclic import in the strict loader.** `_workflow_yaml`
  imported `strict_load` at module level while `_strict_yaml.check()` reached
  back for `REPO_ROOT` from inside the function. It worked only because that
  second import was deferred — a real cycle wearing a workaround.
  `_strict_yaml` is the bottom of this stack and now derives `REPO_ROOT`
  itself, two lines of pathlib against a dependency cycle.

### Changed

- **The release procedure now says how to produce the promotion record.**
  `docs/09` described the gate and the record's shape without saying who builds
  it, which read as though the record had to be hand-written. It does not:
  `scripts/promotion_record.py` in the control plane already builds and verifies
  it against the same `nddev-release-promotion/v1` schema and the same nine
  evidence roles the gate enforces. Documented with the exact `create` / `verify`
  invocation, the `git tag -s -F` step that puts it in the signed annotation, and
  the three properties easiest to get wrong: canonical compact JSON plus one LF,
  the 168-hour freshness window, and the commit identity every evidence entry
  must agree on.

- **Three repository-operation skills became one.** `nddev-repo-orientation`,
  `nddev-change-flow` and `nddev-release-flow` described a single workflow across
  three files that had to be kept in step with each other *and* with `AGENTS.md`,
  and drifted from both. `nddev-repo-flow` replaces them: 439 lines to 138, ten
  skills instead of twelve, and the procedure lives in one place while the facts
  live in the brief.

- **The public library stopped publishing account-observed estate state.**
  `docs/17` and `docs/18` carried a live operations report: licence counts,
  repository inventory ("23 repos", "all 51 repositories", "36 on default setup,
  8 on their own"), an invoice total, AI-credit spend to the cent, a metered-pool
  reading with a projected exhaustion date, and a named private repository. None
  of it was secret, which is why it survived review — the defect is the trust
  domain. A consumer reads a public library for stable contracts, not for what
  one organization's bill looked like on one morning, and every figure was stale
  within days.

  Durable statements stay: which products the estate holds, why push protection
  is off, that a security configuration attaches atomically, that a budget cannot
  stop a licence-based product, that a second committer is the largest available
  step change. Countable account state moves to the control plane, and
  `scripts/check_public_docs.py` now rejects inventory counts and cent-precision
  currency in public prose so the report cannot creep back. `docs/16` also
  restated the AI-credit tariff, which the freshness-gated ledger owns; it now
  references the fact instead.

### Fixed

- **Pin comments could say nothing, and two lied.** `check_pinned_actions.py`
  required only that *some* `#` comment follow the SHA, so `#` and `# bumped`
  both passed — while the comment is the only human-readable half of a pin and
  the thing a reviewer reads when diffing a Dependabot bump. It must now name a
  release (`# vX.Y.Z`) or an ISO date for upstreams that publish none
  (`google/clusterfuzzlite`). Two pins carried a moving major tag; resolved
  against the upstream tag list to `# v2.12.1` (`r-lib/actions/setup-r`) and
  `# v3.0.0-beta.1` (`swift-actions/setup-swift`).

- **`catalog/tools.yml` recorded pins that were no longer running.** Adding a
  cross-check between each pin comment and the catalog's `current_version`
  immediately found `codeql-action` at `v4.37.0` / `99df26d4` and `setup-gradle`
  at `v6.2.0` / `3f131e86` while the workflows had been bumped to `v4.37.5` /
  `d1ba80a1` and `v6.3.0` / `9c971963`. The catalog exists to record which build
  is pinned and was wrong about it for two tools across eight call sites, in the
  direction that matters least visibly: a reviewer checking "what does this SHA
  correspond to" got a stale answer. Both corrected against the upstream tag
  list and the cross-check now runs in the gate.

### Security

- **The release path had a documented promotion gate it never called.**
  `release-promotion-gate.yml` existed, was validated by its own fixtures, was
  drawn in `docs/09` as `release.yml -> promotion -> supply-chain`, and had a
  caller example — while the repository's actual `release.yml` ran
  `publish: needs: resolve` straight into the write-capable reusable. A control
  that is not in the path is not a control.

  `release.yml` is now `resolve -> promotion -> authorize -> publish`. Every
  write scope (`contents`, `id-token`, `attestations`, `artifact-metadata`)
  lives on `publish`, which cannot start until the machine gate verifies the
  tag's control-plane promotion record *and* a human approves through the
  protected `release` environment. `environment:` is not permitted on a job that
  calls a reusable workflow, so the approval sits in its own unprivileged
  `authorize` job. `scripts/check_release_graph.py` walks the `needs` graph and
  rejects any release-capable job reachable without both gates, plus five
  negative fixtures including the exact defect that shipped.

  **This is a release-blocking change on purpose.** No existing tag carries an
  `nddev-release-promotion/v1` record, and the `release` environment does not
  exist yet, so the next tag fails closed until both are in place.

- **`gate.yml` was sold as a branch-protection primitive and could not be one.**
  A reusable workflow cannot read its caller's `needs` context, so results
  arrive as the caller-authored `needs_json` string. Executed against the
  embedded verifier, five forged inputs all passed — including
  `needs_json: '{}'` with `required_jobs: ''`, which produced a green named
  check while asserting nothing at all.

  It is now labelled a non-authoritative reporting helper in its header, in the
  catalog, and in `docs/08`, and it fails closed on inputs that assert nothing:
  empty or non-object `needs_json`, empty `required_jobs`, a required job absent
  from `needs`, an entry without a `result`, and a `required_jobs` list that
  omits a job present in `needs` (which let a failing job be dropped by
  shrinking the list). Two inputs still pass and always will — a fabricated
  all-success object, and fabricated job names — because no validation inside a
  reusable can distinguish those from genuine caller data;
  `scripts/check_gate_contract.py` asserts that too, so the limitation stays
  visible instead of being rediscovered by a consumer.

  `examples/quality/caller-native-gate.yml` is the required-check replacement,
  evaluating the real `needs` context in the caller. `ci.yml` now uses that
  shape for `ci-gate` itself.

### Fixed

- **A duplicate mapping key in a canonical catalog was accepted silently.**
  `catalog/runtime-coverage.yml` carried `validator:` twice in two records, and
  every loader was `yaml.safe_load`, which keeps the last value. Demonstrated:
  pointing the second copy at a non-existent script left the gate green while
  the real validator reference was discarded. `scripts/_strict_yaml.py` is now
  the single loader for every canonical YAML and rejects duplicate keys with
  file, line, and key; the tree-wide scan and its fixtures run first in the gate.

- **The profile resolver answered 13 of 96 repository shapes.** Named profiles
  were doing double duty as ergonomics *and* as the semantic domain, so any
  valid combination nobody had named — Secret-Protection-only, Code-Quality-only,
  and 81 others — exited with "no named profile covers it". Presets and validity
  are now separate: `catalog/profiles.yml` declares the plan gates and the
  derivation rules, and `resolve_profile.py` synthesizes a deterministic
  programme with a derivation trace for any shape a plan gate does not forbid.
  72 shapes resolve (13 preset, 59 derived) and 24 are refused with a stated
  reason (Code Quality below a Team plan). A derived mode compiles **no** cost —
  a costed envelope is a verified decision, not an inference. The exhaustive
  96-shape matrix is now an invariant in `validate_all`.

- **One required job coupled product invariants to the calendar.** All 22
  validators ran in a single blocking gate, including the expiry sweep over
  external product facts. Reproduced: a one-line comment change in `java-ci.yml`
  became unmergeable because a third-party runner vendor's pricing fact reached
  its expiry date.

  `validate_all.py` now runs three tiers. **core** is blocking and holds only
  properties of the tree. **touched** is blocking but scoped — a fact is checked
  for expiry only when the changed capability declares it, a waiver only when its
  workflow was touched. **scheduled** is advisory and runs in the new
  `maintenance.yml`, which files a single tracking issue rather than leaving
  findings in a run log. Verified by advancing the clock to 2026-11-01 with 30
  facts and 4 waivers past due: core and touched stay green for an unrelated
  bugfix, scheduled reports the debt, and a change to a capability that *depends*
  on a stale fact is still blocked. `release.yml` runs the full sweep, because a
  release must not ship carrying an expired claim.

- **`required-gate` owed no evidence.** The proof obligation covered `release`
  and `security-blocking` only, so workflows whose entire job is deciding whether
  a merge proceeds could rest at `unverified` — which is where `gate.yml` sat.
  `required-gate` joins the obligated tiers and its five members are pinned.
  Resolved honestly: `monorepo-changed-paths.yml` to `static-only` behind its
  hermetic Git-DAG fixtures, `gate.yml` reclassified to `supporting` behind
  `check_gate_contract.py` (pinned at its new tier so the change is deliberate
  rather than a quiet relabel), and dated waivers for `coverage-gate.yml`,
  `pr-hygiene.yml` and `private-static.yml`, staggered against the existing wall.
  No record in an obligated tier is `unverified` any more.

- **The GDS projection fix is drafted but not claimed here.** The correction —
  a repository-tier override plus this module claiming it — is prepared in
  NDDev-it-com/github-device-sync#150 and blocked on the estate's
  content-addressed provenance: adding a policy *source* stales every generated
  projection in the same commit, and regenerating them needs a registered device
  identity. This module therefore does **not** yet list the `ci-workflows`
  profile; `gds compile policy` fails closed with `GDS_POLICY_PROFILE_MISSING`
  when a declared profile has no source, so claiming it early would break the
  estate rather than fix it. `docs/08` records the diagnosis and the remedy.

- **Governance was described in four places that disagreed.** Settled against
  the live API: the repository allows `merge` only (`allow_squash_merge: false`),
  which matches `.github/rulesets/branch-main.json`.
  `.github/branch-protection/main.json` claimed to record the same ruleset while
  describing `squash` and linear history; nothing read it and no validator
  compared it to anything. Deleted — two files describing one object is the
  defect. `docs/08` now carries an ownership table and records that
  `.gds/compiled-policy.json` is **also wrong** (`allow_squash_merge: true`
  under `management: managed`) and **cannot be fixed here**: it is generated,
  its sources live outside this repository, and the policy itself forbids
  editing generated projections.

- **The instruction surfaces contradicted each other and the CI they describe.**
  `AGENTS.md`, `.claude/CLAUDE.md`, `CONTRIBUTING.md` and a skill all told
  contributors to run `python3 -m pip install`, while the estate policy forbids
  `pip`/`pipx` and mutable resolution (`go install ...@latest`, also documented)
  and CI actually ran `uv pip install --system`. All four now match CI.
  `AGENTS.md` is rewritten as a compact map (179 → 118 lines) built around a
  change-impact map and a table of contracts pointing at the executable
  validator that owns each; `.claude/CLAUDE.md` is a 19-line delta (was 125) and
  states that `AGENTS.md` is not auto-loaded in Claude Code. Both said "eight
  portable skills" against nine in `EXPECTED_SKILLS`.

- **`catalog/tools.yml` was factually wrong about its own consumers.**
  `actions/checkout` declared 9 workflows and was used in 46; `setup-python` 3 of
  6; `upload-artifact` 2 of 7 — and four actions used on disk had no entry at all
  (`cargo-deny-action`, `taiki-e/install-action`, both
  `clusterfuzzlite/actions/*`), because the pin validators check pin format and
  never catalog membership. `used_by` is the list a reviewer reads to answer
  "which workflows does this SHA bump affect?". Corrected and now derived from
  the tree by `scripts/check_tool_registry.py`.

- **Caller commands did not fail fast.** 47 sites across 23 workflows ran
  `bash -c "$COMMAND"`; the inner shell inherits nothing from the step, so a
  caller passing `lint; test` or `build | tee log` got exit 0 from a failing
  first command and the reusable reported success. The fail-fast contract
  existed but was written for `private-static.yml` alone; it now applies
  everywhere a caller's command is executed, enforced by
  `check_workflow_contracts.py`.

- **README compiled a public cost the catalog forbids compiling.** It stated
  flatly that public repositories are "not free" for Code Quality, while the
  fact ledger records the public rate as **disputed between GitHub's own
  sources** and says not to compile one in either direction. The fact also
  contradicted itself — its `conditions` recorded the dispute while a later
  `notes` entry resolved it — so both were corrected: the licence requirement is
  stated, the rate stays account-observed.

- **Three reusables shipped with no caller example** (`gate.yml`,
  `rust-supply-chain.yml`, `clusterfuzzlite.yml`) despite the rule being written
  down. Examples added, and `check_examples.py` now enforces coverage.

- **`Last generated: 2026-07-11` was a hard-coded literal** in
  `generate_docs.py`, printed on documents rendered from a catalog edited in
  August. Replaced with the newest `last_verified` among the rows each document
  renders: deterministic, so the drift check stays meaningful, and it answers
  the question a reader actually has.

- **A release-path cache-poisoning vector** (zizmor, high): `setup-uv` caches by
  default, which would make the Actions cache an input to a release build. The
  release preflight sets `enable-cache: false`.

### Fixed

- **The zizmor invocation is now pinned to the version CI runs.** AGENTS.md said
  `zizmor …`, which uses whatever is on `PATH` — a different version reports
  different findings than the gate. It now says `uvx zizmor@1.26.1 …`, matching
  `zizmor-sarif.yml`'s `zizmor_version` default, with the instruction to read the
  pin from the workflow if the two ever disagree. Run against this tree at that
  version: **no findings, 10 suppressed.**

- **Recorded that a push/schedule-only workflow must never be a required check.**
  OSSF Scorecard supports `push` and `schedule` on the default branch only, so as
  a required context it can never report on a pull-request head: it protects
  nothing and blocks every merge. Two estate repositories sat unmergeable on
  exactly this, and the requirement lived in classic branch protection rather
  than a ruleset, so a ruleset-shaped investigation found nothing.

- **The Rust CodeQL claim was too strong.** `docs/17` said Rust "cannot be
  CodeQL-scanned this way at all" because the default-setup REST enum rejects
  it. GitHub's changelog is clear that Rust left public preview and is
  **generally available for default setup** since October 2025, so the enum is
  this account's surface lagging the product, not a product limitation.
  Re-verified 2026-08-10: the enum still rejects `rust` and `GET` does not offer
  it on the three repositories here that contain Rust. Recorded as pending and
  retryable rather than impossible.

- **Resolution was leaking capabilities across entitlements.** `private_paid`
  is the Advanced Security tier column, so it marks CodeQL, dependency review
  and native secret scanning `available` for the whole tier. The resolver read
  that column whenever *any* add-on was held and applied its entitlement gate
  only to values priced `paid`, so a private repository holding just Secret
  Protection resolved to "you can run CodeQL", and one holding just Code Quality
  resolved to the entire Advanced Security surface. Verified against GitHub's
  own product split: CodeQL code scanning and dependency review on private
  repositories require **Code Security** specifically, and Code Quality is a
  separate licence that unlocks none of it.

  Two corrections: the tier column now keys off the two Advanced Security
  products rather than any add-on, and the entitlement gate applies to every
  `private_paid` capability that names an unlock, not only to `paid` ones. A
  `free` value is never gated, so CodeQL and secret scanning stay available on
  public repositories regardless of add-ons — the first attempt at this fix
  removed them, which the public-profile invariant now prevents.

  Four probe-based invariants join `profile-resolution`: Secret Protection alone
  must not resolve Code Security capabilities and must resolve its own; Code
  Quality alone must resolve nothing from Advanced Security; and the
  zero-entitlement public profile must keep the free surface.

### Added

- **`docs/adr/` records the decisions behind the contracts**, in the estate's ADR
  format, with a generated index. Four entries: the catalog as source of truth
  with docs as a projection; operating modes compiled rather than described;
  absence of evidence as a failure for blocking workflows; and the caller, never
  the library, choosing its runner. Each states what the contract defends
  against, so a later change reverses a decision deliberately rather than by
  accident. `AGENTS.md` and `nddev-repo-orientation` point at them.

- **`scripts/resolve_profile.py` makes a mode selectable, not just declared.**
  `profiles.yml` said what a mode *is* — entitlements, controls, cost — but not
  what you *run* in it, and a mode you cannot turn into a workflow set is a
  description rather than a selection. Give the resolver a repository's shape
  (`--visibility`, `--plan`, and the three add-on flags) or a profile id, and it
  returns the profile, its controls and cost, and the capability/workflow set
  split into run / conditional / unavailable, with the free substitute for
  everything the mode does not entitle.

  Which tier column applies is derived rather than guessed: public repositories
  read `public_oss`, private and internal ones read `private_paid` when any
  add-on is held and `private_free` otherwise. A capability priced `paid` is
  included only when the entitlement that unlocks it is actually on, which is
  what lets the two public profiles — sharing a tier column, differing in
  entitlements — resolve to different programmes (65 vs 64 capabilities).

  Its invariants run in `validate_all` as `profile-resolution`: every profile
  resolves to a non-empty programme and is selectable from its own selectors,
  the full paid profile leaves nothing unavailable, the zero-cost private
  profile genuinely excludes the paid surface, and two profiles sharing a tier
  column may not resolve identically. Verified by breaking each and watching the
  gate name the specific failure. The generated matrix now carries each
  profile's programme size.

- **`catalog/profiles.yml` makes the mode model machine-readable**, with
  `scripts/validate_profiles.py` in `validate_all` and
  `docs/generated/profile-matrix.md` rendered from it.

  The tier model previously existed twice: three columns per capability in
  `capabilities.yml`, and prose in `docs/00`, `docs/16` and `docs/17` describing
  modes the catalog could not express. The prose drifted silently and more than
  once — the $80 envelope named a control that cannot stop anything, and its
  coverage figures had moved on.

  The model declares the axes as **independent** — visibility, base plan, the
  three add-on entitlements, and seven operational controls — rather than as a
  line from free to paid. It carries all eight Code Security / Secret Protection
  / Code Quality combinations so no repository is unplaceable, and four
  operating profiles: `public-free-standalone`, `private-free-max`,
  `public-enterprise-max` and `enterprise-full-private-fixed80`.

  The validator encodes failures that actually happened rather than generic
  schema rules: itemised fixed lines must sum to the declared total; a
  fixed-cost profile may not permit AI credits or Actions overage, nor set
  `code_quality_ai: on_push`; attestations on private repositories require
  Enterprise Cloud and Code Quality requires Team or Enterprise (plan gates, not
  visibility gates); a public profile may not use persistent self-hosted
  runners; private CodeQL requires Code Security. Each rule has a regression
  fixture, and all four headline rules were also verified live by breaking the
  catalog and watching the gate fail.

  Tier prose now references profiles instead of restating them, and `docs/00`
  says outright that where it and the generated matrix disagree, the matrix
  wins — it is validated and the prose is not. `nddev-repo-orientation` and
  `nddev-change-flow` carry the new catalog and the failure it produces, so the
  golden path teaches it rather than leaving it to be discovered.

- **`catalog/runtime-coverage.yml` records `criticality`, and the ledger now
  carries a proof obligation** (schema `nddev-ci-runtime-contract-coverage/v2`).
  It policed whether a *claimed* status was honest but never required a claim,
  so `unverified` — the default — was an unlimited resting state and `ci-gate`
  stayed green over 42 of 46 unproven reusables. Every record now declares
  `release`, `security-blocking`, `required-gate` or `supporting`, and for the
  first two `unverified` is rejected: prove it, mark `static-only` behind an
  executable validator, or take a waiver with an owner and an expiry.
  Classified all 46 — 3 release, 10 security-blocking, 6 required-gate,
  27 supporting. `release-supply-chain.yml` and `release-supply-chain-free.yml`
  became `static-only` behind `check_release_supply_chain.py`, which runs real
  fixtures; the nine security scanners with no executable stand-in took dated
  waivers, staggered one per date from 2026-09-15 to 2027-01-15 so renewals
  never land as one cliff.

  Two properties stop this being ceremony: `PINNED_CRITICALITY` fixes the
  blocking families so the obligation cannot be dodged by relabelling a record
  `supporting`, and the waiver dates are spread. Both directions are covered by
  new fixtures, and verified by hand: expired waiver, security workflow demoted
  to `unverified`, `static-only` naming a missing validator, and the relabel
  dodge each produce exactly one failure.

### Fixed

- **`.claude/CLAUDE.md` named the wrong runtime-proven workflows.** It listed
  `release-supply-chain.yml`, `actionlint.yml` and `zizmor-sarif.yml`; the
  ledger's proven records are `public-dependency-review.yml` and
  `public-scorecard-json.yml`.

- **Every example outside `examples/nddev/` now names its runner, and
  `check_examples.py` enforces it.** 36 example jobs across 37 files inherited
  `runner: amsterdam` from the reusable they call. These are copy-paste
  templates: outside this estate the label never resolves and the job queues
  forever; inside it, on a public repository, inheriting the default puts
  untrusted fork-PR code on trusted private infrastructure. The default is a
  property of the pinned commit, not of the caller, so the caller states it.
  `check_workflow_contracts.py` already enforced this for this repository's own
  self-calls; the rule now reaches the surface we publish to consumers.
  `examples/nddev/` is exempt — it is estate-specific by name.

- **`docs/16-code-quality.md` no longer claims Code Quality has no API.** It
  documents four REST endpoints (`GET`/`PATCH …/code-quality/setup`, findings
  list and detail) and the setup object's fields, so the product's state is
  assertable and drift-checkable by the estate reconciler. Reconciling it is
  still explicitly out of scope for this library — the catalog entry keeps
  `workflow: null` / `example: null`.

- **The Code Quality corrections now reach the catalog, not only the tier doc.**
  `catalog/capabilities.yml` is the source of truth and still carried the
  no-API claim and the undisputed-public-rate claim, as did
  `docs/05-runners.md` (labeled-runner selection), `docs/02-private-free.md`
  and the `ci-consumer-adoption` skill. The capability's `risks` now state the
  dispute, name the REST API, and record that its check runs collide with
  CodeQL default setup on `Analyze (<language>)`. Historical CHANGELOG entries
  are left as written — they record what was believed at the time.

- **The disputed public Code Quality rate is now recorded as disputed.**
  GitHub's product page states "$0 per committer" for public repositories while
  the billing documentation states every active committer consumes a licence
  with no visibility exemption. `github-code-quality-transition` previously
  asserted one side of this. Neither reading may be compiled into a cost; the
  public rate is account-observed until licensing or an invoice settles it. The
  $10 private rate, the Team/Enterprise gate and the once-per-organization
  committer count are unaffected.

- **`teamcity-professional` claimed unlimited build configurations.** The free
  Professional licence caps them at 100 configurations and 10 pipelines
  (+10 per additional agent); only build *time* is unlimited.
- **`pr-hygiene.yml` accepts a `runner` input**, so a caller can move its four
  jobs onto a self-hosted fleet instead of being pinned to `ubuntu-latest`.

  It defaults to `ubuntu-latest`, unlike most reusables here. This workflow is
  driven by `pull_request`, so on a public caller it executes fork-authored
  content; a self-hosted default would hand that content an estate runner
  without the caller ever naming one. Estate callers opt in explicitly, which is
  already the pattern their `go-ci.yml` calls follow.

  `cross-platform-smoke.yml` deliberately gains no such input: its `os_list`
  already *is* a list of runner labels, so a caller wanting a fleet runner passes
  it there and keeps the OS matrix as the single place OS selection lives.

### Changed

- **All 38 product facts dated 2026-07-11 re-verified against their sources and
  re-stamped 2026-08-10.** They shared a single `expires_after: 2026-08-10`, so
  the ledger would have failed `validate_all` in one 38-fact block from
  2026-08-11. New expiries are staggered across 2026-09-04…2026-11-06 by how
  fast each source actually moves, so the largest future refresh is 9 facts.

- **Dead and imprecise fact sources replaced.** `semaphoreci.com` 301s to
  `semaphore.io`; `ubicloud.com/pricing` returns 404. Added the sources that
  actually carry the claim: the artifact-attestations plan gate, the
  self-hosted-runner untrusted-fork warning, and the Harness credit figure.

- **`github-actions-security` gained an inherited-runner rule.** The runner
  audit now covers the runner a caller *inherits* rather than declares: a
  reusable's `runner` default belongs to the pinned commit, so a library that
  defaults it to a private self-hosted label makes every pin bump a silent
  re-routing of untrusted fork code, invisible in the calling repository's diff.
  Public callers must select the runner explicitly; generic reusables must
  require it or default to a hosted label.

- **`azure-pipelines-private` records two newly material conditions:** the
  Microsoft-hosted free tier is not automatic and must be enabled by linking an
  Azure subscription, and public projects are retired and convert to private in
  2027. **`gitlab-open-source-program`** records the annual renewal requirement
  and that the program page does not state the compute-minute accrual period
  unambiguously.
- **`hadolint-ci.yml` now runs a checksum-verified hadolint binary instead of
  `hadolint/hadolint-action`.** The action is a Docker *container action*, and
  the runner starts those itself with a hardcoded `-v /var/run/docker.sock`. A
  self-hosted runner on rootless Docker has no readable socket there, so the job
  failed with `permission denied while trying to connect to the docker API` —
  under this workflow's own `runner: amsterdam` default, which made it broken by
  default for self-hosted callers. No caller-side setting could fix it, because
  the runner and not the workflow chooses that mount. hadolint now downloads
  like actionlint and shellcheck already do: pinned version, SHA256 verified
  against the upstream `checksums.sha256`, installed into `RUNNER_TEMP/bin`
  rather than `/usr/local/bin`. Two new optional inputs, `hadolint_version` and
  `hadolint_sha256`, default to `2.15.1` and its published digest. Behaviour is
  otherwise unchanged: `recursive` performs the same `**/<dockerfile>`
  expansion, `ignore` still accepts comma- or space-separated codes, and
  `failure_threshold` maps to `--failure-threshold` as before. A runner-contract
  step now fails fast when the runner is not Linux X64, since the pinned digest
  covers only that binary.

- **`public-codeql.yml` now provisions the repository Go toolchain for Go
  analysis.** The language matrix conditionally runs the digest-pinned
  `actions/setup-go` against `go.mod` with cache writes disabled, so persistent
  runners cannot fail CodeQL extraction merely because `go` is absent from
  their ambient `PATH`.

- **`go-ci.yml` now exposes a backward-compatible `cache` input.** It defaults
  to `true` for hosted and existing callers; warm self-hosted runners with
  independently owned Go caches can set `cache: false` to avoid redundant or
  conflicting `actions/setup-go` cache restore/save work.

- **Persistent self-hosted checkout jobs now isolate global Git config.**
  `actionlint`, `cross-platform-smoke`, `private-static`, `public-codeql`,
  `secret-scan`, and `zizmor-no-sarif` point `GIT_CONFIG_GLOBAL` at a
  job-unique file under `runner.temp`, preventing ambient runner Authorization
  headers from being combined with the scoped `actions/checkout` token. Caller
  inputs and permissions are unchanged. All public `ci-workflows` self-callers
  now also select `ubuntu-latest` explicitly, so private-consumer runner
  defaults can never route this public repository to the self-hosted fleet.

- **The tool catalog now matches the already-merged Coveralls 2.3.8 and
  actions/stale 11.0.0 workflow pins.** Dependabot advanced the executable
  refs without updating their catalog-owned versions and SHA records, which
  made the catalog validator correctly fail. Runtime evidence for
  `secret-scan.yml` and `zizmor-sarif.yml` is also honestly downgraded after
  their checkout-byte change instead of retaining stale proof digests.

- **`public-codeql.yml` gained `build_command` and `post_analyze_command` inputs.**
  `build_command` runs a custom build (e.g. `cargo build --workspace --locked`)
  instead of autobuild. `post_analyze_command` runs a hook after analysis with
  `if: always()`, enabling repo-local extraction-diagnostics collection.
- **`public-scorecard.yml` gained `filter_rule_ids`,
  `normalize_placeholder_uris`, and `upload_sarif_on_forks` inputs.**
  `filter_rule_ids` drops non-actionable checks (MaintainedID, CodeReviewID,
  CIIBestPracticesID). `normalize_placeholder_uris` fixes non-URI-safe
  artifact locations. `upload_sarif_on_forks` gates fork-PR uploads.

- **`rust-ci.yml` gained 5 new inputs for full Rust CI coverage.**
  `test_matrix_os` (JSON array for OS matrix testing), `fmt_command` (dedicated
  rustfmt job), `clippy_command` (dedicated clippy lint job), `msrv_toolchain`
  + `msrv_command` (minimum supported Rust version check). All default to
  empty — existing callers are unaffected.

### Added

- **`release-promotion-gate.yml` binds public publication to exact private
  promotion evidence.** The read-only reusable accepts only a GitHub-verified
  signed annotated numeric tag whose canonical `nddev-release-promotion/v1`
  JSON names the exact public commit, module version, private control-plane
  commit, registry digest, and a complete non-expired evidence set. It rejects
  unsigned, lightweight, stale, wrong-repository/SHA/version, failed,
  incomplete, malformed, and unauthorized-substitute records. A macOS x64
  artifact-validation substitute is accepted only when it states its residual
  limitations. The publish job remains separate and must declare
  `needs: promotion`, so it receives no write permissions until this gate
  succeeds.

- **`coverage-gate.yml` gained an install command and artifact upload.** Four
  new inputs: `install_command` (string, default `''` — runs before the coverage
  command to install the coverage tool, e.g. `cargo install cargo-llvm-cov`;
  skipped when empty), `upload_artifact` (boolean, default false),
  `artifact_name` (string, default `coverage-report`), and `artifact_path`
  (string, default `''` — required when `upload_artifact` is true). When
  `upload_artifact` is true, the report is uploaded as a workflow artifact via
  `actions/upload-artifact`. Off by default, so existing callers are unaffected.

- **`actionlint.yml` grew optional shellcheck support.** Three new inputs —
  `enable_shellcheck` (boolean, default false), `shellcheck_version` (default
  `0.11.0`), and `shellcheck_sha256` (SHA256 of
  `shellcheck-v<ver>.linux.x86_64.tar.xz`, required when enabled). When
  `enable_shellcheck` is true, the workflow downloads the checksum-verified
  shellcheck tarball (verifying with sha256sum) and runs it on tracked `*.sh`
  files after actionlint. Off by default, so existing callers are unaffected.

- **`pr-hygiene.yml` grew pr-title and stale options.** The `pr-title` job now
  accepts `pr_title_types` (comma-separated conventional-commit types, converted
  to the newline-delimited `types:` the action expects; empty keeps the action
  defaults), `pr_title_require_scope`, and `pr_title_subject_pattern`. The
  `stale` job now accepts `stale_operations_per_run`,
  `stale_exempt_issue_labels`, and `stale_exempt_pr_labels`. All default to the
  prior behaviour, so existing callers are unaffected.

- **`clusterfuzzlite.yml` — ClusterFuzzLite PR (code-change) and batch fuzzing.**
  Reusable CFLite workflow with sanitizer matrix, configurable mode, fuzz
  duration, and SARIF output. Distinct from `fuzzing.yml` (cargo-fuzz).

- **`rust-supply-chain.yml` — cargo-deny + cargo-audit + cargo-machete.** Three
  independently-toggleable jobs for Rust supply-chain health: deny
  (bans/licenses/advisories/sources), audit (RustSec vulnerability database),
  and machete (unused dependency detection). All tool versions are
  caller-overridable with estate-verified SHA-pinned defaults.

- **`gate.yml` — caller-named gate job for branch-protection required-check contexts.**
  Reusable workflows produce job names like `rust (1.94.0)` or `CodeQL (rust)`
  that don't match the short, exact context names branch protection expects
  (`CI`, `CodeQL`, `Scorecard`). This workflow emits a single job whose `name:`
  is the caller-supplied `check_name`, runs `if: always()`, and validates that
  every declared upstream job result is `success` (with an `allow_skipped`
  allow-list for jobs like coverage that may be toggled off). Enables migration
  of repos with branch-protection required checks to reusable workflows.

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
