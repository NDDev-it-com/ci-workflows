# Evidence orchestration caller pattern

Run the compiler in a caller-native planning job, save its outputs, and call the
existing reusable workflows conditionally. Do not copy their implementation.
The planning job's own timeout/concurrency policy belongs to the caller; elapsed
duration is never an evidence-selection or pass/fail input.

```yaml
jobs:
  evidence-plan:
    runs-on: ubuntu-latest
    permissions: { contents: read }
    outputs:
      selected: ${{ steps.plan.outputs.selected_lane_ids }}
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          repository: NDDev-it-com/ci-workflows
          ref: <sha>
          path: .ci-workflows
          persist-credentials: false
      - id: plan
        run: >-
          python3 .ci-workflows/scripts/compile_evidence_plan.py
          --level pr-required --platform github-actions --os ubuntu --arch x64
          --profile public --risks code,security --changes workflows

  actionlint:
    needs: evidence-plan
    if: contains(fromJSON(needs.evidence-plan.outputs.selected), 'actionlint')
    permissions: { contents: read }
    uses: NDDev-it-com/ci-workflows/.github/workflows/actionlint.yml@<sha>
    with: { runner: ubuntu-latest }
```

For `native-disposable-host` lanes, the output contains a handoff rather than a
workflow. The owning fleet/bootstrap repository must prove every declared host
capability on a one-job disposable machine; this repository does not simulate
reboot, GUI/session, SSH/network, or system-hardening evidence on hosted CI.
