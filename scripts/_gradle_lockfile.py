#!/usr/bin/env python3
"""Parse the canonical single-project lockfile emitted by Gradle 9.5.0."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

HEADER = (
    "# This is a Gradle generated file for dependency locking.",
    "# Manual edits can break the build and are not advised.",
    "# This file is expected to be part of source control.",
)


class GradleLockfileError(ValueError):
    """The bytes are not Gradle 9.5.0 canonical writer output."""


@dataclass(frozen=True)
class GradleLockfile:
    entries: tuple[str, ...]
    dependency_modules: tuple[str, ...]
    resolved_configurations: tuple[str, ...]
    empty_configurations: tuple[str, ...]


def _configuration_list(value: str, *, allow_empty: bool, context: str) -> tuple[str, ...]:
    if not value:
        if allow_empty:
            return ()
        raise GradleLockfileError(f"{context}: configuration list is empty")
    values = tuple(value.split(","))
    if any(not item or item.strip() != item or any(char.isspace() for char in item)
           or "=" in item for item in values):
        raise GradleLockfileError(f"{context}: malformed configuration list")
    if tuple(sorted(set(values))) != values:
        raise GradleLockfileError(
            f"{context}: configurations must be unique and strictly lexical"
        )
    return values


def parse_gradle_95_lockfile_bytes(raw: bytes, *, source: str) -> GradleLockfile:
    """Validate exact Gradle 9.5 canonical writer bytes without normalizing them."""
    if raw.startswith(b"\xef\xbb\xbf"):
        raise GradleLockfileError(f"{source}: UTF-8 BOM is forbidden")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GradleLockfileError(f"{source}: invalid UTF-8") from exc
    if "\r" in text or not text.endswith("\n") or text.endswith("\n\n"):
        raise GradleLockfileError(
            f"{source}: canonical output requires LF and exactly one terminal LF"
        )
    lines = text[:-1].split("\n")
    if tuple(lines[:len(HEADER)]) != HEADER:
        raise GradleLockfileError(f"{source}: canonical Gradle header is missing or changed")
    records = lines[len(HEADER):]
    if not records or any(not line for line in records):
        raise GradleLockfileError(f"{source}: blank or missing lock record")
    if any(line.startswith("#") for line in records):
        raise GradleLockfileError(f"{source}: comments are allowed only in the canonical header")
    empty_positions = [index for index, line in enumerate(records) if line.startswith("empty=")]
    if empty_positions != [len(records) - 1]:
        raise GradleLockfileError(
            f"{source}: exactly one empty= aggregate must be the terminal record"
        )
    empty_line = records[-1]
    if empty_line.count("=") != 1:
        raise GradleLockfileError(f"{source}: malformed terminal empty= aggregate")
    empty_configurations = _configuration_list(
        empty_line.removeprefix("empty="), allow_empty=True,
        context=f"{source}: empty aggregate",
    )

    modules: list[str] = []
    used_configurations: set[str] = set()
    for line_number, line in enumerate(records[:-1], start=len(HEADER) + 1):
        if line.count("=") != 1:
            raise GradleLockfileError(f"{source}:{line_number}: malformed dependency record")
        module, configuration_text = line.split("=", 1)
        coordinates = module.split(":")
        if len(coordinates) != 3 or any(
            not item or item.strip() != item or any(char.isspace() for char in item)
            or "," in item or "=" in item
            for item in coordinates
        ):
            raise GradleLockfileError(f"{source}:{line_number}: malformed module identity")
        configurations = _configuration_list(
            configuration_text, allow_empty=False,
            context=f"{source}:{line_number}",
        )
        modules.append(module)
        used_configurations.update(configurations)
    if tuple(sorted(set(modules))) != tuple(modules):
        raise GradleLockfileError(
            f"{source}: dependency modules must be unique and strictly lexical"
        )
    overlap = sorted(used_configurations.intersection(empty_configurations))
    if overlap:
        raise GradleLockfileError(
            f"{source}: configurations cannot be both resolved and empty: {overlap}"
        )
    return GradleLockfile(
        entries=tuple(records),
        dependency_modules=tuple(modules),
        resolved_configurations=tuple(sorted(used_configurations.union(empty_configurations))),
        empty_configurations=empty_configurations,
    )


def parse_gradle_95_lockfile(path: Path, *, source: str | None = None) -> GradleLockfile:
    return parse_gradle_95_lockfile_bytes(path.read_bytes(), source=source or str(path))
