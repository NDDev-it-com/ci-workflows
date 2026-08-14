# Language & quality packs (July 2026 expansion)

This page documents the reusable packs added in the July 2026 expansion. Every
pack follows the library conventions (top-level `permissions: {}`, SHA-pinned
actions with version comments, env-indirected caller commands, `timeout-minutes`,
and an explicit private-free-safe action surface) and is validated by
`scripts/validate_all.py`. The
machine-readable source of truth is
[`catalog/capabilities.yml`](../catalog/capabilities.yml); the full matrix is in
[generated/capability-matrix.md](generated/capability-matrix.md).

Tier legend: **Public** = free on public repos; **Private-free** = free on
private repos (no paid GHAS); **Private-paid** = available with GHAS. Language
build packs consume metered runner minutes on private repos (marked
*conditional* in the catalog) but need no paid feature. They contain no
Harden-Runner reference, so private callers do not need a disable toggle.

## Language packs

Dual-tier, caller-command-driven with sensible defaults.

| Pack | Workflow | Example |
| --- | --- | --- |
| Dart/Flutter | `dart-flutter-ci.yml` | [dart-flutter](../examples/languages/dart-flutter.yml) |
| C/C++ | `cpp-ci.yml` | [cpp](../examples/languages/cpp.yml) |
| Qt | `qt-ci.yml` | [qt](../examples/languages/qt.yml) |
| Kotlin/Android | `kotlin-android-ci.yml` | [kotlin-android](../examples/languages/kotlin-android.yml) |
| Swift | `swift-ci.yml` | [swift](../examples/languages/swift.yml) |
| R | `r-ci.yml` | [r](../examples/languages/r.yml) |
| HTML/CSS/web | `web-ci.yml` | [web](../examples/languages/web.yml) |
| SQL | `sql-ci.yml` | [sql](../examples/languages/sql.yml) |

The Dart/Flutter, Kotlin/Android, and Qt callers above deliberately retain each
reusable workflow's default resolve/build/test commands, so the fixture estate
exercises the defaults a consumer inherits rather than a bespoke invocation. Pin
an exact Flutter or Qt release: a mutable channel selector resolves to different
bytes on different days and cannot be evidence of anything.

Each of the three emits a **runtime receipt** as a `workflow_call` output. The
receipt is a discriminated record — `kind` names the pack, `sections` lists what
that run actually produced — and it is deliberately generic. A caller who takes
a documented "Empty to skip" option simply gets a receipt without that section;
the reusable never requires a Gradle wrapper, an Android SDK, an APK, a module
named `app`, or dependency-verification metadata, because none of those are
things a reusable workflow may demand of an arbitrary project. Android also
reports `untrusted_roots`, which keeps "no SDK on this runner" distinct from "an
SDK I will not vouch for".

Provenance in the receipt names the **callee**, via
`job.workflow_repository` / `job.workflow_sha` / `job.workflow_file_path`. Inside
a called reusable every `github.*` value describes the *caller*, so anything
derived from `github.workspace` or `github.workflow_ref` would describe the
consumer's tree instead of the workflow that ran.

Assertions specific to this repository's fixtures — the exact task graph, the
required SDK platform and build-tools, the APK, the dependency locks, the
verification metadata — live in the observer job of
`runtime-fixtures-languages.yml` and in `check_sdk_runtime_fixtures.py`, never in
the reusable. The observer rejects a missing, skipped, or partial caller result.
Provisioning duration is telemetry, not a correctness threshold.

All three SDK lanes run in the estate and all three are recorded as
`runtime-proven`. A companion job regenerates the Android dependency closure
from a clean tree on every run and fails if it differs from what is committed,
so the locks and verification metadata cannot rot unnoticed.

All three SDK packs provision their own toolchain rather than delegating to a
vendored setup action. Flutter resolves Google's published release manifest and
verifies the archive against the SHA-256 it publishes; Qt drives a pinned
`aqtinstall` directly. Both used to be refused during `Set up job` in any
repository enforcing full-SHA action pinning — the control this library
recommends — because their vendored actions named nested actions by tag.
`check_transitive_action_pins.py` reports that class for any action in the
advisory sweep, and currently reports the tree clean.

These join the existing Python, Node, Go, Rust, Java, .NET, container, and
Terraform packs. Swift defaults to a macOS runner (10x minute multiplier); its
SwiftLint step runs on macOS only.

The Go pack checks out one commit by default. Callers whose validation reads
Git ancestry or pull-request merge parents must set `fetch_depth: 0`; the
default remains `1` for backward compatibility and faster tree-only builds.
`cache` likewise defaults to `true`. A warm self-hosted caller may set it to
`false` when that runner independently owns its module/build caches, avoiding a
second cache layer restoring archives over an already populated tree.

## Quality gates

| Pack | Workflow | Tiers | Example |
| --- | --- | --- | --- |
| Coverage (Codecov/Coveralls) | `coverage-gate.yml` | all (token on private) | [coverage-gate](../examples/quality/coverage-gate.yml) |
| Docs quality (lychee/typos/markdownlint) | `docs-quality.yml` | free everywhere | [docs-quality](../examples/quality/docs-quality.yml) |
| PR hygiene (commitlint/PR-title/labeler/stale) | `pr-hygiene.yml` | free everywhere | [pr-hygiene](../examples/quality/pr-hygiene.yml) |

## Free security (SAST / SCA / IaC)

Free on **every** tier, including private-free where CodeQL and dependency review
are paid GHAS. All are gate-only (no SARIF upload, so no `security-events`
permission is required).

| Pack | Tool | Workflow | Example |
| --- | --- | --- | --- |
| SAST | Semgrep OSS | `semgrep-ci.yml` | [semgrep](../examples/security/semgrep.yml) |
| SCA | OSV-Scanner | `osv-scan.yml` | [osv-scan](../examples/security/osv-scan.yml) |
| SCA | Grype | `grype-scan.yml` | [grype-scan](../examples/security/grype-scan.yml) |
| Dockerfile | hadolint | `hadolint-ci.yml` | [hadolint](../examples/security/hadolint.yml) |
| IaC | Checkov | `iac-scan.yml` | [iac-scan](../examples/security/iac-scan.yml) |

## Advanced testing

| Pack | Workflow | Example |
| --- | --- | --- |
| Mutation testing (mutmut/cargo-mutants/Stryker) | `mutation-testing.yml` | [mutation-testing](../examples/testing/mutation-testing.yml) |
| Fuzzing (cargo-fuzz; ClusterFuzzLite noted) | `fuzzing.yml` | [fuzzing](../examples/testing/fuzzing.yml) |
| Benchmark + regression alert (history publish) | `benchmark.yml` | [benchmark](../examples/testing/benchmark.yml) |
| Benchmark regression check (read-only compare) | `benchmark-compare.yml` | [benchmark-compare](../examples/testing/benchmark-compare.yml) |

## Level-3 opt-in (self-contained examples)

Delivered as self-contained caller examples (no reusable workflow), since they
wrap fast-moving third-party services and are opt-in.

| Pattern | Example | Notes |
| --- | --- | --- |
| AI code review | [ai-review](../examples/level3/ai-review.yml) | Claude Code Action; CodeRabbit (free OSS) / Qodo alternatives. Advisory — human review stays the merge gate. |
| Release automation | [release-please](../examples/level3/release-please.yml) | Complements the tag-driven attested release; changesets for monorepos. |

---
Last verified: 2026-07-10
