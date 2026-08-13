#!/usr/bin/env python3
"""Generate the canonical SDK fixture byte-provenance manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath

from _strict_yaml import strict_load

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO_ROOT / "tests" / "fixtures" / "sdk-runtime-spec.yml"


def _validated_bytes(relative: str, kind: str) -> bytes:
    posix = PurePosixPath(relative)
    if posix.is_absolute() or ".." in posix.parts or str(posix) != relative:
        raise ValueError(f"non-canonical source path: {relative!r}")
    path = REPO_ROOT / relative
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"source must be a regular non-symlink file: {relative}")
    raw = path.read_bytes()
    if kind == "text":
        if raw.startswith(b"\xef\xbb\xbf"):
            raise ValueError(f"UTF-8 BOM is forbidden: {relative}")
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"source is not UTF-8: {relative}: {exc}") from exc
        if b"\r" in raw:
            raise ValueError(f"text source must be LF-only: {relative}")
        if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
            raise ValueError(f"text source needs exactly one terminal LF: {relative}")
    elif kind != "binary":
        raise ValueError(f"unsupported source kind {kind!r}: {relative}")
    return raw


def render() -> bytes:
    spec = strict_load(SPEC_PATH)
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for fixture in spec.get("fixtures", []):
        fixture_id = fixture.get("id")
        entries = fixture.get("source_files", [])
        paths = [entry.get("path") for entry in entries]
        if paths != sorted(paths):
            raise ValueError(f"{fixture_id}: source_files must use lexical POSIX order")
        for entry in entries:
            relative = entry.get("path")
            kind = entry.get("kind")
            if not isinstance(relative, str) or relative in seen:
                raise ValueError(f"duplicate or invalid source path: {relative!r}")
            if not isinstance(kind, str):
                raise ValueError(f"missing source kind: {relative}")
            seen.add(relative)
            raw = _validated_bytes(relative, kind)
            rows.append({
                "fixture": fixture_id,
                "kind": kind,
                "path": relative,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
            })
    ordered = sorted(rows, key=lambda row: str(row["path"]))
    payload = {
        "byte_contract": spec["byte_contract"],
        "fixtures": ordered,
        "schema_version": spec["schema_version"],
        "spec_sha256": hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest(),
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        expected = render()
        spec = strict_load(SPEC_PATH)
        output = REPO_ROOT / spec["generated_manifest"]
    except (KeyError, OSError, TypeError, ValueError) as exc:
        print(f"sdk-runtime-manifest: {exc}", file=sys.stderr)
        return 1
    if args.check:
        actual = output.read_bytes() if output.is_file() else b""
        if actual != expected:
            print(
                "sdk-runtime-manifest: generated manifest is stale; run "
                "python3 scripts/generate_sdk_runtime_manifest.py",
                file=sys.stderr,
            )
            return 1
        print("sdk-runtime-manifest: OK")
        return 0
    output.write_bytes(expected)
    print(f"wrote {output.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
