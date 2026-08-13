#!/usr/bin/env python3
"""Strict parser for Gradle 9.5 canonical single-project lockfiles."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

HEADER = (
    "# This is a Gradle generated file for dependency locking.",
    "# Manual edits can break the build and are not advised.",
    "# This file is expected to be part of source control.",
)


class GradleLockfileError(ValueError):
    """The lockfile is not canonical Gradle 9.5 writer output."""


@dataclass(frozen=True)
class GradleLockfile:
    entries: tuple[str, ...]
    resolved_configurations: tuple[str, ...]


def parse_gradle_95_lockfile(path: Path, *, source: str | None = None) -> GradleLockfile:
    label = source or str(path)
    raw = path.read_bytes()
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise GradleLockfileError(f"{label}: lockfile must be UTF-8 LF with terminal LF")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise GradleLockfileError(f"{label}: lockfile is not UTF-8") from exc
    if tuple(lines[:3]) != HEADER:
        raise GradleLockfileError(f"{label}: noncanonical Gradle lockfile header")
    rows = lines[3:]
    if not rows or rows[-1].split("=", 1)[0] != "empty":
        raise GradleLockfileError(f"{label}: exactly one terminal empty= aggregate is required")
    if sum(row.startswith("empty=") for row in rows) != 1:
        raise GradleLockfileError(f"{label}: empty= aggregate is missing, duplicate, or misplaced")
    modules: list[str] = []
    configurations: set[str] = set()
    for index, row in enumerate(rows):
        if not row or row.startswith("#") or row.count("=") != 1 or row != row.strip():
            raise GradleLockfileError(f"{label}:{index + 4}: malformed record")
        module, joined = row.split("=", 1)
        values = joined.split(",") if joined else []
        if values != sorted(set(values)) or any(not value for value in values):
            raise GradleLockfileError(f"{label}:{index + 4}: configurations are not unique lexical values")
        configurations.update(values)
        if module == "empty":
            continue
        if module.count(":") < 2 or not all(module.split(":")):
            raise GradleLockfileError(f"{label}:{index + 4}: invalid dependency notation")
        if not values:
            raise GradleLockfileError(f"{label}:{index + 4}: dependency has no configurations")
        modules.append(module)
    if modules != sorted(set(modules)):
        raise GradleLockfileError(f"{label}: dependency records are not unique lexical values")
    return GradleLockfile(tuple(modules), tuple(sorted(configurations)))
