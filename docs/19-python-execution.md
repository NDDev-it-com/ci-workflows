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
and [Python 3.13 `runpy`](https://docs.python.org/3.13/library/runpy.html).
