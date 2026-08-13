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
import site
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path
from symtable import SymbolTable, symtable
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
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
            roots.add(node.module.split(".", 1)[0])
    return roots


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
    if _normalized_distribution(distribution.metadata.get("Name", "")) != \
            _normalized_distribution(dependency["distribution"]):
        problems.append("installed distribution name differs from dependency policy")
    if distribution.version != dependency["version"]:
        problems.append(
            f"{dependency['distribution']} version must be {dependency['version']}, "
            f"got {distribution.version}"
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


def _venv_identity_problems(
    identity: Mapping[str, Any], config: Mapping[str, str], *,
    expected_prefix: Path | None = None,
) -> list[str]:
    problems: list[str] = []
    venv_policy = load_policy()["python"]["venv"]
    prefix = Path(identity["prefix"]).absolute()
    base_prefix = Path(identity["base_prefix"]).absolute()
    exec_prefix = Path(identity["exec_prefix"]).absolute()
    base_exec_prefix = Path(identity["base_exec_prefix"]).absolute()
    executable = Path(identity["executable"]).absolute()
    real_prefix = prefix.resolve()
    real_base_prefix = base_prefix.resolve()
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
    home = config.get("home")
    home_path = Path(home).absolute() if home else None
    home_candidates = [] if home_path is None or not home_path.is_dir() else [
        home_path / name for name in venv_policy["home_interpreter_names"]
        if (home_path / name).is_file()
    ]
    configured_executable = config.get("executable")
    declared_paths = [
        Path(value).absolute() for value in (
            identity.get("base_executable", ""), configured_executable or "",
        ) if value
    ]
    if any(not path.is_file() for path in declared_paths):
        problems.append("declared base executable is missing or non-regular")
    declared_targets = {path.resolve() for path in declared_paths if path.is_file()}
    home_targets = {candidate.resolve() for candidate in home_candidates}
    common_targets = declared_targets & home_targets if declared_targets else home_targets
    if len(common_targets) != 1:
        problems.append("pyvenv home does not identify one coherent base executable")
        real_base_executable = None
    else:
        real_base_executable = next(iter(common_targets))
        if not _inside(real_base_executable, real_base_prefix):
            problems.append("declared base executable is outside the base installation")
    if len({path.resolve() for path in declared_paths}) > 1:
        problems.append("runtime and pyvenv base executable identities differ")
    executable_parents = {prefix / "bin", prefix / "Scripts"}
    if executable.parent not in executable_parents or not executable.is_file():
        problems.append("venv interpreter is not a regular executable in the venv")
    elif real_base_executable is not None and executable.resolve() not in {
        real_base_executable, executable,
    }:
        problems.append("venv interpreter does not bind the declared base executable")
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
        "purelib": sysconfig.get_path("purelib"),
        "platlib": sysconfig.get_path("platlib"),
        "enable_user_site": site.ENABLE_USER_SITE,
    }
    problems += _venv_identity_problems(
        identity, config,
        expected_prefix=REPO_ROOT / load_policy()["python"]["venv"]["path"],
    )
    return identity, problems


def _venv_receipt() -> dict[str, str]:
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
    base_executable = identity.get("base_executable") or config.get("executable")
    if not base_executable:
        home = Path(config["home"])
        names = load_policy()["python"]["venv"]["home_interpreter_names"]
        candidates = [home / name for name in names if (home / name).is_file()]
        if len({candidate.resolve() for candidate in candidates}) != 1:
            raise RuntimeError("cannot emit a receipt without one base executable")
        base_executable = str(candidates[0])
    return {
        "base_executable": str(Path(base_executable).resolve()),
        "base_prefix": str(Path(identity["base_prefix"]).resolve()),
        "dependency": dependency["distribution"],
        "dependency_origin": str(Path(spec.origin).resolve()),
        "dependency_version": distribution.version,
        "executable": str(Path(identity["executable"]).resolve()),
        "platlib": str(Path(identity["platlib"]).resolve()),
        "prefix": str(Path(identity["prefix"]).resolve()),
        "purelib": str(Path(identity["purelib"]).resolve()),
        "python_version": identity["version"],
    }


def _trusted_paths(dependency_root: Path | None) -> list[Path]:
    stdlib = Path(sysconfig.get_path("stdlib")).resolve()
    platstdlib = Path(sysconfig.get_path("platstdlib")).resolve()
    paths = [SCRIPTS, stdlib, platstdlib, stdlib / "lib-dynload"]
    if dependency_root is not None:
        paths.insert(1, dependency_root)
    return list(dict.fromkeys(path for path in paths if path.exists()))


