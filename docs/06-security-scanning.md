# Security scanning

The library layers several complementary scanners. Each catches a different bug
class; none subsumes another. This doc maps scanners to workflows and tiers.

| Scanner | Catches | Workflow | Free on private? |
| --- | --- | --- | --- |
| CodeQL | Code vulnerabilities (semantic) | `public-codeql.yml` | ❌ paid (GHAS) |
| zizmor | Actions workflow security anti-patterns | `zizmor-sarif.yml` / `zizmor-no-sarif.yml` | ✅ (no-sarif variant) |
| gitleaks | Secrets in code + git history | `secret-scan.yml` | ✅ |
| Native secret scanning | Known secret patterns + push protection | repo setting | ❌ paid |
| actionlint | Workflow YAML errors | `actionlint.yml` | ✅ |
| Trivy / Semgrep / OSV-Scanner | Containers / SAST / OSV deps | optional | ✅ (external tools) |

<a id="codeql"></a>
## CodeQL

CodeQL builds a queryable database from your code and runs security queries
against it. It supports major compiled and interpreted languages plus `actions`
(workflow analysis). Results appear in the **Code scanning** tab as alerts, and
GHAS repos get **Copilot Autofix** suggestions on those alerts.

- Free on public; paid (GHAS) on private.
- The reusable runs a language matrix; default query suite is
  `security-and-quality`.
- Requires `security-events: write` on the caller job.

See [01 Public OSS free](01-public-oss-free.md#codeql) for the caller example.

## SARIF upload

SARIF is the standard format for static-analysis results. Any tool that emits
SARIF can upload to code scanning via `github/codeql-action/upload-sarif`, which
renders findings as alerts. SARIF upload requires code scanning, which is **free
on public and paid on private** — hence the zizmor split below.

<a id="zizmor"></a>
## zizmor

zizmor is a static analyzer specifically for **GitHub Actions security**,
catching classes that actionlint and CodeQL miss:

- **Template injection** — untrusted `${{ ... }}` interpolated into a `run:`
  script (see [security/pull-request-target.md](security/pull-request-target.md)).
- **Credential persistence** — `actions/checkout` leaving credentials on disk
  (`persist-credentials: true`).
- **Excessive permissions** — jobs granting more `GITHUB_TOKEN` scope than used.
- **Impostor / confusable action refs** — refs that look legitimate but resolve
  to an unexpected commit, and unpinned/mutable references.

The library ships two callers:

| Workflow | Behavior | Tier |
| --- | --- | --- |
| `zizmor-sarif.yml` | Runs zizmor, **uploads SARIF** to code scanning, fails on findings | Public / GHAS |
| `zizmor-no-sarif.yml` | Runs zizmor, **fails the job** on findings, no upload | Private-free |

Inputs (both): `persona` (`regular` default, `pedantic`, `auditor`),
`min_severity` (default `low`), `target`, `enable_harden_runner`. The `sarif`
variant additionally uploads to code scanning and needs `security-events:
write`.

> This repository's own `ci.yml` runs zizmor with the **default `regular`
> persona** against its own workflows.

## gitleaks

gitleaks scans the working tree **and full git history** for secrets, using a
digest-pinned container image with `--redact` (never prints matched values) and
`--exit-code 1` (fails on any finding). It is free on public and private, making
it the private-tier stand-in for native secret scanning. The caller uses
`fetch-depth: 0` so history is available.

## Native secret scanning + push protection

GitHub's native secret scanning detects known provider token formats; **push
protection** blocks a push that introduces one. Free on public, paid (Secret
Protection) on private. It is a repository setting, not a workflow, and
complements gitleaks (native = live provider patterns + push-time blocking;
gitleaks = history-aware, custom rules, portable to private-free).

## External scanner options

These are not shipped as first-class reusables but integrate cleanly (via
`private-static.yml` or `container-ci.yml`) and are all free/OSS:

| Tool | Use | Where |
| --- | --- | --- |
| **Semgrep** | Lightweight multi-language SAST with custom rules | `private-static.yml` command |
| **Trivy** | Container/image + IaC + dependency vulnerability scan | `container-ci.yml` |
| **OSV-Scanner** | Vulnerabilities from the OSV database across lockfiles | `private-static.yml` command |

All three can emit SARIF for upload on public/GHAS repos. See
[13 External tools](13-external-tools.md).

---
Last verified: 2026-07-04
