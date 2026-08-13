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


def _python_key(name: str) -> bool:
    return name.upper().startswith("PYTHON")


def clean_environment(
    overrides: Mapping[str, str] | None = None,
    *,
    inherit: Sequence[str] = (),
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Construct the only normal child environment; never merge ambient state."""
    policy = load_policy()
    contract = policy["environment"]
    ambient = os.environ if source is None else source
    allowlist = set(contract["base_allowlist"])
    requested = allowlist | set(inherit)
    forbidden = sorted(name for name in requested if _python_key(name))
    if forbidden:
        raise ValueError(f"interpreter-control variables cannot be inherited: {forbidden}")
    env = {
        name: str(ambient[name])
        for name in sorted(requested)
        if name in ambient and not _python_key(name)
    }
    env.update({str(k): str(v) for k, v in contract["canonical_values"].items()})
    for name, value in (overrides or {}).items():
        if _python_key(name):
            raise ValueError(f"interpreter-control override is forbidden: {name}")
        env[str(name)] = str(value)
    stripped = sorted({name for name in ambient if _python_key(name)})
    prior_raw = ambient.get(contract["stripped_names_evidence"], "[]")
    try:
        prior = json.loads(prior_raw)
    except json.JSONDecodeError as exc:
        raise ValueError("stripped-environment evidence is malformed") from exc
    if not isinstance(prior, list) or not all(isinstance(item, str) for item in prior):
        raise ValueError("stripped-environment evidence must be a string array")
    evidence_name = contract["stripped_names_evidence"]
    env[evidence_name] = json.dumps(
        sorted(set(prior) | set(stripped)), separators=(",", ":"),
    )
    return env


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
    env = clean_environment(source=os.environ)
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
    problems: list[str] = []
    try:
        distribution = importlib.metadata.distribution("PyYAML")
        spec = importlib.util.find_spec("yaml")
    except importlib.metadata.PackageNotFoundError:
        return None, ["pinned PyYAML distribution is unavailable"]
    if distribution.version != "6.0.3":
        problems.append(f"PyYAML version must be 6.0.3, got {distribution.version}")
    if spec is None or spec.origin is None:
        return None, problems + ["yaml module origin is unavailable"]
    origin = Path(spec.origin).resolve()
    root = origin.parent.parent
    if root == REPO_ROOT or REPO_ROOT in root.parents or origin != root / "yaml/__init__.py":
        problems.append(f"PyYAML origin is untrusted: {origin}")
    return root, problems


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
    if len(surfaces) != 45 or set(files) != expected:
        problems.append(
            f"inventory drift: count={len(surfaces)} "
            f"missing={sorted(expected - set(files))} extra={sorted(set(files) - expected)}"
        )
    if tool not in surfaces or Path(tool).name != tool or not tool.endswith(".py"):
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
    mapping = {
        "check_sdk_runtime_fixtures.py": ("CALLER_RESULT", "SDK_RUNTIME_EVIDENCE"),
        "generate_android_fixture_provenance.py": (
            "ANDROID_HOME", "ANDROID_SDK_ROOT", "CI", "JAVA_HOME",
        ),
        "negative_gate_probe.py": ("GH_TOKEN", "GITHUB_TOKEN"),
        "render_runtime_evidence.py": ("GUARDS", "PROVES", "RESULTS", "RUN_URL"),
        "verify_scorecard_runtime.py": ("GH_HOST", "GH_TOKEN"),
    }
    return mapping.get(tool, ())


def _launch(tool: str, args: list[str]) -> int:
    policy = load_policy()
    surfaces = _policy_surfaces(policy)
    if tool not in surfaces or Path(tool).name != tool:
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
    return {
        "role": role,
        "isolated": sys.flags.isolated,
        "ignore_environment": sys.flags.ignore_environment,
        "safe_path": sys.flags.safe_path,
        "no_user_site": sys.flags.no_user_site,
        "dont_write_bytecode": sys.flags.dont_write_bytecode,
        "python_keys": sorted(name for name in os.environ if _python_key(name)),
        "stripped": json.loads(os.environ.get(evidence_name, "[]")),
        "locale": {"LANG": os.environ.get("LANG"), "LC_ALL": os.environ.get("LC_ALL")},
    }


def _probe_child() -> int:
    env = clean_environment(source=os.environ)
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


def _probe_generations(root: Path) -> list[str]:
    problems: list[str] = []
    command = [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--probe-middle"]
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
    for label, payload in (("middle", middle), ("leaf", middle.get("leaf", {}))):
        if not isinstance(payload, dict):
            problems.append(f"{label} probe payload is missing")
            continue
        if payload.get("python_keys"):
            problems.append(f"{label} inherited interpreter-control variables")
        if payload.get("stripped") != expected:
            problems.append(f"{label} stripped-name evidence differs from policy")
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
    return counts, problems


def _static_problems(policy: Mapping[str, Any], files: Mapping[str, Path]) -> list[str]:
    problems: list[str] = []
    surfaces = _policy_surfaces(policy)
    expected_files = surfaces | {META_GATE}
    if len(surfaces) != 45 or set(files) != expected_files:
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
    sibling = {path.stem for path in files.values()}
    stdlib = set(sys.stdlib_module_names)
    actual_graph: dict[str, list[str]] = {}
    external_graph: dict[str, list[str]] = {}
    actual_edges: dict[str, dict[str, dict[str, Any]]] = {}
    for name, path in files.items():
        source = path.read_text(encoding="utf-8")
        if "os.environ.copy()" in source or re.search(r"\{\s*\*\*os\.environ", source):
            problems.append(f"{name}: ambient environment merge is forbidden")
        try:
            tree = ast.parse(source, filename=str(path), feature_version=(3, 13))
        except SyntaxError as exc:
            problems.append(f"{name}: Python 3.13 syntax error: {exc}")
            continue
        undefined = sorted(_undefined_names(source, str(path)))
        if undefined:
            problems.append(f"{name}: undefined global names {undefined}")
        roots = _import_roots(tree)
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
    if actual_edges != policy["process_edges"]:
        problems.append(f"Python process-edge registry drifted: actual={actual_edges}")
    return problems


def workflow_python_invocation_problems(path: Path, text: str) -> list[str]:
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
            if launcher not in stripped:
                problems.append(f"{path.name}:{line_number}: launcher invocation is not canonical")
            continue
        match = subject_pattern.search(stripped)
        if match and match.group(1) in surfaces:
            problems.append(
                f"{path.name}:{line_number}: repository subject must use canonical launcher"
            )
            continue
        if "<<'PY'" in stripped and not re.search(r"\bpython3\s+-I(?:\s+-\b[^<]*)?\s+<<'PY'$", stripped):
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


def _selftest(policy: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    valid = "import json\nVALUE=1\ndef f(x):\n return json.dumps(x+VALUE)\n"
    invalid = valid + "def broken():\n return NEVER_IMPORTED\n"
    if _undefined_names(valid, "<valid>") or _undefined_names(invalid, "<invalid>") != {"NEVER_IMPORTED"}:
        problems.append("undefined-name selftest failed")
    if not _import_side_effects(ast.parse("import pathlib\npathlib.Path('x').write_text('x')\n")):
        problems.append("import-write selftest failed")
    try:
        clean_environment({"PYTHONPATH": "forbidden"})
    except ValueError:
        pass
    else:
        problems.append("normal environment accepted interpreter-control override")
    with tempfile.TemporaryDirectory() as raw:
        if not _resource_problems(Path(raw), policy):
            problems.append("missing-resource selftest failed")
    return problems


def check() -> list[str]:
    try:
        policy = load_policy()
    except RuntimeError as exc:
        return [str(exc)]
    problems = _selftest(policy)
    files = _files()
    problems += _static_problems(policy, files)
    dependency_root, dependency_problems = _dependency_root()
    problems += dependency_problems
    problems += _resource_problems(REPO_ROOT, policy)
    if sys.version_info[:2] != (3, 13):
        problems.append(
            f"cold contract requires Python 3.13, got {sys.version_info.major}.{sys.version_info.minor}"
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
    if sys.argv[1:] == ["--probe-leaf"]:
        print(json.dumps(_probe_payload("leaf"), sort_keys=True, separators=(",", ":")))
        raise SystemExit(0)
    if sys.argv[1:] == ["--probe-fail"]:
        print("probe-child-diagnostic", file=sys.stderr)
        raise SystemExit(37)
    raise SystemExit(main())
