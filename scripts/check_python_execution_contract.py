#!/usr/bin/env python3
"""Own isolated Python launch, environment taint, imports, and process edges."""
from __future__ import annotations

import ast
import builtins
import importlib
import importlib.metadata
import importlib.util
import json
import os
import py_compile
import re
import runpy
import shlex
import site
import subprocess
import sys
import sysconfig
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from symtable import SymbolTable, symtable
from types import ModuleType
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
PACKAGE_NAME = "ci_workflows_tools"
PACKAGE_INIT = "__init__.py"
POLICY_PATH = REPO_ROOT / "catalog" / "python-execution.yml"
META_GATE = "check_python_execution_contract.py"
SPECIAL_GLOBALS = {
    "__builtins__", "__cached__", "__file__", "__loader__", "__name__",
    "__package__", "__spec__",
}
MUTATING_CALLS = {
    "copy", "copy2", "copyfile", "copytree", "mkdir", "move", "open",
    "remove", "rename", "replace", "rmtree", "run", "check_call",
    "check_output", "unlink", "urlopen", "write_bytes", "write_text",
}
PROCESS_CALLS = {"run", "Popen", "check_call", "check_output"}
OS_PROCESS_PREFIXES = ("exec", "spawn")
OS_PROCESS_NAMES = {"system", "popen"}

# Documents are discovered, never merely read from the registry. See
# `_discovered_tool_documents` for why a closed allowlist was fail-open.
DISCOVERY_SUFFIXES = (".md", ".yml", ".yaml")
DISCOVERY_SKIP_PREFIXES = (
    ".git/", ".venv/", ".ruff_cache/",
    # Globbed directly and checked with the full workflow grammar.
    ".github/workflows/",
    # Declared rejection-only by `source_classes`; these exist to be refused.
    "tests/fixtures/negative/",
)
DISCOVERY_SKIP_PARTS = ("__pycache__",)
# A Python interpreter launching a path under `scripts/`. Deliberately matches
# both the bare `python3 scripts/x.py` shape and the launcher prefix, because
# the point is to find every document that *claims* to run a repository tool,
# including the ones that claim it wrongly.
REPOSITORY_TOOL_INVOCATION = re.compile(
    r"""(?:^|[\s"'`(])(?:[\w./-]*python[\w.]*)\s+(?:-\S+\s+)*scripts/"""
    r"""([A-Za-z_][A-Za-z0-9_]*\.py)"""
)


@dataclass(frozen=True)
class Invocation:
    executable: str
    flags: tuple[str, ...]
    launcher: str
    verb: str
    subject: str
    arguments: tuple[str, ...]


class SourceRole(str, Enum):
    WORKFLOW = "workflow"
    REPOSITORY_LAUNCHER = "repository-launcher"
    ADOPTION_GUIDE = "adoption-guide"
    CONSUMER_COMMAND = "consumer-command"
    SHELL_FIXTURE = "shell-fixture"


class SourceLanguage(str, Enum):
    YAML = "yaml"
    MARKDOWN = "markdown"
    PYTHON = "python"
    SHELL = "shell"


@dataclass(frozen=True)
class InvocationSource:
    path: Path
    text: str
    role: SourceRole
    language: SourceLanguage


@dataclass(frozen=True)
class ExtractedCommand:
    source_path: Path
    line: int
    location: str
    role: SourceRole
    language: SourceLanguage
    grammar: SourceLanguage
    text: str


def _repository_package_spec(root: Path) -> tuple[Any | None, list[str]]:
    """Build one exact package spec and report typed origin failures."""
    problems: list[str] = []
    package_init = root / PACKAGE_INIT
    if root.is_symlink() or package_init.is_symlink() or not package_init.is_file():
        return None, ["repository tool package root is missing or unsafe"]
    try:
        text = package_init.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return None, [f"repository tool package manifest is unreadable: {exc}"]
    if text != (
        '"""Repository-owned validator package; loaded only by the isolated launcher."""\n'
        "\nPACKAGE_CONTRACT = \"ci-workflows-tools-v1\"\n"
    ):
        problems.append("repository tool package manifest is stale or duplicated")
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME, package_init, submodule_search_locations=[str(root)],
    )
    if spec is None or spec.loader is None \
            or spec.origin != str(package_init) \
            or tuple(spec.submodule_search_locations or ()) != (str(root),):
        problems.append("cannot construct the repository tool package spec")
    return spec, problems


def _loaded_package_problems(module: ModuleType, root: Path) -> list[str]:
    spec = getattr(module, "__spec__", None)
    locations = tuple(getattr(spec, "submodule_search_locations", ()) or ())
    if getattr(spec, "origin", None) != str(root / PACKAGE_INIT) \
            or locations != (str(root),):
        return ["repository tool package is duplicated or has wrong origin"]
    if getattr(module, "PACKAGE_CONTRACT", None) != "ci-workflows-tools-v1":
        return ["repository tool package contract is missing or stale"]
    return []


