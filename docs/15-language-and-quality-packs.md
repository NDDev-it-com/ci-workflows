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
reusable workflow's default resolve/build/test commands. Pin an exact Flutter or
Qt release for reproducible evidence. Android projects should commit the Gradle
wrapper with its published distribution checksum, dependency locks, and strict
verification metadata covering the complete default `./gradlew build` graph.
The local provenance generator strips ambient Android/JDK roots, derives them
from verified `java` and `sdkmanager` executables on its clean `PATH`, then
injects only coherent JDK 21 and SDK roots into the build child.
Root validation walks directory identities without following symlinks. On
Darwin, only the operating system's identity-equivalent `/var` → `/private/var`
namespace alias is accepted; owned-root symlinks and alternate aliases fail.
The reusable emits a redacted evidence receipt; fixture observers reject a
missing/skipped caller, toolchain drift, empty test result, or substituted
command. Provisioning duration is telemetry, not a correctness threshold.

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
