# Hermetic repository Python execution

Repository-owned Python tools have one execution boundary:

```bash
.venv/bin/python -I -B scripts/check_python_execution_contract.py --launch validate_all.py --
```

Create the repository environment from the selected CPython 3.13 interpreter
with `python3.13 -I -B -m venv --copies .venv`, then install the hash-locked
requirements explicitly into `.venv/bin/python`. Activation is neither needed
nor trusted.

Before invoking the dependency-aware launcher, run the stdlib-only cold syntax
gate with `.venv/bin/python -I -B scripts/check_python_syntax.py`. It AST-parses
and byte-compiles every Python surface and independently proves that balanced,
quoted and multiline parser fixtures pass while malformed delimiters and
truncated constructions fail. This separate boundary remains runnable when a
semantic validator itself cannot be imported.

`catalog/python-execution.yml` is the machine-readable authority for the pinned
Python minor, exact surface inventory, sibling and external dependency graph,
required repository resources, subprocess edges, and child-environment policy.
The launcher rejects unknown or traversing tool names and does not add the
checkout or `scripts/` to `sys.path`. Instead, `scripts/__init__.py` is the exact
repository-tool package manifest. The stdlib-only bootstrap registers that
package through an `importlib` file spec whose sole submodule search location is
the verified, non-symlink repository `scripts/` directory; every sibling import
is package-qualified and every subject executes by its qualified module name.
Missing, stale, duplicate, shadowed, or wrong-origin package/helper identities
fail before subject execution. PyYAML remains an external dependency and is
accepted only from its separately verified hash-pinned venv distribution.
Invocation text is parsed into one typed `executable / flags / launcher / verb /
subject / arguments` record after deterministic POSIX continuation folding.
Workflow YAML is loaded structurally: only `jobs.*.steps[*].run` is executable
command input, and it must be a non-empty scalar. Nested `defaults.run`
mappings and reusable input definitions are configuration, while a null,
mapping, sequence, malformed scalar, or truncated command at a step boundary
fails closed. The same Invocation parser and renderer then validate decoded
literal, folded, quoted and multiline commands. Documentation is registered as
one of three source roles: repository-launcher references must demonstrate the
launcher, adoption guides may combine repository planning commands with
consumer examples, and consumer-command examples must not depend on this
library's repository-only launcher. The registry also fixes each source
language. Markdown contributes executable commands only from explicitly
language-tagged shell fences, Python only from registered AST string fixtures,
and workflow YAML only from structurally parsed step `run` scalars. Prose,
comments, mapping keys, and negative corpora are not re-tokenized as shell.
Every extracted command retains source path, line, role, and language;
unclassified sources, duplicate surfaces, and role drift fail closed.
The compatibility contract is CPython `3.13`, not one cross-host patch number:
uv may resolve that minor request to a newer supported patch. Each individual
environment is nevertheless exact and fail-closed: runtime `version_info`,
CPython implementation version, import cache tag, `pyvenv.cfg` version, base
installation, and executable must all describe the same patch. A
dependency-bearing subject is physically launched with `.venv/bin/python`;
the ambient `python3`, `PATH`, and `VIRTUAL_ENV` cannot select its interpreter.
Self workflows obtain the exact interpreter path from `actions/setup-python`,
disable that action's PATH mutation, create a copy-based `.venv`, and always
invoke the repository path. A stdlib-only launcher started under another
interpreter may make exactly one early `execve` transition to
`.venv/bin/python`; the transition emits a typed receipt and a missing,
foreign, symlinked, or repeated target fails before dependency import.
PyYAML is trusted only from the active Python 3.13 virtual environment: the
interpreter, prefix, base interpreter, `pyvenv.cfg`, non-system site-packages,
distribution metadata and import origin must form one coherent non-escaping
identity. `VIRTUAL_ENV` text is neither read nor trusted.
The venv is identified by Python's own runtime facts: `sys.prefix` and
`sys.exec_prefix` resolve to the repository-owned `.venv`, while
`sys.base_prefix`, `sys.base_exec_prefix`, and the optional
`sys._base_executable` anchor the base installation. The `pyvenv.cfg` `home`
directory must contain an interpreter resolving to that same base executable;
it is deliberately not required to equal the executable's parent because
framework and package-manager layouts need not have that shape. Exact patch
version, disabled system/user sites, trusted `purelib`/`platlib`, distribution
metadata, and module origin are checked independently. Harmless parent-path
aliases are resolved; a symlink that escapes a trusted root is rejected.

Every child process receives an allowlisted environment rather than an ambient
copy. Interpreter-control variables (`PYTHON*`, case-insensitively) are removed
at every process edge and their names are carried as structured stripping
evidence. The same transition records the exact allowlisted variable names it
inherited; values are never written to evidence. Locale is canonicalized to
`C`. A validator may inherit an additional variable only through its explicit
launcher profile; Python-control variables can never be added there.
Each AST-observed process edge selects a total machine-readable profile for its
API, executable origin, argv form, cwd behavior, and environment replacement.
`os.execve` is the one replacement edge: its third positional mapping is the
complete child environment, and the registry rejects a missing, duplicated, or
untyped edge.
Dependency-bearing negative probes bind their workflow input to the exact
validated repository interpreter with `--python-input NAME=ARGS`. The harness
requires pytest to resolve inside that same venv before either fixture runs;
missing/import/setup failures are reported as `NOT_PROVEN`, while evidence
requires the bad fixture to fail for its assertion and the clean control to
complete successfully. Ambient `python`, PATH lookup, and caller-supplied
interpreter text cannot satisfy this contract.
GitHub API verifier edges use the `network-gh` profile with an explicit
repository cwd and only the named `GH_HOST`/`GH_TOKEN` inheritance; this matches
both byte and JSON API calls rather than treating their explicit cwd as ambient
preservation.

The blocking cold-process gate proves Python 3.13 isolated mode, no bytecode
writes, hostile working-directory and shadow-module resistance, pinned PyYAML
ownership, exact imports/resources, no import-time writes, registered explicit
subprocess environments, multi-generation taint removal, and preservation of a
child's first exit code and diagnostic. It imports mutating generators but does
not execute them. Business semantics remain in their dedicated validators and
`validate_all.py`; cold startup success is never substituted for those checks.

Embedded one-off Python inside a workflow is a separate contract and runs as
`python3 -I`. It is not a registered repository tool and cannot use the launcher
to bypass the surface inventory.

Primary contracts: [Python 3.13 command-line and environment
semantics](https://docs.python.org/3.13/using/cmdline.html), [Python 3.13
subprocess environment replacement](https://docs.python.org/3.13/library/subprocess.html),
[Python 3.13 virtual environments](https://docs.python.org/3.13/library/venv.html),
[Python 3.13 `sys` prefixes](https://docs.python.org/3.13/library/sys.html), and
[Python 3.13 `runpy`](https://docs.python.org/3.13/library/runpy.html). The
[uv Python-version contract](https://docs.astral.sh/uv/concepts/python-versions/)
defines a minor-only request as a compatible line whose preferred patch can be
upgraded; this repository therefore checks exact in-environment coherence
instead of hard-coding whichever patch one runner resolved today.
The pinned [`actions/setup-python` output
contract](https://github.com/actions/setup-python/blob/main/docs/advanced-usage.md#outputs-and-environment-variables)
provides the absolute bootstrap interpreter; its PATH update is disabled so
that only the recorded output can create the repository environment.
