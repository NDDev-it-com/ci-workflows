---
name: nddev-release-flow
description: The end-to-end release procedure for nddev-ci-workflows — version prep, the signed SemVer tag, the immutable-release verification checklist, and the post-release runtime-coverage re-promotion. Invoke when cutting or verifying a release. Requires an authorized maintainer.
license: AGPL-3.0-or-later
compatibility: Codex and Agent Skills compatible; OpenCode discovers .agents/skills. Generate .claude/skills mirrors for Claude Code.
metadata:
  version: 1.0.0
  owner: NDDev
  status: proposed
  reviewed_at: '2026-07-12'
---

# Releasing nddev-ci-workflows

Publishing a release is outward-facing and irreversible — do it only with
maintainer authorization. New to the repo? Read `nddev-repo-orientation` and
`nddev-change-flow` first.

## Release model

A release is triggered by a maintainer **pushing a SemVer tag**. The self
`release.yml` then calls `release-supply-chain.yml`, which validates a
byte-exact `VERSION`, finds a single matching `CHANGELOG.md` heading, and
publishes **five immutable checksummed assets in one `gh release create`**: the
tracked-source archive, `sbom.spdx.json`, `release-notes.md`,
`release-manifest.json`, and `SHA256SUMS`.

Releases are **immutable** — never re-publish or `gh release upload --clobber`.
A mistake ships in the next version, never as an edit to a published one.

## Step 1 — version prep (a normal PR)

1. Bump `VERSION` to `X.Y.Z` (strict numeric SemVer, no leading zeros, one
   LF-terminated line).
2. In `CHANGELOG.md`, insert a `## [X.Y.Z] - YYYY-MM-DD` heading directly under
   `## [Unreleased]`, moving the accumulated entries beneath it and leaving
   `[Unreleased]` empty. Use today's date; the release validator matches the
   version, not the date, but keep it honest.
3. Choose the number: this is `0.x`, so a **breaking or fail-closed contract
   change lands as a minor bump**; pure fixes/docs are a patch.
4. Confirm consistency and gate, then PR + squash-merge:

```bash
cat VERSION
grep -c '^## \[X.Y.Z\]' CHANGELOG.md      # must be exactly 1
python3 scripts/validate_all.py
python3 scripts/generate_docs.py --check
```

## Step 2 — cut the signed tag

After the prep PR is merged, tag the merged commit on `main` (SSH signing is
configured in this checkout):

```bash
git checkout main && git pull --ff-only
cat VERSION                                # must equal the tag you are about to cut
git tag -s X.Y.Z -m "nddev-ci-workflows X.Y.Z"
git tag -v X.Y.Z                           # expect a Good signature
git push origin X.Y.Z                      # this triggers release.yml
```

## Step 3 — monitor and verify

Watch the run, then verify the published release from its own bytes — do not
trust that it succeeded:

```bash
gh run list --workflow release.yml --limit 1
D=$(mktemp -d); gh release download X.Y.Z -D "$D"
(cd "$D" && shasum -a 256 -c SHA256SUMS)   # every non-checksum asset OK
```

Verification checklist:

- **Assets**: exactly the five above; `SHA256SUMS` verifies.
- **Manifest** (`release-manifest.json`): `slsa_build_level` is `3` for the
  attested variant (`null` for the free variant); `source_commit` equals the
  tag's peeled commit; `required_artifacts` lists the exact closure.
- **SBOM**: `sbom.spdx.json` creator is the pinned Syft version (check
  `creationInfo.creators`).
- **Attestations** (attested variant): both verify —

  ```bash
  A="$D/<package>-X.Y.Z.tar.gz"
  gh attestation verify "$A" -R OWNER/REPO; echo "provenance EXIT=$?"
  gh attestation verify "$A" -R OWNER/REPO --predicate-type https://spdx.dev/Document; echo "sbom EXIT=$?"
  ```

  `EXIT=0` means verified even when the CLI prints no banner in a non-TTY.
- **Release state**: immutable, not draft, not prerelease, marked Latest
  (`gh api repos/OWNER/REPO/releases/tags/X.Y.Z`).
- **Tag**: `git tag -v X.Y.Z` reports a Good signature.

## Step 4 — re-promote the runtime-coverage record

Step 1's prep PR did not change `release-supply-chain.yml`, so the bytes the
release run executed equal the current file. If a prior change had dropped that
record to `static-only` (the "static-only dance" in `nddev-change-flow`), close
the honesty loop now — in a small follow-up PR:

```bash
shasum -a 256 .github/workflows/release-supply-chain.yml   # the new proven_digest
```

Set the record back to `status: runtime-proven`, `last_run:` the release run
URL, `proven_digest:` that sha256, and update the evidence line. Then
`python3 scripts/validate_runtime_coverage.py` must pass (it recomputes and
matches the digest). This lands under `[Unreleased]` for the next release.

## Gotchas

- **`release.yml` never sets `runtime_paths`**, so the optional runtime-bundle
  path (and its `runtime_paths ⊆ archive_paths` guard) is not exercised by the
  self-release — it is covered only by `check_release_supply_chain.py` fixtures.
  A self-release proves the archive / SBOM / attest / publish lanes.
- **`VERSION` and the tag must match exactly**, and there must be exactly one
  matching changelog heading, or the release run fails its own guards.
- The self archive selects the complete library surface (a fixed root set the
  release validator asserts); do not narrow it.
- After the release, confirm `main == origin/main` and the gate is still green.
