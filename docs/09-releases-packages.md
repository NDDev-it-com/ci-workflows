# Releases and packages

This doc covers the release flow — from a SemVer tag to an immutable, attested
GitHub Release — and package publication to GHCR, npm, and PyPI using OIDC
trusted publishing (no long-lived tokens).

## Tag-driven release flow

Releases are **tag-driven**. Pushing a numeric SemVer tag (`X.Y.Z`) triggers the
release entrypoint, which resolves and validates the version and then calls the
supply-chain reusable.

```
push tag X.Y.Z ──▶ release.yml (resolve + validate) ──▶ release-supply-chain.yml
                                                          ├─ deterministic archive
                                                          ├─ SPDX SBOM + SHA256SUMS
                                                          ├─ Sigstore attestations
                                                          └─ immutable GitHub Release
```

`release.yml` validates three things before publishing:

1. The version is numeric SemVer `X.Y.Z`.
2. It equals the `VERSION` file.
3. `CHANGELOG.md` has a matching `## [X.Y.Z]` section.

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
    uses: NDDev-it-com/nddev-ci-workflows/.github/workflows/release-supply-chain.yml@<full-sha>
    with:
      version: ${{ github.ref_name }}
      package_name: my-repo
      archive_paths: "README.md LICENSE VERSION CHANGELOG.md src"
```

## Immutable releases

**Immutable releases are GA (2025-10-28): published assets cannot be modified,
deleted, or clobbered.** Publish with **one-shot create** (all assets at once,
fail if it exists) or **draft → attach → publish**. `gh release upload
--clobber` **fails** on an immutable release — never rely on it. Full guidance
and commands: [07 Supply chain](07-supply-chain-slsa-sbom-attestations.md#immutable-releases-ga-2025-10-28).

## CHANGELOG-driven notes

Release notes are extracted from the `## [X.Y.Z]` section of `CHANGELOG.md` (or a
`notes_file` input). Keep a Keep-a-Changelog-style file with an `[Unreleased]`
section that you promote to a version on release.

## GHCR (container packages)

GitHub Container Registry hosts images at `ghcr.io/OWNER/IMAGE`. Public packages
are free and world-readable. Push from CI with the built-in token:

```yaml
- run: echo "${{ secrets.GITHUB_TOKEN }}" | docker login ghcr.io -u ${{ github.actor }} --password-stdin
- run: docker push ghcr.io/${{ github.repository }}:${{ github.ref_name }}
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
  the authorized workflow without an `NPM_TOKEN`.

```yaml
jobs:
  publish-pypi:
    permissions:
      id-token: write        # OIDC — mints the short-lived registry credential
      contents: read
    steps:
      - uses: actions/checkout@<full-sha>
      - run: python -m build
      # upload via the trusted-publishing flow; no stored PyPI token
```

This eliminates the most common package-registry compromise vector (leaked
long-lived publish tokens). See
[10 Deployments & environments](10-deployments-environments.md#cloud-oidc) for
the same pattern applied to cloud providers.

---
Last verified: 2026-07-04
