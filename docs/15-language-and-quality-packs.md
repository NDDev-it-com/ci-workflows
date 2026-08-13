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

These join the existing Python, Node, Go, Rust, Java, .NET, container, and
Terraform packs. Swift defaults to a macOS runner (10x minute multiplier); its
SwiftLint step runs on macOS only.

Flutter, Android and Qt have bounded real projects under `tests/fixtures/` and
exact-version callers in the language evidence estate. Their reusable jobs emit
a redacted JSON receipt containing the resolved hosted-runner OS/architecture,
SDK/tool versions, lock or checksum identities, cache identity, commands, test
count and produced-binary digest. Independent observer jobs reject missing,
skipped or partial receipts; a successful static gate is not runtime evidence.
The authored byte contract is `tests/fixtures/sdk-runtime-spec.yml`, and
`sdk-runtime-manifest.json` is generated from the exact checked-in bytes.

For Android, `setup-gradle` explicitly selects its MIT-licensed `basic` cache
provider. This keeps the shared public/private workflow independent of the
separate enhanced commercial cache service. Consumers should commit the Gradle
wrapper distribution checksum, wrapper JAR, dependency lockfiles and dependency
verification metadata. Flutter and Qt callers should use exact SDK versions;
wildcards remain supported for compatibility but are not eligible runtime proof.
Android evidence keeps the requested Java selector separate from observation:
`java_version_input` records the caller contract, while `java_version_resolved`
and the runtime/vendor/VM fields record the actual executable. Matching
launcher and daemon JVM identities come from the exact `./gradlew --version`
invocation; missing or divergent observed identities fail closed. A desired
major is never repeated as though it were a measured runtime.

The Android lock closure follows the canonical Gradle 9.5 single-project
writer format, not the reader's broader legacy tolerance: the exact generated
three-line header is followed by unique lexically ordered dependency records,
then exactly one terminal `empty=` aggregate. Configuration lists are unique
and lexical; extra comments, blank lines, malformed/unknown records, partial
output and records after `empty=` fail closed. The generator validates Gradle's
bytes as emitted and never sorts or rewrites them to satisfy the evidence gate.

The fixture contract is itself executed in a fresh Python 3.13 process from an
unrelated working directory. The repository-wide Python execution gate owns the
complete validator/generator inventory, compiles every file, rejects undefined
globals and unowned imports, prohibits import-time I/O/process/network calls,
and runs each validator's positive/adversarial self-check with isolated import
state and a sanitized environment. This prevents an aggregate in-process import
cache or contributor shell environment from hiding a missing dependency.
Repository-owned isolated execution uses one vocabulary:
`python3 scripts/check_python_execution_contract.py --launch <tool.py> -- <args>`.
The launcher derives whether pinned PyYAML is permitted from the registered
transitive graph; stdlib-only tools do not silently acquire that dependency.

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
Last verified: 2026-08-13
