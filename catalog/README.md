# Capability catalog

This directory is the **machine-readable source of truth** for the capabilities,
external tools, and deprecations of `ci-workflows`. Human-facing docs under
`docs/` are mirrors of this catalog, not the other way around.
`scripts/validate_catalog.py` enforces the schema and internal consistency
defined below (required keys, key order, enum membership, and cross-file
references).

**Last verified: 2026-07-11**

## Files

| File | Top-level key | Purpose |
| --- | --- | --- |
| `capabilities.yml` | `capabilities:` | Every CI/CD, security, supply-chain, and governance capability with tier availability. |
| `tools.yml` | `tools:` | External actions, CLIs, containers, and services referenced by the workflows, with pins. |
| `deprecations.yml` | `deprecations:` | Retiring, deprecated, and removed capabilities and the migration path. |
| `schema/capability.schema.yaml` | JSON Schema | Machine-readable shape for `capabilities.yml`; `scripts/validate_catalog.py` is the enforcing validator. |

## Naming note

`workflow:` paths are the canonical on-disk inventory. `zizmor` is intentionally
split into `zizmor-sarif.yml` (public/GHAS SARIF upload) and
`zizmor-no-sarif.yml` (private-free, no `security-events: write`). Language and
stack packs are materialized workflows, not placeholders.

## Generated mirrors

`scripts/generate_docs.py` derives small, reviewable mirrors from this catalog:

- `docs/generated/capability-matrix.md`
- `docs/generated/workflow-inventory.md`

Run `python3 scripts/generate_docs.py --check` before release; `ci.yml` runs it
through `scripts/validate_all.py` so generated docs cannot drift from the
catalog or workflow tree.

## `capabilities.yml` schema

Each entry under `capabilities:` uses exactly these keys, in this order. Every
key is always present; use `null` or `[]` when not applicable.

| Key | Type | Notes |
| --- | --- | --- |
| `id` | string | kebab-case, unique across the file. |
| `name` | string | Human-readable name. |
| `cluster` | enum | One of: `actions-core`, `runners`, `security-scanning`, `supply-chain`, `governance`, `releases-packages`, `deployments`, `observability`, `community-dx`, `external-tools`, `ai-agentic`. |
| `status` | enum | One of: `ga`, `preview`, `deprecated`, `retiring`, `planned`. |
| `public_oss` | enum | Availability on public OSS repos: `free`, `paid`, `unavailable`, `conditional`. |
| `private_free` | enum | Availability on private repos on the free plan: `free`, `paid`, `unavailable`, `conditional`. |
| `private_paid` | enum | Availability on private repos on a paid plan: `available`, `unavailable`, `conditional`. |
| `workflow` | string \| null | Repo-relative workflow path, or `null` for platform features. |
| `example` | string \| null | Repo-relative example path, or `null`. |
| `required_permissions` | list | `GITHUB_TOKEN` scopes, e.g. `["contents: read","security-events: write"]`, or `[]`. |
| `required_settings` | list | Repo/org settings needed, e.g. `["GitHub Advanced Security enabled"]`, or `[]`. |
| `risks` | list | Short risk strings, or `[]`. |
| `deprecations` | string \| null | Deprecation note, or `null`. |
| `last_verified` | string | ISO date, `"2026-07-04"`. |
| `sources` | list | Authoritative URLs (official GitHub / project docs). |

### Tier semantics

- `public_oss` / `private_free` use `free | paid | unavailable | conditional`.
- `private_paid` uses `available | unavailable | conditional`.
- `conditional` means "available but gated" — e.g. requires an opt-in, a preview
  enrollment, a paid add-on plan, metered runner minutes, or a security caveat.
  Details belong in `required_settings` or `risks`.

## `tools.yml` schema

Each entry under `tools:`:

| Key | Type | Notes |
| --- | --- | --- |
| `id` | string | kebab-case, unique. |
| `name` | string | Tool name. |
| `homepage` | string | Upstream URL. |
| `kind` | enum | One of: `action`, `cli`, `container`, `service`. |
| `current_version` | string \| null | Pinned version tag. |
| `pin` | string \| null | Full commit SHA / digest pin string for actions and containers; `null` for CLIs pinned by version+checksum. |
| `used_by` | list | Workflow paths that consume the tool. |
| `last_verified` | string | ISO date. |

## `deprecations.yml` schema

Each entry under `deprecations:`:

| Key | Type | Notes |
| --- | --- | --- |
| `id` | string | kebab-case, unique. |
| `name` | string | Human-readable name. |
| `status` | enum | One of: `retiring`, `deprecated`, `removed`. |
| `effective_date` | string \| null | ISO date of retirement/removal, or `null` if none announced. |
| `replacement` | string | Recommended replacement capability. |
| `notes` | string | Migration context. |
| `sources` | list | Authoritative URLs. |
