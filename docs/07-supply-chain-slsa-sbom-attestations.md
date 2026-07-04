# Supply chain — SLSA, SBOM, and artifact attestations

This is the heart of the library: producing verifiable evidence of *what was
built, from what source, by which workflow*. `release-supply-chain.yml`
implements the whole chain — deterministic archive, SPDX SBOM, `SHA256SUMS`,
Sigstore-backed attestations, and an immutable GitHub Release.

## SLSA levels and how we reach Build L3

SLSA (Supply-chain Levels for Software Artifacts) grades build integrity.

| Level | Requirement | Our status |
| --- | --- | --- |
| Build L1 | Provenance exists | ✅ |
| Build L2 | Signed provenance from a hosted build service | ✅ GitHub Artifact Attestations |
| Build L3 | Non-falsifiable provenance; build runs in an isolated, hardened service | ✅ **because the build runs inside a reusable workflow** |

GitHub **Artifact Attestations** provide SLSA **Build L2** out of the box.
**Build L3 is achieved when the build runs inside a reusable workflow**, because
the reusable's identity and isolation make the provenance non-falsifiable by the
calling repository. `release-supply-chain.yml` *is* a reusable workflow, so
releases built through it qualify to claim **SLSA Build L3**.

## Sigstore

Attestations are signed with **Sigstore** keyless signing: a short-lived
certificate is issued against the workflow's OIDC identity, the signature is
recorded in a transparency log, and verification checks the signature and the
identity — no long-lived signing key to manage or leak. This is why the release
job needs `id-token: write`.

## Attestation actions

| Action | Produces | Key inputs |
| --- | --- | --- |
| `actions/attest-build-provenance` | Build provenance for an artifact | `subject-path` |
| `actions/attest-sbom` | SBOM attestation bound to an artifact | `subject-path`, `sbom-path` |
| `actions/attest` | Generic attestation; accepts `sbom-path` since v4 | `subject-path`, optional `sbom-path` / `predicate-*` |

Both approaches are valid:

- **Dedicated actions** — `attest-build-provenance` for the archive plus
  `attest-sbom` for the SBOM. Clearest intent.
- **Generic `actions/attest`** — a single action attesting each subject; since
  v4 it accepts `sbom-path` directly.

The **SBOM must be SPDX or CycloneDX JSON**. The library emits SPDX.

Required permissions for any attestation job:

```yaml
permissions:
  id-token: write        # Sigstore keyless signing
  attestations: write    # record the attestation
  contents: read         # (write only if the same job also publishes the Release)
```

## Generating the SBOM

Two supported paths:

1. **`anchore/sbom-action`** with `format: spdx-json` — scans the build and
   emits an SPDX-JSON SBOM suitable for `attest-sbom`.
2. **Dependency-graph SBOM export API** — for the repository's *declared*
   dependencies:

```bash
gh api /repos/{owner}/{repo}/dependency-graph/sbom > sbom.spdx.json
```

The API returns SPDX-JSON of declared dependencies; `anchore/sbom-action`
inspects actual build contents. Use the API for a dependency inventory and
`sbom-action` for a build-artifact SBOM.

## SHA256SUMS

Alongside the archive and SBOM, the release publishes `SHA256SUMS` so consumers
can verify byte integrity independently of Sigstore:

```bash
sha256sum -c SHA256SUMS
```

## Verifying attestations

Verify that an artifact was built by the expected repository/workflow:

```bash
# Build provenance for a downloaded file
gh attestation verify my-app-1.2.3.tar.gz -R NDDev-it-com/my-repo

# SBOM attestation — declare the predicate type
gh attestation verify sbom.spdx.json -R NDDev-it-com/my-repo \
  --predicate-type https://spdx.dev/Document/v2.3

# Offline / air-gapped verification
gh attestation verify my-app-1.2.3.tar.gz \
  --bundle attestation.jsonl \
  --custom-trusted-root trusted_root.json
```

## Immutable releases (GA 2025-10-28)

**Immutable releases are GA as of 2025-10-28. Once a release is published, its
assets cannot be modified, deleted, or clobbered.** This changes how you publish:

- `gh release upload --clobber` **fails** against an immutable release — it is
  not a safe fallback and must not be relied on.
- Publish by **creating the release with all assets in one shot** (fail if the
  release already exists), or **create a draft, attach every asset, then
  publish**.

```bash
# One-shot create with all assets; fails if the tag's release already exists
gh release create "$VERSION" \
  --verify-tag \
  --title "$VERSION" \
  --notes-file dist/release-notes.md \
  dist/*
```

```bash
# Or: draft → attach → publish
gh release create "$VERSION" --draft --verify-tag --title "$VERSION"
gh release upload "$VERSION" dist/*
gh release edit "$VERSION" --draft=false
```

> Any residual `gh release view ... && gh release upload --clobber` fallback is
> dead code on a repo with immutable releases enabled — it will error rather
> than update. Restructure to one-shot create or draft→publish.

See [09 Releases & packages](09-releases-packages.md) for the tag-driven flow.

## The release-supply-chain job at a glance

1. Harden runner + checkout (`fetch-depth: 0`, `persist-credentials: false`).
2. Validate version equals the tag and the `VERSION` file.
3. Build a **deterministic** `tar.gz` (`--sort=name`, fixed `--mtime`, numeric
   owner) so the archive is reproducible.
4. Emit `release-manifest.json` and an SPDX `sbom.spdx.json`.
5. Compute `SHA256SUMS`.
6. Attest the archive and the SBOM (Sigstore keyless).
7. Publish the immutable GitHub Release with all assets.

---
Last verified: 2026-07-04
