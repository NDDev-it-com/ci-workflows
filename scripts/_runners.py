#!/usr/bin/env python3
"""One definition of what a runner label means, shared by every validator.

Two checks need this and used to answer it differently. `check_examples.py`
knew that hosted is not the same as free and rejected larger runners anywhere.
`check_workflow_contracts.py` required the literal string `ubuntu-latest` for
this repository's own reusable calls — which stopped a public repository from
inheriting a private self-hosted default, but also forbade `macos-latest`, a
standard hosted runner that is unmetered on public repositories exactly like
`ubuntu-latest`. The fixture estate hit that wall the moment it tried to prove
`swift-ci.yml`, whose whole point is macOS.

Both checks want the same property and should not be able to drift apart:

* **hosted** — a label every GitHub account resolves. Anything else is
  somebody's private fleet, and pointing a public repository at one turns a
  forked pull request into remote code execution on that hardware.
* **standard, not larger** — `github-actions-public-standard` in the fact
  ledger is `public-unmetered` for *standard* runners only, while
  `github-actions-larger-runners` is "always billed, including public
  repositories". `ubuntu-latest-8-cores` passes any prefix test for "hosted"
  and still bills a repository that believed its CI was free.
"""
from __future__ import annotations

# Labels every GitHub account can resolve, for all three operating systems.
HOSTED_RUNNER_PREFIXES = ("ubuntu-", "macos-", "windows-")

# Larger runners are named by a size suffix and are billed from the first
# minute even on public repositories.
LARGER_RUNNER_SUFFIXES = ("-cores", "-large", "-xlarge")


def is_standard_hosted(label: object) -> bool:
    """True when `label` is a standard GitHub-hosted runner.

    Standard means unmetered on public repositories in all three operating
    systems. A larger runner is hosted but billed, so it is not standard.
    """
    if not isinstance(label, str) or not label:
        return False
    if label.endswith(LARGER_RUNNER_SUFFIXES):
        return False
    return label.startswith(HOSTED_RUNNER_PREFIXES)