def _runtime_problems() -> list[str]:
    problems: list[str] = []
    if sys.version_info[:2] != (3, 13):
        problems.append(
            f"requires Python 3.13, got {sys.version_info.major}.{sys.version_info.minor}"
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
    problems = _runtime_problems()
    surfaces = _policy_surfaces(policy)
    files = _files()
    expected = surfaces | {META_GATE}
    if len(surfaces) != policy["python"]["subject_count"] or set(files) != expected:
        problems.append(
            f"inventory drift: count={len(surfaces)} "
            f"missing={sorted(expected - set(files))} extra={sorted(set(files) - expected)}"
        )
    if not _registered_tool(tool, surfaces):
        problems.append(f"unregistered or unsafe Python tool {tool!r}")
    needs_yaml = tool in surfaces and _needs_yaml(tool, policy)
    if needs_yaml != (dependency_raw != "-"):
        problems.append("dependency claim differs from the registered import graph")
    dependency_root = Path(dependency_raw).resolve() if dependency_raw != "-" else None
    sys.path[:] = [str(path) for path in _trusted_paths(dependency_root)]
    for module, path in ((path.stem, path) for path in files.values()):
        spec = importlib.util.find_spec(module)
        if spec is None or spec.origin is None or Path(spec.origin).resolve() != path:
            problems.append(f"sibling module {module!r} resolves outside scripts/")
    if needs_yaml:
        root, dependency_problems = _dependency_root()
        problems += dependency_problems
        if root != dependency_root:
            problems.append("bootstrap PyYAML origin differs from launcher claim")
    problems += _resource_problems(REPO_ROOT, policy)
    if problems:
        for problem in problems:
            print(f"python-bootstrap: {problem}", file=sys.stderr)
        return 2
    if import_only:
        importlib.import_module(Path(tool).stem)
        return 0
    sys.argv = [str(files[tool]), *args]
    runpy.run_module(Path(tool).stem, run_name="__main__", alter_sys=False)
    return 0


def _surface_inherit(tool: str) -> tuple[str, ...]:
    values = load_policy().get("surface_environment", {}).get(tool, [])
    return tuple(values) if isinstance(values, list) else ()


def _launch(tool: str, args: list[str]) -> int:
    policy = load_policy()
    surfaces = _policy_surfaces(policy)
    if not _registered_tool(tool, surfaces):
        print(f"python-launcher: unregistered or unsafe Python tool {tool!r}", file=sys.stderr)
        return 2
    dependency_root: Path | None = None
    if _needs_yaml(tool, policy):
        dependency_root, problems = _dependency_root()
        if problems or dependency_root is None:
            for problem in problems or ["pinned PyYAML dependency is unavailable"]:
                print(f"python-launcher: {problem}", file=sys.stderr)
            return 2
    command = [
        sys.executable, "-I", "-B", str(Path(__file__).resolve()),
        "--bootstrap", tool, str(dependency_root) if dependency_root else "-", "--", *args,
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
        if "env" not in keywords or isinstance(keywords.get("env"), ast.Constant) \
                and keywords["env"].value is None:
            problems.append(f"{function}:{node.lineno}: process edge has implicit env")
        env_value = keywords.get("env")
        if isinstance(env_value, ast.Attribute) and isinstance(env_value.value, ast.Name) \
                and env_value.value.id == "os" and env_value.attr == "environ":
            problems.append(f"{function}:{node.lineno}: process edge forwards os.environ")
    return counts, problems


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
    venv_policy = policy["python"].get("venv", {})
    expected_home_names = [
        f"python{policy['python']['major_minor']}", "python3", "python",
        f"python{policy['python']['major_minor']}.exe", "python.exe",
    ]
    if venv_policy != {
        "path": ".venv",
        "implementation": "CPython",
        "include_system_site_packages": False,
        "home_interpreter_names": expected_home_names,
    }:
        problems.append("Python active-venv identity policy is non-canonical")
    surfaces = _policy_surfaces(policy)
    expected_files = surfaces | {META_GATE}
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
    sibling = {path.stem for path in files.values()}
    stdlib = set(sys.stdlib_module_names)
    actual_graph: dict[str, list[str]] = {}
    external_graph: dict[str, list[str]] = {}
    actual_edges: dict[str, dict[str, dict[str, Any]]] = {}
    for name, path in files.items():
        source = path.read_text(encoding="utf-8")
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
) -> list[str]:
    """Enforce distinct canonical shapes for subjects and embedded programs."""
    problems: list[str] = []
    launcher = "python3 -I -B scripts/check_python_execution_contract.py --launch "
    subject_pattern = re.compile(r"\bpython3\s+(?:-I\s+|-B\s+)*scripts/([\w.-]+\.py)")
    surfaces = _policy_surfaces(load_policy())
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if "python3" not in stripped:
            continue
        if "scripts/check_python_execution_contract.py" in stripped:
            if launcher not in stripped or not re.search(r"--(?:\s|$)", stripped):
                problems.append(f"{path.name}:{line_number}: launcher invocation is not canonical")
            continue
        match = subject_pattern.search(stripped)
        if match and match.group(1) in surfaces:
            problems.append(
                f"{path.name}:{line_number}: repository subject must use canonical launcher"
            )
            continue
        if enforce_embedded and "<<'PY'" in stripped and not re.search(
            r"\bpython3\s+-I(?:\s+-)?(?:\s+[^<]+)?\s+<<'PY'$", stripped,
        ):
            problems.append(f"{path.name}:{line_number}: embedded Python must use isolated mode")
    return problems


def _run_import(tool: str, cwd: Path, dependency_root: Path | None) -> str | None:
    command = [
        sys.executable, "-I", "-B", str(Path(__file__).resolve()),
        "--bootstrap", tool, str(dependency_root) if dependency_root else "-",
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
    base_executable = Path(active_identity["base_executable"])
    valid_identities: dict[str, dict[str, Any]] = {}
    for label, prefix in {
        "local-captured-shape": root / "local-venv",
        "setup-uv-hosted-shape": root / "workspace" / ".venv",
    }.items():
        executable = prefix / "bin" / "python3"
        executable.parent.mkdir(parents=True)
        executable.symlink_to(base_executable)
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

    valid = valid_identities["setup-uv-hosted-shape"]
    config = dict(active_config)
    optional_base = dict(valid, base_executable="")
    if _venv_identity_problems(optional_base, config):
        problems.append("optional _base_executable selftest rejected pyvenv home identity")
    outside_site = root / "outside" / "site-packages"
    outside_site.mkdir(parents=True)
    wrong_prefix = dict(valid, purelib=str(outside_site), platlib=str(outside_site))
    wrong_version = dict(config, version_info="3.12.0")
    wrong_config_executable = dict(config, executable=str(root / "other-python"))
    user_site = dict(valid, enable_user_site=True)
    wrong_base_prefix = dict(valid, base_prefix=str(root / "other-base"))
    wrong_base_executable = dict(valid, base_executable=str(root / "other-python"))
    symlink_site = root / "symlink" / "site-packages"
    symlink_site.parent.mkdir()
    symlink_site.symlink_to(outside_site, target_is_directory=True)
    symlink_identity = dict(valid, purelib=str(symlink_site), platlib=str(symlink_site))
    for label, identity, candidate_config in (
        ("wrong-prefix", wrong_prefix, config),
        ("wrong-version", valid, wrong_version),
        ("wrong-config-executable", valid, wrong_config_executable),
        ("user-site", user_site, config),
        ("wrong-base-prefix", wrong_base_prefix, config),
        ("wrong-base-executable", wrong_base_executable, config),
        ("symlink-site", symlink_identity, config),
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
    return problems


def _selftest(policy: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    valid = "import json\nVALUE=1\ndef f(x):\n return json.dumps(x+VALUE)\n"
    invalid = valid + "def broken():\n return NEVER_IMPORTED\n"
    if _undefined_names(valid, "<valid>") or _undefined_names(invalid, "<invalid>") != {"NEVER_IMPORTED"}:
        problems.append("undefined-name selftest failed")
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
    for source in (
        "from subprocess import run\nrun(['true'], env={})\n",
        "import subprocess as sp\nsp.run(['true'], env={})\n",
    ):
        if not _process_edges(ast.parse(source))[1]:
            problems.append("process-alias selftest failed")
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
            "python3 -I -B scripts/check_python_execution_contract.py "
            "--launch validate_all.py --",
            False,
        ),
        "direct-subject": ("python3 -I scripts/validate_all.py", True),
        "missing-bytecode-guard": (
            "python3 -I scripts/check_python_execution_contract.py "
            "--launch validate_all.py --",
            True,
        ),
        "embedded-isolated": ("python3 -I - '$VALUE' <<'PY'", False),
        "embedded-ambient": ("python3 - <<'PY'", True),
    }
    for label, (text, should_fail) in invocation_cases.items():
        failed = bool(workflow_python_invocation_problems(
            Path(label), text, enforce_embedded=label.startswith("embedded-"),
        ))
        if failed != should_fail:
            problems.append(f"workflow invocation selftest failed: {label}")
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        if not _resource_problems(root, policy):
            problems.append("missing-resource selftest failed")
        problems += _venv_selftest(root, policy)
    return problems


def check() -> list[str]:
    try:
        policy = load_policy()
    except RuntimeError as exc:
        return [str(exc)]
    problems = _runtime_problems()
    problems += _selftest(policy)
    files = _files()
    problems += _static_problems(policy, files)
    dependency_root, dependency_problems = _dependency_root()
    problems += dependency_problems
    problems += _resource_problems(REPO_ROOT, policy)
    for workflow in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        problems += workflow_python_invocation_problems(
            workflow, workflow.read_text(encoding="utf-8"),
        )
    if dependency_root is None:
        return problems
    with tempfile.TemporaryDirectory(prefix="ci-workflows-python-contract-") as raw:
        root = Path(raw)
        hostile_cwd = root / "hostile-cwd"
        cache = root / "bytecode"
        hostile_cwd.mkdir()
        cache.mkdir()
        (hostile_cwd / "_workflow_yaml.py").write_text("raise RuntimeError('shadow')\n")
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
