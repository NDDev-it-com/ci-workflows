#!/usr/bin/env python3
"""Executable contract probes for secret-scan's container and binary modes."""
from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from _strict_yaml import strict_load
from _workflow_yaml import REPO_ROOT, WORKFLOWS_DIR, get_on, load_yaml
from check_python_execution_contract import clean_environment

WORKFLOW = WORKFLOWS_DIR / "secret-scan.yml"
EXPECTED_VERSION = "8.30.1"
EXPECTED_SHA256 = "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"
EXPECTED_CONTAINER = "zricethezav/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f"


def _steps(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = document.get("jobs", {}).get("gitleaks", {}).get("steps", [])
    return {str(step.get("name")): step for step in raw if isinstance(step, dict)}


def _python(step: dict[str, Any], marker: str = "python3 -I <<'PY'") -> str:
    lines = str(step.get("run", "")).splitlines()
    starts = [i for i, line in enumerate(lines) if marker in line]
    if len(starts) != 1:
        raise ValueError(f"expected one {marker!r} heredoc, found {len(starts)}")
    start = starts[0] + 1
    end = next(i for i in range(start, len(lines)) if lines[i] == "PY")
    return "\n".join(lines[start:end]) + "\n"


def _run(program: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-"], input=program, text=True,
        capture_output=True, check=False, env=clean_environment(env),
    )


def _guard_cases(program: str, problems: list[str]) -> None:
    cases = [
        ("container-default", "container", EXPECTED_VERSION, EXPECTED_SHA256, "macOS", "ARM64", True),
        ("binary-linux-x64", "binary", EXPECTED_VERSION, EXPECTED_SHA256, "Linux", "X64", True),
        ("unknown-mode", "native", EXPECTED_VERSION, EXPECTED_SHA256, "Linux", "X64", False),
        ("missing-digest", "binary", EXPECTED_VERSION, "", "Linux", "X64", False),
        ("uppercase-digest", "binary", EXPECTED_VERSION, EXPECTED_SHA256.upper(), "Linux", "X64", False),
        ("bad-digest", "binary", EXPECTED_VERSION, "0" * 64, "Linux", "X64", False),
        ("unknown-version", "binary", "8.30.0", EXPECTED_SHA256, "Linux", "X64", False),
        ("unsupported-os", "binary", EXPECTED_VERSION, EXPECTED_SHA256, "macOS", "X64", False),
        ("unsupported-arch", "binary", EXPECTED_VERSION, EXPECTED_SHA256, "Linux", "ARM64", False),
    ]
    for label, mode, version, digest, runner_os, arch, success in cases:
        with tempfile.TemporaryDirectory(prefix="gitleaks-guard-") as raw:
            root = Path(raw)
            result = _run(program, {
                "GITLEAKS_EXECUTION_MODE": mode,
                "GITLEAKS_BINARY_VERSION": version,
                "GITLEAKS_BINARY_SHA256": digest,
                "GITLEAKS_RUNNER_OS": runner_os,
                "GITLEAKS_RUNNER_ARCH": arch,
                "GITHUB_ENV": str(root / "env"),
                "GITHUB_STEP_SUMMARY": str(root / "summary"),
            })
            if (result.returncode == 0) != success:
                problems.append(f"execution guard {label} returned {result.returncode}, expected {'success' if success else 'failure'}")
            if label == "binary-linux-x64" and "GITLEAKS_BINARY_URL=https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz" not in (root / "env").read_text():
                problems.append("binary guard did not select the exact allowlisted upstream URL")


def _archive(path: Path, kind: str) -> None:
    with tarfile.open(path, "w:gz") as bundle:
        for name in ("LICENSE", "README.md", "gitleaks"):
            info = tarfile.TarInfo(name)
            payload = b"fixture"
            info.size = len(payload)
            info.mode = 0o755 if name == "gitleaks" else 0o644
            if kind == "symlink" and name == "gitleaks":
                info.type = tarfile.SYMTYPE
                info.linkname = "/bin/true"
                info.size = 0
                payload = b""
            bundle.addfile(info, io.BytesIO(payload))
        if kind in {"traversal", "duplicate", "special", "corrupt-set"}:
            name = {"traversal": "../escape", "duplicate": "gitleaks", "special": "device", "corrupt-set": "extra"}[kind]
            info = tarfile.TarInfo(name)
            payload = b"bad"
            info.size = len(payload)
            if kind == "special":
                info.type = tarfile.CHRTYPE
                info.size = 0
                payload = b""
            bundle.addfile(info, io.BytesIO(payload))


def _archive_cases(program: str, problems: list[str]) -> None:
    for kind, success in (("valid", True), ("corrupt", False), ("traversal", False), ("duplicate", False), ("symlink", False), ("special", False), ("corrupt-set", False)):
        with tempfile.TemporaryDirectory(prefix="gitleaks-archive-") as raw:
            root = Path(raw)
            archive = root / "fixture.tar.gz"
            if kind == "corrupt":
                archive.write_bytes(b"not a gzip archive")
            else:
                _archive(archive, kind)
            result = _run(program, {"GITLEAKS_ARCHIVE": str(archive), "GITLEAKS_DESTINATION": str(root / "installed")})
            if (result.returncode == 0) != success:
                problems.append(f"archive probe {kind} returned {result.returncode}, expected {'success' if success else 'failure'}")
            if not success and (root / "installed").exists():
                problems.append(f"archive probe {kind} left an installed binary after rejection")


def check() -> list[str]:
    problems: list[str] = []
    document = load_yaml(WORKFLOW)
    call = get_on(document).get("workflow_call", {})
    inputs = call.get("inputs", {}) if isinstance(call, dict) else {}
    expected_defaults = {
        "execution_mode": "container",
        "gitleaks_binary_version": EXPECTED_VERSION,
        "gitleaks_binary_sha256": EXPECTED_SHA256,
        "gitleaks_image": EXPECTED_CONTAINER,
    }
    catalog = strict_load(REPO_ROOT / "catalog" / "capabilities.yml")
    capability = next(item for item in catalog["capabilities"] if item.get("workflow") == ".github/workflows/secret-scan.yml")
    if capability.get("runtime_requirements_by_execution_mode") != {
        "container": ["container-runtime"], "binary": []
    }:
        problems.append("secret-scan execution modes are not bound to exact machine requirements in capabilities.yml")
    tools = strict_load(REPO_ROOT / "catalog" / "tools.yml")
    gitleaks = next(item for item in tools["tools"] if item.get("id") == "gitleaks")
    expected_release = f"linux_x64 size:8230402 sha256:{EXPECTED_SHA256}"
    if gitleaks.get("binary_release") != expected_release:
        problems.append("tools.yml Gitleaks binary release pin does not match the workflow allowlist")
    for name, expected in expected_defaults.items():
        got = inputs.get(name, {}).get("default") if isinstance(inputs, dict) else None
        if got != expected:
            problems.append(f"secret-scan input {name} default is {got!r}, expected {expected!r}")
    steps = _steps(document)
    required = {
        "Validate Gitleaks execution contract", "Run gitleaks detect (history-aware, digest-pinned container)",
        "Install verified Gitleaks binary", "Run gitleaks detect (history-aware, verified binary)",
        "Clean verified Gitleaks binary state", "Summarize Gitleaks execution", "Upload gitleaks report",
    }
    missing = required - steps.keys()
    if missing:
        return [f"secret-scan missing contract steps: {sorted(missing)}"]
    try:
        _guard_cases(_python(steps["Validate Gitleaks execution contract"]), problems)
        _archive_cases(_python(steps["Install verified Gitleaks binary"], "python3 -I <<'PY'"), problems)
    except (ValueError, StopIteration) as exc:
        problems.append(f"secret-scan embedded-program extraction failed: {exc}")
    container_run = str(steps["Run gitleaks detect (history-aware, digest-pinned container)"].get("run", ""))
    if "docker run --rm" not in container_run or '"${GITLEAKS_IMAGE}" "${args[@]}"' not in container_run:
        problems.append("default container lane no longer preserves the digest-pinned docker invocation")
    binary_text = "\n".join(str(step.get("run", "")) for name, step in steps.items() if "binary" in name.lower())
    if re.search(r"\bdocker\s+(run|pull|build)\b", binary_text):
        problems.append("binary lane invokes Docker")
    binary_run = str(steps["Run gitleaks detect (history-aware, verified binary)"].get("run", ""))
    for token in ("--redact", "--no-banner", "--exit-code 1", "GITLEAKS_CONFIG_PATH", "GITLEAKS_REPORT_PATH", "GITLEAKS_REPORT_FORMAT"):
        if token not in container_run or token not in binary_run:
            problems.append(f"scan-mode parity lost required token {token!r}")
    install = str(steps["Install verified Gitleaks binary"].get("run", ""))
    for token in ("sha256sum -c -", "GITLEAKS_BINARY_SIZE", "version_output", "GITLEAKS_BINARY_VERSION"):
        if token not in install:
            problems.append(f"binary installer lost fail-closed check {token!r}")
    upload = steps["Upload gitleaks report"]
    if upload.get("if") != "${{ always() && inputs.upload_report && inputs.report_path != '' }}":
        problems.append("report upload condition changed across execution modes")
    cleanup = str(steps["Clean verified Gitleaks binary state"].get("run", ""))
    if "find \"$GITLEAKS_BINARY_ROOT\" -depth -delete" not in cleanup or "GITLEAKS_CLEANUP=verified" not in cleanup:
        problems.append("binary cleanup is not observable and fail-closed")
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_secret_scan_contract: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("check_secret_scan_contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
