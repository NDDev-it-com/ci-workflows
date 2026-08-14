#!/usr/bin/env python3
"""Regenerate Android fixture locks and verification closure from exact build."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from ci_workflows_tools._gradle_lockfile import GradleLockfileError, parse_gradle_95_lockfile
from ci_workflows_tools._sdk_environment import (
    EVIDENCE_NAME,
    JvmIdentity,
    derive_android_environment,
    validate_jvm_identity,
)
from ci_workflows_tools.check_python_execution_contract import clean_environment

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "tests" / "fixtures" / "android"
METADATA = Path("gradle/verification-metadata.xml")
RECEIPT = Path("gradle/provenance-manifest.json")
WRAPPER_SHA256 = "497c8c2a7e5031f6aa847f88104aa80a93532ec32ee17bdb8d1d2f67a194a9c7"
DIST_SHA256 = "553c78f50dafcd54d65b9a444649057857469edf836431389695608536d6b746"
GENERATION_ARGS = [
    "./gradlew", "build",
    "--write-verification-metadata", "sha256",
    "--write-locks",
    "--dependency-verification", "strict",
    "--no-build-cache",
    "--no-configuration-cache",
    "--console", "plain",
]
STRICT_ARGS = [
    "./gradlew", "build",
    "--dependency-verification", "strict",
    "--no-build-cache",
    "--no-configuration-cache",
    "--console", "plain",
]
IGNORED = {".gradle", "build", ".DS_Store"}
NS = {"v": "https://schema.gradle.org/dependency-verification"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ignore(_: str, names: list[str]) -> set[str]:
    return {name for name in names if name in IGNORED}


def _copy_pristine(destination: Path) -> None:
    shutil.copytree(SOURCE, destination, symlinks=False, ignore=_ignore)
    for path in [destination / METADATA, destination / RECEIPT, *destination.rglob("*.lockfile")]:
        if path.exists():
            path.unlink()


def _environment(home: Path) -> dict[str, str]:
    clean = clean_environment({"CI": "true", "GRADLE_USER_HOME": str(home)})
    java = shutil.which("java", path=clean.get("PATH"))
    sdkmanager = shutil.which("sdkmanager", path=clean.get("PATH"))
    if not java or not sdkmanager:
        raise RuntimeError("clean PATH must resolve java and sdkmanager")
    properties = _java_properties(Path(java), clean)
    return derive_android_environment(
        clean, os.environ, java_executable=Path(java), java_properties=properties,
        sdkmanager_executable=Path(sdkmanager), java_major="21",
        compile_sdk="37", build_tools="36.0.0",
    )


def _java_properties(executable: Path, environment: dict[str, str]) -> dict[str, str]:
    output = subprocess.run(
        [str(executable), "-XshowSettings:properties", "-version"],
        env=environment, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=True,
    ).stdout
    return dict(re.findall(
        r"^\s+(java\.(?:home|runtime\.version|vendor|version|vm\.name)) = (.+)$",
        output, re.MULTILINE,
    ))


def _run(args: list[str], cwd: Path, home: Path) -> str:
    result = subprocess.run(
        args, cwd=cwd, env=_environment(home), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(args)}")
    return result.stdout


def _wrapper_contract(root: Path) -> None:
    jar = root / "gradle/wrapper/gradle-wrapper.jar"
    properties = (root / "gradle/wrapper/gradle-wrapper.properties").read_text(
        encoding="utf-8"
    )
    if sha256(jar) != WRAPPER_SHA256:
        raise RuntimeError("Gradle wrapper JAR checksum mismatch")
    if "gradle-9.5.0-bin.zip" not in properties:
        raise RuntimeError("Gradle wrapper does not select exact 9.5.0 binary distribution")
    if f"distributionSha256Sum={DIST_SHA256}" not in properties:
        raise RuntimeError("Gradle distribution checksum mismatch")


def _artifacts(metadata: Path) -> list[dict[str, str]]:
    root = ET.parse(metadata).getroot()
    configuration = root.find("v:configuration", NS)
    if configuration is None \
            or configuration.findtext("v:verify-metadata", namespaces=NS) != "true" \
            or configuration.findtext("v:verify-signatures", namespaces=NS) != "false":
        raise RuntimeError("verification metadata must verify metadata with SHA-256")
    if configuration.find("v:trusted-artifacts", NS) is not None:
        raise RuntimeError("verification metadata may not trust wildcard artifacts")
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    components = root.find("v:components", NS)
    if components is None:
        raise RuntimeError("verification metadata has no components")
    for component in components.findall("v:component", NS):
        group = component.attrib.get("group", "")
        name = component.attrib.get("name", "")
        version = component.attrib.get("version", "")
        for artifact in component.findall("v:artifact", NS):
            filename = artifact.attrib.get("name", "")
            key = (group, name, version, filename)
            hashes = artifact.findall("v:sha256", NS)
            if not all(key) or key in seen or len(hashes) != 1:
                raise RuntimeError(f"invalid/duplicate verification artifact: {key}")
            digest = hashes[0].attrib.get("value", "")
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise RuntimeError(f"invalid SHA-256 for verification artifact: {key}")
            if any(child.tag != f"{{{NS['v']}}}sha256" for child in artifact):
                raise RuntimeError(f"non-SHA256 verification method for artifact: {key}")
            seen.add(key)
            rows.append({
                "artifact": filename, "group": group, "name": name,
                "sha256": digest, "version": version,
            })
    rows.sort(key=lambda row: (
        row["group"], row["name"], row["version"], row["artifact"]
    ))
    if not rows:
        raise RuntimeError("verification artifact closure is empty")
    return rows


def _lock_receipts(root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(root.rglob("*.lockfile")):
        relative = path.relative_to(root).as_posix()
        try:
            parsed = parse_gradle_95_lockfile(path, source=relative)
        except GradleLockfileError as exc:
            raise RuntimeError(str(exc)) from exc
        rows.append({
            "entries": list(parsed.entries),
            "path": relative,
            "resolved_configurations": list(parsed.resolved_configurations),
            "sha256": sha256(path),
        })
    if not rows or not any(row["path"] == "app/gradle.lockfile" for row in rows):
        raise RuntimeError("exact build did not create the Android app lockfile")
    return rows


def _task_graph(output: str) -> list[str]:
    tasks: list[str] = []
    for line in output.splitlines():
        match = re.match(r"> Task (:[^ ]+)", line)
        if match and match.group(1) not in tasks:
            tasks.append(match.group(1))
    required = {":app:assembleDebug", ":app:testDebugUnitTest", ":app:lintDebug", ":app:build"}
    missing = sorted(required - set(tasks))
    if missing:
        raise RuntimeError(f"exact build task graph is incomplete: missing {missing}")
    return tasks


def _java_identity(executable: Path | str, home: Path) -> dict[str, str]:
    environment = _environment(home)
    resolved = shutil.which(str(executable), path=environment.get("PATH")) \
        if not Path(executable).is_absolute() else str(executable)
    if not resolved:
        raise RuntimeError(f"cannot resolve Java executable {executable}")
    properties = _java_properties(Path(resolved), environment)
    required = {"java.home", "java.runtime.version", "java.vendor", "java.version", "java.vm.name"}
    if set(properties) != required:
        raise RuntimeError(f"cannot parse complete Java identity: {sorted(properties)}")
    return properties


def _versions(root: Path, home: Path) -> dict[str, str]:
    gradle = _run(["./gradlew", "--version", "--console", "plain"], root, home)
    gradle_match = re.search(r"^Gradle (\S+)$", gradle, re.MULTILINE)
    launcher_match = re.search(r"^Launcher JVM:\s+(.+)$", gradle, re.MULTILINE)
    daemon_match = re.search(r"^Daemon JVM:\s+(.+)$", gradle, re.MULTILINE)
    if not launcher_match or not daemon_match:
        raise RuntimeError("Gradle --version omitted launcher or daemon JVM identity")
    gradle_version = gradle_match.group(1) if gradle_match else ""
    launcher_raw = launcher_match.group(1).strip()
    daemon_raw = daemon_match.group(1).strip()
    daemon_home = daemon_raw.split(" (", 1)[0]
    java = _java_identity("java", home)
    daemon = _java_identity(Path(daemon_home) / "bin/java", home)
    launcher_identity = re.fullmatch(r"(\S+) \((.+)\)", launcher_raw)
    if not launcher_identity:
        raise RuntimeError("Gradle launcher JVM identity is unparseable")
    launcher_version, launcher_details = launcher_identity.groups()
    if gradle_version != "9.5.0" or not java["java.version"].startswith("21."):
        raise RuntimeError(
            f"generator requires Gradle 9.5.0 and JDK 21, got "
            f"{gradle_version}/{java['java.version']}"
        )
    launcher_vendor = launcher_details.removesuffix(" " + java["java.runtime.version"])
    validate_jvm_identity(JvmIdentity(
        requested_major="21", java_home=java["java.home"],
        java_version=java["java.version"], java_runtime_version=java["java.runtime.version"],
        java_vendor=java["java.vendor"], java_vm_name=java["java.vm.name"],
        launcher_version=launcher_version,
        launcher_runtime_version=java["java.runtime.version"],
        launcher_vendor=launcher_vendor, launcher_vm_name=java["java.vm.name"],
        daemon_home=daemon["java.home"], daemon_version=daemon["java.version"],
        daemon_runtime_version=daemon["java.runtime.version"],
        daemon_vendor=daemon["java.vendor"], daemon_vm_name=daemon["java.vm.name"],
    ))
    return {
        "gradle_daemon_jvm_resolved": daemon_raw,
        "gradle_daemon_jvm_home_resolved": daemon["java.home"],
        "gradle_daemon_jvm_runtime_version_resolved": daemon["java.runtime.version"],
        "gradle_daemon_jvm_vendor_resolved": daemon["java.vendor"],
        "gradle_daemon_jvm_version_resolved": daemon["java.version"],
        "gradle_daemon_jvm_vm_name_resolved": daemon["java.vm.name"],
        "gradle_launcher_jvm_resolved": launcher_raw,
        "gradle_launcher_jvm_runtime_version_resolved": java["java.runtime.version"],
        "gradle_launcher_jvm_vendor_resolved": launcher_vendor,
        "gradle_launcher_jvm_version_resolved": launcher_version,
        "gradle_launcher_jvm_vm_name_resolved": java["java.vm.name"],
        "gradle_version": gradle_version,
        "java_runtime_version_resolved": java["java.runtime.version"],
        "java_home_resolved": java["java.home"],
        "java_vendor_resolved": java["java.vendor"],
        "java_version_input": "21",
        "java_version_resolved": java["java.version"],
        "java_vm_name_resolved": java["java.vm.name"],
        "sdk_environment": json.loads(_environment(home)[EVIDENCE_NAME]),
    }


def _receipt(root: Path, output: str, identities: dict[str, str]) -> bytes:
    metadata = root / METADATA
    artifacts = _artifacts(metadata)
    locks = _lock_receipts(root)
    configurations = sorted({
        configuration
        for lock in locks
        for configuration in lock["resolved_configurations"]
    })
    payload = {
        "artifacts": artifacts,
        "default_command": "./gradlew build",
        "distribution_sha256": DIST_SHA256,
        "generation_arguments": GENERATION_ARGS,
        **identities,
        "locks": locks,
        "resolution_scope": "fresh exact build plus Gradle verification bootstrap resolvable configurations",
        "resolved_locked_configurations": configurations,
        "schema_version": 1,
        "task_graph": _task_graph(output),
        "verification_metadata_sha256": sha256(metadata),
        "wrapper_jar_sha256": WRAPPER_SHA256,
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def generate() -> tuple[dict[Path, bytes], str]:
    with tempfile.TemporaryDirectory(prefix="ci-workflows-android-provenance-") as temp:
        temp_root = Path(temp)
        first = temp_root / "generate" / "android"
        first.parent.mkdir()
        _copy_pristine(first)
        _wrapper_contract(first)
        first_home = temp_root / "gradle-home-generate"
        identities = _versions(first, first_home)
        output = _run(GENERATION_ARGS, first, first_home)
        receipt = _receipt(first, output, identities)

        generated = {
            METADATA: (first / METADATA).read_bytes(),
            RECEIPT: receipt,
        }
        for lock in sorted(first.rglob("*.lockfile")):
            generated[lock.relative_to(first)] = lock.read_bytes()

        second = temp_root / "verify" / "android"
        second.parent.mkdir()
        _copy_pristine(second)
        for relative, raw in generated.items():
            target = second / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        _wrapper_contract(second)
        strict_output = _run(STRICT_ARGS, second, temp_root / "gradle-home-verify")
        if "BUILD SUCCESSFUL" not in strict_output:
            raise RuntimeError("strict fresh-home default build did not report success")
        return generated, output


def _current_generated() -> dict[Path, bytes]:
    paths = [METADATA, RECEIPT, *sorted(
        path.relative_to(SOURCE) for path in SOURCE.rglob("*.lockfile")
    )]
    return {relative: (SOURCE / relative).read_bytes() for relative in paths if (SOURCE / relative).is_file()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        generated, output = generate()
    except (OSError, RuntimeError, subprocess.SubprocessError, ET.ParseError) as exc:
        print(f"android-provenance: {exc}", file=sys.stderr)
        return 1
    if args.check:
        current = _current_generated()
        if current != generated:
            missing = sorted(str(path) for path in generated.keys() - current.keys())
            extra = sorted(str(path) for path in current.keys() - generated.keys())
            changed = sorted(
                str(path) for path in generated.keys() & current.keys()
                if generated[path] != current[path]
            )
            print(
                f"android-provenance: generated drift: missing={missing} "
                f"extra={extra} changed={changed}", file=sys.stderr,
            )
            return 1
        print("android-provenance: reproducible exact-build closure OK")
        return 0
    current = _current_generated()
    for stale in current.keys() - generated.keys():
        (SOURCE / stale).unlink()
    for relative, raw in generated.items():
        target = SOURCE / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    print("android-provenance: wrote exact-build metadata, locks, and receipt")
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
