# Hermetic repository Python execution

Repository-owned Python tools have one execution boundary:

```bash
python3 -I -B scripts/check_python_execution_contract.py --launch TOOL.py -- [ARGS...]
```

`catalog/python-execution.yml` is the machine-readable authority for the pinned
Python minor, exact surface inventory, sibling and external dependency graph,
required repository resources, subprocess edges, and child-environment policy.
The launcher rejects unknown or traversing tool names, reconstructs `sys.path`
from the repository `scripts/` directory, the standard library, and the exact
hash-pinned PyYAML installation when the registered import graph needs it.
The compatibility contract is CPython `3.13`, not one cross-host patch number:
uv may resolve that minor request to a newer supported patch. Each individual
environment is nevertheless exact and fail-closed: runtime `version_info`,
CPython implementation version, import cache tag, `pyvenv.cfg` version, base
installation, and executable must all describe the same patch. A
dependency-bearing subject is physically launched with `.venv/bin/python`;
the ambient `python3`, `PATH`, and `VIRTUAL_ENV` cannot select its interpreter.
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
