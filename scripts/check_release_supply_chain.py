#!/usr/bin/env python3
"""Fail-closed regression checks for the reusable release supply chain.

The release workflow executes in the caller checkout, so its archive and
version guards are embedded in YAML. This validator extracts those exact Python
programs and exercises them in hermetic temporary Git repositories instead of
maintaining a second, weaker implementation of the contract.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from _workflow_yaml import WORKFLOWS_DIR, load_yaml

REUSABLE = WORKFLOWS_DIR / "release-supply-chain.yml"
FREE = WORKFLOWS_DIR / "release-supply-chain-free.yml"
SELF_RELEASE = WORKFLOWS_DIR / "release.yml"
ATTEST_STEP_NAMES = ("Attest build provenance (archive)", "Attest SBOM (archive)")
EXPECTED_STATIC_ASSETS = {
    "sbom.spdx.json",
    "release-notes.md",
    "release-manifest.json",
    "SHA256SUMS",
}
SYFT_PINS = {
    "ARM64": {
        "archive_arch": "arm64",
        "sha256": "dc630590c953347789d08f8ebf57c7d8094db89100785fcd94b1cddeac791804",
        "size": "25154290",
    },
    "X64": {
        "archive_arch": "amd64",
        "sha256": "0d6be741479eddd2c8644a288990c04f3df0d609bbc1599a005532a9dff63509",
        "size": "27565477",
    },
}
SYFT_VERSION = "1.42.3"


def _steps(workflow: dict[str, Any], job_name: str) -> list[dict[str, Any]]:
    jobs = workflow.get("jobs", {})
    job = jobs.get(job_name, {}) if isinstance(jobs, dict) else {}
    raw_steps = job.get("steps", []) if isinstance(job, dict) else []
    if not isinstance(raw_steps, list):
        return []
    return [step for step in raw_steps if isinstance(step, dict)]


def _step(
    workflow: dict[str, Any], job_name: str, step_name: str
) -> dict[str, Any] | None:
    for step in _steps(workflow, job_name):
        if step.get("name") == step_name:
            return step
    return None


def _embedded_python(step: dict[str, Any] | None) -> str:
    if not isinstance(step, dict) or not isinstance(step.get("run"), str):
        raise ValueError("step has no run program")
    lines = step["run"].splitlines()
    starts = [
        index
        for index, line in enumerate(lines)
        if re.search(r"\bpython3\s+-I(?:\s+-\s+[^<]+)?\s+<<'PY'$", line.strip())
    ]
    if len(starts) != 1:
        raise ValueError(f"expected one isolated Python heredoc, found {len(starts)}")
    start = starts[0] + 1
    try:
        end = next(index for index in range(start, len(lines)) if lines[index] == "PY")
    except StopIteration as exc:
        raise ValueError("isolated Python heredoc is not terminated") from exc
    return "\n".join(lines[start:end]) + "\n"


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    return subprocess.run(
        command,
        cwd=cwd,
        env=process_env,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _run_python(
    program: str,
    *,
    cwd: Path,
    env: dict[str, str],
    args: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    return _run(
        [sys.executable, "-I", "-", *args],
        cwd=cwd,
        env=env,
        input_text=program,
    )


def _init_repo(root: Path) -> None:
    commands = (
        ["git", "init", "--quiet"],
        ["git", "config", "user.name", "Release Validator"],
        ["git", "config", "user.email", "release-validator@example.invalid"],
    )
    for command in commands:
        result = _run(command, cwd=root)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "temporary Git setup failed")


def _commit_all(root: Path) -> None:
    for command in (["git", "add", "--all"], ["git", "commit", "-qm", "fixture"]):
        result = _run(command, cwd=root)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "temporary Git commit failed")


def _tag(root: Path, version: str = "1.2.3") -> None:
    result = _run(["git", "tag", version], cwd=root)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "temporary Git tag failed")


def _expect_failure(
    problems: list[str], label: str, result: subprocess.CompletedProcess[str]
) -> None:
    if result.returncode == 0:
        problems.append(f"release regression fixture unexpectedly passed: {label}")


def _find_gnu_tar() -> str | None:
    for name in ("gtar", "tar"):
        candidate = shutil.which(name)
        if candidate is None:
            continue
        result = subprocess.run(
            [candidate, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0 and result.stdout.startswith(b"tar (GNU tar)"):
            return candidate
    return None


def _check_gnu_tar_archive(
    root: Path,
    file_list: Path,
    expected: set[bytes],
    problems: list[str],
) -> None:
    gnu_tar = _find_gnu_tar()
    if gnu_tar is None:
        return
    source_time = _run(["git", "log", "-1", "--format=%cI"], cwd=root).stdout.strip()
    command = [
        gnu_tar,
        "--create",
        "--file=-",
        "--sort=name",
        f"--mtime={source_time}",
        "--owner=0",
        "--group=0",
        "--numeric-owner",
        "--no-recursion",
        "--null",
        "--verbatim-files-from",
        f"--files-from={file_list}",
    ]

    archives = []
    for _ in range(2):
        tar_result = subprocess.run(
            command,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if tar_result.returncode != 0:
            problems.append(
                "GNU tar rejected the option-safe tracked-file list: "
                + tar_result.stderr.decode(errors="replace").strip()
            )
            return
        gzip_result = subprocess.run(
            ["gzip", "-n"],
            input=tar_result.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if gzip_result.returncode != 0:
            problems.append("gzip -n failed during release archive simulation")
            return
        archives.append(gzip_result.stdout)
    if archives[0] != archives[1]:
        problems.append("release archive simulation is not byte-reproducible")

    listing = subprocess.run(
        [gnu_tar, "--list", "--file=-"],
        input=gzip.decompress(archives[0]),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if listing.returncode != 0:
        problems.append("GNU tar could not list the simulated release archive")
        return
    archived = {line for line in listing.stdout.splitlines() if line}
    if archived != expected:
        problems.append("GNU tar archive differs from the exact tracked-file closure")


def _check_archive_program(program: str, problems: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-release-archive-") as raw_root:
        root = Path(raw_root)
        _init_repo(root)
        (root / "README.md").write_text("fixture\n", encoding="utf-8")
        (root / "src").mkdir()
        (root / "src" / "tracked.txt").write_text("tracked\n", encoding="utf-8")
        (root / "space dir").mkdir()
        (root / "space dir" / "file name.txt").write_text("space\n", encoding="utf-8")
        (root / "tracked-link").symlink_to("README.md")
        _commit_all(root)
        (root / "src" / "untracked.txt").write_text("untracked\n", encoding="utf-8")

        output = root / "archive-files.nul"
        output.touch(mode=0o600)
        valid = _run_python(
            program,
            cwd=root,
            env={"ARCHIVE_PATHS": 'README.md src "space dir/file name.txt"'},
            args=(str(output),),
        )
        if valid.returncode != 0:
            problems.append(
                "release archive normalizer rejected valid tracked paths: "
                + (valid.stderr.strip() or "unknown error")
            )
            return
        selected = {entry for entry in output.read_bytes().split(b"\0") if entry}
        expected = {
            b"README.md",
            b"src/tracked.txt",
            b"space dir/file name.txt",
        }
        if selected != expected:
            problems.append(
                "release archive normalizer did not produce the exact tracked file set"
            )
        if b"src/untracked.txt" in selected:
            problems.append("release archive normalizer admitted an untracked file")
        _check_gnu_tar_archive(root, output, expected, problems)

        invalid_inputs = {
            "empty": "",
            "unmatched": "missing",
            "absolute": "/etc/passwd",
            "dot": ".",
            "dot-traversal": "../README.md",
            "non-normalized": "src/",
            "option-like": "--checkpoint-action=exec=touch marker",
            "duplicate": "README.md README.md",
            "control": "README.md\nLICENSE",
            "pathspec-magic": ":(glob)**",
            "tracked-symlink": "tracked-link",
        }
        for label, value in invalid_inputs.items():
            candidate = root / f"invalid-{label}.nul"
            candidate.touch(mode=0o600)
            result = _run_python(
                program,
                cwd=root,
                env={"ARCHIVE_PATHS": value},
                args=(str(candidate),),
            )
            _expect_failure(problems, f"archive_paths/{label}", result)

        (root / "README.md").write_text("modified\n", encoding="utf-8")
        dirty_output = root / "dirty.nul"
        dirty_output.touch(mode=0o600)
        dirty = _run_python(
            program,
            cwd=root,
            env={"ARCHIVE_PATHS": "README.md"},
            args=(str(dirty_output),),
        )
        _expect_failure(problems, "archive_paths/modified-tracked-file", dirty)


def _write_payload_fixture(root: Path) -> tuple[Path, Path]:
    source = root / "source"
    payload = root / "payload"
    source.mkdir()
    payload.mkdir()
    (source / "README.md").write_text("fixture\n", encoding="utf-8")
    (source / "nested").mkdir()
    (source / "nested" / "file.txt").write_text("nested\n", encoding="utf-8")
    shutil.copytree(source, payload, dirs_exist_ok=True)
    archive = root / "fixture-1.2.3.tar.gz"
    with tarfile.open(archive, mode="w:gz") as bundle:
        bundle.add(source / "README.md", arcname="README.md", recursive=False)
        bundle.add(
            source / "nested" / "file.txt",
            arcname="nested/file.txt",
            recursive=False,
        )
    return archive, payload


def _check_payload_program(program: str, problems: list[str]) -> None:
    def run_fixture(root: Path, payload: Path) -> subprocess.CompletedProcess[str]:
        return _run_python(
            program,
            cwd=root,
            env={
                "PACKAGE_NAME": "fixture",
                "RELEASE_DIST": str(root),
                "RELEASE_PAYLOAD": str(payload),
                "RELEASE_VERSION": "1.2.3",
            },
        )

    with tempfile.TemporaryDirectory(prefix="nddev-release-payload-") as raw_root:
        root = Path(raw_root)
        _, payload = _write_payload_fixture(root)
        valid = run_fixture(root, payload)
        if valid.returncode != 0:
            problems.append(
                "archive payload verifier rejected an exact extraction: "
                + (valid.stderr.strip() or "unknown error")
            )

    for label, mutate in (
        (
            "extra-file",
            lambda payload: (payload / "extra.txt").write_text(
                "extra\n", encoding="utf-8"
            ),
        ),
        ("extra-directory", lambda payload: (payload / "empty").mkdir()),
        (
            "modified-file",
            lambda payload: (payload / "README.md").write_text(
                "modified\n", encoding="utf-8"
            ),
        ),
        (
            "symlink",
            lambda payload: (payload / "unsafe-link").symlink_to("README.md"),
        ),
    ):
        with tempfile.TemporaryDirectory(
            prefix=f"nddev-release-payload-{label}-"
        ) as raw_root:
            root = Path(raw_root)
            _, payload = _write_payload_fixture(root)
            mutate(payload)
            _expect_failure(
                problems,
                f"archive-payload/{label}",
                run_fixture(root, payload),
            )


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o700)


def _check_syft_program(
    program: str,
    step_env: dict[str, Any],
    problems: list[str],
) -> None:
    expected_env = {
        "SYFT_CHECK_FOR_APP_UPDATE": "false",
        "SYFT_LINUX_ARM64_SHA256": SYFT_PINS["ARM64"]["sha256"],
        "SYFT_LINUX_ARM64_SIZE": SYFT_PINS["ARM64"]["size"],
        "SYFT_LINUX_X64_SHA256": SYFT_PINS["X64"]["sha256"],
        "SYFT_LINUX_X64_SIZE": SYFT_PINS["X64"]["size"],
        "SYFT_VERSION": SYFT_VERSION,
    }
    for name, expected in expected_env.items():
        if str(step_env.get(name, "")) != expected:
            problems.append(f"Syft release pin mismatch for {name}")

    curl_stub = r"""#!/usr/bin/env python3
