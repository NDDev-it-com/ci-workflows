#!/usr/bin/env python3
"""Validate bounded SDK fixtures, byte provenance, callers, and runtime receipts."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from typing import Any

from _strict_yaml import strict_load
from _gradle_lockfile import (
    GradleLockfileError,
    parse_gradle_95_lockfile,
    parse_gradle_95_lockfile_bytes,
)
from _workflow_yaml import get_on, load_yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO_ROOT / "tests" / "fixtures" / "sdk-runtime-spec.yml"
IGNORED_DIRS = {".dart_tool", ".gradle", "build"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VERIFY_NS = {"v": "https://schema.gradle.org/dependency-verification"}
ANDROID_GENERATION_ARGUMENTS = [
    "./gradlew", "build",
    "--write-verification-metadata", "sha256",
    "--write-locks",
    "--dependency-verification", "strict",
    "--no-build-cache",
    "--no-configuration-cache",
    "--console", "plain",
]
JAVA_EVIDENCE_FIELDS = (
    "java_version_input", "java_version_resolved",
    "java_runtime_version_resolved", "java_vendor_resolved",
    "java_vm_name_resolved", "gradle_launcher_jvm_resolved",
    "gradle_launcher_jvm_version_resolved",
    "gradle_launcher_jvm_runtime_version_resolved",
    "gradle_launcher_jvm_vendor_resolved",
    "gradle_launcher_jvm_vm_name_resolved", "gradle_daemon_jvm_resolved",
    "gradle_daemon_jvm_version_resolved",
    "gradle_daemon_jvm_runtime_version_resolved",
    "gradle_daemon_jvm_vendor_resolved",
    "gradle_daemon_jvm_vm_name_resolved",
)


def _java_identity_problems(receipt: dict[str, Any], context: str) -> list[str]:
    problems: list[str] = []
    if any(not isinstance(receipt.get(field), str) or not receipt[field] for field in JAVA_EVIDENCE_FIELDS):
        return [f"{context}: complete observed Java/Gradle JVM identity is required"]
    requested = receipt["java_version_input"]
    resolved = receipt["java_version_resolved"]
    if requested != "21" or not re.fullmatch(r"21(?:[.][0-9A-Za-z+_-]+)+", resolved):
        problems.append(f"{context}: requested JDK 21 is not backed by an exact observed runtime")
    for role in ("gradle_launcher", "gradle_daemon"):
        if receipt[f"{role}_jvm_version_resolved"] != resolved \
                or receipt[f"{role}_jvm_runtime_version_resolved"] != receipt["java_runtime_version_resolved"] \
                or receipt[f"{role}_jvm_vendor_resolved"] != receipt["java_vendor_resolved"] \
                or receipt[f"{role}_jvm_vm_name_resolved"] != receipt["java_vm_name_resolved"]:
            problems.append(f"{context}: {role} JVM diverges from observed build Java")
    expected_launcher = (
        f'{resolved} ({receipt["java_vendor_resolved"]} '
        f'{receipt["java_runtime_version_resolved"]})'
    )
    if receipt["gradle_launcher_jvm_resolved"] != expected_launcher \
            or " (" not in receipt["gradle_daemon_jvm_resolved"]:
        problems.append(f"{context}: raw Gradle launcher/daemon identities are unparseable")
    return problems


def _canonical_manifest(spec: dict[str, Any], root: Path) -> tuple[bytes, list[str]]:
    """Independently recompute bytes; do not share generator implementation."""
    problems: list[str] = []
    rows: list[dict[str, object]] = []
    seen_paths: set[str] = set()
    seen_digests: set[str] = set()
    fixtures = spec.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        return b"", ["spec.fixtures must be a non-empty list"]
    for fixture in fixtures:
        fixture_id = fixture.get("id") if isinstance(fixture, dict) else None
        entries = fixture.get("source_files") if isinstance(fixture, dict) else None
        if not isinstance(fixture_id, str) or not isinstance(entries, list) or not entries:
            problems.append(f"invalid fixture row: {fixture!r}")
            continue
        paths = [entry.get("path") for entry in entries if isinstance(entry, dict)]
        if len(paths) != len(entries) or paths != sorted(paths):
            problems.append(f"{fixture_id}: source_files must be non-empty lexical mappings")
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            relative = entry.get("path")
            kind = entry.get("kind")
            if not isinstance(relative, str) or not isinstance(kind, str):
                problems.append(f"{fixture_id}: invalid source entry {entry!r}")
                continue
            pure = PurePosixPath(relative)
            if pure.is_absolute() or ".." in pure.parts or str(pure) != relative:
                problems.append(f"{fixture_id}: non-canonical source path {relative!r}")
                continue
            if relative in seen_paths:
                problems.append(f"duplicate source path {relative}")
                continue
            seen_paths.add(relative)
            path = root / relative
            if path.is_symlink() or not path.is_file():
                problems.append(f"missing/unsafe source file {relative}")
                continue
            raw = path.read_bytes()
            if kind == "text":
                if raw.startswith(b"\xef\xbb\xbf"):
                    problems.append(f"{relative}: UTF-8 BOM is forbidden")
                try:
                    raw.decode("utf-8")
                except UnicodeDecodeError:
                    problems.append(f"{relative}: invalid UTF-8")
                if b"\r" in raw:
                    problems.append(f"{relative}: CR/CRLF is forbidden")
                if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
                    problems.append(f"{relative}: needs exactly one terminal LF")
            elif kind != "binary":
                problems.append(f"{relative}: unknown kind {kind!r}")
            digest = hashlib.new("sha256", raw).hexdigest()
            if digest in seen_digests:
                problems.append(f"duplicate source digest {digest} at {relative}")
            seen_digests.add(digest)
            rows.append({
                "fixture": fixture_id,
                "kind": kind,
                "path": relative,
                "sha256": digest,
                "size": len(raw),
            })
    expected_files: set[str] = set()
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            continue
        directory = fixture.get("working_directory")
        if not isinstance(directory, str):
            continue
        base = root / directory
        if not base.is_dir():
            problems.append(f"fixture directory missing: {directory}")
            continue
        for path in base.rglob("*"):
            if any(part in IGNORED_DIRS for part in path.relative_to(base).parts):
                continue
            if path.is_symlink():
                problems.append(f"fixture symlink forbidden: {path.relative_to(root)}")
            elif path.is_file():
                expected_files.add(path.relative_to(root).as_posix())
    undeclared = sorted(expected_files - seen_paths)
    unused = sorted(seen_paths - expected_files)
    if undeclared:
        problems.append(f"undeclared fixture sources: {undeclared}")
    if unused:
        problems.append(f"declared source outside fixture inventory: {unused}")
    payload = {
        "byte_contract": spec.get("byte_contract"),
        "fixtures": sorted(rows, key=lambda row: str(row["path"])),
        "schema_version": spec.get("schema_version"),
        "spec_sha256": hashlib.sha256((root / SPEC_PATH.relative_to(REPO_ROOT)).read_bytes()).hexdigest(),
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode(), problems


def _workflow_inputs(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    workflow = load_yaml(path)
    call = get_on(workflow).get("workflow_call", {})
    return call.get("inputs", {}), workflow


def _caller_problems(spec: dict[str, Any], caller: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    jobs = caller.get("jobs", {})
    expected = {
        "flutter": (
            "fixture-dart-flutter-ci", "observe-dart-flutter-ci",
            "./.github/workflows/dart-flutter-ci.yml",
            {"runner": "ubuntu-latest", "flutter_version": "3.47.0",
             "working_directory": "tests/fixtures/flutter"},
        ),
        "android": (
            "fixture-kotlin-android-ci", "observe-kotlin-android-ci",
            "./.github/workflows/kotlin-android-ci.yml",
            {"runner": "ubuntu-latest", "working_directory": "tests/fixtures/android"},
        ),
        "qt": (
            "fixture-qt-ci", "observe-qt-ci", "./.github/workflows/qt-ci.yml",
            {"runner": "ubuntu-latest", "qt_version": "6.8.4",
             "working_directory": "tests/fixtures/qt"},
        ),
    }
    for kind, (job_id, observer_id, reusable, inputs) in expected.items():
        job = jobs.get(job_id, {})
        if job.get("uses") != reusable or job.get("with") != inputs:
            problems.append(f"{kind}: fixture caller must use exact default-contract inputs")
        if "if" in job or job.get("permissions") != {"contents": "read"}:
            problems.append(f"{kind}: fixture caller may not be conditional or overprivileged")
        observer = jobs.get(observer_id, {})
        if observer.get("needs") != job_id or observer.get("if") != "always()":
            problems.append(f"{kind}: observer must run always after its exact caller")
        steps = observer.get("steps", [])
        runs = [step.get("run", "") for step in steps if isinstance(step, dict)]
        envs = [step.get("env", {}) for step in steps if isinstance(step, dict)]
        if not any(f"--receipt {kind}" in run and 'test "$CALLER_RESULT" = success' in run for run in runs):
            problems.append(f"{kind}: observer does not fail closed on caller/receipt")
        if not any("SDK_RUNTIME_EVIDENCE" in env for env in envs):
            problems.append(f"{kind}: observer is not wired to reusable output")
    evidence = jobs.get("evidence", {})
    needs = evidence.get("needs", [])
    for kind, (job_id, observer_id, _, _) in expected.items():
        if job_id not in needs or observer_id not in needs:
            problems.append(f"{kind}: evidence summary is missing caller/observer needs")
    render = next((
        step for step in evidence.get("steps", [])
        if isinstance(step, dict) and step.get("name") == "Render evidence for the runtime-coverage ledger"
    ), {})
    guards = str(render.get("env", {}).get("GUARDS", ""))
    for _, (job_id, observer_id, _, _) in expected.items():
        if job_id not in guards or observer_id not in guards:
            problems.append(f"{job_id}: evidence GUARDS binding missing")
    return problems


def _android_provenance_problems(android_root: Path) -> list[str]:
    """Independently validate Gradle's generated exact-build closure."""
    problems: list[str] = []
    metadata_path = android_root / "gradle/verification-metadata.xml"
    receipt_path = android_root / "gradle/provenance-manifest.json"
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"Android provenance receipt missing/invalid: {exc}"]
    if not isinstance(receipt, dict) or receipt.get("schema_version") != 1:
        return ["Android provenance receipt must use schema_version 1"]
    expected_identity = {
        "default_command": "./gradlew build",
        "generation_arguments": ANDROID_GENERATION_ARGUMENTS,
        "gradle_version": "9.5.0",
        "java_version_input": "21",
        "wrapper_jar_sha256": "497c8c2a7e5031f6aa847f88104aa80a93532ec32ee17bdb8d1d2f67a194a9c7",
        "distribution_sha256": "553c78f50dafcd54d65b9a444649057857469edf836431389695608536d6b746",
        "resolution_scope": "fresh exact build plus Gradle verification bootstrap resolvable configurations",
    }
    for key, expected in expected_identity.items():
        if receipt.get(key) != expected:
            problems.append(f"Android provenance {key} drifted from exact-build contract")
    problems += _java_identity_problems(receipt, "Android provenance")
    tasks = receipt.get("task_graph")
    if not isinstance(tasks, list) or len(tasks) != len(set(tasks)):
        problems.append("Android provenance task graph must be a unique ordered list")
    else:
        required = {":app:assembleDebug", ":app:testDebugUnitTest", ":app:lintDebug"}
        if not required.issubset(set(tasks)):
            problems.append("Android provenance task graph is narrower than default build")
    try:
        metadata_raw = metadata_path.read_bytes()
        xml = ET.fromstring(metadata_raw)
    except (OSError, ET.ParseError) as exc:
        return problems + [f"Android verification metadata missing/invalid: {exc}"]
    if receipt.get("verification_metadata_sha256") != hashlib.sha256(metadata_raw).hexdigest():
        problems.append("Android verification metadata digest/receipt mismatch")
    configuration = xml.find("v:configuration", VERIFY_NS)
    if configuration is None \
            or configuration.findtext("v:verify-metadata", namespaces=VERIFY_NS) != "true" \
            or configuration.findtext("v:verify-signatures", namespaces=VERIFY_NS) != "false":
        problems.append("Android verification must be strict SHA-256 metadata verification")
    elif any(configuration.find(f"v:{name}", VERIFY_NS) is not None for name in (
        "trusted-artifacts", "ignored-keys", "trusted-keys"
    )):
        problems.append("Android verification metadata contains a trust bypass")
    actual_artifacts: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    components = xml.find("v:components", VERIFY_NS)
    for component in components.findall("v:component", VERIFY_NS) if components is not None else []:
        identity = (
            component.attrib.get("group", ""), component.attrib.get("name", ""),
            component.attrib.get("version", ""),
        )
        for artifact in component.findall("v:artifact", VERIFY_NS):
            filename = artifact.attrib.get("name", "")
            key = (*identity, filename)
            hashes = artifact.findall("v:sha256", VERIFY_NS)
            digest = hashes[0].attrib.get("value", "") if len(hashes) == 1 else ""
            if not all(key) or key in seen or not SHA256_RE.fullmatch(digest) \
                    or len(artifact) != 1:
                problems.append(f"Android verification artifact is duplicate/malformed: {key}")
            seen.add(key)
            actual_artifacts.append({
                "artifact": filename, "group": identity[0], "name": identity[1],
                "sha256": digest, "version": identity[2],
            })
    actual_artifacts.sort(key=lambda row: (
        row["group"], row["name"], row["version"], row["artifact"]
    ))
    if not actual_artifacts or receipt.get("artifacts") != actual_artifacts:
        problems.append("Android artifact closure has missing, modified, stale, or reordered entries")

    actual_locks: list[dict[str, object]] = []
    for path in sorted(android_root.rglob("*.lockfile")):
        relative = path.relative_to(android_root).as_posix()
        try:
            parsed = parse_gradle_95_lockfile(path, source=relative)
        except (OSError, GradleLockfileError) as exc:
            problems.append(f"Android lockfile is not canonical: {exc}")
            continue
        actual_locks.append({
            "entries": list(parsed.entries), "path": relative,
            "resolved_configurations": list(parsed.resolved_configurations),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    if not actual_locks or receipt.get("locks") != actual_locks:
        problems.append("Android lock closure has missing, modified, stale, or reordered entries")
    configurations = sorted({
        configuration
        for lock in actual_locks
        for configuration in lock["resolved_configurations"]
    })
    if not configurations or receipt.get("resolved_locked_configurations") != configurations:
        problems.append("Android resolved-configuration closure is missing or stale")

    for relative in ("build.gradle.kts", "app/build.gradle.kts"):
        text = (android_root / relative).read_text(encoding="utf-8")
        if "lockAllConfigurations()" not in text or "lockMode.set(LockMode.STRICT)" not in text:
            problems.append(f"Android strict dependency locking missing from {relative}")
    properties = (android_root / "gradle.properties").read_text(encoding="utf-8")
    if "org.gradle.dependency.verification=strict" not in properties \
            or "org.gradle.dependency.verification.console=verbose" not in properties:
        problems.append("Android strict/observable dependency verification properties missing")
    return problems


def _gradle_lockfile_grammar_selftest_problems(android_root: Path) -> list[str]:
    """Prove each canonical-writer invariant rejects a distinct corruption."""
    problems: list[str] = []
    path = android_root / "app/gradle.lockfile"
    raw = path.read_bytes()
    try:
        canonical = parse_gradle_95_lockfile_bytes(raw, source="canonical-selftest")
    except GradleLockfileError as exc:
        return [f"Gradle lock grammar selftest rejected canonical source: {exc}"]
    records = list(canonical.entries)
    dependency_rows = records[:-1]
    if len(dependency_rows) < 2:
        return ["Gradle lock grammar selftest needs at least two dependency rows"]

    def encoded(candidate_records: list[str], *, suffix: bytes = b"\n") -> bytes:
        header = raw.split(b"\n", 3)[:3]
        return b"\n".join([*header, *(row.encode("utf-8") for row in candidate_records)]) + suffix

    first_module, first_configurations = dependency_rows[0].split("=", 1)
    first_configuration = first_configurations.split(",", 1)[0]
    empty_configurations = records[-1].removeprefix("empty=")
    mutations: dict[str, bytes] = {
        "missing-empty": encoded(dependency_rows),
        "duplicate-empty": encoded([*records, records[-1]]),
        "misplaced-nonterminal-empty": encoded([
            *dependency_rows[:-1], records[-1], dependency_rows[-1],
        ]),
        "malformed-empty": encoded([*dependency_rows, f"empty=={empty_configurations}"]),
        "nonlexical-dependencies": encoded([
            dependency_rows[1], dependency_rows[0], *dependency_rows[2:], records[-1],
        ]),
        "duplicate-module": encoded([
            dependency_rows[0], dependency_rows[0], *dependency_rows[1:], records[-1],
        ]),
        "duplicate-configuration": encoded([
            f"{first_module}={first_configurations},{first_configuration}",
            *dependency_rows[1:], records[-1],
        ]),
        "unexpected-record": encoded([*dependency_rows, "unexpected", records[-1]]),
        "truncated-terminal-lf": encoded(records, suffix=b""),
        "partial-record": encoded([
            f"{first_module}=", *dependency_rows[1:], records[-1],
        ]),
        "blank-line": encoded([dependency_rows[0], "", *dependency_rows[1:], records[-1]]),
        "extra-comment": encoded([dependency_rows[0], "# extra", *dependency_rows[1:], records[-1]]),
    }
    if empty_configurations:
        empty_first = empty_configurations.split(",", 1)[0]
        mutations["duplicate-empty-configuration"] = encoded([
            *dependency_rows, f"empty={empty_configurations},{empty_first}",
        ])
    for label, candidate in mutations.items():
        try:
            parse_gradle_95_lockfile_bytes(candidate, source=f"negative-{label}")
        except GradleLockfileError:
            continue
        problems.append(f"Gradle lock grammar selftest accepted {label}")
    return problems


def _contract_problems(spec: dict[str, Any], root: Path = REPO_ROOT) -> list[str]:
    problems: list[str] = []
    expected_ids = ["flutter", "android", "qt"]
    fixtures = spec.get("fixtures", [])
    if [row.get("id") for row in fixtures if isinstance(row, dict)] != expected_ids:
        problems.append(f"fixture ids/order must be {expected_ids}")
        return problems
    by_id = {row["id"]: row for row in fixtures}
    problems += _gradle_lockfile_grammar_selftest_problems(
        root / "tests/fixtures/android"
    )

    flutter = by_id["flutter"]
    ftool = flutter.get("toolchain", {})
    if ftool != {
        "channel": "stable",
        "flutter_version": "3.47.0",
        "dart_version": "3.13.0",
        "framework_revision": "4cf24164269a5ebf0c16a028a00727d0e77bbb05",
        "linux_x64_archive": "stable/linux/flutter_linux_3.47.0-stable.tar.xz",
        "linux_x64_archive_sha256": "26cd99d3d94b1367e6b50535a18aeef0282c10a535bbe3ec493534dcdab75296",
    }:
        problems.append("flutter toolchain identity drifted from reviewed official release")
    fcache = flutter.get("cache_contract", {})
    if fcache.get("sdk_key_template") != "flutter-:os:-:channel:-:version:-:arch:-:hash:" \
            or "pubspec-lock-sha256" not in str(fcache.get("pub_key_template")):
        problems.append("flutter cache-key contract drifted")
    pubspec = (root / "tests/fixtures/flutter/pubspec.yaml").read_text(encoding="utf-8")
    if ">=3.13.0 <4.0.0" not in pubspec:
        problems.append("flutter pubspec no longer binds Dart 3.13")

    android = by_id["android"]
    atool = android.get("toolchain", {})
    versions = (root / "tests/fixtures/android/gradle/libs.versions.toml").read_text(encoding="utf-8")
    wrapper_props = (root / "tests/fixtures/android/gradle/wrapper/gradle-wrapper.properties").read_text(encoding="utf-8")
    wrapper_jar = root / "tests/fixtures/android/gradle/wrapper/gradle-wrapper.jar"
    required_android = {
        "agp_version": "9.3.1", "kotlin_version": "2.2.10",
        "gradle_version": "9.5.0", "java_version_input": 21,
        "compile_sdk": 37, "build_tools": "36.0.0",
        "gradle_distribution_sha256": "553c78f50dafcd54d65b9a444649057857469edf836431389695608536d6b746",
        "gradle_wrapper_jar_sha256": "497c8c2a7e5031f6aa847f88104aa80a93532ec32ee17bdb8d1d2f67a194a9c7",
    }
    if atool != required_android:
        problems.append("Android toolchain identity drifted from reviewed compatibility mapping")
    if android.get("java_evidence_fields") != list(JAVA_EVIDENCE_FIELDS):
        problems.append("Android Java evidence vocabulary drifted")
    if android.get("lockfile_contract") != {
        "format": "gradle-9.5-single-project-v1",
        "encoding": "utf-8-lf-terminal-lf",
        "header": "exact-gradle-generated-three-line-header",
        "dependency_order": "strict-lexical-unique-module",
        "configuration_order": "strict-lexical-unique",
        "empty_aggregate": "exactly-one-terminal",
        "source": "gradle-v9.5.0-LockFileReaderWriter",
    }:
        problems.append("Android Gradle lockfile grammar contract drifted")
    for literal in ('agp = "9.3.1"', 'kotlin = "2.2.10"', 'compile-sdk = "37"', 'build-tools = "36.0.0"'):
        if literal not in versions:
            problems.append(f"Android version catalog missing {literal}")
    if "gradle-9.5.0-bin.zip" not in wrapper_props or required_android["gradle_distribution_sha256"] not in wrapper_props:
        problems.append("Gradle wrapper URL/checksum drifted")
    if not wrapper_jar.is_file() or hashlib.sha256(wrapper_jar.read_bytes()).hexdigest() != required_android["gradle_wrapper_jar_sha256"]:
        problems.append("Gradle wrapper JAR checksum drifted")
    android_workflow = (root / ".github/workflows/kotlin-android-ci.yml").read_text(encoding="utf-8")
    if "cache-provider: basic" not in android_workflow:
        problems.append("Kotlin/Android workflow must select tier-neutral basic cache")
    problems += _android_provenance_problems(root / "tests/fixtures/android")

    qt = by_id["qt"]
    qtool = qt.get("toolchain", {})
    if qtool.get("qt_version") != "6.8.4" or qtool.get("aqtinstall_version") != "3.3.0" \
            or qtool.get("py7zr_version") != "1.0.0":
        problems.append("Qt/aqt/py7zr exact toolchain identity drifted")
    if qt.get("cache_contract", {}).get("key_prefix") != "qt-ci-v1":
        problems.append("Qt cache-key prefix drifted")
    qt_workflow = (root / ".github/workflows/qt-ci.yml").read_text(encoding="utf-8")
    for literal in ("cache-key-prefix: qt-ci-v1", "aqtversion: '==3.3.0'", "py7zrversion: '==1.0.0'"):
        if literal not in qt_workflow:
            problems.append(f"Qt workflow missing pinned contract {literal}")

    for fixture in fixtures:
        workflow_path = root / fixture["workflow"]
        inputs, _ = _workflow_inputs(workflow_path)
        commands = fixture["default_commands"]
        mapping = {
            "resolve": "pub_get_command", "format": "format-check-sentinel",
            "analyze": "analyze-sentinel", "test": "test_command",
            "build": "build_command", "configure": "configure_command",
        }
        for name, command in commands.items():
            input_name = mapping[name]
            if input_name == "format-check-sentinel":
                actual = "dart format --output=none --set-exit-if-changed ." if inputs.get("format_check", {}).get("default") is True else ""
            elif input_name == "analyze-sentinel":
                actual = "flutter analyze" if inputs.get("analyze", {}).get("default") is True else ""
            else:
                actual = inputs.get(input_name, {}).get("default")
            if actual != command:
                problems.append(f"{fixture['id']}: default {name} command drifted: {actual!r}")
        call = get_on(load_yaml(workflow_path)).get("workflow_call", {})
        outputs = call.get("outputs", {})
        jobs = load_yaml(workflow_path).get("jobs", {})
        job = next(iter(jobs.values()), {})
        if outputs.get("evidence", {}).get("value") is None \
                or job.get("permissions") != {"contents": "read"} \
                or "evidence" not in job.get("outputs", {}):
            problems.append(f"{fixture['id']}: reusable evidence output/least permissions drifted")
    caller = load_yaml(root / ".github/workflows/runtime-fixtures-languages.yml")
    problems += _caller_problems(spec, caller)
    return problems


def _manifest_problems(spec: dict[str, Any], root: Path = REPO_ROOT) -> list[str]:
    expected, problems = _canonical_manifest(spec, root)
    output = spec.get("generated_manifest")
    if not isinstance(output, str):
        return problems + ["generated_manifest must be a repository-relative path"]
    path = root / output
    actual = path.read_bytes() if path.is_file() else b""
    if actual != expected:
        problems.append("sdk runtime manifest is missing/stale")
    else:
        try:
            rows = json.loads(actual)["fixtures"]
        except (json.JSONDecodeError, KeyError, TypeError):
            problems.append("sdk runtime manifest is not canonical JSON")
        else:
            digests = [row.get("sha256") for row in rows]
            if any(not isinstance(value, str) or not SHA256_RE.fullmatch(value) for value in digests):
                problems.append("manifest contains a malformed sha256")
            if len(digests) != len(set(digests)):
                problems.append("manifest contains duplicate digest rows")
    return problems


def validate_receipt(kind: str, raw: str) -> list[str]:
    """Fail closed on missing/skipped/partial runtime evidence."""
    try:
        receipt = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return [f"{kind}: evidence is missing or invalid JSON"]
    if not isinstance(receipt, dict):
        return [f"{kind}: evidence must be an object"]
    problems: list[str] = []
    common = {"os": "Linux", "runner_arch": "X64"}
    for key, value in common.items():
        if receipt.get(key) != value:
            problems.append(f"{kind}: {key} must be {value!r}")
    if kind == "flutter":
        exact = {
            "flutter_version": "3.47.0", "dart_version": "3.13.0",
            "flutter_revision": "4cf24164269a5ebf0c16a028a00727d0e77bbb05",
            "flutter_channel": "stable", "test_command": "flutter test",
            "pub_get_command": "flutter pub get",
        }
        if receipt.get("test_count", 0) < 1:
            problems.append("flutter: zero tests")
        if not str(receipt.get("cache_key", "")).startswith("flutter-linux-stable-3.47.0-x64-"):
            problems.append("flutter: SDK cache key drifted")
        if not str(receipt.get("pub_cache_key", "")).endswith(
            "-" + str(receipt.get("pubspec_lock_sha256", "missing"))
        ):
            problems.append("flutter: pub cache key is not lock-bound")
    elif kind == "android":
        exact = {
            "gradle_version": "9.5.0", "java_version_input": "21",
            "build_command": "./gradlew build", "cache_provider": "basic",
            "setup_android": "false",
            "wrapper_jar_sha256": "497c8c2a7e5031f6aa847f88104aa80a93532ec32ee17bdb8d1d2f67a194a9c7",
        }
        if receipt.get("test_count", 0) < 1 or receipt.get("apk_count", 0) < 1:
            problems.append("android: build did not produce a test and APK")
        if not receipt.get("lock_sha256") or not receipt.get("verification_metadata_sha256"):
            problems.append("android: lock/verification identity missing")
        provenance_path = REPO_ROOT / "tests/fixtures/android/gradle/provenance-manifest.json"
        try:
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"android: canonical provenance receipt unavailable: {exc}")
        else:
            expected_locks = {
                row["path"]: row["sha256"] for row in provenance.get("locks", [])
                if isinstance(row, dict) and isinstance(row.get("path"), str)
                and isinstance(row.get("sha256"), str)
            }
            if receipt.get("lock_sha256") != expected_locks:
                problems.append("android: runtime lock closure differs from canonical exact-build closure")
            if receipt.get("verification_metadata_sha256") != provenance.get(
                "verification_metadata_sha256"
            ):
                problems.append("android: runtime verification metadata differs from canonical closure")
            wrapper_properties = (
                REPO_ROOT / "tests/fixtures/android/gradle/wrapper/gradle-wrapper.properties"
            )
            if receipt.get("wrapper_properties_sha256") != hashlib.sha256(
                wrapper_properties.read_bytes()
            ).hexdigest():
                problems.append("android: runtime wrapper properties identity drifted")
        if "36.0.0" not in receipt.get("sdk_build_tools", []) \
                or not any(str(value).startswith("37") for value in receipt.get("sdk_platforms", [])):
            problems.append("android: resolved SDK 37 / Build Tools 36.0.0 missing")
        if not str(receipt.get("java_version_resolved", "")).startswith("21"):
            problems.append("android: resolved JDK is not 21")
        problems += _java_identity_problems(receipt, "android")
    elif kind == "qt":
        exact = {
            "qt_version": "6.8.4", "qt_version_input": "6.8.4",
            "cache_key_prefix": "qt-ci-v1",
            "configure_command": "cmake -S . -B build -DCMAKE_BUILD_TYPE=Release",
            "build_command": "cmake --build build --parallel",
            "test_command": "ctest --test-dir build --output-on-failure",
        }
        if receipt.get("test_count", 0) < 1 or not receipt.get("binary_sha256"):
            problems.append("qt: CTest/binary evidence missing")
        if "3.3.0" not in str(receipt.get("aqt_version", "")):
            problems.append("qt: aqtinstall version drifted")
        if not receipt.get("compiler") or not receipt.get("cmake_version"):
            problems.append("qt: compiler/CMake identity missing")
    else:
        return [f"unsupported SDK fixture receipt {kind!r}"]
    for key, value in exact.items():
        if receipt.get(key) != value:
            problems.append(f"{kind}: {key} expected {value!r}, got {receipt.get(key)!r}")
    for key, value in receipt.items():
        if key.endswith("sha256") and isinstance(value, str) and not SHA256_RE.fullmatch(value):
            problems.append(f"{kind}: malformed {key}")
        if key.endswith("_sha256") and isinstance(value, list) \
                and (not value or any(not isinstance(item, str) or not SHA256_RE.fullmatch(item) for item in value)):
            problems.append(f"{kind}: malformed {key} list")
        if key == "lock_sha256" and isinstance(value, dict) \
                and any(not isinstance(item, str) or not SHA256_RE.fullmatch(item) for item in value.values()):
            problems.append(f"{kind}: malformed lock digest map")
    return problems


def _selftest(spec: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    digest = "a" * 64
    receipts = {
        "flutter": {
            "os": "Linux", "runner_arch": "X64", "flutter_version": "3.47.0",
            "dart_version": "3.13.0", "flutter_revision": "4cf24164269a5ebf0c16a028a00727d0e77bbb05",
            "flutter_channel": "stable", "test_command": "flutter test",
            "pub_get_command": "flutter pub get", "test_count": 1,
            "cache_key": "flutter-linux-stable-3.47.0-x64-4cf24164269a5ebf0c16a028a00727d0e77bbb05",
            "pub_cache_key": f"flutter-pub-linux-stable-3.47.0-x64-revision-{digest}",
            "pubspec_lock_sha256": digest, "test_log_sha256": digest,
        },
        "android": {
            "os": "Linux", "runner_arch": "X64", "gradle_version": "9.5.0",
            "java_version_input": "21", "java_version_resolved": "21.0.8",
            "java_runtime_version_resolved": "21.0.8+9-LTS",
            "java_vendor_resolved": "Eclipse Adoptium",
            "java_vm_name_resolved": "OpenJDK 64-Bit Server VM",
            "gradle_launcher_jvm_resolved": "21.0.8 (Eclipse Adoptium 21.0.8+9-LTS)",
            "gradle_launcher_jvm_version_resolved": "21.0.8",
            "gradle_launcher_jvm_runtime_version_resolved": "21.0.8+9-LTS",
            "gradle_launcher_jvm_vendor_resolved": "Eclipse Adoptium",
            "gradle_launcher_jvm_vm_name_resolved": "OpenJDK 64-Bit Server VM",
            "gradle_daemon_jvm_resolved": "/opt/java/21 (using current Java home)",
            "gradle_daemon_jvm_version_resolved": "21.0.8",
            "gradle_daemon_jvm_runtime_version_resolved": "21.0.8+9-LTS",
            "gradle_daemon_jvm_vendor_resolved": "Eclipse Adoptium",
            "gradle_daemon_jvm_vm_name_resolved": "OpenJDK 64-Bit Server VM",
            "build_command": "./gradlew build", "cache_provider": "basic",
            "setup_android": "false", "test_count": 1, "apk_count": 1,
            "apk_sha256": [digest], "build_log_sha256": digest,
            "lock_sha256": {"app/gradle.lockfile": digest},
            "verification_metadata_sha256": digest,
            "wrapper_jar_sha256": "497c8c2a7e5031f6aa847f88104aa80a93532ec32ee17bdb8d1d2f67a194a9c7",
            "wrapper_properties_sha256": digest,
            "sdk_build_tools": ["36.0.0"], "sdk_platforms": ["37"],
        },
        "qt": {
            "os": "Linux", "runner_arch": "X64", "qt_version": "6.8.4",
            "qt_version_input": "6.8.4", "cache_key_prefix": "qt-ci-v1",
            "configure_command": "cmake -S . -B build -DCMAKE_BUILD_TYPE=Release",
            "build_command": "cmake --build build --parallel",
            "test_command": "ctest --test-dir build --output-on-failure",
            "test_count": 1, "binary_sha256": [digest], "test_log_sha256": digest,
            "aqt_version": "aqtinstall(aqt) v3.3.0", "cmake_version": "4.1.0",
            "compiler": "g++ 14.2.0",
        },
    }
    provenance_path = REPO_ROOT / "tests/fixtures/android/gradle/provenance-manifest.json"
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        receipts["android"]["lock_sha256"] = {
            row["path"]: row["sha256"] for row in provenance["locks"]
        }
        receipts["android"]["verification_metadata_sha256"] = provenance[
            "verification_metadata_sha256"
        ]
        receipts["android"]["wrapper_properties_sha256"] = hashlib.sha256((
            REPO_ROOT / "tests/fixtures/android/gradle/wrapper/gradle-wrapper.properties"
        ).read_bytes()).hexdigest()
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        problems.append(f"receipt selftest cannot load canonical Android provenance: {exc}")
    for kind, receipt in receipts.items():
        if validate_receipt(kind, json.dumps(receipt)):
            problems.append(f"receipt selftest rejected valid {kind} evidence")
    for kind in ("flutter", "android", "qt"):
        if not validate_receipt(kind, ""):
            problems.append(f"receipt selftest accepted missing {kind} evidence")
        changed_receipt = copy.deepcopy(receipts[kind])
        changed_receipt["test_count"] = 0
        if not validate_receipt(kind, json.dumps(changed_receipt)):
            problems.append(f"receipt selftest accepted zero-test {kind} evidence")
    changed_receipt = copy.deepcopy(receipts["flutter"])
    changed_receipt["flutter_version"] = "3.47.1"
    if not validate_receipt("flutter", json.dumps(changed_receipt)):
        problems.append("receipt selftest accepted wrong Flutter SDK")
    changed_receipt = copy.deepcopy(receipts["android"])
    changed_receipt["wrapper_jar_sha256"] = "bad"
    if not validate_receipt("android", json.dumps(changed_receipt)):
        problems.append("receipt selftest accepted malformed wrapper digest")
    changed_receipt = copy.deepcopy(receipts["android"])
    changed_receipt["java_version_resolved"] = changed_receipt["java_version_input"]
    if not validate_receipt("android", json.dumps(changed_receipt)):
        problems.append("receipt selftest accepted desired Java input as observed runtime")
    changed_receipt = copy.deepcopy(receipts["android"])
    changed_receipt["gradle_launcher_jvm_version_resolved"] = "17.0.12"
    if not validate_receipt("android", json.dumps(changed_receipt)):
        problems.append("receipt selftest accepted Gradle launcher JVM drift")
    changed_receipt = copy.deepcopy(receipts["android"])
    changed_receipt["gradle_daemon_jvm_vendor_resolved"] = "Unexpected Vendor"
    if not validate_receipt("android", json.dumps(changed_receipt)):
        problems.append("receipt selftest accepted Gradle daemon JVM drift")
    changed_receipt = copy.deepcopy(receipts["android"])
    changed_receipt["lock_sha256"] = {
        key: "0" * 64 for key in changed_receipt["lock_sha256"]
    }
    if not validate_receipt("android", json.dumps(changed_receipt)):
        problems.append("receipt selftest accepted stale but well-formed Android lock closure")
    changed_receipt = copy.deepcopy(receipts["qt"])
    changed_receipt["cache_key_prefix"] = "shared"
    if not validate_receipt("qt", json.dumps(changed_receipt)):
        problems.append("receipt selftest accepted wrong Qt cache key")

    android_source = REPO_ROOT / "tests/fixtures/android"
    with tempfile.TemporaryDirectory() as temp:
        baseline = Path(temp) / "android"
        shutil.copytree(android_source, baseline)
        if _android_provenance_problems(baseline):
            problems.append("Android provenance selftest rejected canonical closure")
        receipt_path = baseline / "gradle/provenance-manifest.json"
        original_receipt = receipt_path.read_bytes()
        metadata_path = baseline / "gradle/verification-metadata.xml"
        original_metadata = metadata_path.read_bytes()
        lock_path = baseline / "app/gradle.lockfile"
        original_lock = lock_path.read_bytes()

        xml = ET.fromstring(original_metadata)
        components = xml.find("v:components", VERIFY_NS)
        first_component = components.find("v:component", VERIFY_NS) if components is not None else None
        first_artifact = first_component.find("v:artifact", VERIFY_NS) if first_component is not None else None
        if first_component is None or first_artifact is None:
            problems.append("Android provenance selftest has no artifact to mutate")
        else:
            first_component.remove(first_artifact)
            metadata_path.write_bytes(ET.tostring(xml, encoding="utf-8", xml_declaration=True))
            if not _android_provenance_problems(baseline):
                problems.append("Android provenance selftest accepted missing metadata")

            metadata_path.write_bytes(original_metadata.replace(b'value="', b'value="0', 1))
            if not _android_provenance_problems(baseline):
                problems.append("Android provenance selftest accepted modified metadata")

            xml = ET.fromstring(original_metadata)
            components = xml.find("v:components", VERIFY_NS)
            stale = ET.SubElement(components, f"{{{VERIFY_NS['v']}}}component", {
                "group": "invalid.example", "name": "stale", "version": "0",
            })
            artifact = ET.SubElement(stale, f"{{{VERIFY_NS['v']}}}artifact", {"name": "stale-0.jar"})
            ET.SubElement(artifact, f"{{{VERIFY_NS['v']}}}sha256", {"value": "0" * 64})
            metadata_path.write_bytes(ET.tostring(xml, encoding="utf-8", xml_declaration=True))
            if not _android_provenance_problems(baseline):
                problems.append("Android provenance selftest accepted stale-extra metadata")

        metadata_path.write_bytes(original_metadata)
        receipt = json.loads(original_receipt)
        receipt["generation_arguments"][1] = ":app:testDebugUnitTest"
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        if not _android_provenance_problems(baseline):
            problems.append("Android provenance selftest accepted narrower-task generation")

        for label, field, value in (
            ("desired-input-as-observation", "java_version_resolved", "21"),
            ("launcher-jvm-drift", "gradle_launcher_jvm_version_resolved", "17.0.12"),
            ("daemon-jvm-missing", "gradle_daemon_jvm_resolved", ""),
        ):
            receipt = json.loads(original_receipt)
            receipt[field] = value
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            if not _android_provenance_problems(baseline):
                problems.append(f"Android provenance selftest accepted {label}")

        receipt_path.write_bytes(original_receipt)
        lock_path.write_bytes(original_lock + b"invalid:stale:0=runtimeClasspath\n")
        if not _android_provenance_problems(baseline):
            problems.append("Android provenance selftest accepted stale/modified lock")
    changed = copy.deepcopy(spec)
    changed["fixtures"][0]["toolchain"]["flutter_version"] = "3.47.1"
    if not _contract_problems(changed):
        problems.append("SDK contract selftest accepted wrong tool version")
    changed = copy.deepcopy(spec)
    changed["fixtures"][2]["cache_contract"]["key_prefix"] = "shared"
    if not _contract_problems(changed):
        problems.append("SDK contract selftest accepted cache-key drift")
    caller = load_yaml(REPO_ROOT / ".github/workflows/runtime-fixtures-languages.yml")
    changed_caller = copy.deepcopy(caller)
    changed_caller["jobs"]["fixture-qt-ci"]["if"] = "false"
    if not _caller_problems(spec, changed_caller):
        problems.append("SDK caller selftest accepted a skipped fixture")
    changed_caller = copy.deepcopy(caller)
    changed_caller["jobs"]["observe-dart-flutter-ci"]["needs"] = "fixture-qt-ci"
    if not _caller_problems(spec, changed_caller):
        problems.append("SDK caller selftest accepted observer drift")

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = root / "tests/fixtures/sample/a.txt"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"alpha\n")
        second = source.parent / "b.txt"
        second.write_bytes(b"bravo\n")
        local_spec_path = root / SPEC_PATH.relative_to(REPO_ROOT)
        local_spec_path.parent.mkdir(parents=True, exist_ok=True)
        local = {
            "schema_version": 1,
            "byte_contract": spec["byte_contract"],
            "generated_manifest": "tests/fixtures/sample-manifest.json",
            "fixtures": [{
                "id": "sample", "working_directory": "tests/fixtures/sample",
                "source_files": [
                    {"path": "tests/fixtures/sample/a.txt", "kind": "text"},
                    {"path": "tests/fixtures/sample/b.txt", "kind": "text"},
                ],
            }],
        }
        local_spec_path.write_text("schema_version: 1\n", encoding="utf-8")
        canonical, baseline = _canonical_manifest(local, root)
        (root / local["generated_manifest"]).write_bytes(canonical)
        if baseline or _manifest_problems(local, root):
            problems.append("SDK manifest selftest rejected canonical fixture")
        mutations = {
            "newline": b"alpha\r\n",
            "encoding": b"\xef\xbb\xbfalpha\n",
            "terminal-newline": b"alpha",
            "modified-source": b"beta\n",
        }
        for label, value in mutations.items():
            source.write_bytes(value)
            if not _manifest_problems(local, root):
                problems.append(f"SDK manifest selftest accepted {label} drift")
        source.write_bytes(b"alpha\n")
        duplicated = copy.deepcopy(local)
        duplicated["fixtures"][0]["source_files"].append(
            {"path": "tests/fixtures/sample/a.txt", "kind": "text"}
        )
        if not _manifest_problems(duplicated, root):
            problems.append("SDK manifest selftest accepted duplicate source/digest")
        same_digest = copy.deepcopy(local)
        third = source.parent / "c.txt"
        third.write_bytes(b"alpha\n")
        same_digest["fixtures"][0]["source_files"].append(
            {"path": "tests/fixtures/sample/c.txt", "kind": "text"}
        )
        if not _manifest_problems(same_digest, root):
            problems.append("SDK manifest selftest accepted duplicate digest")
        third.unlink()
        reordered = copy.deepcopy(local)
        reordered["fixtures"][0]["source_files"].reverse()
        if not _manifest_problems(reordered, root):
            problems.append("SDK manifest selftest accepted path/order drift")
        extra = source.parent / "unused.txt"
        extra.write_bytes(b"unused\n")
        if not _manifest_problems(local, root):
            problems.append("SDK manifest selftest accepted unused source")
    return problems


def check() -> list[str]:
    try:
        spec = strict_load(SPEC_PATH)
    except (OSError, ValueError) as exc:
        return [f"cannot load SDK runtime spec: {exc}"]
    if not isinstance(spec, dict) or spec.get("schema_version") != 1:
        return ["SDK runtime spec must be schema_version 1"]
    problems = _contract_problems(spec)
    problems += _manifest_problems(spec)
    problems += _selftest(spec)
    return problems


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--receipt":
        raw = os.environ.get("SDK_RUNTIME_EVIDENCE", "")
        problems = validate_receipt(sys.argv[2], raw)
    elif len(sys.argv) == 1:
        problems = check()
    else:
        print("usage: check_sdk_runtime_fixtures.py [--receipt flutter|android|qt]", file=sys.stderr)
        return 2
    if problems:
        for problem in problems:
            print(f"sdk-runtime-fixtures: {problem}", file=sys.stderr)
        return 1
    print("sdk-runtime-fixtures: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
