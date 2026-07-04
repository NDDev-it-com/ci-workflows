# Deployments and environments

Environments gate deployments with protection rules, scope secrets to a stage,
and — with cloud OIDC — let jobs obtain short-lived credentials instead of
storing long-lived cloud keys.

## Environments

An environment is a named deployment target (`staging`, `production`) with its
own protection rules, secrets, and variables. Reference it on a job:

```yaml
jobs:
  deploy:
    environment: production
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read
    steps:
      - run: ./deploy.sh
```

Secrets/variables defined on an environment are only available to jobs that
target it, so production credentials never leak into unrelated jobs.

## Deployment protection rules

Environments can require approval and delay before a deployment job runs:

| Rule | Effect |
| --- | --- |
| **Required reviewers** | Named users/teams must approve before the job runs |
| **Wait timer** | Enforced delay (e.g. 10 min) before deployment proceeds |
| **Deployment branches/tags** | Only listed refs may deploy to this environment |
| **Custom protection rules** | Third-party gates via the deployment protection API |

Use required reviewers for `production` and restrict deployment branches to your
release refs. These pair with rulesets (see
[08 Governance & rulesets](08-governance-rulesets.md)).

## GitHub Pages

Pages publishes static sites. The modern flow uses the Actions deployment path
with the `github-pages` environment:

```yaml
permissions:
  pages: write
  id-token: write
jobs:
  deploy:
    environment:
      name: github-pages
      url: ${{ steps.deploy.outputs.page_url }}
    steps:
      - uses: actions/upload-pages-artifact@<full-sha>
      - id: deploy
        uses: actions/deploy-pages@<full-sha>
```

Free on public repos. Build docs with `docs-ci.yml` and deploy via Pages.

<a id="cloud-oidc"></a>
## Cloud OIDC — short-lived credentials

Instead of storing long-lived cloud keys as secrets, use **OIDC federation**:
the job presents a signed OIDC token describing its identity (repo, ref,
environment); the cloud provider's trust policy validates it and returns
**short-lived** credentials.

```yaml
permissions:
  id-token: write        # request the OIDC token
  contents: read
steps:
  - uses: aws-actions/configure-aws-credentials@<full-sha>
    with:
      role-to-assume: arn:aws:iam::123456789012:role/ci-deploy
      aws-region: eu-central-1
  # subsequent AWS calls use short-lived, auto-expiring credentials
```

The same pattern applies to all three major clouds:

| Provider | Action | Trust anchor |
| --- | --- | --- |
| **AWS** | `aws-actions/configure-aws-credentials` | IAM OIDC provider + role trust policy |
| **GCP** | `google-github-actions/auth` | Workload Identity Federation pool |
| **Azure** | `azure/login` | Federated credential on an app registration |

Scope the cloud trust policy to specific repo/ref/environment claims so only the
intended workflow can assume the role. This is the recommended posture for every
tier and removes stored cloud secrets entirely — the same OIDC mechanism backs
[trusted publishing](09-releases-packages.md#npm--pypi-trusted-publishing-via-oidc)
and [Sigstore attestations](07-supply-chain-slsa-sbom-attestations.md#sigstore).

---
Last verified: 2026-07-04
