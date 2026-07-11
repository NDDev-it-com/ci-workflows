# Supply chain — SLSA, SBOM, and artifact attestations

This is the heart of the library: producing verifiable evidence of *what was
built, from what source, by which workflow*. `release-supply-chain.yml`
implements the whole chain — deterministic archive, SPDX SBOM, canonical
release notes, `SHA256SUMS`, Sigstore-backed attestations, and an immutable
GitHub Release. `release-supply-chain-free.yml` is the same closed pipeline
without the attestation steps, for repositories where the platform withholds
attestations.

## Plan availability

GitHub **Artifact Attestations** are available to **public repositories on
every GitHub plan**. Private and internal repositories require **GitHub
Enterprise Cloud**: this is a plan gate, not part of GHAS/Code Security, and
attestations are not supported on GitHub Enterprise Server at all. On a
private Free, Pro, or Team repository the `actions/attest*` steps fail before
the release is created, so the private-free tier calls
[`release-supply-chain-free.yml`](02-private-free.md) — identical archive,
SBOM, canonical notes, manifest, and `SHA256SUMS`, no attestation actions,
`contents: write` only, and `slsa_build_level: null` in the manifest. On GHEC,
private-repository attestations use GitHub's internal Sigstore instance (same
codebase, no public transparency log) instead of the Sigstore Public Good
Instance.

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
releases built through it qualify to claim **SLSA Build L3**. These claims
apply where attestations are plan-eligible (see above);
`release-supply-chain-free.yml` deliberately claims nothing
(`slsa_build_level: null`).

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
  id-token: write          # Sigstore keyless signing
  attestations: write      # record the attestation
  artifact-metadata: write # actions/attest artifact storage record (v4.1.1)
  contents: read           # (write only if the same job also publishes the Release)
```

## Generating the SBOM

Two supported paths:

1. **Checksum-pinned Syft CLI** — the release reusable downloads the exact
   Syft 1.46.0 Linux AMD64/ARM64 archive, verifies its pinned byte size and
   SHA-256, and scans a private extraction of the tracked-source archive. It
   emits SPDX-JSON suitable for attestation and never executes a remote
   installer or scans the wider checkout.
2. **Dependency-graph SBOM export API** — for the repository's *declared*
   dependencies:

```bash
gh api /repos/{owner}/{repo}/dependency-graph/sbom > sbom.spdx.json
```

The API returns SPDX-JSON of declared dependencies; the checksum-pinned Syft
CLI inspects actual build contents. Use the API for a dependency inventory and
the pinned Syft path for a build-artifact SBOM.

## SHA256SUMS

Alongside the archive, SBOM, canonical release notes, and manifest, the release
publishes `SHA256SUMS` covering those other four assets so consumers can verify
byte integrity independently of Sigstore:

```bash
sha256sum -c SHA256SUMS
```

## Verifying attestations

Verify that an artifact was built by the expected repository/workflow:

```bash
# Build provenance for a downloaded file
gh attestation verify my-app-1.2.3.tar.gz -R NDDev-it-com/my-repo

# SBOM attestation for the released artifact — declare the predicate type
gh attestation verify my-app-1.2.3.tar.gz -R NDDev-it-com/my-repo \
  --predicate-type https://spdx.dev/Document/v2.3

# Offline / air-gapped verification
gh attestation verify my-app-1.2.3.tar.gz \
  --bundle attestation.jsonl \
  --custom-trusted-root trusted_root.json
```

## Exporting the repository SBOM

For dependency-graph SBOM export, use:

```bash
scripts/export_repo_sbom.sh NDDev-it-com/my-repo dist/repository.sbom.spdx.json
```

This calls GitHub's Dependency Graph SBOM endpoint and verifies the returned
document is SPDX 2.3 JSON. It complements, but does not replace, the release
SBOM generated by `release-supply-chain.yml`.

## Immutable releases (GA 2025-10-28)

**Immutable releases are GA as of 2025-10-28. Once a release is published, its
assets cannot be modified, deleted, or clobbered.** This changes how you publish:

- `gh release upload --clobber` **fails** against an immutable release — it is
  not a safe fallback and must not be relied on.
- Publish by **creating the release with all assets in one shot** (fail if the
  release already exists), or **create a draft, attach every asset, then
  publish**.
- GitHub still permits an immutable release's title and body to be edited. Use
  the checksummed `release-notes.md` asset as the canonical note record and as
  the initial body source; do not treat mutable release metadata as the
  integrity boundary.

```bash
# One-shot create with all assets; fails if the tag's release already exists
release_dist="${RUNNER_TEMP}/release-dist"
gh release create "$VERSION" \
  --verify-tag \
  --title "$VERSION" \
  --notes-file "$release_dist/release-notes.md" \
  "$release_dist/my-app-${VERSION}.tar.gz" \
  "$release_dist/sbom.spdx.json" \
  "$release_dist/release-notes.md" \
  "$release_dist/release-manifest.json" \
  "$release_dist/SHA256SUMS"
```

```bash
# Or: draft → attach → publish
gh release create "$VERSION" --draft --verify-tag --title "$VERSION"
gh release upload "$VERSION" \
  "$release_dist/my-app-${VERSION}.tar.gz" \
  "$release_dist/sbom.spdx.json" \
  "$release_dist/release-notes.md" \
  "$release_dist/release-manifest.json" \
  "$release_dist/SHA256SUMS"
gh release edit "$VERSION" --draft=false
```

> Any residual `gh release view ... && gh release upload --clobber` fallback is
> dead code on a repo with immutable releases enabled — it will error rather
> than update. Restructure to one-shot create or draft→publish.

See [09 Releases & packages](09-releases-packages.md) for the tag-driven flow.

## The release-supply-chain job at a glance

1. Validate strict numeric SemVer, a safe package name, and a supported Linux
   X64/ARM64 runner before the version input reaches checkout.
2. Check out the exact requested tag without persisted Git credentials, then
   revalidate its one-line `VERSION`, tag context, and tracked changelog
   heading, requiring exactly one match.
3. Expand normalized regular-file selections through literal
   `git ls-files -z` and build a deterministic `tar.gz` from the option-safe NUL
   list.
4. Extract that archive privately, verify its file/digest closure, and generate
   the SPDX SBOM from only that exact payload with checksum-pinned Syft.
5. Materialize non-empty canonical `release-notes.md`, emit
   `release-manifest.json` with source tag/commit identity, compute `SHA256SUMS`,
   and require exactly the five declared regular assets.
6. Attest the archive and the SBOM (Sigstore keyless).
7. Revalidate the remote tag object and publish those five assets in one
   immutable create call, using the canonical notes asset as the release body.

---
Last verified: 2026-07-11