import json
import os
import pathlib
import sys

args = sys.argv[1:]
output = pathlib.Path(args[args.index("--output") + 1])
maximum = int(args[args.index("--max-filesize") + 1])
output.parent.mkdir(parents=True, exist_ok=True)
with output.open("wb") as stream:
    stream.truncate(maximum)
pathlib.Path(os.environ["CURL_CAPTURE"]).write_text(
    json.dumps(args), encoding="utf-8"
)
"""
    checksum_stub = r"""#!/usr/bin/env python3
import os
import pathlib
import sys

pathlib.Path(os.environ["CHECKSUM_CAPTURE"]).write_text(
    sys.stdin.read(), encoding="utf-8"
)
"""
    tar_stub = r"""#!/usr/bin/env python3
import os
import pathlib
import stat
import sys

args = sys.argv[1:]
directory_arg = next(value for value in args if value.startswith("--directory="))
directory = pathlib.Path(directory_arg.split("=", 1)[1])
binary = directory / "syft"
binary.write_text(os.environ["FAKE_SYFT_PROGRAM"], encoding="utf-8")
binary.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
"""
    fake_syft = r"""#!/usr/bin/env python3
import json
import os
import pathlib
import sys

args = sys.argv[1:]
if args[:1] == ["version"]:
    print(json.dumps({"version": os.environ["SYFT_VERSION"]}))
    raise SystemExit(0)
