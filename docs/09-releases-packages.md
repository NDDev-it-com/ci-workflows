# Releases and packages

This doc covers the release flow — from a SemVer tag to an immutable, attested
GitHub Release — and package publication to GHCR, npm, and PyPI using OIDC
trusted publishing (no long-lived tokens).

## Tag-driven release flow

Releases are **tag-driven**. Pushing a numeric SemVer tag (`X.Y.Z`) triggers the
release entrypoint, which resolves and validates the version and then calls the
supply-chain reusable.

```text
push tag X.Y.Z
  └─ release.yml (resolve + validate)
      └─ release-supply-chain.yml
          ├─ tracked-source archive
          ├─ exact-payload SPDX SBOM
          ├─ canonical release notes
          ├─ manifest + SHA256SUMS
          ├─ Sigstore attestations
          └─ immutable GitHub Release
```

`release.yml` validates three things before publishing:

1. The version is numeric SemVer `X.Y.Z` with no leading zeros.
2. `VERSION` is exactly that value plus one trailing LF, with no other bytes.
3. `CHANGELOG.md` has exactly one matching `## [X.Y.Z]` section.

The reusable then checks out `refs/tags/X.Y.Z` itself. Each `archive_paths`
selection must be a normalized relative path that matches the literal Git
index. Directory selections expand to tracked descendants only; untracked
build output is excluded. Empty, unmatched, absolute, traversing, option-like,
control-character, duplicate, symlink, submodule, non-regular, or
dirty-worktree inputs fail closed. Input SemVer is validated before checkout;
after checkout, the reusable revalidates the exact tag's `VERSION`, tag context,
and exactly one tracked `CHANGELOG.md` heading when that file is present.

### Consumer caller

```yaml
# .github/workflows/release.yml
name: release
on: { push: { tags: ["[0-9]+.[0-9]+.[0-9]+"] } }
permissions: {}
jobs:
  publish:
    permissions:
      contents: write
      id-token: write
      attestations: write
      artifact-metadata: write
    uses: NDDev-it-com/nddev-ci-workflows/.github/workflows/release-supply-chain.yml@<full-sha>
    with:
      version: ${{ github.ref_name }}
      package_name: my-repo
      archive_paths: "README.md LICENSE VERSION CHANGELOG.md src"
```

The attested caller above requires a **public repository (any plan)** or a
**private repository on GitHub Enterprise Cloud** — Artifact Attestations are
plan-gated on private/internal repos. Private Free/Pro/Team repositories call
`release-supply-chain-free.yml` instead, with `permissions: { contents: write }`
only; it publishes the same five checksummed assets without attestation steps
(see [`examples/release/private-free-release.yml`](../examples/release/private-free-release.yml)
and [07 Supply chain](07-supply-chain-slsa-sbom-attestations.md)).

## Immutable releases

**Immutable releases are GA (2025-10-28): published assets cannot be modified,
deleted, or clobbered.** Publish with **one-shot create** (all assets at once,
fail if it exists) or **draft → attach → publish**. `gh release upload
--clobber` **fails** on an immutable release — never rely on it. Full guidance
and commands: [07 Supply chain](07-supply-chain-slsa-sbom-attestations.md#immutable-releases-ga-2025-10-28).

The release has exactly five assets: the tracked-source archive, its SPDX SBOM,
canonical `release-notes.md`, `release-manifest.json`, and `SHA256SUMS`. The
manifest declares that complete set and records the source tag object plus
peeled commit; the checksum file covers the other four assets. The same
changelog-derived or explicit canonical notes file is used as the initial
release body. GitHub permits an immutable release's title and body to be edited,
so consumers should treat the checksummed notes asset, not release metadata, as
the integrity boundary. Checksum-pinned Syft scans an extracted copy of the
exact archive, not the wider caller checkout, and the remote tag object is
revalidated immediately before publish.

### Migrating from 0.4.x to 0.5.0

Remove `sbom_source_path`, select a Linux X64/ARM64 runner, provide an exact
LF-terminated `VERSION`, and restrict `archive_paths` to normalized tracked
regular-file selections. An explicit `notes_file` must be tracked, regular, and
not a symlink. These are intentional breaking changes to close archive/SBOM and
immutable-release integrity gaps.

`0.5.1` preserves that caller contract and adds canonical release notes to the
immutable manifest/checksum boundary.

## CHANGELOG-driven notes

Release notes are extracted from the `## [X.Y.Z]` section of `CHANGELOG.md` (or
from a regular non-symlink `notes_file` tracked by the release tag). The result
must contain non-whitespace UTF-8 content and becomes both the checksummed
`release-notes.md` asset and the initial release body. Keep a
Keep-a-Changelog-style file with an `[Unreleased]` section that you promote to a
version on release. A release must provide one of those two non-empty sources.

## GHCR (container packages)

GitHub Container Registry hosts images at `ghcr.io/OWNER/IMAGE`. Public packages
are free and world-readable. Push from CI with the built-in token:

```yaml
- name: Log in to GHCR
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
    GH_ACTOR: ${{ github.actor }}
  run: >-
    echo "$GH_TOKEN" |
    docker login ghcr.io --username "$GH_ACTOR" --password-stdin
- name: Push image
  env:
    IMAGE: ghcr.io/${{ github.repository }}:${{ github.ref_name }}
  run: docker push "$IMAGE"
```

Grant `packages: write` on the job. Attest the image with
`attest-build-provenance` (subject = image digest). Container builds are covered
by `container-ci.yml` (see [13 External tools](13-external-tools.md)).

## npm / PyPI trusted publishing via OIDC

Prefer **trusted publishing**: the registry verifies the workflow's OIDC
identity and mints a short-lived credential at publish time. **No long-lived npm
or PyPI token is stored** as a secret.

- **PyPI** — configure a trusted publisher (repo + workflow) in the PyPI project
  settings, then publish with `id-token: write` and no `password`.
- **npm** — configure the package for trusted publishing (OIDC) and publish from
  the authorized workflow without an `NPM_TOKEN`. npm trusted publishing
  currently supports GitHub-hosted runners, not self-hosted runners.

Copy-paste examples:

- [`examples/release/npm-trusted-publishing.yml`](../examples/release/npm-trusted-publishing.yml)
- [`examples/release/pypi-trusted-publishing.yml`](../examples/release/pypi-trusted-publishing.yml)

This eliminates the most common package-registry compromise vector (leaked
long-lived publish tokens). See
[10 Deployments & environments](10-deployments-environments.md#cloud-oidc) for
the same pattern applied to cloud providers.

---
Last verified: 2026-07-11
