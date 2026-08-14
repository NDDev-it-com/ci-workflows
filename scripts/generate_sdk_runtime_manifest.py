#!/usr/bin/env python3
"""Generate the byte-provenance manifest for the three SDK fixtures."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from ci_workflows_tools._strict_yaml import strict_load

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "tests/fixtures/sdk-runtime-spec.yml"
OUTPUT = ROOT / "tests/fixtures/sdk-runtime-manifest.json"
FIXTURE_ROOTS = ("tests/fixtures/flutter", "tests/fixtures/android", "tests/fixtures/qt")
IGNORED = {".dart_tool", ".gradle", "build"}


def source_paths() -> list[Path]:
    paths = []
    for relative in FIXTURE_ROOTS:
        for path in (ROOT / relative).rglob("*"):
            if any(part in IGNORED for part in path.relative_to(ROOT).parts):
                continue
            if path.is_symlink() or (path.exists() and not path.is_file() and not path.is_dir()):
                raise ValueError(f"fixture entry must be regular: {path.relative_to(ROOT)}")
            if path.is_file():
                paths.append(path)
    return sorted(paths, key=lambda path: path.relative_to(ROOT).as_posix())


def render() -> bytes:
    spec_raw = SPEC.read_bytes()
    strict_load(SPEC)
    rows = []
    for path in source_paths():
        relative = path.relative_to(ROOT).as_posix()
        raw = path.read_bytes()
        kind = "binary" if relative.endswith("gradle-wrapper.jar") else "text"
        if kind == "text":
            raw.decode("utf-8")
            if b"\r" in raw or not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
                raise ValueError(f"{relative}: text must be LF-only with exactly one terminal LF")
        rows.append({"kind": kind, "path": relative, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)})
    return (json.dumps({
        "files": rows,
        "schema_version": 1,
        "spec_sha256": hashlib.sha256(spec_raw).hexdigest(),
    }, indent=2, sort_keys=True) + "\n").encode()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        expected = render()
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"sdk-runtime-manifest: {exc}", file=sys.stderr)
        return 1
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_bytes() != expected:
            print("sdk-runtime-manifest: stale generated data", file=sys.stderr)
            return 1
        print("sdk-runtime-manifest: OK")
        return 0
    OUTPUT.write_bytes(expected)
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
