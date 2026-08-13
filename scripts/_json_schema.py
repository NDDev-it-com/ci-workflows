#!/usr/bin/env python3
"""A dependency-free validator for the JSON Schema subset this catalog uses.

`catalog/schema/capability.schema.yaml` was documented as the enforced shape of
`capabilities.yml`, but the only thing any validator ever did with it was check
that the file existed. Nothing read it, so it drifted away from the tree it
claimed to describe in both directions at once: it declared
`additionalProperties: false` while omitting `runtime_requirements`, which two
capabilities use — so applying it would have failed the catalog — and it
declared `last_verified` a pattern-checked string while seven entries were
written unquoted and parsed as `datetime.date`. A schema nobody executes is
documentation wearing a validator's clothes.

Only the keywords the catalog schema actually uses are implemented, and an
unknown keyword is an error rather than a silent pass — a validator that
quietly ignores what it does not understand is how the original gap felt safe.
The repository ships PyYAML and nothing else, so this stays in the standard
library like `_strict_yaml.py`.
"""
from __future__ import annotations

import re
from typing import Any

# Annotation keywords carry no assertion; everything else must be implemented.
ANNOTATIONS = {"$schema", "$id", "title", "description", "$comment", "examples"}
SUPPORTED = {
    "type", "enum", "pattern", "properties", "required", "additionalProperties",
    "items", "minItems", "minLength", "anyOf",
}

TYPES: dict[str, type | tuple[type, ...]] = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "integer": int,
    "number": (int, float),
}


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "integer":
        # JSON Schema: booleans are not integers.
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    python_type = TYPES.get(expected)
    if python_type is None:
        return False
    if isinstance(value, bool) and python_type in (int, (int, float)):
        return False
    return isinstance(value, python_type)


def validate(instance: Any, schema: Any, path: str = "") -> list[str]:
    """Every way `instance` violates `schema`, each as one reviewable string."""
    problems: list[str] = []
    where = path or "<root>"
    if not isinstance(schema, dict):
        return [f"{where}: schema fragment is not a mapping"]

    unknown = set(schema) - SUPPORTED - ANNOTATIONS
    if unknown:
        return [f"{where}: schema uses unsupported keywords {sorted(unknown)}"]

    if "anyOf" in schema:
        branches = schema["anyOf"]
        if not isinstance(branches, list) or not branches:
            return [f"{where}: anyOf must be a non-empty list"]
        if not any(not validate(instance, branch, path) for branch in branches):
            problems.append(f"{where}: value matches no anyOf branch")
        return problems

    if "type" in schema:
        expected = schema["type"]
        names = expected if isinstance(expected, list) else [expected]
        if not any(_type_matches(instance, name) for name in names):
            actual = "null" if instance is None else type(instance).__name__
            problems.append(f"{where}: expected type {expected!r}, got {actual}")
            # Every later keyword assumes the type held.
            return problems

    if "enum" in schema and instance not in schema["enum"]:
        problems.append(f"{where}: {instance!r} is not one of {schema['enum']}")

    if "pattern" in schema and isinstance(instance, str):
        if re.search(schema["pattern"], instance) is None:
            problems.append(f"{where}: {instance!r} does not match {schema['pattern']!r}")

    if "minLength" in schema and isinstance(instance, str):
        if len(instance) < schema["minLength"]:
            problems.append(f"{where}: shorter than minLength {schema['minLength']}")

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            problems.append(f"{where}: fewer than minItems {schema['minItems']}")
        if "items" in schema:
            for index, item in enumerate(instance):
                problems += validate(item, schema["items"], f"{where}[{index}]")

    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in instance:
                problems.append(f"{where}: missing required property {name!r}")
        if schema.get("additionalProperties") is False:
            extra = sorted(set(instance) - set(properties))
            if extra:
                problems.append(f"{where}: unexpected properties {extra}")
        for name, value in instance.items():
            if name in properties:
                problems += validate(value, properties[name], f"{where}.{name}")

    return problems


def selftest() -> list[str]:
    """Prove the validator accepts what it should and refuses what it must.

    A schema validator that never rejects is exactly the failure it was written
    to end, so the negative cases matter more than the positive one.
    """
    problems: list[str] = []
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "when"],
        "properties": {
            "id": {"type": "string", "pattern": "^[a-z-]+$"},
            "when": {"type": "string", "pattern": "^20[0-9]{2}-[0-9]{2}-[0-9]{2}$"},
            "tags": {"type": "array", "minItems": 1, "items": {"enum": ["a", "b"]}},
            "note": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
    }
    valid = {"id": "ok-id", "when": "2026-08-14", "tags": ["a"], "note": None}
    if validate(valid, schema):
        problems.append("_json_schema selftest: a valid instance was rejected")
    invalid = {
        "wrong-type": {"id": 7, "when": "2026-08-14"},
        # The exact defect this module exists to catch: an unquoted YAML date
        # arrives as datetime.date, not str.
        "date-not-string": {"id": "ok", "when": __import__("datetime").date(2026, 8, 14)},
        "bad-pattern": {"id": "ok", "when": "14-08-2026"},
        "missing-required": {"id": "ok"},
        "unexpected-property": {"id": "ok", "when": "2026-08-14", "extra": 1},
        "empty-array": {"id": "ok", "when": "2026-08-14", "tags": []},
        "bad-enum": {"id": "ok", "when": "2026-08-14", "tags": ["c"]},
        "failed-anyof": {"id": "ok", "when": "2026-08-14", "note": 5},
    }
    for label, instance in invalid.items():
        if not validate(instance, schema):
            problems.append(f"_json_schema selftest: {label} was accepted")
    if not validate({"id": "ok", "when": "2026-08-14"}, {"type": "object", "nope": 1}):
        problems.append("_json_schema selftest: an unsupported keyword was ignored")
    return problems