def _register_repository_package() -> None:
    """Register the exact repository package without changing sys.path."""
    existing = sys.modules.get(PACKAGE_NAME)
    if existing is not None:
        problems = _loaded_package_problems(existing, SCRIPTS)
        if problems:
            raise RuntimeError(problems[0])
        return
    spec, problems = _repository_package_spec(SCRIPTS)
    if problems or spec is None:
        raise RuntimeError(problems[0] if problems else "package spec is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(PACKAGE_NAME, None)
        raise
    problems = _loaded_package_problems(module, SCRIPTS)
    if problems:
        sys.modules.pop(PACKAGE_NAME, None)
        raise RuntimeError(problems[0])


def _helper_origin_problems(root: Path, module: str, origin: str | None) -> list[str]:
    expected = root / f"{module}.py"
    if not expected.is_file() or expected.is_symlink():
        return [f"repository helper {module!r} is missing or unsafe"]
    if origin is None or Path(origin).resolve() != expected.resolve():
        return [f"repository helper {module!r} has wrong or shadowed origin"]
    return []


def _canonical_invocation(subject: str, arguments: Sequence[str] = ()) -> Invocation:
    prefix = load_policy()["python"]["launcher_prefix"]
    return Invocation(prefix[0], tuple(prefix[1:3]), prefix[3], prefix[4], subject,
                      tuple(arguments))


def _render_invocation(invocation: Invocation) -> str:
    return shlex.join([
        invocation.executable, *invocation.flags, invocation.launcher,
        invocation.verb, invocation.subject, "--", *invocation.arguments,
    ])


def _dependency_python_argv(
    executable: Path, expected: Path, prefix: Path, module_origin: Path,
    arguments: str,
) -> list[str]:
    """Validate one captured interpreter/dependency shape and return exact argv."""
    if executable.is_symlink() or executable.resolve() != expected.resolve():
        raise ValueError("dependency command is not running on the repository interpreter")
    try:
        tokens = shlex.split(arguments, posix=True)
    except ValueError as exc:
        raise ValueError(f"dependency command arguments are malformed: {exc}") from exc
    if not tokens or any(token in {"&&", "||", ";", "|", "<", ">"} for token in tokens):
        raise ValueError("dependency command arguments must be a non-empty argv sequence")
    if module_origin.is_symlink() or not _inside(module_origin.resolve(), prefix.resolve()):
        raise ValueError("required dependency is missing or outside the repository venv")
    return [str(executable), *tokens]


def dependency_python_command(arguments: str, required_module: str) -> str:
    """Bind fixture arguments to the already-verified repository interpreter."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", required_module):
        raise ValueError("dependency module name is invalid")
    spec = importlib.util.find_spec(required_module)
    if spec is None or spec.origin is None:
        raise ValueError(f"required module {required_module!r} is unavailable")
    argv = _dependency_python_argv(
        Path(sys.executable), _repository_interpreter(load_policy()),
        Path(sys.prefix), Path(spec.origin), arguments,
    )
    return shlex.join(argv)


def _logical_shell_commands(text: str) -> list[tuple[int, str]]:
    """Join only POSIX backslash continuations while retaining start lines."""
    commands: list[tuple[int, str]] = []
    parts: list[str] = []
    start = 0
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not parts and (not stripped or stripped.startswith("#")):
            continue
        if not parts:
            start = number
        continued = stripped.endswith("\\")
        parts.append(stripped[:-1].rstrip() if continued else stripped)
        if not continued:
            commands.append((start, " ".join(part for part in parts if part)))
            parts = []
    if parts:
        raise ValueError(f"line {start}: truncated POSIX continuation")
    return commands


def _parse_invocation(command: str) -> Invocation | None:
    marker = "scripts/check_python_execution_contract.py"
    if marker not in command and "scripts/" not in command and "python" not in command:
        return None
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError as exc:
        raise ValueError(f"malformed shell command: {exc}") from exc
    for operator in ("&&", "||", ";"):
        if operator in tokens:
            tokens = tokens[:tokens.index(operator)]
    try:
        index = tokens.index(marker)
    except ValueError:
        nested = [token for token in tokens if marker in token]
        if len(nested) == 1 and nested[0] != command:
            return _parse_invocation(nested[0])
        return None
    if index < 3 or len(tokens) <= index + 3:
        return Invocation(tokens[0] if tokens else "", tuple(tokens[1:index]), marker,
                          "", "", ())
    tail = tokens[index + 1:]
    if tail.count("--") != 1:
        return Invocation(tokens[0], tuple(tokens[1:index]), marker,
                          "<invalid-separator>",
                          tail[1] if len(tail) > 1 else "", ())
    separator = tail.index("--")
    subject = tail[1] if len(tail) > 1 else ""
    return Invocation(tokens[0], tuple(tokens[1:index]), marker, tail[0], subject,
                      tuple(tail[separator + 1:]))


def _workflow_commands(source: InvocationSource) -> tuple[list[ExtractedCommand], list[str]]:
    """Return only executable step.run scalars from one strict YAML workflow."""
    try:
        strict_yaml = importlib.import_module(f"{PACKAGE_NAME}._strict_yaml")
        document = strict_yaml.strict_loads(source.text, str(source.path))
    except Exception as exc:
        return [], [f"{source.path.name}: workflow YAML is invalid: {exc}"]
    if not isinstance(document, dict):
        return [], [f"{source.path.name}: workflow root must be a mapping"]
    jobs = document.get("jobs")
    if not isinstance(jobs, dict):
        return [], [f"{source.path.name}: workflow jobs must be a mapping"]
    commands: list[ExtractedCommand] = []
    problems: list[str] = []
    run_lines = iter(
        number for number, raw in enumerate(source.text.splitlines(), 1)
        if raw.lstrip().startswith("run:")
    )
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps", [])
        if not isinstance(steps, list):
            problems.append(f"{source.path.name}: jobs.{job_name}.steps must be a list")
            continue
        for index, step in enumerate(steps):
            if not isinstance(step, dict) or "run" not in step:
                continue
            location = f"jobs.{job_name}.steps[{index}].run"
            command = step["run"]
            if not isinstance(command, str) or not command.strip():
                problems.append(
                    f"{source.path.name}: {location} must be a non-empty command scalar"
                )
                continue
            line = next(run_lines, 1)
            commands.append(ExtractedCommand(
                source.path, line, location, source.role, source.language,
                SourceLanguage.SHELL, command,
            ))
    return commands, problems


def _markdown_commands(source: InvocationSource) -> tuple[list[ExtractedCommand], list[str]]:
    commands: list[ExtractedCommand] = []
    problems: list[str] = []
    fence_language: str | None = None
    fence_start = 0
    lines: list[str] = []
    executable = {"bash", "sh", "shell", "zsh"}
    for number, raw in enumerate(source.text.splitlines(), 1):
        match = re.match(r"^\s*```([^\s`]*)\s*$", raw)
        if match:
            if fence_language is None:
                fence_language = match.group(1).lower()
                fence_start = number + 1
                lines = []
            else:
                if fence_language in executable:
                    try:
                        logical = _logical_shell_commands("\n".join(lines))
                    except ValueError as exc:
                        problems.append(f"{source.path.name}: fence@{fence_start}: {exc}")
                        logical = []
                    for offset, command in logical:
                        if _is_repository_command_candidate(command):
                            line = fence_start + offset - 1
                            commands.append(ExtractedCommand(
                                source.path, line, f"fence@{line}", source.role,
                                source.language, SourceLanguage.SHELL, command,
                            ))
                fence_language = None
                lines = []
            continue
        if fence_language is not None:
            lines.append(raw)
    if fence_language is not None:
        problems.append(f"{source.path.name}: unterminated Markdown fence at line {fence_start - 1}")
    return commands, problems


def _python_commands(source: InvocationSource) -> tuple[list[ExtractedCommand], list[str]]:
    try:
        tree = ast.parse(source.text, filename=str(source.path), feature_version=(3, 13))
    except SyntaxError as exc:
        return [], [f"{source.path.name}: Python source is invalid: {exc}"]
    commands: list[ExtractedCommand] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        try:
            logical = _logical_shell_commands(node.value)
        except ValueError as exc:
            if _is_repository_command_candidate(node.value):
                return [], [f"{source.path.name}: string@{node.lineno}: {exc}"]
            continue
        for offset, command in logical:
            if _is_repository_command_candidate(command):
                line = node.lineno + offset - 1
                commands.append(ExtractedCommand(
                    source.path, line, f"string@{line}", source.role,
                    source.language, SourceLanguage.SHELL, command,
                ))
    return commands, []


def _is_repository_command_candidate(command: str) -> bool:
    return bool(re.search(
        r"scripts/(?:check_python_(?:execution_contract|syntax)|[A-Za-z0-9_]+)\.py\b",
        command,
    ))


def _source_commands(source: InvocationSource) -> tuple[list[ExtractedCommand], list[str]]:
    if source.language is SourceLanguage.YAML:
        return _workflow_commands(source)
    if source.language is SourceLanguage.MARKDOWN:
        return _markdown_commands(source)
    if source.language is SourceLanguage.PYTHON:
        return _python_commands(source)
    if source.language is not SourceLanguage.SHELL:
        return [], [f"{source.path.name}: unclassified executable source language"]
    try:
        commands = _logical_shell_commands(source.text)
    except ValueError as exc:
        return [], [f"{source.path.name}: {exc}"]
    return [
        ExtractedCommand(source.path, number, f"line {number}", source.role,
                         source.language, SourceLanguage.SHELL, command)
        for number, command in commands
    ], []


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate policy key {key!r}")
        result[key] = value
    return result


def load_policy() -> dict[str, Any]:
    """Load the JSON-subset YAML policy without needing a site dependency."""
    try:
        raw = POLICY_PATH.read_text(encoding="utf-8")
        policy = json.loads(raw, object_pairs_hook=_no_duplicates)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"cannot load canonical Python execution policy: {exc}") from exc
    if not isinstance(policy, dict):
        raise RuntimeError("canonical Python execution policy is not a mapping")
    return policy


def _policy_surfaces(policy: Mapping[str, Any]) -> set[str]:
    groups = policy.get("surface_groups")
    if not isinstance(groups, dict):
        return set()
    return {
        item
        for values in groups.values()
        if isinstance(values, list)
        for item in values
        if isinstance(item, str)
    }


def _registered_tool(tool: str, surfaces: set[str]) -> bool:
    return tool in surfaces and Path(tool).name == tool and tool.endswith(".py")


def _python_key(name: str) -> bool:
    return name.upper().startswith("PYTHON")


def _evidence_names(raw: str, label: str) -> set[str]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} evidence is malformed") from exc
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise ValueError(f"{label} evidence must be a string array")
    return set(parsed)


def _transition_environment(
    source: Mapping[str, str],
    overrides: Mapping[str, str] | None = None,
    *,
    inherit: Sequence[str] = (),
) -> dict[str, str]:
    """Apply the one pure, observable environment transition."""
    policy = load_policy()
    contract = policy["environment"]
    allowlist = set(contract["base_allowlist"])
    allowed_inherit = {
        name
        for values in policy.get("surface_environment", {}).values()
        for name in values
    }
    requested_inherit = set(inherit)
    unknown = sorted(requested_inherit - allowed_inherit)
    if unknown:
        raise ValueError(f"unregistered inherited variables: {unknown}")
    requested = allowlist | requested_inherit
    forbidden = sorted(name for name in requested if _python_key(name))
    if forbidden:
        raise ValueError(f"interpreter-control variables cannot be inherited: {forbidden}")
    env = {
        name: str(source[name])
        for name in sorted(requested)
        if name in source and not _python_key(name)
    }
    canonical = {str(k): str(v) for k, v in contract["canonical_values"].items()}
    for name, value in (overrides or {}).items():
        if _python_key(name):
            raise ValueError(f"interpreter-control override is forbidden: {name}")
        if name in canonical and str(value) != canonical[name]:
            raise ValueError(f"canonical environment override is forbidden: {name}")
        env[str(name)] = str(value)
    env.update(canonical)
    stripped_name = contract["stripped_names_evidence"]
    inherited_name = contract["inherited_names_evidence"]
    prior_stripped = _evidence_names(source.get(stripped_name, "[]"), "stripped")
    prior_inherited = _evidence_names(source.get(inherited_name, "[]"), "inherited")
    stripped = {name for name in source if _python_key(name)}
    generated = set(canonical) | set(overrides or {})
    inherited = {
        name for name in requested
        if name in source and not _python_key(name) and name not in generated
    }
    env[stripped_name] = json.dumps(
        sorted(prior_stripped | stripped), separators=(",", ":"),
    )
    env[inherited_name] = json.dumps(
        sorted(prior_inherited | inherited), separators=(",", ":"),
    )
    return env


def clean_environment(
    overrides: Mapping[str, str] | None = None,
    *,
    inherit: Sequence[str] = (),
) -> dict[str, str]:
    """The sole ambient bootstrap boundary for every child process."""
    return _transition_environment(os.environ, overrides, inherit=inherit)


def hostile_probe_environment(root: Path) -> dict[str, str]:
    """Inject taint at the one registered outer edge, never at a normal edge."""
    policy = load_policy()
    names = policy["environment"]["hostile_probe_variables"]
    values = {
        "PYTHONBREAKPOINT": "hostile.breakpoint",
        "PYTHONCOERCECLOCALE": "warn",
        "PYTHONHOME": str(root / "missing-python-home"),
        "PYTHONIOENCODING": "ascii:strict",
        "PYTHONPATH": str(root / "shadow"),
        "PYTHONUTF8": "0",
        "PYTHONWARNINGS": "error",
        "pythonpath": str(root / "mixed-case-shadow"),
    }
    if sorted(values) != sorted(names):
        raise RuntimeError("hostile probe variables drifted from policy")
    env = clean_environment()
    # This edge owns the exact taint set. Ambient stripping is proven by the
    # outer launcher; the nested probe must not inherit machine-specific names
    # in its expected receipt.
    env[policy["environment"]["stripped_names_evidence"]] = "[]"
    env[policy["environment"]["inherited_names_evidence"]] = "[]"
    env.update(values)
    env["LANG"] = "invalid_LOCALE.invalid"
    env["LC_ALL"] = "invalid_LOCALE.invalid"
    return env


def _files() -> dict[str, Path]:
    return {path.name: path for path in sorted(SCRIPTS.glob("*.py"))}


def _import_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith(f"{PACKAGE_NAME}."):
                roots.add(node.module.split(".", 1)[1].split(".", 1)[0])
            elif node.module == PACKAGE_NAME:
                roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            else:
                roots.add(node.module.split(".", 1)[0])
    return roots


def _unqualified_sibling_imports(tree: ast.AST, siblings: set[str]) -> list[str]:
    """Reject sibling imports that bypass the verified repository package."""
    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in siblings:
                    problems.append(f"line {node.lineno}: unqualified sibling import {root!r}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".", 1)[0]
            if root in siblings:
                problems.append(f"line {node.lineno}: unqualified sibling import {root!r}")
    return problems


def _needs_yaml(tool: str, policy: Mapping[str, Any]) -> bool:
    graph = policy["sibling_imports"]
    external = policy["direct_external_imports"]
    pending = [tool]
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        if "yaml" in external.get(current, []):
            return True
        pending.extend(f"{name}.py" for name in graph.get(current, []))
    return False


def _dependency_root() -> tuple[Path | None, list[str]]:
    policy = load_policy()
    dependency = policy["python"]["external_dependencies"]["yaml"]
    problems: list[str] = []
    lock_path = (REPO_ROOT / policy["python"]["dependency_lock"]).absolute()
    if lock_path != lock_path.resolve() or not _inside(lock_path.resolve(), REPO_ROOT) \
            or not lock_path.is_file():
        return None, [f"dependency lock is not a regular repository file: {lock_path}"]
    try:
        lock_text = lock_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return None, [f"cannot read hash-pinned dependency lock: {exc}"]
    problems += _locked_dependency_problems(lock_text, dependency)
    try:
        distribution = importlib.metadata.distribution(dependency["distribution"])
        spec = importlib.util.find_spec("yaml")
    except importlib.metadata.PackageNotFoundError:
        return None, ["pinned PyYAML distribution is unavailable"]
    problems += _distribution_identity_problems(
        distribution.metadata.get("Name", ""), distribution.version, dependency,
    )
    if spec is None or spec.origin is None:
        return None, problems + ["yaml module origin is unavailable"]
    identity, identity_problems = _active_venv_identity()
    problems += identity_problems
    if identity is None:
        return None, problems
    roots = {Path(identity[name]).resolve() for name in ("purelib", "platlib")}
    distribution_root = Path(distribution.locate_file("")).absolute()
    metadata_entries = [
        entry for entry in (distribution.files or [])
        if entry.name == "METADATA" and entry.parent.name.endswith(".dist-info")
    ]
    if len(metadata_entries) != 1:
        problems.append("installed distribution has no unique dist-info/METADATA record")
        distribution_path = distribution_root / "<missing-dist-info>"
    else:
        distribution_path = Path(
            distribution.locate_file(metadata_entries[0])
        ).absolute().parent
    origin_raw = Path(spec.origin).absolute()
    root = distribution_root.resolve()
    problems += _dependency_path_problems(
        roots, distribution_root, distribution_path, origin_raw,
        dependency["module_path"],
    )
    return root, problems


def _normalized_distribution(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _distribution_identity_problems(
    name: str, version: str, dependency: Mapping[str, str],
) -> list[str]:
    problems: list[str] = []
    if _normalized_distribution(name) != _normalized_distribution(dependency["distribution"]):
        problems.append("installed distribution name differs from dependency policy")
    if version != dependency["version"]:
        problems.append(
            f"{dependency['distribution']} version must be {dependency['version']}, got {version}"
        )
    return problems


def _locked_dependency_problems(
    text: str, dependency: Mapping[str, str],
) -> list[str]:
    problems: list[str] = []
    normalized = _normalized_distribution(dependency["distribution"])
    requirement = re.compile(
        rf"(?im)^{re.escape(normalized)}=={re.escape(dependency['version'])}\s*\\$"
    )
    if len(requirement.findall(text)) != 1:
        problems.append("dependency lock lacks one exact pinned distribution/version record")
    hashes = re.findall(r"(?m)^\s+--hash=sha256:([0-9a-f]{64})(?:\s*\\)?$", text)
    if not hashes or len(hashes) != len(set(hashes)):
        problems.append("dependency lock hashes are missing, malformed, or duplicated")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("--hash=") \
                or requirement.fullmatch(stripped):
            continue
        problems.append(f"dependency lock contains an unexpected record: {stripped!r}")
    return problems


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _dependency_path_problems(
    site_roots: set[Path], distribution_root: Path, distribution_path: Path,
    origin: Path, module_path: str,
) -> list[str]:
    problems: list[str] = []
    real_root = distribution_root.resolve()
    real_distribution = distribution_path.resolve()
    real_origin = origin.resolve()
    if real_root not in site_roots:
        problems.append(f"distribution root is outside the active venv: {distribution_root}")
    if not _inside(real_distribution, real_root):
        problems.append(f"distribution metadata escapes the active venv: {distribution_path}")
    if not _inside(real_origin, real_root) \
            or real_origin != real_root / module_path:
        problems.append(f"dependency import origin is untrusted: {origin}")
    return problems


def _read_pyvenv(path: Path) -> tuple[dict[str, str], list[str]]:
    problems: list[str] = []
    if not path.is_file() or path.is_symlink():
        return {}, [f"active venv has no regular non-symlink pyvenv.cfg: {path}"]
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        return {}, [f"cannot read active pyvenv.cfg: {exc}"]
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        if "=" not in line:
            problems.append(f"pyvenv.cfg:{number}: malformed record")
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if not key or key in values:
            problems.append(f"pyvenv.cfg:{number}: empty or duplicate key")
            continue
        values[key] = value
    return values, problems


def _base_anchor(
    identity: Mapping[str, Any], config: Mapping[str, str],
    venv_policy: Mapping[str, Any],
) -> tuple[Path | None, list[str]]:
    """Resolve optional runtime and config facts to one base executable."""
    problems: list[str] = []
    home = config.get("home")
    home_path = Path(home).absolute() if home else None
    home_candidates = [] if home_path is None or not home_path.is_dir() else [
        home_path / name for name in venv_policy["home_interpreter_names"]
        if (home_path / name).is_file()
    ]
    declared_paths = [
        Path(value).absolute() for value in (
            identity.get("base_executable", ""), config.get("executable", ""),
        ) if value
    ]
    if any(not path.is_file() for path in declared_paths):
        problems.append("declared base executable is missing or non-regular")
    declared_targets = {path.resolve() for path in declared_paths if path.is_file()}
    home_targets = {candidate.resolve() for candidate in home_candidates}
    candidates = declared_targets & home_targets if declared_targets else home_targets
    if len(candidates) != 1:
        problems.append("pyvenv home does not identify one coherent base executable")
        return None, problems
    if len(declared_targets) > 1:
        problems.append("runtime and pyvenv base executable identities differ")
    return next(iter(candidates)), problems


def _venv_identity_problems(
    identity: Mapping[str, Any], config: Mapping[str, str], *,
    expected_prefix: Path | None = None,
) -> list[str]:
    problems: list[str] = []
    policy = load_policy()
    venv_policy = policy["python"]["venv"]
    prefix = Path(identity["prefix"]).absolute()
    base_prefix = Path(identity["base_prefix"]).absolute()
    exec_prefix = Path(identity["exec_prefix"]).absolute()
    base_exec_prefix = Path(identity["base_exec_prefix"]).absolute()
    executable = Path(identity["executable"]).absolute()
    real_prefix = prefix.resolve()
    real_base_prefix = base_prefix.resolve()
    version_info = tuple(identity["version_info"])
    implementation_version = tuple(identity["implementation_version"])
    expected_line = tuple(int(part) for part in policy["python"]["major_minor"].split("."))
    if version_info[:2] != expected_line or version_info[3:] != (
        venv_policy["release_level"], 0,
    ):
        problems.append("runtime Python identity is outside the canonical compatibility line")
    if identity["implementation_name"] != venv_policy["implementation_name"] \
            or implementation_version != version_info:
        problems.append("runtime and CPython implementation identities differ")
    if identity["cache_tag"] != f"cpython-{expected_line[0]}{expected_line[1]}":
        problems.append("runtime import cache tag differs from the CPython compatibility line")
    if real_prefix == real_base_prefix:
        problems.append("interpreter is not inside a virtual environment")
    if expected_prefix is not None and (
        not expected_prefix.is_dir() or expected_prefix.is_symlink()
        or real_prefix != expected_prefix.resolve()
        or not _inside(real_prefix, REPO_ROOT.resolve())
    ):
        problems.append("active virtual environment is not the repository-owned .venv")
    if exec_prefix != prefix or base_exec_prefix.resolve() != base_prefix.resolve():
        problems.append("interpreter prefix and exec-prefix identities are incoherent")
    real_base_executable, anchor_problems = _base_anchor(identity, config, venv_policy)
    problems += anchor_problems
    if real_base_executable is not None:
        if not _inside(real_base_executable, real_base_prefix):
            problems.append("declared base executable is outside the base installation")
    executable_parents = {prefix / "bin", prefix / "Scripts"}
    if executable.parent not in executable_parents or not executable.is_file() \
            or executable.is_symlink():
        problems.append("venv interpreter is not a regular executable in the venv")
    # A copy-based venv intentionally has a distinct executable inode. Its
    # base provenance is established by the coherent runtime/config/home
    # anchors above, while this executable is constrained to the venv root.
    expected_system_site = str(venv_policy["include_system_site_packages"]).lower()
    if config.get("include-system-site-packages", "").lower() != expected_system_site:
        problems.append("pyvenv must disable system site-packages")
    configured_version = config.get("version_info", config.get("version", ""))
    if configured_version != identity["version"]:
        problems.append("pyvenv version differs from the running interpreter")
    if config.get("implementation", venv_policy["implementation"]) != \
            venv_policy["implementation"]:
        problems.append("pyvenv implementation must be CPython")
    if identity["enable_user_site"] is not False:
        problems.append("active interpreter must disable user site-packages")
    for key in ("purelib", "platlib"):
        path = Path(identity[key]).absolute()
        if not _inside(path.resolve(), real_prefix) \
                or path.name != "site-packages":
            problems.append(f"{key} escapes the active-venv site-packages root")
    return problems


def _active_venv_identity() -> tuple[dict[str, Any] | None, list[str]]:
    prefix = Path(sys.prefix).absolute()
    config, problems = _read_pyvenv(prefix / "pyvenv.cfg")
    identity = {
        "prefix": str(prefix),
        "base_prefix": sys.base_prefix,
        "exec_prefix": sys.exec_prefix,
        "base_exec_prefix": sys.base_exec_prefix,
        "executable": sys.executable,
        "base_executable": getattr(sys, "_base_executable", ""),
        "version": ".".join(str(part) for part in sys.version_info[:3]),
        "version_info": tuple(sys.version_info),
        "implementation_name": sys.implementation.name,
        "implementation_version": tuple(sys.implementation.version),
        "cache_tag": sys.implementation.cache_tag,
        "purelib": sysconfig.get_path("purelib"),
        "platlib": sysconfig.get_path("platlib"),
        "stdlib": sysconfig.get_path("stdlib"),
        "platstdlib": sysconfig.get_path("platstdlib"),
        "scripts": sysconfig.get_path("scripts"),
        "data": sysconfig.get_path("data"),
        "enable_user_site": site.ENABLE_USER_SITE,
    }
    problems += _venv_identity_problems(
        identity, config,
        expected_prefix=REPO_ROOT / load_policy()["python"]["venv"]["path"],
    )
    return identity, problems


def _repository_interpreter(policy: Mapping[str, Any]) -> Path:
    """Return the single executable named by the repository policy."""
    raw = policy["python"]["dependency_interpreter"]
    path = REPO_ROOT / raw
    expected = REPO_ROOT / policy["python"]["venv"]["path"] / "bin" / "python"
    if path != expected:
        raise RuntimeError("repository interpreter policy is not canonical")
    return path


def _bootstrap_receipt(policy: Mapping[str, Any]) -> tuple[str, str]:
    contract = policy["python"]["bootstrap"]
    return contract["transition_receipt"], contract["receipt_version"]


def _bootstrap_decision(current: Path, expected: Path, receipt: str | None,
                        receipt_value: str) -> str:
    """Classify the one-way interpreter edge without executing it."""
    if receipt not in (None, receipt_value):
        return "malformed-receipt"
    if current.resolve() == expected.resolve():
        return "arrived" if receipt == receipt_value else "current"
    if receipt == receipt_value:
        return "loop-or-wrong-target"
    return "transition"


def _ensure_repository_interpreter() -> None:
    """Perform at most one stdlib-only transition before identity/import checks."""
    policy = load_policy()
    expected = _repository_interpreter(policy)
    receipt_name, receipt_value = _bootstrap_receipt(policy)
    received = os.environ.get(receipt_name)
    current = Path(sys.executable).absolute()
    if received not in (None, receipt_value):
        print("python-launcher: malformed bootstrap receipt", file=sys.stderr)
        raise SystemExit(2)
    if not expected.is_file() or expected.is_symlink() or not os.access(expected, os.X_OK):
        print("python-launcher: repository interpreter is unavailable or unsafe", file=sys.stderr)
        raise SystemExit(2)
    decision = _bootstrap_decision(current, expected, received, receipt_value)
    if decision in {"current", "arrived"}:
        if decision == "arrived":
            print(
                "python-bootstrap-transition: "
                + json.dumps(
                    {"from": "external", "to": str(expected), "version": receipt_value},
                    sort_keys=True, separators=(",", ":"),
                ),
                file=sys.stderr,
            )
        return
    if decision == "loop-or-wrong-target":
        print("python-launcher: bootstrap transition loop or wrong target", file=sys.stderr)
        raise SystemExit(2)
    env = clean_environment({receipt_name: receipt_value})
    argv = [str(expected), "-I", "-B", str(Path(__file__).resolve()), *sys.argv[1:]]
    os.execve(expected, argv, env)


def _venv_receipt() -> dict[str, Any]:
    """Return non-secret runtime identity evidence from the validated process."""
    identity, problems = _active_venv_identity()
    if problems or identity is None:
        raise RuntimeError("cannot emit an unvalidated venv identity receipt")
    dependency = load_policy()["python"]["external_dependencies"]["yaml"]
    distribution = importlib.metadata.distribution(dependency["distribution"])
    spec = importlib.util.find_spec("yaml")
    if spec is None or spec.origin is None:
        raise RuntimeError("cannot emit a receipt without the yaml import origin")
    config, config_problems = _read_pyvenv(Path(identity["prefix"]) / "pyvenv.cfg")
    if config_problems:
        raise RuntimeError("cannot emit a receipt without pyvenv identity")
    base_executable, anchor_problems = _base_anchor(
        identity, config, load_policy()["python"]["venv"],
    )
    if anchor_problems or base_executable is None:
        raise RuntimeError("cannot emit a receipt without one base executable")
    def path_identity(raw: str) -> dict[str, str]:
        path = Path(raw)
        return {"raw": raw, "resolved": str(path.resolve())}

    return {
        "base_executable": str(base_executable),
        "cache_tag": identity["cache_tag"],
        "dependency": dependency["distribution"],
        "dependency_origin": str(Path(spec.origin).resolve()),
        "dependency_version": distribution.version,
        "implementation": identity["implementation_name"],
        "implementation_version": list(identity["implementation_version"]),
        "paths": {
            name: path_identity(str(identity[name]))
            for name in (
                "executable", "prefix", "exec_prefix", "base_prefix",
                "base_exec_prefix", "base_executable", "purelib", "platlib",
                "stdlib", "platstdlib", "scripts", "data",
            ) if identity[name]
        },
        "pyvenv": dict(sorted(config.items())),
        "sys_version": sys.version,
        "version_info": list(identity["version_info"]),
    }


def _runtime_problems(policy: Mapping[str, Any] | None = None) -> list[str]:
    problems: list[str] = []
    active_policy = policy or load_policy()
    expected = tuple(
        int(part) for part in active_policy["python"]["major_minor"].split(".")
    )
    if sys.version_info[:2] != expected:
        problems.append(
            f"requires Python {expected[0]}.{expected[1]}, "
            f"got {sys.version_info.major}.{sys.version_info.minor}"
        )
    for name in ("isolated", "ignore_environment", "no_user_site", "safe_path"):
        if getattr(sys.flags, name, 0) != 1:
            problems.append(f"launcher requires sys.flags.{name}=1")
    if getattr(sys.flags, "dont_write_bytecode", 0) != 1:
        problems.append("launcher requires sys.flags.dont_write_bytecode=1")
    return problems


def _resource_problems(root: Path, policy: Mapping[str, Any]) -> list[str]:
    return [
        f"missing required repository resource {relative}"
        for relative in policy["required_resources"]
        if not (root / relative).exists()
    ]


def _bootstrap(
    tool: str, dependency_raw: str, args: list[str], *, import_only: bool,
) -> int:
    policy = load_policy()
    problems = _runtime_problems(policy)
    surfaces = _policy_surfaces(policy)
    files = _files()
    expected = surfaces | {META_GATE, PACKAGE_INIT}
    if len(surfaces) != policy["python"]["subject_count"] or set(files) != expected:
        problems.append(
            f"inventory drift: count={len(surfaces)} "
            f"missing={sorted(expected - set(files))} extra={sorted(set(files) - expected)}"
        )
    if not _registered_tool(tool, surfaces):
        problems.append(f"unregistered or unsafe Python tool {tool!r}")
    needs_yaml = tool in surfaces and _needs_yaml(tool, policy)
    if needs_yaml != (dependency_raw == "@active"):
        problems.append("dependency claim differs from the registered import graph")
    dependency_root: Path | None = None
    if needs_yaml:
        dependency_root, dependency_problems = _dependency_root()
        problems += dependency_problems
    _register_repository_package()
    for module, path in ((path.stem, path) for path in files.values()
                         if path.name != PACKAGE_INIT):
        spec = importlib.util.find_spec(f"{PACKAGE_NAME}.{module}")
        problems += _helper_origin_problems(
            SCRIPTS, module, spec.origin if spec is not None else None,
        )
    problems += _resource_problems(REPO_ROOT, policy)
    if problems:
        for problem in problems:
            print(f"python-bootstrap: {problem}", file=sys.stderr)
        return 2
    if import_only:
        importlib.import_module(f"{PACKAGE_NAME}.{Path(tool).stem}")
        return 0
    if needs_yaml:
        print(
            "python-execution-receipt: "
            + json.dumps(_venv_receipt(), sort_keys=True, separators=(",", ":")),
            file=sys.stderr,
        )
    sys.argv = [str(files[tool]), *args]
    runpy.run_module(
        f"{PACKAGE_NAME}.{Path(tool).stem}", run_name="__main__", alter_sys=False,
    )
    return 0


def _surface_inherit(tool: str) -> tuple[str, ...]:
    values = load_policy().get("surface_environment", {}).get(tool, [])
    return tuple(values) if isinstance(values, list) else ()


def _subject_interpreter(
    tool: str, policy: Mapping[str, Any], *, root: Path = REPO_ROOT,
    current: Path | None = None,
) -> tuple[Path | None, str, list[str]]:
    """Select the physical interpreter before the subject process is built."""
    if not _needs_yaml(tool, policy):
        return current or Path(sys.executable), "-", []
    executable = root / policy["python"]["dependency_interpreter"]
    expected_parent = root / policy["python"]["venv"]["path"] / "bin"
    if executable.parent != expected_parent or not executable.is_file() \
            or executable.is_symlink() \
            or not os.access(executable, os.X_OK):
        return None, "@active", ["repository dependency interpreter is unavailable"]
    return executable, "@active", []


def _launch(tool: str, args: list[str]) -> int:
    policy = load_policy()
    surfaces = _policy_surfaces(policy)
    if not _registered_tool(tool, surfaces):
        print(f"python-launcher: unregistered or unsafe Python tool {tool!r}", file=sys.stderr)
        return 2
    executable, dependency_claim, problems = _subject_interpreter(tool, policy)
    if problems or executable is None:
        for problem in problems or ["repository dependency interpreter is unavailable"]:
            print(f"python-launcher: {problem}", file=sys.stderr)
        return 2
    command = [
        str(executable), "-I", "-B", str(Path(__file__).resolve()),
        "--bootstrap", tool, dependency_claim, "--", *args,
    ]
    env = clean_environment(inherit=_surface_inherit(tool))
    completed = subprocess.run(command, env=env, check=False)
    return completed.returncode


def _probe_payload(role: str) -> dict[str, Any]:
    policy = load_policy()
    evidence_name = policy["environment"]["stripped_names_evidence"]
    inherited_name = policy["environment"]["inherited_names_evidence"]
    return {
        "role": role,
        "isolated": sys.flags.isolated,
        "ignore_environment": sys.flags.ignore_environment,
        "safe_path": sys.flags.safe_path,
        "no_user_site": sys.flags.no_user_site,
        "dont_write_bytecode": sys.flags.dont_write_bytecode,
        "python_keys": sorted(name for name in os.environ if _python_key(name)),
        "stripped": json.loads(os.environ.get(evidence_name, "[]")),
        "inherited": json.loads(os.environ.get(inherited_name, "[]")),
        "environment_keys": sorted(os.environ),
        "locale": {"LANG": os.environ.get("LANG"), "LC_ALL": os.environ.get("LC_ALL")},
    }


def _probe_child() -> int:
    env = clean_environment()
    completed = subprocess.run(
        [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--probe-leaf"],
        env=env, text=True, encoding="utf-8", stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )
    if completed.returncode != 0:
        sys.stderr.write(completed.stderr)
        return completed.returncode
    payload = _probe_payload("middle")
    payload["leaf"] = json.loads(completed.stdout)
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


def _probe_sanitize() -> int:
    """Cross the owned ambient boundary before any observed subject starts."""
    completed = subprocess.run(
        [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--probe-middle"],
        env=clean_environment(), text=True, encoding="utf-8",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    return completed.returncode


def _probe_generations(root: Path) -> list[str]:
    problems: list[str] = []
    command = [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--probe-sanitize"]
    completed = subprocess.run(
        command, cwd=root, env=hostile_probe_environment(root), text=True,
        encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    failure = subprocess.run(
        [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--probe-fail"],
        cwd=root, env=clean_environment(), text=True, encoding="utf-8",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if completed.returncode != 0:
        return [f"multi-generation hostile probe failed: {completed.stderr.strip()}"]
    try:
        middle = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return [f"multi-generation hostile probe emitted invalid JSON: {exc}"]
    expected = sorted(load_policy()["environment"]["hostile_probe_variables"])
    environment_contract = load_policy()["environment"]
    base_allowlist = set(environment_contract["base_allowlist"])
    canonical_names = set(environment_contract["canonical_values"])
    for label, payload in (("middle", middle), ("leaf", middle.get("leaf", {}))):
        if not isinstance(payload, dict):
            problems.append(f"{label} probe payload is missing")
            continue
        if payload.get("python_keys"):
            problems.append(f"{label} inherited interpreter-control variables")
        if payload.get("stripped") != expected:
            problems.append(f"{label} stripped-name evidence differs from policy")
        expected_inherited = sorted(
            (base_allowlist - canonical_names) & set(payload.get("environment_keys", []))
        )
        if payload.get("inherited") != expected_inherited:
            problems.append(f"{label} inherited-name evidence differs from transition")
        if payload.get("locale") != {"LANG": "C", "LC_ALL": "C"}:
            problems.append(f"{label} locale is not canonical")
        for flag in (
            "isolated", "ignore_environment", "safe_path", "no_user_site",
            "dont_write_bytecode",
        ):
            if payload.get(flag) != 1:
                problems.append(f"{label} omitted interpreter flag {flag}")
    if failure.returncode != 37 or failure.stderr != "probe-child-diagnostic\n":
        problems.append("nested child exit/diagnostic was not preserved exactly")
    return problems


def _undefined_names(source: str, filename: str) -> set[str]:
    table = symtable(source, filename, "exec")
    module_defined = {
        symbol.get_name() for symbol in table.get_symbols()
        if symbol.is_assigned() or symbol.is_imported() or symbol.is_namespace()
    }
    allowed = set(dir(builtins)) | SPECIAL_GLOBALS
    unresolved: set[str] = set()

    def visit(scope: SymbolTable) -> None:
        for symbol in scope.get_symbols():
            name = symbol.get_name()
            if not symbol.is_referenced() or name in allowed:
                continue
            if scope.get_type() == "module" and name not in module_defined:
                unresolved.add(name)
            elif scope.get_type() != "module" and symbol.is_global() \
                    and name not in module_defined:
                unresolved.add(name)
        for child in scope.get_children():
            visit(child)

    visit(table)
    return unresolved


def _import_side_effects(tree: ast.Module) -> list[str]:
    problems: list[str] = []
    for node in tree.body:
        candidates: list[ast.AST] = []
        if isinstance(node, ast.Expr):
            candidates.append(node.value)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            candidates.append(node.value)
        for candidate in candidates:
            for child in ast.walk(candidate):
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                    name = child.func.attr
                elif isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                    name = child.func.id
                else:
                    continue
                if name in MUTATING_CALLS:
                    problems.append(f"line {child.lineno}: import-time call to {name!r}")
    return problems


def _function_name(node: ast.AST, parents: Mapping[ast.AST, ast.AST]) -> str:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
    return "<module>"


def _process_edges(tree: ast.Module) -> tuple[dict[str, int], list[str]]:
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    counts: dict[str, int] = {}
    problems: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {"os", "subprocess"} and alias.asname is not None:
                    problems.append(
                        f"line {node.lineno}: process module {alias.name!r} may not be aliased"
                    )
        elif isinstance(node, ast.ImportFrom) and node.module in {"os", "subprocess"}:
            problems.append(
                f"line {node.lineno}: process functions must not be imported directly"
            )
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value.id if isinstance(node.func.value, ast.Name) else ""
        name = node.func.attr
        is_process = owner == "subprocess" and name in PROCESS_CALLS
        is_os_process = owner == "os" and (
            name in OS_PROCESS_NAMES or name.startswith(OS_PROCESS_PREFIXES)
        )
        if not is_process and not is_os_process:
            continue
        function = _function_name(node, parents)
        counts[function] = counts.get(function, 0) + 1
        keywords = {item.arg: item.value for item in node.keywords if item.arg}
        positional_env = owner == "os" and name in {"execve", "execvpe"} \
            and len(node.args) >= 3
        if not positional_env and (
            "env" not in keywords or isinstance(keywords.get("env"), ast.Constant)
            and keywords["env"].value is None
        ):
            problems.append(f"{function}:{node.lineno}: process edge has implicit env")
        env_value = node.args[2] if positional_env else keywords.get("env")
        if isinstance(env_value, ast.Attribute) and isinstance(env_value.value, ast.Name) \
                and env_value.value.id == "os" and env_value.attr == "environ":
            problems.append(f"{function}:{node.lineno}: process edge forwards os.environ")
    return counts, problems


def _process_semantic_problems(
    tree: ast.Module, filename: str, policy: Mapping[str, Any],
) -> list[str]:
    """Bind every AST process call to the complete semantics of its profile."""
    problems: list[str] = []
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    registered = policy["process_edges"].get(filename, {})
    profiles = policy["process_profiles"]
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value.id if isinstance(node.func.value, ast.Name) else ""
        name = node.func.attr
        if owner == "subprocess" and name in PROCESS_CALLS:
            observed_api = "subprocess"
        elif owner == "os" and (name in OS_PROCESS_NAMES or name.startswith(OS_PROCESS_PREFIXES)):
            observed_api = "execve" if name == "execve" else "os-process"
        else:
            continue
        function = _function_name(node, parents)
        edge = registered.get(function)
        if not isinstance(edge, dict) or edge.get("profile") not in profiles:
            continue  # The inventory-drift error owns missing registrations.
        profile = profiles[edge["profile"]]
        if profile["api"] != observed_api:
            problems.append(
                f"{function}:{node.lineno}: process API differs from profile"
            )
        keywords = {item.arg: item.value for item in node.keywords if item.arg}
        has_cwd = "cwd" in keywords and not (
            isinstance(keywords["cwd"], ast.Constant) and keywords["cwd"].value is None
        )
        if profile["cwd"] == "explicit" and not has_cwd:
            problems.append(f"{function}:{node.lineno}: profile requires explicit cwd")
        if profile["cwd"] == "preserve" and has_cwd:
            problems.append(f"{function}:{node.lineno}: profile requires preserved cwd")
        if observed_api == "execve":
            if len(node.args) != 3 or node.keywords:
                problems.append(f"{function}:{node.lineno}: execve shape is not exact")
            elif not all(isinstance(item, ast.Name) for item in node.args) \
                    or [item.id for item in node.args] != ["expected", "argv", "env"]:
                problems.append(
                    f"{function}:{node.lineno}: execve path/argv/env binding is not canonical"
                )
            else:
                env_name = node.args[2].id
                scope = node
                while scope in parents and not isinstance(
                    scope, (ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    scope = parents[scope]
                assignments = [
                    item for item in ast.walk(scope)
                    if isinstance(item, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == env_name
                            for target in item.targets)
                    and isinstance(item.value, ast.Call)
                    and isinstance(item.value.func, ast.Name)
                    and item.value.func.id == "clean_environment"
                ]
                if len(assignments) != 1 or assignments[0].lineno >= node.lineno:
                    problems.append(
                        f"{function}:{node.lineno}: execve env lacks one prior clean transition"
                    )
    return problems


def _is_os_environ(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
        and node.value.id == "os" and node.attr == "environ"


def _environment_boundary_problems(
    tree: ast.Module, filename: str, policy: Mapping[str, Any],
) -> list[str]:
    """Recognize the one policy-owned ambient-to-clean semantic transition."""
    problems: list[str] = []
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    boundary = policy["environment"]["bootstrap_boundary"]
    observed: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "copy" and _is_os_environ(node.func.value):
            problems.append(f"line {node.lineno}: ambient environment copy is forbidden")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "dict" and node.args and _is_os_environ(node.args[0]):
            problems.append(f"line {node.lineno}: ambient environment dict merge is forbidden")
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if key is None and _is_os_environ(value):
                    problems.append(f"line {node.lineno}: ambient environment spread is forbidden")
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) \
                or node.func.id != boundary["transition"] \
                or not node.args or not _is_os_environ(node.args[0]):
            continue
        observed.append((_function_name(node, parents), node.func.id))
    expected = [(boundary["function"], boundary["transition"])] \
        if filename == boundary["surface"] else []
    if observed != expected:
        problems.append(
            f"ambient bootstrap boundary drifted: observed={observed} expected={expected}"
        )
    return problems


def _inheritance_call_problems(
    tree: ast.Module, filename: str, policy: Mapping[str, Any],
) -> list[str]:
    problems: list[str] = []
    allowed = set(policy.get("surface_environment", {}).get(filename, []))
    boundary_surface = policy["environment"]["bootstrap_boundary"]["surface"]
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) \
                or node.func.id != "clean_environment":
            continue
        keyword = next((item.value for item in node.keywords if item.arg == "inherit"), None)
        if keyword is None:
            continue
        if isinstance(keyword, (ast.Tuple, ast.List)) and all(
            isinstance(item, ast.Constant) and isinstance(item.value, str)
            for item in keyword.elts
        ):
            requested = {item.value for item in keyword.elts}
            if requested - allowed:
                problems.append(
                    f"line {node.lineno}: unregistered inherited variables "
                    f"{sorted(requested - allowed)}"
                )
            continue
        function = _function_name(node, parents)
        canonical_dynamic = filename == boundary_surface and function == "_launch" \
            and isinstance(keyword, ast.Call) and isinstance(keyword.func, ast.Name) \
            and keyword.func.id == "_surface_inherit"
        if not canonical_dynamic:
            problems.append(
                f"line {node.lineno}: inherited variables must be literal or policy-resolved"
            )
    return problems


def _static_problems(policy: Mapping[str, Any], files: Mapping[str, Path]) -> list[str]:
    problems: list[str] = []
    if policy["python"].get("package") != {
        "name": PACKAGE_NAME,
        "root": "scripts",
        "init": "scripts/__init__.py",
        "loading": "verified-file-spec",
        "sys_path_mutation": False,
        "editable_install": False,
    }:
        problems.append("Python repository-tool package policy is non-canonical")
    if policy["python"].get("dynamic_sibling_imports") != {
        META_GATE: ["_strict_yaml"],
    } or f'import_module(f"{{PACKAGE_NAME}}._strict_yaml")' not in Path(
        __file__
    ).read_text(encoding="utf-8"):
        problems.append("Python dynamic sibling-import policy is non-canonical")
    venv_policy = policy["python"].get("venv", {})
    expected_home_names = [
        f"python{policy['python']['major_minor']}", "python3", "python",
        f"python{policy['python']['major_minor']}.exe", "python.exe",
    ]
    if venv_policy != {
        "path": ".venv",
        "implementation": "CPython",
        "implementation_name": "cpython",
        "release_level": "final",
        "patch_policy": "per-environment-exact",
        "include_system_site_packages": False,
        "home_interpreter_names": expected_home_names,
    }:
        problems.append("Python active-venv identity policy is non-canonical")
    expected_bootstrap = {
        "transition_receipt": "NDDEV_PYTHON_BOOTSTRAP",
        "receipt_version": "repository-venv-v1",
        "maximum_transitions": 1,
    }
    if policy["python"].get("bootstrap") != expected_bootstrap:
        problems.append("Python bootstrap transition policy is non-canonical")
    expected_prefix = [
        policy["python"]["dependency_interpreter"], "-I", "-B",
        "scripts/check_python_execution_contract.py", "--launch",
    ]
    if policy["python"].get("launcher_prefix") != expected_prefix:
        problems.append("Python launcher prefix differs from repository interpreter policy")
    expected_syntax_prefix = [
        policy["python"]["dependency_interpreter"], "-I", "-B",
        "scripts/check_python_syntax.py",
    ]
    if policy["python"].get("syntax_gate_prefix") != expected_syntax_prefix:
        problems.append("Python cold syntax prefix differs from repository interpreter policy")
    documents = policy["python"].get("invocation_documents")
    if not isinstance(documents, dict) or list(documents) != sorted(documents):
        problems.append("Python invocation-document inventory is not canonical")
    elif any(
        not isinstance(item, str) or Path(item).is_absolute() or ".." in Path(item).parts
        or not isinstance(registration, dict)
        or set(registration) != {"role", "language"}
        or registration["role"] not in {
            "adoption-guide", "consumer-command", "repository-launcher",
        }
        or registration["language"] not in {"markdown", "python", "yaml"}
        for item, registration in documents.items()
    ):
        problems.append("Python invocation-document inventory contains an unsafe path")
    exemptions = policy["python"].get("invocation_document_exemptions")
    if not isinstance(exemptions, dict) or list(exemptions) != sorted(exemptions):
        problems.append("Python invocation-document exemptions are not canonical")
    elif any(
        not isinstance(item, str) or Path(item).is_absolute() or ".." in Path(item).parts
        or not isinstance(reason, str) or not reason.strip()
        for item, reason in exemptions.items()
    ):
        problems.append(
            "Python invocation-document exemptions need a safe path and a reason"
        )
    expected_source_classes = {
        "production_workflows": ".github/workflows/*.yml",
        "negative_corpora": "tests/fixtures/negative/**",
        "negative_contract": "rejection-only",
    }
    if policy["python"].get("source_classes") != expected_source_classes:
        problems.append("Python executable source-class policy is non-canonical")
    surfaces = _policy_surfaces(policy)
    expected_files = surfaces | {META_GATE, PACKAGE_INIT}
    if len(surfaces) != policy["python"]["subject_count"] or set(files) != expected_files:
        problems.append(
            f"Python inventory drift: count={len(surfaces)} "
            f"missing={sorted(expected_files - set(files))} "
            f"extra={sorted(set(files) - expected_files)}"
        )
    grouped = [
        item for values in policy.get("surface_groups", {}).values() for item in values
    ]
    if len(grouped) != len(set(grouped)):
        problems.append("Python policy assigns a surface to multiple groups")
    inherited = policy.get("surface_environment", {})
    if not isinstance(inherited, dict) or set(inherited) - surfaces:
        problems.append("Python surface environment names an unknown subject")
    elif any(
        not isinstance(values, list)
        or any(not isinstance(name, str) or _python_key(name) for name in values)
        for values in inherited.values()
    ):
        problems.append("Python surface environment contains invalid inheritance")
    sibling = {path.stem for path in files.values() if path.name != PACKAGE_INIT}
    stdlib = set(sys.stdlib_module_names)
    actual_graph: dict[str, list[str]] = {}
    external_graph: dict[str, list[str]] = {}
    actual_edges: dict[str, dict[str, dict[str, Any]]] = {}
    for name, path in files.items():
        source = path.read_text(encoding="utf-8")
        if re.search(r"sys\.path\s*(?:\[.*\])?\s*=|sys\.path\.(?:insert|append|extend)", source):
            problems.append(f"{name}: repository tools may not mutate sys.path")
        try:
            tree = ast.parse(source, filename=str(path), feature_version=(3, 13))
        except SyntaxError as exc:
            problems.append(f"{name}: Python 3.13 syntax error: {exc}")
            continue
        undefined = sorted(_undefined_names(source, str(path)))
        if undefined:
            problems.append(f"{name}: undefined global names {undefined}")
        roots = _import_roots(tree)
        problems += [
            f"{name}: {issue}"
            for issue in _unqualified_sibling_imports(tree, sibling)
        ]
        problems += [
            f"{name}: {issue}"
            for issue in _environment_boundary_problems(tree, name, policy)
        ]
        problems += [
            f"{name}: {issue}"
            for issue in _inheritance_call_problems(tree, name, policy)
        ]
        actual_graph[name] = sorted(roots & sibling)
        actual_external = sorted(roots - stdlib - sibling)
        external_graph[name] = actual_external
        for issue in _import_side_effects(tree):
            problems.append(f"{name}: {issue}")
        counts, edge_problems = _process_edges(tree)
        problems += [f"{name}: {issue}" for issue in edge_problems]
        problems += [
            f"{name}: {issue}"
            for issue in _process_semantic_problems(tree, name, policy)
        ]
        if counts:
            registered = policy["process_edges"].get(name, {})
            actual_edges[name] = {
                function: {
                    "count": count,
                    "profile": registered.get(function, {}).get("profile", "<unregistered>"),
                }
                for function, count in sorted(counts.items())
            }
    expected_graph = {
        name: sorted(policy["sibling_imports"].get(name, [])) for name in files
    }
    if actual_graph != expected_graph:
        problems.append("Python sibling import graph differs from canonical policy")
    expected_external = {
        name: sorted(policy["direct_external_imports"].get(name, [])) for name in files
    }
    if external_graph != expected_external:
        problems.append(f"Python external dependency graph drifted: {external_graph}")
    declared_dependencies = set(policy["python"].get("external_dependencies", {}))
    observed_dependencies = {
        dependency for values in external_graph.values() for dependency in values
    }
    if declared_dependencies != observed_dependencies:
        problems.append("Python dependency policy differs from external import graph")
    if actual_edges != policy["process_edges"]:
        problems.append(f"Python process-edge registry drifted: actual={actual_edges}")
    profile_fields = {"api", "executable", "argv", "cwd", "environment"}
    profile_values = {
        "api": {"subprocess", "execve"},
        "executable": {
            "current-interpreter", "path-search", "repository-venv",
            "selected-interpreter",
        },
        "argv": {"exact", "sequence"},
        "cwd": {"explicit", "explicit-or-preserve", "preserve"},
        "environment": {
            "replace-clean", "replace-clean-inherit-named",
            "replace-owned-hostile",
        },
    }
    for name, profile in policy.get("process_profiles", {}).items():
        if not isinstance(profile, dict) or set(profile) != profile_fields:
            problems.append(f"Python process profile {name!r} is not total")
            continue
        for field, allowed_values in profile_values.items():
            if profile[field] not in allowed_values:
                problems.append(
                    f"Python process profile {name!r} has invalid {field} semantics"
                )
    referenced_profiles = {
        edge["profile"]
        for functions in policy["process_edges"].values()
        for edge in functions.values()
    }
    if referenced_profiles != set(policy.get("process_profiles", {})):
        problems.append("Python process profile inventory differs from registered edges")
    return problems


def workflow_python_invocation_problems(
    path: Path, text: str, *, enforce_embedded: bool = False,
    role: SourceRole = SourceRole.WORKFLOW,
    language: SourceLanguage | None = None,
) -> list[str]:
    """Enforce distinct canonical shapes for subjects and embedded programs."""
    problems: list[str] = []
    surfaces = _policy_surfaces(load_policy())
    if language is None:
        if role is SourceRole.WORKFLOW:
            language = SourceLanguage.YAML
        elif role is SourceRole.SHELL_FIXTURE:
            language = SourceLanguage.SHELL
        else:
            return [f"{path.name}: executable source language is not registered"]
    source = InvocationSource(path, text, role, language)
    commands, source_problems = _source_commands(source)
    problems += source_problems
    launcher_count = 0
    seen: set[tuple[int, str, SourceRole, SourceLanguage, SourceLanguage]] = set()
    for extracted in commands:
        location = extracted.location
        scalar = extracted.text
        identity = (
            extracted.line, scalar, extracted.role, extracted.language,
            extracted.grammar,
        )
        if identity in seen:
            problems.append(f"{path.name}:{location}: duplicate executable surface")
            continue
        seen.add(identity)
        try:
            logical = _logical_shell_commands(scalar)
        except ValueError as exc:
            problems.append(f"{path.name}:{location}: {exc}")
            continue
        for _, command in logical:
            embedded_candidate = enforce_embedded and "<<'PY'" in command
            if not _is_repository_command_candidate(command) and not embedded_candidate:
                continue
            try:
                invocation = _parse_invocation(command)
            except ValueError as exc:
                problems.append(f"{path.name}:{location}: {exc}")
                continue
            if invocation is not None:
                launcher_count += 1
                expected = _canonical_invocation(invocation.subject, invocation.arguments)
                if invocation != expected or invocation.subject not in surfaces:
                    problems.append(
                        f"{path.name}:{location}: launcher invocation is not canonical"
                    )
                continue
            try:
                tokens = shlex.split(command, posix=True)
            except ValueError as exc:
                problems.append(f"{path.name}:{location}: malformed shell command: {exc}")
                continue
            direct_subjects = {
                Path(token).name for token in tokens
                if token.startswith("scripts/") and Path(token).name in surfaces
            }
            syntax_prefix = load_policy()["python"]["syntax_gate_prefix"]
            if tokens == syntax_prefix:
                continue
            if direct_subjects:
                problems.append(
                    f"{path.name}:{location}: repository subject must use canonical launcher"
                )
                continue
            if enforce_embedded and "<<'PY'" in command and not re.search(
                r"\bpython3\s+-I(?:\s+-)?(?:\s+[^<]+)?\s+<<'PY'$", command,
            ):
                problems.append(
                    f"{path.name}:{location}: embedded Python must use isolated mode"
                )
    if role is SourceRole.REPOSITORY_LAUNCHER and launcher_count == 0:
        problems.append(f"{path.name}: repository-launcher source has no launcher invocation")
    if role is SourceRole.CONSUMER_COMMAND and launcher_count:
        problems.append(f"{path.name}: consumer-command source invokes repository launcher")
    return problems


def workflow_python_provisioning_problems(path: Path, text: str) -> list[str]:
    """Require deterministic venv provisioning wherever the launcher is used."""
    launcher = " ".join(load_policy()["python"]["launcher_prefix"])
    if launcher not in text:
        return []
    problems: list[str] = []
    if "activate-environment: true" in text:
        problems.append(f"{path.name}: setup-uv activation may shadow the repository interpreter")
    if "-m venv --copies .venv" not in text:
        problems.append(f"{path.name}: launcher has no copy-based repository venv provisioning")
    if path.name != "runtime-fixtures.yml":
        for marker in (
            "update-environment: false",
            "PYTHON_PATH: ${{ steps.python.outputs.python-path }}",
        ):
            if marker not in text:
                problems.append(f"{path.name}: launcher provisioning lacks {marker!r}")
    return problems


def _run_import(tool: str, cwd: Path, dependency_root: Path | None) -> str | None:
    command = [
        sys.executable, "-I", "-B", str(Path(__file__).resolve()),
        "--bootstrap", tool, "@active" if dependency_root else "-",
        "--import-only", "--",
    ]
    completed = subprocess.run(
        command, cwd=cwd, env=clean_environment(), text=True, encoding="utf-8",
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    if completed.returncode != 0 or "Traceback (most recent call last):" in completed.stdout:
        return f"{tool}: cold import failed: {completed.stdout[-1600:].strip()}"
    return None


def _venv_selftest(root: Path, policy: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    dependency = policy["python"]["external_dependencies"]["yaml"]
    active_identity, active_problems = _active_venv_identity()
    if active_problems or active_identity is None:
        return ["cannot derive venv selftests from the active runtime identity"]
    active_config, config_problems = _read_pyvenv(
        Path(active_identity["prefix"]) / "pyvenv.cfg"
    )
    if config_problems:
        return ["cannot derive venv selftests from the active pyvenv.cfg"]
    base_executable, anchor_problems = _base_anchor(
        active_identity, active_config, policy["python"]["venv"],
    )
    if anchor_problems or base_executable is None:
        return ["cannot derive venv selftests from the active base identity"]
    valid_identities: dict[str, dict[str, Any]] = {}
    for label, prefix in {
        "local-captured-shape": root / "local-venv",
        "relocated-venv-shape": root / "workspace" / ".venv",
    }.items():
        executable = prefix / "bin" / "python3"
        executable.parent.mkdir(parents=True)
        executable.write_text("copied-interpreter-fixture\n", encoding="utf-8")
        executable.chmod(0o700)
        site_root = prefix / "lib" / "python3.13" / "site-packages"
        site_root.mkdir(parents=True)
        identity = dict(active_identity)
        identity.update({
            "prefix": str(prefix), "exec_prefix": str(prefix),
            "executable": str(executable), "purelib": str(site_root),
            "platlib": str(site_root),
        })
        config = dict(active_config)
        if _venv_identity_problems(identity, config):
            problems.append(f"{label} active-venv parity selftest failed")
        valid_identities[label] = identity

    valid = valid_identities["relocated-venv-shape"]
    config = dict(active_config)
    optional_base = dict(valid, base_executable="")
    if _venv_identity_problems(optional_base, config):
        problems.append("optional _base_executable selftest rejected pyvenv home identity")
    outside_site = root / "outside" / "site-packages"
    outside_site.mkdir(parents=True)
    wrong_prefix = dict(valid, purelib=str(outside_site), platlib=str(outside_site))
    wrong_version = dict(config, version_info="3.12.0")
    stale_runtime = dict(valid, version="3.13.0")
    stale_runtime["version_info"] = (3, 13, 0, "final", 0)
    stale_runtime["implementation_version"] = (3, 13, 0, "final", 0)
    wrong_implementation = dict(valid, implementation_name="pypy")
    wrong_cache_tag = dict(valid, cache_tag="cpython-312")
    wrong_config_executable = dict(config, executable=str(root / "other-python"))
    user_site = dict(valid, enable_user_site=True)
    wrong_base_prefix = dict(valid, base_prefix=str(root / "other-base"))
    wrong_base_executable = dict(valid, base_executable=str(root / "other-python"))
    symlink_site = root / "symlink" / "site-packages"
    symlink_site.parent.mkdir()
    symlink_site.symlink_to(outside_site, target_is_directory=True)
    symlink_identity = dict(valid, purelib=str(symlink_site), platlib=str(symlink_site))
    symlink_executable = Path(valid["prefix"]) / "bin" / "linked-python"
    symlink_executable.symlink_to(Path(valid["executable"]))
    symlink_executable_identity = dict(valid, executable=str(symlink_executable))
    for label, identity, candidate_config in (
        ("wrong-prefix", wrong_prefix, config),
        ("wrong-version", valid, wrong_version),
        ("stale-runtime-version", stale_runtime, config),
        ("wrong-implementation", wrong_implementation, config),
        ("wrong-cache-tag", wrong_cache_tag, config),
        ("wrong-config-executable", valid, wrong_config_executable),
        ("user-site", user_site, config),
        ("wrong-base-prefix", wrong_base_prefix, config),
        ("wrong-base-executable", wrong_base_executable, config),
        ("symlink-site", symlink_identity, config),
        ("symlink-executable", symlink_executable_identity, config),
    ):
        if not _venv_identity_problems(identity, candidate_config):
            problems.append(f"active-venv negative selftest passed: {label}")
    linked_prefix = root / "linked-venv"
    linked_prefix.symlink_to(Path(valid["prefix"]), target_is_directory=True)
    if not _venv_identity_problems(valid, config, expected_prefix=linked_prefix):
        problems.append("symlinked venv-root negative selftest passed")

    valid_lock = (
        f"{dependency['distribution'].lower()}=={dependency['version']} \\\n"
        f"    --hash=sha256:{'a' * 64}\n"
    )
    if _locked_dependency_problems(valid_lock, dependency):
        problems.append("hash-pinned dependency selftest rejected canonical input")
    for label, text in (
        ("unpinned", f"{dependency['distribution'].lower()}=={dependency['version']}\n"),
        ("wrong-version", f"{dependency['distribution'].lower()}==0.0.0 \\\n"
         f"    --hash=sha256:{'a' * 64}\n"),
    ):
        if not _locked_dependency_problems(text, dependency):
            problems.append(f"dependency-lock negative selftest passed: {label}")
    for label, name, version in (
        ("wrong-distribution", "NotPyYAML", dependency["version"]),
        ("wrong-installed-version", dependency["distribution"], "0.0.0"),
    ):
        if not _distribution_identity_problems(name, version, dependency):
            problems.append(f"dependency-identity negative selftest passed: {label}")

    site_root = Path(valid["purelib"])
    dist_info = site_root / "pyyaml-6.0.3.dist-info"
    dist_info.mkdir()
    module = site_root / "yaml"
    module.mkdir()
    origin = module / "__init__.py"
    origin.write_text("fixture\n", encoding="utf-8")
    if _dependency_path_problems(
        {site_root.resolve()}, site_root, dist_info, origin, dependency["module_path"],
    ):
        problems.append("dependency-origin selftest rejected canonical venv paths")
    escaped = root / "escaped-yaml.py"
    escaped.write_text("fixture\n", encoding="utf-8")
    origin.unlink()
    origin.symlink_to(escaped)
    if not _dependency_path_problems(
        {site_root.resolve()}, site_root, dist_info, origin, dependency["module_path"],
    ):
        problems.append("dependency-origin symlink escape selftest passed")
    config_file = root / "pyvenv.cfg"
    config_file.write_text("home = /fixture\n", encoding="utf-8")
    config_link = root / "linked-pyvenv.cfg"
    config_link.symlink_to(config_file)
    if not _read_pyvenv(config_link)[1]:
        problems.append("pyvenv.cfg symlink negative selftest passed")
    missing_config = root / "missing-pyvenv.cfg"
    if not _read_pyvenv(missing_config)[1]:
        problems.append("missing pyvenv.cfg negative selftest passed")
    malformed_config = root / "malformed-pyvenv.cfg"
    malformed_config.write_text("home=/x\nhome=/y\nunknown\n", encoding="utf-8")
    if len(_read_pyvenv(malformed_config)[1]) != 2:
        problems.append("duplicate/malformed pyvenv.cfg negative selftest failed")
    return problems


def _selftest(policy: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="ci-workflows-package-fixture-") as raw_package:
        package_root = Path(raw_package) / "scripts"
        package_root.mkdir()
        package_init = package_root / PACKAGE_INIT
        canonical_manifest = (SCRIPTS / PACKAGE_INIT).read_text(encoding="utf-8")
        package_init.write_text(canonical_manifest, encoding="utf-8")
        helper = package_root / "helper.py"
        helper.write_text("VALUE = 1\n", encoding="utf-8")
        if _helper_origin_problems(package_root, "helper", str(helper)):
            problems.append("repository helper valid-origin selftest failed")
        if not _helper_origin_problems(package_root, "missing", None):
            problems.append("missing repository helper negative selftest passed")
        if not _helper_origin_problems(package_root, "helper", str(outside := Path(raw_package) / "shadow.py")):
            problems.append("shadowed repository helper negative selftest passed")
        outside.write_text("VALUE = 2\n", encoding="utf-8")
        helper.unlink()
        helper.symlink_to(outside)
        if not _helper_origin_problems(package_root, "helper", str(helper)):
            problems.append("symlinked repository helper negative selftest passed")
        valid_spec, valid_problems = _repository_package_spec(package_root)
        if valid_problems or valid_spec is None:
            problems.append("repository package valid-origin selftest failed")
        package_init.write_text("PACKAGE_CONTRACT = 'stale'\n", encoding="utf-8")
        if not _repository_package_spec(package_root)[1]:
            problems.append("stale package manifest negative selftest passed")
        package_init.unlink()
        if not _repository_package_spec(package_root)[1]:
            problems.append("missing package manifest negative selftest passed")
        outside.write_text(canonical_manifest, encoding="utf-8")
        package_init.symlink_to(outside)
        if not _repository_package_spec(package_root)[1]:
            problems.append("symlinked package manifest negative selftest passed")
        if valid_spec is not None:
            valid_module = importlib.util.module_from_spec(valid_spec)
            valid_module.PACKAGE_CONTRACT = "ci-workflows-tools-v1"
            if _loaded_package_problems(valid_module, package_root):
                problems.append("loaded package identity selftest rejected canonical origin")
            wrong_module = ModuleType(PACKAGE_NAME)
            wrong_module.__spec__ = importlib.util.spec_from_file_location(
                PACKAGE_NAME, outside, submodule_search_locations=[str(package_root)],
            )
            wrong_module.PACKAGE_CONTRACT = "ci-workflows-tools-v1"
            if not _loaded_package_problems(wrong_module, package_root):
                problems.append("wrong-origin package negative selftest passed")
            stale_module = importlib.util.module_from_spec(valid_spec)
            stale_module.PACKAGE_CONTRACT = "stale"
            if not _loaded_package_problems(stale_module, package_root):
                problems.append("stale loaded package negative selftest passed")
    valid = "import json\nVALUE=1\ndef f(x):\n return json.dumps(x+VALUE)\n"
    invalid = valid + "def broken():\n return NEVER_IMPORTED\n"
    if _undefined_names(valid, "<valid>") or _undefined_names(invalid, "<invalid>") != {"NEVER_IMPORTED"}:
        problems.append("undefined-name selftest failed")
    sibling_names = {"helper"}
    if _unqualified_sibling_imports(
        ast.parse("from ci_workflows_tools import helper\n"), sibling_names,
    ):
        problems.append("qualified sibling-import selftest failed")
    for source in ("import helper\n", "from helper import VALUE\n"):
        if not _unqualified_sibling_imports(ast.parse(source), sibling_names):
            problems.append("unqualified sibling-import negative selftest failed")
    canonical_dependency = shlex.join([sys.executable, "-m", "yaml"])
    try:
        observed_dependency = dependency_python_command("-m yaml", "yaml")
    except ValueError as exc:
        problems.append(f"dependency Python binding selftest rejected canonical input: {exc}")
    else:
        if observed_dependency != canonical_dependency:
            problems.append("dependency Python binding selftest rendered the wrong command")
    for arguments, module in (
        ("", "yaml"), ("-m yaml && echo bypass", "yaml"),
        ("-m missing", "module-that-cannot-exist"),
    ):
        try:
            dependency_python_command(arguments, module)
        except ValueError:
            pass
        else:
            problems.append("dependency Python binding negative selftest passed")
    with tempfile.TemporaryDirectory(prefix="ci-workflows-python-binding-") as raw:
        root = Path(raw)
        expected = root / ".venv" / "bin" / "python"
        origin = root / ".venv" / "lib" / "python3.13" / "site-packages" / "pytest" / "__init__.py"
        expected.parent.mkdir(parents=True)
        origin.parent.mkdir(parents=True)
        expected.write_text("fixture\n", encoding="utf-8")
        origin.write_text("fixture\n", encoding="utf-8")
        if _dependency_python_argv(expected, expected, root / ".venv", origin, "-m pytest") != [
            str(expected), "-m", "pytest",
        ]:
            problems.append("captured dependency Python binding selftest drifted")
        outside = root / "outside" / "pytest.py"
        outside.parent.mkdir()
        outside.write_text("fixture\n", encoding="utf-8")
        for executable, module_origin in (
            (root / "foreign" / "python", origin), (expected, outside),
        ):
            try:
                _dependency_python_argv(
                    executable, expected, root / ".venv", module_origin, "-m pytest",
                )
            except ValueError:
                pass
            else:
                problems.append("foreign dependency Python binding negative selftest passed")
    if not _import_side_effects(ast.parse("import pathlib\npathlib.Path('x').write_text('x')\n")):
        problems.append("import-write selftest failed")
    safe_surfaces = {"registered.py"}
    for candidate, accepted in {
        "registered.py": True,
        "missing.py": False,
        "../registered.py": False,
        "sub/registered.py": False,
        "registered": False,
    }.items():
        if _registered_tool(candidate, safe_surfaces) != accepted:
            problems.append(f"registered-tool selftest failed: {candidate}")
    with tempfile.TemporaryDirectory() as raw_interpreter:
        interpreter_root = Path(raw_interpreter)
        dependency_python = interpreter_root / policy["python"]["dependency_interpreter"]
        dependency_python.parent.mkdir(parents=True)
        dependency_python.write_text("fixture\n", encoding="utf-8")
        dependency_python.chmod(0o700)
        yaml_executable, yaml_claim, yaml_problems = _subject_interpreter(
            "validate_catalog.py", policy, root=interpreter_root,
            current=Path("/ambient/python3"),
        )
        stdlib_executable, stdlib_claim, stdlib_problems = _subject_interpreter(
            "check_docs_links.py", policy, root=interpreter_root,
            current=Path("/trusted/setup-python"),
        )
        if yaml_problems or yaml_executable != dependency_python or yaml_claim != "@active":
            problems.append("dependency subject did not select the repository venv")
        if stdlib_problems or stdlib_executable != Path("/trusted/setup-python") \
                or stdlib_claim != "-":
            problems.append("stdlib-only subject did not preserve its isolated interpreter")
        linked_python = dependency_python.with_name("linked-python")
        linked_python.symlink_to(dependency_python)
        linked_policy = json.loads(json.dumps(policy))
        linked_policy["python"]["dependency_interpreter"] = str(
            linked_python.relative_to(interpreter_root)
        )
        if not _subject_interpreter(
            "validate_catalog.py", linked_policy, root=interpreter_root,
        )[2]:
            problems.append("symlinked dependency interpreter negative selftest passed")
        dependency_python.unlink()
        if not _subject_interpreter(
            "validate_catalog.py", policy, root=interpreter_root,
        )[2]:
            problems.append("missing dependency interpreter negative selftest passed")
        dependency_python.write_text("fixture\n", encoding="utf-8")
        dependency_python.chmod(0o600)
        if not _subject_interpreter(
            "validate_catalog.py", policy, root=interpreter_root,
        )[2]:
            problems.append("non-executable dependency interpreter negative selftest passed")
    for source in (
        "from subprocess import run\nrun(['true'], env={})\n",
        "import subprocess as sp\nsp.run(['true'], env={})\n",
    ):
        if not _process_edges(ast.parse(source))[1]:
            problems.append("process-alias selftest failed")
    exec_valid = ast.parse("import os\ndef edge():\n os.execve('/x', ['/x'], {})\n")
    exec_missing = ast.parse("import os\ndef edge():\n os.execv('/x', ['/x'])\n")
    duplicate = ast.parse(
        "import subprocess\ndef edge():\n"
        " subprocess.run(['x'], env={})\n subprocess.run(['y'], env={})\n"
    )
    if _process_edges(exec_valid) != ({"edge": 1}, []):
        problems.append("execve replacement-environment selftest failed")
    if not _process_edges(exec_missing)[1]:
        problems.append("inherited exec environment negative selftest passed")
    if _process_edges(duplicate)[0] != {"edge": 2}:
        problems.append("duplicate process-edge selftest failed")
    environment = policy["environment"]
    stripped_name = environment["stripped_names_evidence"]
    inherited_name = environment["inherited_names_evidence"]
    source = {
        "PATH": "/fixture/bin", "LANG": "hostile", "LC_ALL": "hostile",
        "GH_TOKEN": "token", "UNNAMED": "must-not-pass",
        "PYTHONHOME": "/hostile", "pythonpath": "/shadow",
        stripped_name: '["PYTHONWARNINGS"]', inherited_name: '["HOME"]',
    }
    transitioned = _transition_environment(source, inherit=("GH_TOKEN",))
    if any(_python_key(name) for name in transitioned):
        problems.append("environment transition retained interpreter-control state")
    if transitioned.get("LANG") != "C" or transitioned.get("LC_ALL") != "C":
        problems.append("environment transition did not canonicalize locale")
    if "UNNAMED" in transitioned or transitioned.get("GH_TOKEN") != "token":
        problems.append("environment transition inheritance allowlist failed")
    if json.loads(transitioned[stripped_name]) != [
        "PYTHONHOME", "PYTHONWARNINGS", "pythonpath",
    ]:
        problems.append("environment transition stripped evidence is not exact")
    if json.loads(transitioned[inherited_name]) != [
        "GH_TOKEN", "HOME", "PATH",
    ]:
        problems.append("environment transition inherited evidence is not exact")
    rejected = (
        ({"PYTHONPATH": "forbidden"}, (), "python override"),
        ({"LANG": "hostile"}, (), "locale override"),
        ({}, ("UNREGISTERED",), "unknown inheritance"),
    )
    for overrides, inherit, label in rejected:
        try:
            _transition_environment(source, overrides, inherit=inherit)
        except ValueError:
            pass
        else:
            problems.append(f"environment transition accepted {label}")
    for evidence_name in (stripped_name, inherited_name):
        malformed = dict(source)
        malformed[evidence_name] = "not-json"
        try:
            _transition_environment(malformed)
        except ValueError:
            pass
        else:
            problems.append(f"environment transition accepted malformed {evidence_name}")
    invocation_cases = {
        "canonical-launcher": (
            _render_invocation(_canonical_invocation("validate_all.py")),
            False,
        ),
        "multiline-launcher": (
            ".venv/bin/python -I -B scripts/check_python_execution_contract.py "
            "--launch " + "\\" + "\nvalidate_all.py -- --tier core",
            False,
        ),
        "quoted-doc-launcher": (
            "\".venv/bin/python -I -B "
            "scripts/check_python_execution_contract.py --launch validate_all.py --\"",
            False,
        ),
        "truncated-continuation": ("run: command \\", True),
        "setup-python-path-shadow": (
            "python3 -I -B scripts/check_python_execution_contract.py "
            "--launch validate_all.py --",
            True,
        ),
        "foreign-venv-launcher": (
            "/tmp/foreign/.venv/bin/python -I -B "
            "scripts/check_python_execution_contract.py --launch validate_all.py --",
            True,
        ),
        "direct-subject": ("python3 -I scripts/validate_all.py", True),
        "canonical-cold-syntax": (
            ".venv/bin/python -I -B scripts/check_python_syntax.py", False,
        ),
        "ambient-cold-syntax": (
            "python3 -I -B scripts/check_python_syntax.py", True,
        ),
        "missing-bytecode-guard": (
            "python3 -I scripts/check_python_execution_contract.py "
            "--launch validate_all.py --",
            True,
        ),
        "missing-separator": (
            ".venv/bin/python -I -B scripts/check_python_execution_contract.py "
            "--launch validate_all.py",
            True,
        ),
        "duplicate-separator": (
            ".venv/bin/python -I -B scripts/check_python_execution_contract.py "
            "--launch validate_all.py -- --",
            True,
        ),
        "embedded-isolated": ("python3 -I - '$VALUE' <<'PY'", False),
        "embedded-ambient": ("python3 - <<'PY'", True),
    }
    for label, (text, should_fail) in invocation_cases.items():
        failed = bool(workflow_python_invocation_problems(
            Path(label), text, enforce_embedded=label.startswith("embedded-"),
            role=SourceRole.SHELL_FIXTURE,
        ))
        if failed != should_fail:
            problems.append(f"workflow invocation selftest failed: {label}")
    canonical = _render_invocation(_canonical_invocation("validate_all.py"))
    workflow_cases = {
        "nested-run-mapping": (
            "jobs:\n  test:\n    defaults:\n      run:\n        shell: bash\n"
            "    steps:\n      - run: echo ok\n",
            False,
        ),
        "literal-command": (
            f"jobs:\n  test:\n    steps:\n      - run: |\n          {canonical}\n",
            False,
        ),
        "folded-command": (
            "jobs:\n  test:\n    steps:\n      - run: >-\n          .venv/bin/python -I -B\n"
            "          scripts/check_python_execution_contract.py --launch validate_all.py --\n",
            False,
        ),
        "quoted-command": (
            f"jobs:\n  test:\n    steps:\n      - run: '{canonical}'\n",
            False,
        ),
        "null-step-command": ("jobs:\n  test:\n    steps:\n      - run:\n", True),
        "mapping-step-command": (
            "jobs:\n  test:\n    steps:\n      - run:\n          shell: bash\n", True,
        ),
        "sequence-step-command": (
            "jobs:\n  test:\n    steps:\n      - run: [echo, ok]\n", True,
        ),
        "malformed-delimiter": (
            "jobs:\n  test:\n    steps:\n      - run: {broken]\n", True,
        ),
        "truncated-scalar": (
            "jobs:\n  test:\n    steps:\n      - run: 'unterminated\n", True,
        ),
    }
    for label, (text, should_fail) in workflow_cases.items():
        failed = bool(workflow_python_invocation_problems(Path(label), text))
        if failed != should_fail:
            problems.append(f"structured workflow invocation selftest failed: {label}")
    document_cases = (
        (SourceRole.REPOSITORY_LAUNCHER, f"```bash\n{canonical}\n```\n", False),
        (SourceRole.REPOSITORY_LAUNCHER, "```bash\necho consumer\n```\n", True),
        (SourceRole.ADOPTION_GUIDE, f"prose with ' unmatched\n```bash\n{canonical}\n```\n", False),
        (SourceRole.CONSUMER_COMMAND, "```bash\necho consumer\n```\n", False),
        (SourceRole.CONSUMER_COMMAND, f"```bash\n{canonical}\n```\n", True),
    )
    for index, (role, text, should_fail) in enumerate(document_cases):
        failed = bool(workflow_python_invocation_problems(
            Path(f"document-{index}.md"), text, role=role,
            language=SourceLanguage.MARKDOWN,
        ))
        if failed != should_fail:
            problems.append(f"typed invocation-source selftest failed: {role.value}/{index}")
    typed_sources = (
        InvocationSource(
            Path("typed.md"),
            f"prose `{canonical}`\n```text\n{canonical}\n```\n```bash\n{canonical}\n```\n",
            SourceRole.ADOPTION_GUIDE, SourceLanguage.MARKDOWN,
        ),
        InvocationSource(
            Path("typed.py"),
            f"# {canonical}\nCOMMAND = {canonical!r}\n",
            SourceRole.REPOSITORY_LAUNCHER, SourceLanguage.PYTHON,
        ),
        InvocationSource(
            Path("typed.yml"),
            f"name: {canonical!r}\njobs:\n  test:\n    steps:\n      - run: {canonical!r}\n",
            SourceRole.WORKFLOW, SourceLanguage.YAML,
        ),
    )
    for source in typed_sources:
        extracted, extraction_problems = _source_commands(source)
        if extraction_problems or len(extracted) != 1:
            problems.append(
                f"typed {source.language.value} extraction selftest failed: "
                f"count={len(extracted)} problems={extraction_problems}"
            )
        elif extracted[0].role is not source.role \
                or extracted[0].language is not source.language \
                or extracted[0].grammar is not SourceLanguage.SHELL \
                or extracted[0].line < 1:
            problems.append(f"typed {source.language.value} metadata selftest failed")
    negative_yaml = InvocationSource(
        Path("negative.yml"), "jobs:\n  broken: {steps: [}\n",
        SourceRole.WORKFLOW, SourceLanguage.YAML,
    )
    negative_commands, negative_problems = _source_commands(negative_yaml)
    if negative_commands or not negative_problems:
        problems.append("negative YAML corpus rejection selftest failed")
    unclassified = workflow_python_invocation_problems(
        Path("unclassified.txt"), canonical, role=SourceRole.ADOPTION_GUIDE,
    )
    if not unclassified:
        problems.append("unclassified executable-source selftest failed")
    provisioning_cases = {
        "canonical": (
            "uses: actions/setup-python@sha\n"
            "id: python\npython-version: '3.13'\nupdate-environment: false\n"
            "PYTHON_PATH: ${{ steps.python.outputs.python-path }}\n"
            "run: \"$PYTHON_PATH\" -I -B -m venv --copies .venv\n"
            ".venv/bin/python -I -B scripts/check_python_execution_contract.py "
            "--launch validate_all.py --\n",
            False,
        ),
        "setup-action-shadow": (
            "activate-environment: true\n-m venv --copies .venv\n"
            ".venv/bin/python -I -B scripts/check_python_execution_contract.py "
            "--launch validate_all.py --\n",
            True,
        ),
        "missing-copy-provision": (
            "update-environment: false\n"
            "PYTHON_PATH: ${{ steps.python.outputs.python-path }}\n"
            ".venv/bin/python -I -B scripts/check_python_execution_contract.py "
            "--launch validate_all.py --\n",
            True,
        ),
    }
    for label, (text, should_fail) in provisioning_cases.items():
        failed = bool(workflow_python_provisioning_problems(Path(label), text))
        if failed != should_fail:
            problems.append(f"workflow provisioning selftest failed: {label}")
    with tempfile.TemporaryDirectory() as raw_bootstrap:
        root = Path(raw_bootstrap)
        expected = root / "repository" / ".venv" / "bin" / "python"
        current = root / "setup-python" / "bin" / "python"
        expected.parent.mkdir(parents=True)
        current.parent.mkdir(parents=True)
        expected.write_text("expected\n", encoding="utf-8")
        current.write_text("current\n", encoding="utf-8")
        receipt = policy["python"]["bootstrap"]["receipt_version"]
        decisions = {
            "transition": _bootstrap_decision(current, expected, None, receipt),
            "loop": _bootstrap_decision(current, expected, receipt, receipt),
            "current": _bootstrap_decision(expected, expected, None, receipt),
            "arrived": _bootstrap_decision(expected, expected, receipt, receipt),
            "malformed": _bootstrap_decision(current, expected, "wrong", receipt),
        }
        if decisions != {
            "transition": "transition", "loop": "loop-or-wrong-target",
            "current": "current", "arrived": "arrived",
            "malformed": "malformed-receipt",
        }:
            problems.append(f"bootstrap decision selftest drifted: {decisions}")
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        if not _resource_problems(root, policy):
            problems.append("missing-resource selftest failed")
        problems += _venv_selftest(root, policy)
    return problems


def _discovered_tool_documents(
    root: Path, subjects: frozenset[str],
) -> dict[str, set[str]]:
    """Every document under `root` that launches a repository Python tool.

    Discovery, not a registry read. `invocation_documents` is a closed
    allowlist, so a document nobody remembered to list was never opened at all:
    `.claude/CLAUDE.md` — the only file Claude Code auto-loads here — carried
    `python3 scripts/validate_all.py` for the whole life of the launcher, which
    aborts with ModuleNotFoundError, while this gate stayed green. A contract
    that can only see what it was told about is fail-open by construction.

    Only tools that are real subjects in this repository's `scripts/` count.
    `docs/09` documents `python3 scripts/promotion_record.py`, which lives in
    the control plane and is none of this contract's business.
    """
    found: dict[str, set[str]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if relative.startswith(DISCOVERY_SKIP_PREFIXES):
            continue
        if any(part in DISCOVERY_SKIP_PARTS for part in path.parts):
            continue
        if path.suffix not in DISCOVERY_SUFFIXES or path.is_symlink() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        tools = {
            tool for tool in REPOSITORY_TOOL_INVOCATION.findall(text) if tool in subjects
        }
        if tools:
            found[relative] = tools
    return found


def _discovery_problems(policy: Mapping[str, Any]) -> list[str]:
    """Every discovered document is either registered or explicitly exempt."""
    problems: list[str] = []
    subjects = frozenset(_policy_surfaces(policy) | {META_GATE})
    registered = set(policy["python"].get("invocation_documents", {}) or {})
    exemptions = policy["python"].get("invocation_document_exemptions", {}) or {}
    discovered = _discovered_tool_documents(REPO_ROOT, subjects)
    for relative, tools in discovered.items():
        if relative in registered or relative in exemptions:
            continue
        problems.append(
            f"unregistered Python invocation document {relative!r} launches "
            f"{sorted(tools)}; register it under invocation_documents or record "
            "an exemption and its reason in catalog/python-execution.yml"
        )
    # An exemption that no longer describes anything is a stale waiver, and a
    # stale waiver is how a closed allowlist rots back into fail-open.
    for relative in sorted(exemptions):
        if relative in registered:
            problems.append(
                f"invocation document {relative!r} is both registered and exempt"
            )
        elif relative not in discovered:
            problems.append(
                f"stale invocation-document exemption {relative!r}: it no longer "
                "launches a repository Python tool"
            )
    return problems


def _discovery_selftests() -> list[str]:
    """Prove discovery fires, scopes to real subjects, and honours the skips."""
    problems: list[str] = []
    subjects = frozenset({"validate_all.py", "generate_docs.py"})
    with tempfile.TemporaryDirectory(prefix="ci-workflows-discovery-") as raw:
        root = Path(raw)
        (root / "docs").mkdir()
        (root / ".github" / "workflows").mkdir(parents=True)
        (root / "tests" / "fixtures" / "negative").mkdir(parents=True)
        cases = {
            "AGENTS.md": "run `python3 scripts/validate_all.py --tier core`\n",
            "docs/launcher.md": (
                ".venv/bin/python -I -B scripts/check_python_execution_contract.py "
                "--launch generate_all.py\n"
                ".venv/bin/python -I -B scripts/generate_docs.py\n"
            ),
            "docs/foreign.md": "python3 scripts/promotion_record.py verify\n",
            "docs/prose.md": "scripts/validate_all.py is the aggregate validator\n",
            ".github/workflows/ci.yml": "run: python3 scripts/validate_all.py\n",
            "tests/fixtures/negative/bad.md": "python3 scripts/validate_all.py\n",
        }
        for relative, text in cases.items():
            (root / relative).write_text(text, encoding="utf-8")
        found = _discovered_tool_documents(root, subjects)
        expected = {"AGENTS.md", "docs/launcher.md"}
        if set(found) != expected:
            problems.append(
                f"discovery selftest: expected {sorted(expected)}, got {sorted(found)}"
            )
        if found.get("AGENTS.md") != {"validate_all.py"}:
            problems.append("discovery selftest: wrong tool set for a launcher document")
    return problems


def _registered_invocation_problems(policy: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    for workflow in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        workflow_text = workflow.read_text(encoding="utf-8")
        problems += workflow_python_invocation_problems(workflow, workflow_text)
        problems += workflow_python_provisioning_problems(workflow, workflow_text)
    for relative, registration in policy["python"].get("invocation_documents", {}).items():
        document = REPO_ROOT / relative
        if not document.is_file() or document.is_symlink():
            problems.append(f"Python invocation document is missing or unsafe: {relative}")
            continue
        problems += workflow_python_invocation_problems(
            document, document.read_text(encoding="utf-8"),
            role=SourceRole(registration["role"]),
            language=SourceLanguage(registration["language"]),
        )
    return problems


def check() -> list[str]:
    try:
        _register_repository_package()
    except RuntimeError as exc:
        return [str(exc)]
    try:
        policy = load_policy()
    except RuntimeError as exc:
        return [str(exc)]
    problems = _runtime_problems()
    files = _files()
    problems += _static_problems(policy, files)
    dependency_root, dependency_problems = _dependency_root()
    problems += dependency_problems
    problems += _resource_problems(REPO_ROOT, policy)
    if dependency_root is None:
        return problems
    with tempfile.TemporaryDirectory(prefix="ci-workflows-python-contract-") as raw:
        root = Path(raw)
        hostile_cwd = root / "hostile-cwd"
        cache = root / "bytecode"
        hostile_cwd.mkdir()
        cache.mkdir()
        (hostile_cwd / "_workflow_yaml.py").write_text("raise RuntimeError('shadow')\n")
        (hostile_cwd / "ci_workflows_tools.py").write_text(
            "raise RuntimeError('package shadow')\n"
        )
        (hostile_cwd / "yaml.py").write_text("raise RuntimeError('shadow')\n")
        (hostile_cwd / "sitecustomize.py").write_text("raise RuntimeError('shadow')\n")
        for name, path in files.items():
            try:
                py_compile.compile(str(path), cfile=str(cache / f"{name}c"), doraise=True)
            except py_compile.PyCompileError as exc:
                problems.append(f"{name}: bytecode compilation failed: {exc.msg}")
        for tool in sorted(_policy_surfaces(policy)):
            issue = _run_import(
                tool, hostile_cwd, dependency_root if _needs_yaml(tool, policy) else None,
            )
            if issue:
                problems.append(issue)
        if problems:
            return problems
        # Semantic assertions run only after every registered surface has
        # passed syntax, dependency-graph, origin and cold-import proof.
        problems += _selftest(policy)
        problems += _discovery_selftests()
        problems += _registered_invocation_problems(policy)
        problems += _discovery_problems(policy)
        problems += _probe_generations(hostile_cwd)
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_python_execution_contract: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("check_python_execution_contract: OK")
    print(
        "python-execution-receipt: "
        + json.dumps(_venv_receipt(), sort_keys=True, separators=(",", ":"))
    )
    return 0


if __name__ == "__main__":
    try:
        _register_repository_package()
    except RuntimeError as exc:
        print(f"python-launcher: {exc}", file=sys.stderr)
        raise SystemExit(2)
    _ensure_repository_interpreter()
    if len(sys.argv) >= 3 and sys.argv[1] == "--launch":
        tool = sys.argv[2]
        tail = sys.argv[3:]
        if not tail or tail[0] != "--":
            print("python-launcher: malformed launch arguments", file=sys.stderr)
            raise SystemExit(2)
        raise SystemExit(_launch(tool, tail[1:]))
    if len(sys.argv) >= 5 and sys.argv[1] == "--bootstrap":
        bootstrap_tool = sys.argv[2]
        bootstrap_dependency = sys.argv[3]
        bootstrap_tail = sys.argv[4:]
        import_only = False
        if bootstrap_tail and bootstrap_tail[0] == "--import-only":
            import_only = True
            bootstrap_tail = bootstrap_tail[1:]
        if not bootstrap_tail or "--" not in bootstrap_tail:
            print("python-bootstrap: malformed bootstrap arguments", file=sys.stderr)
            raise SystemExit(2)
        separator = bootstrap_tail.index("--")
        if bootstrap_tail[separator + 1:] and import_only:
            print("python-bootstrap: import-only mode takes no subject arguments", file=sys.stderr)
            raise SystemExit(2)
        raise SystemExit(_bootstrap(
            bootstrap_tool, bootstrap_dependency, bootstrap_tail[separator + 1:],
            import_only=import_only,
        ))
    if sys.argv[1:] == ["--probe-middle"]:
        raise SystemExit(_probe_child())
    if sys.argv[1:] == ["--probe-sanitize"]:
        raise SystemExit(_probe_sanitize())
    if sys.argv[1:] == ["--probe-leaf"]:
        print(json.dumps(_probe_payload("leaf"), sort_keys=True, separators=(",", ":")))
        raise SystemExit(0)
    if sys.argv[1:] == ["--probe-fail"]:
        print("probe-child-diagnostic", file=sys.stderr)
        raise SystemExit(37)
    raise SystemExit(main())
