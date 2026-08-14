#!/usr/bin/env python3
"""Pinning an action by SHA does not pin what that action calls.

`check_pinned_actions.py` proves every `uses:` written here is a full commit
SHA. That is one level deep. A composite action's own `action.yml` may refer to
further actions by tag, and GitHub resolves the **entire** nested graph at job
setup — so under the repository control "require actions to be pinned to a
full-length commit SHA", which `docs/00` and the consumer-adoption skill both
recommend, the job is refused before a single step runs:

    The action actions/cache@v5 is not allowed in NDDev-it-com/ci-workflows
    because all actions must be pinned to a full-length commit SHA.

That is how `dart-flutter-ci.yml` and `qt-ci.yml` turned out to be unusable in
any organisation following this library's own advice, and nothing static could
see it: `subosito/flutter-action` and `jurplel/install-qt-action` are correctly
pinned *here*, and reach `actions/cache@v5`, `actions/setup-python@v6` and
`jurplel/install-qt-action/action@v4` from inside. See issue #150.

This resolves each pinned third-party action at its pinned SHA and reports every
nested reference that is not itself a commit SHA — so the next one is found by
reading, not by a fixture failing in a way that takes a runner round trip to
diagnose.

Advisory tier. It reads other repositories over the network, and what a third
party writes in its own `action.yml` is not a property of this tree.
"""
from __future__ import annotations

import os
import re
import urllib.error
import urllib.request

from ci_workflows_tools._workflow_yaml import WORKFLOWS_DIR, workflow_files

USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(?P<ref>[^\s#]+)", re.MULTILINE)
SHA = re.compile(r"^[0-9a-f]{40}$")
NESTED_USES = re.compile(r"^\s*uses:\s*(?P<ref>[^\s#]+)", re.MULTILINE)
TIMEOUT_SECONDS = 30
API = "https://api.github.com/repos/{repo}/contents/{path}?ref={ref}"


def _candidate_paths(subdirectory: str) -> tuple[str, ...]:
    """Where the definition of a pinned reference lives, by kind.

    A pinned reference is either an action, whose definition is `action.yml` or
    `action.yaml` in its directory, or a reusable workflow, which *is* the file.
    Treating the second as the first asks for `.github/workflows/x.yml/action.yml`,
    gets a 404, and reports a missing definition for a perfectly good pin.
    Reusable workflows carry `uses:` of their own, so they belong in this audit
    rather than being skipped: a third party's workflow can name unpinned
    actions exactly as a third party's composite action can.
    """
    if subdirectory.endswith((".yml", ".yaml")):
        return (subdirectory,)
    if subdirectory:
        return (f"{subdirectory}/action.yml", f"{subdirectory}/action.yaml")
    return ("action.yml", "action.yaml")


def _selftest() -> list[str]:
    problems: list[str] = []
    for subdirectory, expected in (
        ("", ("action.yml", "action.yaml")),
        ("setup", ("setup/action.yml", "setup/action.yaml")),
        (".github/workflows/release.yml", (".github/workflows/release.yml",)),
        (".github/workflows/release.yaml", (".github/workflows/release.yaml",)),
    ):
        actual = _candidate_paths(subdirectory)
        if actual != expected:
            problems.append(
                f"reference-kind selftest: {subdirectory!r} resolved to {actual}, "
                f"expected {expected}")
    return problems


def _third_party_pins() -> dict[str, set[str]]:
    """Every distinct `owner/repo[/path]@sha` this repository calls, and where."""
    pins: dict[str, set[str]] = {}
    for path in workflow_files():
        relative = path.relative_to(WORKFLOWS_DIR.parent.parent).as_posix()
        for match in USES.finditer(path.read_text(encoding="utf-8")):
            ref = match.group("ref")
            if ref.startswith("./") or ref.startswith("docker://"):
                continue
            _, _, revision = ref.partition("@")
            if SHA.fullmatch(revision):
                pins.setdefault(ref, set()).add(relative)
    return pins


def _fetch(repo: str, path: str, ref: str, token: str | None) -> str | None:
    request = urllib.request.Request(
        API.format(repo=repo, path=path, ref=ref),
        headers={"Accept": "application/vnd.github.raw+json",
                 "User-Agent": "nddev-ci-workflows-pin-audit"},
    )
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def _token() -> str | None:
    """The token comes from the environment, never from shelling out to `gh`.

    Reading it with `gh auth token` would add a process edge for a value the
    caller already has, and the same rule the brief states for zizmor applies
    here: pass it in. Unauthenticated the API allows 60 requests an hour, which
    this exhausts, so a missing token is reported rather than worked around.
    """
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        value = os.environ.get(name)
        if value:
            return value
    return None


def check() -> list[str]:
    problems: list[str] = _selftest()
    token = _token()
    if token is None:
        return problems + [
            "nested action pins unverified: set GH_TOKEN; the unauthenticated "
            "API rate limit cannot cover every pinned action"]
    for pin, callers in sorted(_third_party_pins().items()):
        location, _, revision = pin.partition("@")
        parts = location.split("/")
        repo = "/".join(parts[:2])
        subdirectory = "/".join(parts[2:])
        candidates = _candidate_paths(subdirectory)
        definition = None
        try:
            for candidate in candidates:
                definition = _fetch(repo, candidate, revision, token)
                if definition is not None:
                    break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            problems.append(f"{pin}: nested pins unverified, {repo} unreachable: {exc}")
            continue
        if definition is None:
            problems.append(f"{pin}: no definition at that ref (looked for {', '.join(candidates)})")
            continue
        # An action may call the same thing from several steps; the finding is
        # about the reference, not about how often it appears.
        for nested in sorted({m.group("ref") for m in NESTED_USES.finditer(definition)}):
            if nested.startswith("./"):
                continue
            if nested.startswith("docker://"):
                if "@sha256:" not in nested:
                    problems.append(
                        f"{pin} calls {nested} without a digest "
                        f"(used by {', '.join(sorted(callers))})")
                continue
            _, _, nested_revision = nested.partition("@")
            if not SHA.fullmatch(nested_revision):
                problems.append(
                    f"{pin} calls {nested}, which is not pinned to a commit SHA — "
                    f"a caller enforcing SHA pinning cannot start "
                    f"{', '.join(sorted(callers))}")
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_transitive_action_pins: FAIL")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("check_transitive_action_pins: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
