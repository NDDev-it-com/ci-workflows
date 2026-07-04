# Community and developer experience

Community health files make a repository legible to contributors and signal
maturity (they also feed OSSF Scorecard, see
[01 Public OSS free](01-public-oss-free.md#scorecard)). This doc covers the
GitHub-native community surfaces and the health checklist.

## Community health files

| File / feature | Purpose |
| --- | --- |
| `README.md` | What the project is, how to consume it |
| `LICENSE` | Legal terms (this repo: AGPL-3.0-or-later) |
| [`SECURITY.md`](../SECURITY.md) | How to report vulnerabilities privately |
| `CONTRIBUTING.md` | How to propose changes |
| `CODE_OF_CONDUCT.md` | Behavioral expectations |
| `SUPPORT.md` | Where to get help |
| `.github/CODEOWNERS` | Required reviewers per path |
| `.github/ISSUE_TEMPLATE/` | Structured issue intake (issue forms) |
| `.github/PULL_REQUEST_TEMPLATE.md` | PR description scaffold |
| `.github/FUNDING.yml` | Sponsorship links |

This repository already ships `README.md`, `LICENSE`, `NOTICE`, `SECURITY.md`,
and `.github/CODEOWNERS`. The remaining files (`CONTRIBUTING.md`,
`CODE_OF_CONDUCT.md`, `SUPPORT.md`, `.github/ISSUE_TEMPLATE/`,
`.github/PULL_REQUEST_TEMPLATE.md`, `.github/FUNDING.yml`) are the community
surfaces to add for a fully green health check.

## Issue forms

Prefer **issue forms** (YAML in `.github/ISSUE_TEMPLATE/*.yml`) over legacy
Markdown templates — they render structured fields and enforce required input.

```yaml
# .github/ISSUE_TEMPLATE/bug.yml
name: Bug report
description: Report a problem with a reusable workflow
labels: [bug]
body:
  - type: input
    id: workflow
    attributes: { label: Which workflow?, placeholder: actionlint.yml }
    validations: { required: true }
  - type: textarea
    id: what-happened
    attributes: { label: What happened?, description: Include the run URL }
    validations: { required: true }
```

Add `.github/ISSUE_TEMPLATE/config.yml` to point people to Discussions/Security
for non-bug traffic.

## PR templates

`.github/PULL_REQUEST_TEMPLATE.md` prompts for the change summary, linked issue,
and a checklist (SHA-pinned actions, least-privilege permissions, changelog
updated). This nudges contributors toward the library's conventions.

## Discussions, Projects, and Sponsors

- **Discussions** — Q&A and design conversation, keeping issues for actionable
  work.
- **Projects** — roadmap/kanban across issues and PRs.
- **Sponsors / `FUNDING.yml`** — surface funding links on the repo.

## Community health checklist

- [ ] `README.md` with purpose + consumption instructions
- [ ] `LICENSE`
- [ ] `SECURITY.md` with a private reporting channel
- [ ] `CONTRIBUTING.md`
- [ ] `CODE_OF_CONDUCT.md`
- [ ] `SUPPORT.md`
- [ ] `.github/CODEOWNERS`
- [ ] Issue forms + `config.yml`
- [ ] PR template
- [ ] `FUNDING.yml` (if accepting sponsorship)

A complete checklist raises the OSSF Scorecard result and lowers contributor
friction.

---
Last verified: 2026-07-04
