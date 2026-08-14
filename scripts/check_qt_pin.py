#!/usr/bin/env python3
"""Resolve the pinned Qt fixture version against Qt's published repository.

`check_flutter_pin.py` exists because a pinned toolchain version nobody machine-
checks is verified by eye, and eyes are wrong. Qt had no equivalent, and the
consequence was already in the tree: the fixture and the consumer-facing example
both pinned Qt **6.8.4**, which the open-source repository does not publish. The
highest 6.8.x it offers is 6.8.3. Qt 6.8 is an LTS series, and LTS patch
releases past a point are commercial-only, so an open-source caller following
the example could never obtain the version it named.

Nothing caught it because `qt-ci.yml` cannot start in this repository at all
(issue #150), so the pin was never exercised. A pin that is only checked when
the lane runs is not checked.

Resolution uses the repository layout itself: every published version has a
directory named `qt6_<major><minor><patch>` with the dots removed — `6.8.3` is
`qt6_683`, `6.10.1` is `qt6_6101` — under the host's `desktop` index. The check
is an exact match against a generated name, so it cannot be satisfied by a
neighbouring version.

Advisory tier. What a third party still publishes is a calendar fact about
someone else, and `AGENTS.md` is explicit that those never sit in the blocking
tier.
"""
from __future__ import annotations

import argparse
import re
import urllib.error
import urllib.request
from pathlib import Path

from ci_workflows_tools._strict_yaml import strict_load

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "tests/fixtures/sdk-runtime-spec.yml"
INDEX = "https://download.qt.io/online/qtsdkrepository/{host}/{target}/"
# The fixture pins ubuntu-latest, so the host index is the Linux one. A caller
# on another operating system reads a different index; this checks the pin the
# fixture actually uses rather than every index Qt publishes.
HOST_INDEX = "linux_x64"
TARGET = "desktop"
TIMEOUT_SECONDS = 30
VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def directory_name(version: str) -> str | None:
    """`6.8.3` -> `qt6_683`. None when the version is not exact `X.Y.Z`."""
    match = VERSION.fullmatch(version)
    if match is None:
        return None
    major, minor, patch = match.groups()
    return f"qt{major}_{major}{minor}{patch}"


def _published(url: str) -> set[str]:
    request = urllib.request.Request(url, headers={"User-Agent": "nddev-ci-workflows-qt-pin"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
        body = response.read().decode("utf-8", errors="replace")
    return set(re.findall(r'href="(qt\d+_\d+)/"', body))


def check(*, offline: bool = False) -> list[str]:
    pin = strict_load(SPEC)["fixtures"]["qt"]["toolchain"]
    version = str(pin["qt_version"])
    expected = directory_name(version)
    if expected is None:
        return [f"qt pin {version!r} is not an exact X.Y.Z version"]
    if offline:
        print("qt-pin: skipped, --offline proves nothing about the pin")
        return []
    url = INDEX.format(host=HOST_INDEX, target=TARGET)
    try:
        published = _published(url)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return [f"qt pin unverified: {url} unreachable: {exc}"]
    if not published:
        return [f"qt pin unverified: {url} listed no Qt directories"]
    if expected in published:
        return []
    prefix = expected.rsplit("_", 1)[0] + "_" + expected.rsplit("_", 1)[1][:2]
    nearby = sorted(name for name in published if name.startswith(prefix))
    return [
        f"qt pin {version} is not published for {HOST_INDEX}/{TARGET}: no {expected} "
        f"directory. Present in that series: {', '.join(nearby) or 'none'}"
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true",
                        help="skip the fetch and report that nothing was proven")
    args = parser.parse_args()
    problems = check(offline=args.offline)
    if problems:
        print("check_qt_pin: FAIL")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("check_qt_pin: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
