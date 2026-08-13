#!/usr/bin/env python3
"""Cold, dependency-free syntax gate for every repository Python surface."""
from __future__ import annotations

import ast
import py_compile
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"


def _fixture_problems() -> list[str]:
    problems: list[str] = []
    valid = {
        "balanced-set": 'VALUES = {"|", ">", "|-", ">+"}\n',
        "quoted": 'VALUE = "run: >1- # folded"\n',
        "multiline": "VALUE = (\n    'first'\n    'second'\n)\n",
    }
    invalid = {
        "mismatched-delimiter": 'VALUES = {"|", ">-")\n',
        "truncated-set": 'VALUES = {"|", ">-"\n',
        "truncated-quoted": 'VALUE = "run: |\n',
        "truncated-multiline": "VALUE = (\n    'first'\n",
    }
    for label, source in valid.items():
        try:
            ast.parse(source, filename=f"<syntax-valid:{label}>", feature_version=(3, 13))
        except SyntaxError as exc:
            problems.append(f"valid syntax fixture {label!r} was rejected: {exc}")
    for label, source in invalid.items():
        try:
            ast.parse(source, filename=f"<syntax-invalid:{label}>", feature_version=(3, 13))
        except SyntaxError:
            continue
        problems.append(f"invalid syntax fixture {label!r} was accepted")
    return problems


def check() -> list[str]:
    problems = _fixture_problems()
    paths = sorted(SCRIPTS.glob("*.py"))
    with tempfile.TemporaryDirectory(prefix="ci-workflows-python-syntax-") as raw:
        cache = Path(raw)
        for path in paths:
            try:
                source = path.read_text(encoding="utf-8")
                ast.parse(source, filename=str(path), feature_version=(3, 13))
            except (OSError, UnicodeError, SyntaxError) as exc:
                problems.append(f"{path.name}: AST parse failed: {exc}")
                continue
            try:
                py_compile.compile(
                    str(path), cfile=str(cache / f"{path.name}c"), doraise=True,
                )
            except py_compile.PyCompileError as exc:
                problems.append(f"{path.name}: bytecode compilation failed: {exc.msg}")
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_python_syntax: FAIL")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("check_python_syntax: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
