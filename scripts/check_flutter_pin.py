#!/usr/bin/env python3
"""Resolve the pinned Flutter fixture toolchain against the official manifest.

`tests/fixtures/sdk-runtime-spec.yml` pins five facts about one Flutter release
-- channel, version, Dart version, framework revision, and the Linux x64 archive
digest. Together they should identify exactly one immutable row of Google's
release manifest. Nothing checked that, so the pin was verified by eye, and an
audit reading it by eye reached the opposite conclusion and proposed re-pinning
a pin that was in fact correct.

Advisory by construction. Whether a release manifest still lists a row is a
calendar-driven property of a third party, not of this tree, and `AGENTS.md` is
explicit that such a check must never sit in the blocking tier: one required job
mixing the two is what let an external fact block an unrelated bugfix. It runs
in the scheduled sweep, where the cost of being wrong is a maintenance ticket.

A pin that resolves to no row, or to more than one, is a finding. A manifest
that cannot be reached is also a finding rather than a silent pass -- the
scheduled sweep runs with network, and a check that quietly does nothing when
the network is down is the failure mode this repository keeps finding in its own
contracts. `--offline` exists for running the full local tier without network
and says plainly that it proved nothing.
"""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ci_workflows_tools._strict_yaml import strict_load

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "tests/fixtures/sdk-runtime-spec.yml"
MANIFEST_URL = (
    "https://storage.googleapis.com/flutter_infra_release/releases/releases_linux.json"
)
TIMEOUT_SECONDS = 30


def _fetch(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _dart_version(release: dict[str, Any]) -> str:
    """The Dart version token.

    The manifest writes `3.13.0` for a release and `3.13.0 (build 3.13.0-x.y)`
    for a prerelease, so the comparison is on the leading token; comparing the
    whole field would make a correct pin look wrong.
    """
    return str(release.get("dart_sdk_version", "")).split(" ")[0]


def _matches(release: dict[str, Any], pin: dict[str, Any]) -> bool:
    return (
        str(release.get("version")) == str(pin["flutter_version"])
        and str(release.get("channel")) == str(pin["channel"])
        and str(release.get("hash")) == str(pin["framework_revision"])
        and str(release.get("sha256")) == str(pin["linux_x64_archive_sha256"])
        and _dart_version(release) == str(pin["dart_version"])
    )


def check(*, offline: bool = False) -> list[str]:
    pin = strict_load(SPEC)["fixtures"]["flutter"]["toolchain"]
    if offline:
        print("flutter-pin: skipped, --offline proves nothing about the pin")
        return []
    try:
        manifest = _fetch(MANIFEST_URL)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return [f"flutter pin unverified: {MANIFEST_URL} unreachable: {exc}"]
    releases = manifest.get("releases")
    if not isinstance(releases, list) or not releases:
        return [f"flutter pin unverified: {MANIFEST_URL} carried no releases list"]
    matched = [release for release in releases if _matches(release, pin)]
    if len(matched) == 1:
        return []
    version = pin["flutter_version"]
    named = [
        release for release in releases
        if str(release.get("version")) == str(version)
        and str(release.get("channel")) == str(pin["channel"])
    ]
    if not named:
        return [
            f"flutter pin {pin['channel']}/{version} is not in the release manifest"
        ]
    if len(matched) > 1:
        return [f"flutter pin {pin['channel']}/{version} matched {len(matched)} rows"]
    row = named[0]
    drift = [
        f"{field}: pinned {pinned!r}, manifest {actual!r}"
        for field, pinned, actual in (
            ("dart_version", str(pin["dart_version"]), _dart_version(row)),
            ("framework_revision", str(pin["framework_revision"]), str(row.get("hash"))),
            ("linux_x64_archive_sha256", str(pin["linux_x64_archive_sha256"]),
             str(row.get("sha256"))),
        )
        if pinned != actual
    ]
    return [f"flutter pin {pin['channel']}/{version} disagrees with the manifest -- "
            + "; ".join(drift)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline", action="store_true",
        help="skip the fetch and report that nothing was proven",
    )
    args = parser.parse_args()
    problems = check(offline=args.offline)
    if problems:
        print("check_flutter_pin: FAIL")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("check_flutter_pin: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