if args[:1] != ["scan"]:
    raise SystemExit(2)
pathlib.Path(os.environ["SYFT_CAPTURE"]).write_text(
    json.dumps(args), encoding="utf-8"
)
output = args[args.index("--output") + 1]
if not output.startswith("spdx-json="):
    raise SystemExit(3)
path = pathlib.Path(output.split("=", 1)[1])
path.write_text('{"spdxVersion":"SPDX-2.3"}\n', encoding="utf-8")
"""

    for runner_arch, pin in SYFT_PINS.items():
        with tempfile.TemporaryDirectory(
            prefix=f"nddev-release-syft-{runner_arch.lower()}-"
        ) as raw_root:
            root = Path(raw_root)
            bin_dir = root / "bin"
            release_dist = root / "release-dist"
            release_payload = root / "release-payload"
            bin_dir.mkdir()
            release_dist.mkdir()
            release_payload.mkdir()
            _write_executable(bin_dir / "curl", curl_stub)
            _write_executable(bin_dir / "sha256sum", checksum_stub)
            _write_executable(bin_dir / "tar", tar_stub)
            curl_capture = root / "curl.json"
            checksum_capture = root / "checksum.txt"
            syft_capture = root / "syft.json"
            env = {
                name: str(value)
                for name, value in step_env.items()
                if isinstance(value, (str, int, float, bool))
            }
            env.update(
                {
                    "CHECKSUM_CAPTURE": str(checksum_capture),
                    "CURL_CAPTURE": str(curl_capture),
                    "FAKE_SYFT_PROGRAM": fake_syft,
                    "PACKAGE_NAME": "fixture",
                    "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                    "RELEASE_DIST": str(release_dist),
                    "RELEASE_PAYLOAD": str(release_payload),
                    "RELEASE_RUNNER_ARCH": runner_arch,
                    "RELEASE_RUNNER_OS": "Linux",
                    "RELEASE_VERSION": "1.2.3",
                    "RUNNER_TEMP": str(root),
                    "SYFT_CAPTURE": str(syft_capture),
                }
            )
            result = _run(
                ["bash", "-euo", "pipefail", "-c", program],
                cwd=root,
                env=env,
            )
            if result.returncode != 0:
                problems.append(
                    f"Syft {runner_arch} pinned-binary fixture failed: "
                    + (result.stderr.strip() or "unknown error")
                )
                continue

            curl_args = json.loads(curl_capture.read_text(encoding="utf-8"))
            expected_url = (
                "https://github.com/anchore/syft/releases/download/"
                f"v{SYFT_VERSION}/syft_{SYFT_VERSION}_linux_"
                f"{pin['archive_arch']}.tar.gz"
            )
            if curl_args[0] != "--disable" or curl_args[-1] != expected_url:
                problems.append(f"Syft {runner_arch} download URL is not exact")
            for token in ("--proto", "--proto-redir", "--max-filesize"):
                if token not in curl_args:
                    problems.append(f"Syft download omits curl guard {token}")
            if curl_args[curl_args.index("--max-filesize") + 1] != pin["size"]:
                problems.append(f"Syft {runner_arch} max size is not pinned")
            checksum = checksum_capture.read_text(encoding="utf-8")
            if not checksum.startswith(f"{pin['sha256']}  "):
                problems.append(f"Syft {runner_arch} SHA-256 selection is wrong")

            syft_args = json.loads(syft_capture.read_text(encoding="utf-8"))
            expected_source = {
                "--source-name",
                "fixture",
                "--source-version",
                "1.2.3",
            }
            if not expected_source.issubset(syft_args):
                problems.append("Syft scan lost fixed source name/version metadata")
            output = syft_args[syft_args.index("--output") + 1]
            if not output.startswith("spdx-json="):
                problems.append("Syft scan output is not fixed to SPDX JSON")
            if not (release_dist / "sbom.spdx.json").is_file():
                problems.append("Syft SBOM output was not atomically finalized")
            if list(release_dist.glob(".sbom.spdx.json.*")):
                problems.append("Syft SBOM atomic temporary file leaked")

    with tempfile.TemporaryDirectory(
        prefix="nddev-release-syft-unsupported-"
    ) as raw_root:
        root = Path(raw_root)
        env = {
            "PACKAGE_NAME": "fixture",
            "RELEASE_DIST": str(root),
            "RELEASE_PAYLOAD": str(root),
            "RELEASE_RUNNER_ARCH": "X86",
            "RELEASE_RUNNER_OS": "Linux",
            "RELEASE_VERSION": "1.2.3",
            "RUNNER_TEMP": str(root),
            **expected_env,
        }
        _expect_failure(
            problems,
            "syft/unsupported-architecture",
            _run(
                ["bash", "-euo", "pipefail", "-c", program],
                cwd=root,
                env=env,
            ),
        )


def _check_version_programs(
    input_program: str,
    checked_out_program: str,
    self_program: str,
    problems: list[str],
) -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-release-version-") as raw_root:
        root = Path(raw_root)
        (root / "VERSION").write_bytes(b"1.2.3\n")
        (root / "CHANGELOG.md").write_text(
            "# Changelog\n\n## [1.2.3] - 2026-07-10\n", encoding="utf-8"
        )
        _init_repo(root)
        _commit_all(root)
        _tag(root)

        # A non-isolated interpreter would import these attacker-controlled files.
        sentinel = root / "stdlib-shadowed"
        for name in ("json.py", "pathlib.py", "sitecustomize.py"):
            (root / name).write_text(
                f"open({str(sentinel)!r}, 'w', encoding='utf-8').close()\n",
                encoding="utf-8",
            )

        input_env = {
            "RELEASE_VERSION": "1.2.3",
            "PACKAGE_NAME": "fixture",
            "RELEASE_RUNNER_ARCH": "X64",
            "RELEASE_RUNNER_OS": "Linux",
        }
        checked_out_env = {
            "RELEASE_VERSION": "1.2.3",
            "RELEASE_REF_NAME": "1.2.3",
            "RELEASE_REF_TYPE": "tag",
        }
        valid_input = _run_python(input_program, cwd=root, env=input_env)
        if valid_input.returncode != 0:
            problems.append(
                "pre-checkout release input guard rejected strict valid input: "
                + (valid_input.stderr.strip() or "unknown error")
            )
        valid_checked_out = _run_python(
            checked_out_program, cwd=root, env=checked_out_env
        )
        if valid_checked_out.returncode != 0:
            problems.append(
                "checked-out release contract rejected strict valid input: "
                + (valid_checked_out.stderr.strip() or "unknown error")
            )

        output = root / "github-output"
        output.touch()
        self_env = {
            "INPUT_VERSION": "1.2.3",
            "EVENT_NAME": "workflow_dispatch",
            "REF_NAME": "main",
            "GITHUB_OUTPUT": str(output),
        }
        valid_self = _run_python(self_program, cwd=root, env=self_env)
        if valid_self.returncode != 0:
            problems.append(
                "self release version guard rejected strict valid input: "
                + (valid_self.stderr.strip() or "unknown error")
            )
        if output.read_text(encoding="utf-8") != "version=1.2.3\n":
            problems.append("self release version guard emitted an invalid job output")
        if sentinel.exists():
            problems.append(
                "release Python isolation allowed checkout module shadowing"
            )

        for value in ("01.2.3", "1.02.3", "1.2.03", "1.2.3-pre", "1.2"):
            _expect_failure(
                problems,
                f"pre-checkout-version/{value}",
                _run_python(
                    input_program,
                    cwd=root,
                    env=input_env | {"RELEASE_VERSION": value},
                ),
            )
            output.write_text("", encoding="utf-8")
            _expect_failure(
                problems,
                f"self-version/{value}",
                _run_python(
                    self_program,
                    cwd=root,
                    env=self_env | {"INPUT_VERSION": value},
                ),
            )

        for label, version_bytes in {
            "missing-lf": b"1.2.3",
            "extra-lf": b"1.2.3\n\n",
            "trailing-space": b"1.2.3 \n",
            "crlf": b"1.2.3\r\n",
        }.items():
            (root / "VERSION").write_bytes(version_bytes)
            _expect_failure(
                problems,
                f"checked-out-VERSION/{label}",
                _run_python(checked_out_program, cwd=root, env=checked_out_env),
            )
            output.write_text("", encoding="utf-8")
            _expect_failure(
                problems,
                f"self-VERSION/{label}",
                _run_python(self_program, cwd=root, env=self_env),
            )
        (root / "VERSION").write_bytes(b"1.2.3\n")

        for label, override in {
            "unsafe-package": {"PACKAGE_NAME": "../fixture"},
            "unsupported-runner-os": {"RELEASE_RUNNER_OS": "macOS"},
            "unsupported-runner-arch": {"RELEASE_RUNNER_ARCH": "X86"},
        }.items():
            _expect_failure(
                problems,
                f"pre-checkout-contract/{label}",
                _run_python(input_program, cwd=root, env=input_env | override),
            )

        _expect_failure(
            problems,
            "checked-out-contract/tag-mismatch",
            _run_python(
                checked_out_program,
                cwd=root,
                env=checked_out_env | {"RELEASE_REF_NAME": "1.2.4"},
            ),
        )
        (root / "CHANGELOG.md").write_text(
            "# Changelog\n\n## [1.2.4] - 2026-07-10\n", encoding="utf-8"
        )
        _expect_failure(
            problems,
            "checked-out-contract/changelog-mismatch",
            _run_python(checked_out_program, cwd=root, env=checked_out_env),
        )
        (root / "CHANGELOG.md").write_text(
            "# Changelog\n\n## [1.2.3] - first\n\n## [1.2.3] - duplicate\n",
            encoding="utf-8",
        )
        _expect_failure(
            problems,
            "checked-out-contract/duplicate-changelog-heading",
            _run_python(checked_out_program, cwd=root, env=checked_out_env),
        )
        output.write_text("", encoding="utf-8")
        _expect_failure(
            problems,
            "self-contract/duplicate-changelog-heading",
            _run_python(self_program, cwd=root, env=self_env),
        )


def _check_notes_program(program: str, problems: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-release-notes-") as raw_root:
        root = Path(raw_root)
        release_dist = root / "release-dist"
        release_dist.mkdir()
        notes = release_dist / "release-notes.md"
        env = {
            "NOTES_FILE": "",
            "RELEASE_DIST": str(release_dist),
            "RELEASE_VERSION": "1.2.3",
        }
        (root / "CHANGELOG.md").write_text(
            "# Changelog\n\n"
            "## [1x2y3] - malformed lookalike\n\n"
            "wrong release body\n\n"
            "## [1.2.3] - 2026-07-10\n\n"
            "exact release body\n\n"
            "## [1.2.4] - 2026-07-11\n\n"
            "next release body\n",
            encoding="utf-8",
        )
        _init_repo(root)
        _commit_all(root)
        result = _run_python(program, cwd=root, env=env)
        if result.returncode != 0:
            problems.append(
                "literal changelog release-note extraction rejected an exact heading: "
                + (result.stderr.strip() or "unknown error")
            )
        elif not notes.is_file():
            problems.append("changelog release-note extraction created no notes file")
        else:
            extracted = notes.read_text(encoding="utf-8")
            if "exact release body" not in extracted:
                problems.append("release notes omitted the exact version section")
            if "wrong release body" in extracted:
                problems.append(
                    "release notes treated dots in the version as regex wildcards"
                )
            if "next release body" in extracted:
                problems.append("release notes crossed the next changelog heading")

        notes.unlink(missing_ok=True)
        (root / "CHANGELOG.md").write_text(
            "# Changelog\n\n## [1x2y3] - malformed lookalike\n",
            encoding="utf-8",
        )
        _expect_failure(
            problems,
            "release-notes/missing-exact-heading",
            _run_python(program, cwd=root, env=env),
        )

        (root / "CHANGELOG.md").write_text(
            "# Changelog\n\n## [1.2.3] - 2026-07-10\n\n   \n"
            "## [1.2.4] - 2026-07-11\n\nnext\n",
            encoding="utf-8",
        )
        _expect_failure(
            problems,
            "release-notes/whitespace-only-changelog-section",
            _run_python(program, cwd=root, env=env),
        )

        custom = root / "CUSTOM-NOTES.md"
        custom.write_text("custom canonical notes\n", encoding="utf-8")
        _commit_all(root)
        custom_result = _run_python(
            program,
            cwd=root,
            env=env | {"NOTES_FILE": "CUSTOM-NOTES.md"},
        )
        if custom_result.returncode != 0:
            problems.append(
                "tracked custom release notes were rejected: "
                + (custom_result.stderr.strip() or "unknown error")
            )
        elif notes.read_text(encoding="utf-8") != "custom canonical notes\n":
            problems.append("custom notes do not equal the canonical asset")

        notes.unlink(missing_ok=True)
        untracked = root / "UNTRACKED-NOTES.md"
        untracked.write_text("untracked\n", encoding="utf-8")
        _expect_failure(
            problems,
            "release-notes/untracked-custom-file",
            _run_python(
                program,
                cwd=root,
                env=env | {"NOTES_FILE": "UNTRACKED-NOTES.md"},
            ),
        )

        empty = root / "EMPTY-NOTES.md"
        empty.write_text(" \n\t\n", encoding="utf-8")
        _commit_all(root)
        _expect_failure(
            problems,
            "release-notes/whitespace-only-custom-file",
            _run_python(
                program,
                cwd=root,
                env=env | {"NOTES_FILE": "EMPTY-NOTES.md"},
            ),
        )

        notes.write_text("pre-existing\n", encoding="utf-8")
        _expect_failure(
            problems,
            "release-notes/pre-existing-output",
            _run_python(
                program,
                cwd=root,
                env=env | {"NOTES_FILE": "CUSTOM-NOTES.md"},
            ),
        )


def _check_publish_program(program: str, problems: list[str]) -> None:
    gh_stub = r"""#!/usr/bin/env python3
import json
import os
import pathlib
import sys

args = sys.argv[1:]
with pathlib.Path(os.environ["GH_CALLS"]).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(args) + "\n")
if args[:1] == ["api"]:
    print(os.environ["REMOTE_TAG_OBJECT"])
"""
    with tempfile.TemporaryDirectory(prefix="nddev-release-publish-") as raw_root:
        root = Path(raw_root)
        bin_dir = root / "bin"
        release_dist = root / "release-dist"
        bin_dir.mkdir()
        release_dist.mkdir()
        _write_executable(bin_dir / "gh", gh_stub)
        (root / "CHANGELOG.md").write_text(
            "# Changelog\n\n## [1.2.3] - 2026-07-10\n\nrelease body\n",
            encoding="utf-8",
        )
        _init_repo(root)
        _commit_all(root)
        _tag(root)
        tag_object = _run(
            ["git", "rev-parse", "refs/tags/1.2.3"], cwd=root
        ).stdout.strip()
        archive = release_dist / "fixture-1.2.3.tar.gz"
        notes = release_dist / "release-notes.md"
        expected_assets = [
            archive,
            release_dist / "sbom.spdx.json",
            notes,
            release_dist / "release-manifest.json",
            release_dist / "SHA256SUMS",
        ]
        for asset in expected_assets:
            asset.write_text(f"{asset.name}\n", encoding="utf-8")
        notes.write_text("\nrelease body\n", encoding="utf-8")
        # An undeclared file proves the publish command does not use an open glob.
        (release_dist / "undeclared.txt").write_text("ignore\n", encoding="utf-8")
        calls = root / "gh-calls.jsonl"
        env = {
            "GH_CALLS": str(calls),
            "GH_TOKEN": "fixture-token",
            "GITHUB_REPOSITORY": "owner/repository",
            "PACKAGE_NAME": "fixture",
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "RELEASE_DIST": str(release_dist),
            "RELEASE_VERSION": "1.2.3",
            "REMOTE_TAG_OBJECT": tag_object,
        }
        result = _run(
            ["bash", "-euo", "pipefail", "-c", program],
            cwd=root,
            env=env,
        )
        if result.returncode != 0:
            problems.append(
                "publish shell rejected exact five-asset fixture: "
                + (result.stderr.strip() or "unknown error")
            )
            return

        invocations = [
            json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()
        ]
        api_calls = [args for args in invocations if args[:1] == ["api"]]
        create_calls = [
            args for args in invocations if args[:2] == ["release", "create"]
        ]
        if len(api_calls) != 1:
            problems.append("publish shell must revalidate the remote tag exactly once")
        if len(create_calls) != 1:
            problems.append("publish shell must invoke gh release create exactly once")
        else:
            expected_create = [
                "release",
                "create",
                "1.2.3",
                "--verify-tag",
                "--title",
                "1.2.3",
                "--notes-file",
                str(notes),
                *(str(path) for path in expected_assets),
            ]
            if create_calls[0] != expected_create:
                problems.append(
                    "publish shell arguments are not the exact five-asset closure"
                )
        if notes.read_text(encoding="utf-8") != "\nrelease body\n":
            problems.append("publish shell generated incorrect changelog release notes")

        calls.write_text("", encoding="utf-8")
        mismatch = _run(
            ["bash", "-euo", "pipefail", "-c", program],
            cwd=root,
            env=env | {"REMOTE_TAG_OBJECT": "0" * 40},
        )
        _expect_failure(problems, "publish/remote-tag-object-mismatch", mismatch)
        mismatch_calls = [
            json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()
        ]
        if any(args[:2] == ["release", "create"] for args in mismatch_calls):
            problems.append(
                "publish shell created a release after remote tag divergence"
            )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _check_asset_program(
    program: str, problems: list[str], *, expected_slsa: int | None
) -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-release-assets-") as raw_root:
        root = Path(raw_root)
        _init_repo(root)
        (root / "source.txt").write_text("source\n", encoding="utf-8")
        _commit_all(root)
        _tag(root)
        release_dist = root / "release-dist"
        release_dist.mkdir()
        archive_name = "fixture-1.2.3.tar.gz"
        (release_dist / archive_name).write_bytes(b"archive")
        (release_dist / "sbom.spdx.json").write_text("{}\n", encoding="utf-8")
        (release_dist / "release-notes.md").write_text(
            "canonical notes\n", encoding="utf-8"
        )
        env = {
            "RELEASE_VERSION": "1.2.3",
            "PACKAGE_NAME": "fixture",
            "RELEASE_DIST": str(release_dist),
        }
        result = _run_python(program, cwd=root, env=env)
        if result.returncode != 0:
            problems.append(
                "release asset finalizer rejected the exact initial set: "
                + (result.stderr.strip() or "unknown error")
            )
            return

        final_names = {path.name for path in release_dist.iterdir()}
        expected_names = EXPECTED_STATIC_ASSETS | {archive_name}
        if final_names != expected_names:
            problems.append("release finalizer did not produce exactly five assets")
        manifest = json.loads(
            (release_dist / "release-manifest.json").read_text(encoding="utf-8")
        )
        if manifest.get("required_artifacts") != [
            archive_name,
            "sbom.spdx.json",
            "release-notes.md",
            "release-manifest.json",
            "SHA256SUMS",
        ]:
            problems.append("release manifest does not declare the exact asset closure")
        if manifest.get("slsa_build_level", "absent") != expected_slsa:
            problems.append(
                "release manifest slsa_build_level does not match the variant "
                f"contract (expected {expected_slsa!r})"
            )
        source_commit = _run(["git", "rev-parse", "HEAD"], cwd=root).stdout.strip()
        source_tag_object = _run(
            ["git", "rev-parse", "refs/tags/1.2.3"], cwd=root
        ).stdout.strip()
        if manifest.get("source_commit") != source_commit:
            problems.append("release manifest omits the exact peeled source commit")
        if manifest.get("source_tag_object") != source_tag_object:
            problems.append("release manifest omits the exact source tag object")
        checksums = {}
        for line in (
            (release_dist / "SHA256SUMS").read_text(encoding="ascii").splitlines()
        ):
            digest, name = line.split("  ", maxsplit=1)
            checksums[name] = digest
        expected_checksums = {
            name: _sha256(release_dist / name)
            for name in (
                archive_name,
                "sbom.spdx.json",
                "release-notes.md",
                "release-manifest.json",
            )
        }
        if checksums != expected_checksums:
            problems.append("SHA256SUMS does not cover the exact non-checksum assets")

        extra_dist = root / "release-dist-extra"
        extra_dist.mkdir()
        (extra_dist / archive_name).write_bytes(b"archive")
        (extra_dist / "sbom.spdx.json").write_text("{}\n", encoding="utf-8")
        (extra_dist / "release-notes.md").write_text("notes\n", encoding="utf-8")
        (extra_dist / "undeclared.txt").write_text("must fail\n", encoding="utf-8")
        _expect_failure(
            problems,
            "asset-closure/unexpected-file",
            _run_python(
                program,
                cwd=root,
                env=env | {"RELEASE_DIST": str(extra_dist)},
            ),
        )

        missing_notes_dist = root / "release-dist-missing-notes"
        missing_notes_dist.mkdir()
        (missing_notes_dist / archive_name).write_bytes(b"archive")
        (missing_notes_dist / "sbom.spdx.json").write_text("{}\n", encoding="utf-8")
        _expect_failure(
            problems,
            "asset-closure/missing-release-notes",
            _run_python(
                program,
                cwd=root,
                env=env | {"RELEASE_DIST": str(missing_notes_dist)},
            ),
        )


def check() -> list[str]:
    problems: list[str] = []
    reusable = load_yaml(REUSABLE)
    free = load_yaml(FREE)
    self_release = load_yaml(SELF_RELEASE)
    reusable_text = REUSABLE.read_text(encoding="utf-8")
    free_text = FREE.read_text(encoding="utf-8")
    self_text = SELF_RELEASE.read_text(encoding="utf-8")

    for name, text in (
        (REUSABLE.name, reusable_text),
        (FREE.name, free_text),
        (SELF_RELEASE.name, self_text),
    ):
        for line_number, line in enumerate(text.splitlines(), start=1):
            if "python3" in line and re.search(r"\bpython3\s+(?!-I\b)", line):
                problems.append(
                    f"{name}:{line_number}: embedded Python must use isolated mode (-I)"
                )

    checkout = _step(reusable, "release", "Checkout")
    checkout_with = checkout.get("with", {}) if isinstance(checkout, dict) else {}
    if not isinstance(checkout_with, dict) or checkout_with.get("ref") != (
        "refs/tags/${{ inputs.version }}"
    ):
        problems.append("release-supply-chain.yml: checkout must pin the requested tag")
    if (
        isinstance(checkout_with, dict)
        and checkout_with.get("persist-credentials") is not False
    ):
        problems.append(
            "release-supply-chain.yml: checkout must not persist credentials"
        )

    release_steps = _steps(reusable, "release")
    step_names = [step.get("name") for step in release_steps]
    expected_step_names = [
        "Validate release inputs before checkout",
        "Checkout",
        "Validate checked-out release contract",
        "Preflight — refuse to modify an existing (immutable) release",
        "Build deterministic tracked-source archive",
        "Verify extracted archive payload",
        "Generate SPDX SBOM from exact archive payload (Syft)",
        "Prepare canonical release notes",
        "Finalize manifest, checksums, and asset closure",
        "Attest build provenance (archive)",
        "Attest SBOM (archive)",
        "Upload workflow artifact",
        "Publish immutable GitHub Release (single create)",
    ]
    if step_names != expected_step_names:
        problems.append("release workflow step order differs from the closed contract")

    if "sbom_source_path" in reusable_text:
        problems.append("removed sbom_source_path input must not reappear")
    for forbidden in (
        "anchore/sbom-action@",
        "raw.githubusercontent.com/anchore/syft",
        "install.sh",
    ):
        if forbidden in reusable_text:
            problems.append(
                f"release workflow contains forbidden Syft bootstrap: {forbidden}"
            )

    syft = _step(
        reusable, "release", "Generate SPDX SBOM from exact archive payload (Syft)"
    )
    syft_run = syft.get("run", "") if isinstance(syft, dict) else ""
    syft_env = syft.get("env", {}) if isinstance(syft, dict) else {}
    if not isinstance(syft_run, str) or not isinstance(syft_env, dict):
        problems.append("release Syft pinned-binary step is missing")
        syft_run = ""
        syft_env = {}
    for token in (
        "curl --disable --fail --show-error --silent --location",
        "--proto '=https' --proto-redir '=https' --tlsv1.2",
        '--max-filesize "$expected_size"',
        "version -o json",
        '--source-name "$PACKAGE_NAME"',
        '--source-version "$RELEASE_VERSION"',
        '--output "spdx-json=$sbom_temporary"',
        'mv -- "$sbom_temporary" "$RELEASE_DIST/sbom.spdx.json"',
    ):
        if token not in syft_run:
            problems.append(f"release Syft step lost required token: {token}")

    self_jobs = self_release.get("jobs", {})
    self_publish = self_jobs.get("publish", {}) if isinstance(self_jobs, dict) else {}
    self_with = self_publish.get("with", {}) if isinstance(self_publish, dict) else {}
    self_archive_paths = (
        self_with.get("archive_paths", "") if isinstance(self_with, dict) else ""
    )
    expected_self_roots = {
        "README.md",
        "LICENSE",
        "NOTICE",
        "SECURITY.md",
        "SUPPORT.md",
        "CODE_OF_CONDUCT.md",
        "CONTRIBUTING.md",
        "AGENTS.md",
        "VERSION",
        "CHANGELOG.md",
        ".gitignore",
        ".github",
        ".claude",
        "catalog",
        "docs",
        "examples",
        "scripts",
        "requirements-ci.in",
        "requirements-ci.txt",
    }
    try:
        actual_self_roots = set(shlex.split(self_archive_paths))
    except (TypeError, ValueError):
        actual_self_roots = set()
    if actual_self_roots != expected_self_roots:
        problems.append("self release archive must select the complete library surface")

    build = _step(reusable, "release", "Build deterministic tracked-source archive")
    build_run = build.get("run", "") if isinstance(build, dict) else ""
    required_archive_tokens = (
        '"--literal-pathspecs",',
        '"ls-files",',
        '"--cached",',
        '"-z",',
        "--null --verbatim-files-from",
        '--files-from="$archive_file_list"',
        "--no-recursion",
    )
    if not isinstance(build_run, str):
        problems.append("release archive build step is missing")
    else:
        for token in required_archive_tokens:
            if token not in build_run:
                problems.append(f"release archive build lost safety token: {token}")

    payload = _step(reusable, "release", "Verify extracted archive payload")
    payload_run = payload.get("run", "") if isinstance(payload, dict) else ""
    if not isinstance(payload_run, str):
        problems.append("release extracted-payload verification step is missing")

    archive_subject = (
        "${{ runner.temp }}/release-dist/"
        "${{ inputs.package_name }}-${{ inputs.version }}.tar.gz"
    )
    provenance = _step(reusable, "release", "Attest build provenance (archive)")
    provenance_with = provenance.get("with", {}) if isinstance(provenance, dict) else {}
    if (
        not isinstance(provenance_with, dict)
        or provenance_with.get("subject-path") != archive_subject
    ):
        problems.append("build provenance must attest the exact release archive")
    sbom_attestation = _step(reusable, "release", "Attest SBOM (archive)")
    sbom_attestation_with = (
        sbom_attestation.get("with", {}) if isinstance(sbom_attestation, dict) else {}
    )
    if (
        not isinstance(sbom_attestation_with, dict)
        or sbom_attestation_with.get("subject-path") != archive_subject
    ):
        problems.append("SBOM attestation must bind the exact release archive")
    if (
        isinstance(sbom_attestation_with, dict)
        and sbom_attestation_with.get("sbom-path")
        != "${{ runner.temp }}/release-dist/sbom.spdx.json"
    ):
        problems.append("SBOM attestation must use the closed SPDX asset")

    upload = _step(reusable, "release", "Upload workflow artifact")
    upload_with = upload.get("with", {}) if isinstance(upload, dict) else {}
    if not isinstance(upload_with, dict) or upload_with.get("path") != (
        "${{ runner.temp }}/release-dist"
    ):
        problems.append(
            "workflow artifact must upload only the closed release directory"
        )
    if (
        isinstance(upload_with, dict)
        and upload_with.get("if-no-files-found") != "error"
    ):
        problems.append(
            "workflow artifact upload must fail when release assets are absent"
        )

    publish = _step(
        reusable, "release", "Publish immutable GitHub Release (single create)"
    )
    publish_run = publish.get("run", "") if isinstance(publish, dict) else ""
    if not isinstance(publish_run, str):
        problems.append("release publish step is missing")
    else:
        if "dist/*" in publish_run:
            problems.append("release publishing must not use an open-ended asset glob")
        if '--notes-file "$RELEASE_DIST/release-notes.md"' not in publish_run:
            problems.append(
                "GitHub Release body must use the canonical release-notes asset"
            )
        for asset in (
            "${PACKAGE_NAME}-${RELEASE_VERSION}.tar.gz",
            "sbom.spdx.json",
            "release-notes.md",
            "release-manifest.json",
            "SHA256SUMS",
        ):
            if asset not in publish_run:
                problems.append(f"release publish asset closure omits {asset}")
        if publish_run.count('gh "${release_args[@]}"') != 1:
            problems.append(
                "release publish shell must have exactly one gh create dispatch"
            )
        for token in (
            "gh api --method GET",
            'git rev-parse --verify "refs/tags/${RELEASE_VERSION}"',
            'if [ "$remote_tag_object" != "$local_tag_object" ]',
        ):
            if token not in publish_run:
                problems.append(f"release publish lost remote tag guard: {token}")

    if "step-security/harden-runner@" in reusable_text:
        problems.append("cross-tier release workflow must remain free of Harden-Runner")
    if reusable_text.count('release_dist / "release-notes.md"') != 1:
        problems.append(
            "canonical release notes must be materialized once in release-dist"
        )

    # ---- private-free variant: plan-eligible contract without attestations ----

    expected_free_step_names = [
        name for name in expected_step_names if name not in ATTEST_STEP_NAMES
    ]
    free_step_names = [step.get("name") for step in _steps(free, "release")]
    if free_step_names != expected_free_step_names:
        problems.append(
            "free release workflow step order must equal the attested contract "
            "minus the two attestation steps"
        )

    for forbidden in (
        "actions/attest",
        "step-security/harden-runner@",
        "sbom_source_path",
        "raw.githubusercontent.com/anchore/syft",
        "install.sh",
    ):
        if forbidden in free_text:
            problems.append(f"free release workflow must not contain: {forbidden}")

    free_jobs = free.get("jobs", {})
    free_job = free_jobs.get("release", {}) if isinstance(free_jobs, dict) else {}
    free_permissions = free_job.get("permissions") if isinstance(free_job, dict) else None
    if free_permissions != {"contents": "write"}:
        problems.append(
            "free release job must request exactly `contents: write` — GitHub "
            "attestation permissions are unavailable on private Free/Pro/Team plans"
        )

    attested_jobs = reusable.get("jobs", {})
    attested_job = (
        attested_jobs.get("release", {}) if isinstance(attested_jobs, dict) else {}
    )
    attested_permissions = (
        attested_job.get("permissions") if isinstance(attested_job, dict) else None
    )
    if attested_permissions != {
        "contents": "write",
        "id-token": "write",
        "attestations": "write",
    }:
        problems.append(
            "attested release job must request exactly contents/id-token/"
            "attestations write"
        )

    # Byte-level step parity: the free pipeline must be the attested pipeline
    # minus attestations, so the two variants cannot silently drift apart.
    slsa_attested = '"slsa_build_level": 3,'
    slsa_free = '"slsa_build_level": None,'
    for name in expected_free_step_names:
        attested_step = _step(reusable, "release", name)
        free_step = _step(free, "release", name)
        if attested_step is None or free_step is None:
            problems.append(f"release variant step missing for parity check: {name}")
            continue
        if name == "Finalize manifest, checksums, and asset closure":
            attested_run = attested_step.get("run")
            free_run = free_step.get("run")
            if (
                not isinstance(attested_run, str)
                or not isinstance(free_run, str)
                or slsa_attested not in attested_run
                or slsa_free not in free_run
                or free_run != attested_run.replace(slsa_attested, slsa_free)
            ):
                problems.append(
                    "free asset finalizer must equal the attested one except "
                    "for `slsa_build_level: None`"
                )
            attested_rest = {k: v for k, v in attested_step.items() if k != "run"}
            free_rest = {k: v for k, v in free_step.items() if k != "run"}
            if attested_rest != free_rest:
                problems.append(
                    "free asset finalizer step metadata drifted from the "
                    "attested variant"
                )
            continue
        if attested_step != free_step:
            problems.append(
                f"free release step drifted from the attested variant: {name}"
            )

    try:
        input_program = _embedded_python(
            _step(reusable, "release", "Validate release inputs before checkout")
        )
        checked_out_program = _embedded_python(
            _step(reusable, "release", "Validate checked-out release contract")
        )
        archive_program = _embedded_python(build)
        payload_program = _embedded_python(payload)
        asset_program = _embedded_python(
            _step(
                reusable, "release", "Finalize manifest, checksums, and asset closure"
            )
        )
        free_asset_program = _embedded_python(
            _step(free, "release", "Finalize manifest, checksums, and asset closure")
        )
        self_version = _embedded_python(
            _step(self_release, "resolve", "Resolve and validate version")
        )
        notes_program = _embedded_python(
            _step(reusable, "release", "Prepare canonical release notes")
        )
    except ValueError as exc:
        problems.append(f"release embedded-program extraction failed: {exc}")
        return problems

    _check_archive_program(archive_program, problems)
    _check_payload_program(payload_program, problems)
    _check_version_programs(input_program, checked_out_program, self_version, problems)
    _check_syft_program(syft_run, syft_env, problems)
    _check_notes_program(notes_program, problems)
    _check_publish_program(publish_run, problems)
    _check_asset_program(asset_program, problems, expected_slsa=3)
    _check_asset_program(free_asset_program, problems, expected_slsa=None)
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("check_release_supply_chain: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("check_release_supply_chain: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
