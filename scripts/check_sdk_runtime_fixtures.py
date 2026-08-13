#!/usr/bin/env python3
"""Validate bounded SDK fixtures and reject false-green runtime receipts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ci_workflows_tools import _gradle_lockfile, _sdk_environment, generate_sdk_runtime_manifest
from ci_workflows_tools._strict_yaml import strict_load
from ci_workflows_tools._workflow_yaml import get_on, load_yaml

ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / "tests/fixtures/sdk-runtime-spec.yml"
MANIFEST = ROOT / "tests/fixtures/sdk-runtime-manifest.json"
WORKFLOWS = ROOT / ".github/workflows"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _workflow_call(path: Path) -> dict[str, Any]:
    doc = load_yaml(path)
    on = get_on(doc)
    return on.get("workflow_call", {}) if isinstance(on, dict) else {}


def _receipt_problems(kind: str, receipt: Any, spec: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if not isinstance(receipt, dict):
        return [f"{kind}: evidence must be a JSON object"]
    common = {"os": "Linux", "runner_arch": "X64",
              "workflow_sha256": _digest(ROOT / spec["workflow"])}
    for key, expected in common.items():
        if receipt.get(key) != expected:
            problems.append(f"{kind}: {key} must equal {expected!r}")
    caller_sha = receipt.get("caller_sha")
    if not isinstance(caller_sha, str) or len(caller_sha) != 40 \
            or any(char not in "0123456789abcdef" for char in caller_sha):
        problems.append(f"{kind}: caller_sha must be a full lowercase Git SHA")
    defaults = spec["default_commands"]
    if kind == "flutter":
        expected = spec["toolchain"]
        checks = {
            "flutter_version": str(expected["flutter_version"]),
            "dart_version": str(expected["dart_version"]),
            "flutter_revision": expected["framework_revision"],
            "pub_get_command": defaults["resolve"], "test_command": defaults["test"],
        }
        if receipt.get("test_count", 0) < 1 or not receipt.get("pubspec_lock_sha256"):
            problems.append("flutter: evidence needs a lock digest and at least one test")
        if any("3.47.0" not in str(receipt.get(key, "")) for key in ("cache_key", "pub_cache_key")):
            problems.append("flutter: action cache identities are required")
    elif kind == "android":
        expected = spec["toolchain"]
        checks = {
            "build_command": defaults["build"], "cache_provider": "basic",
            "gradle_version": str(expected["gradle_version"]),
            "java_version_input": str(expected["java_version_input"]),
            "setup_android": "false",
            "wrapper_jar_sha256": expected["gradle_wrapper_jar_sha256"],
        }
        if receipt.get("test_count", 0) < 1 or not receipt.get("apk_sha256"):
            problems.append("android: evidence needs an APK and at least one test")
        expected_platforms = {
            f"android-{expected['compile_sdk']}",
            f"android-{expected['compile_sdk']}.0",
        }
        observed_platforms = set(receipt.get("sdk_platforms", []))
        if len(expected_platforms & observed_platforms) != 1:
            problems.append("android: required SDK platform is absent")
        if str(expected["build_tools"]) not in receipt.get("sdk_build_tools", []):
            problems.append("android: required build-tools are absent")
        if not receipt.get("lock_sha256") or not receipt.get("verification_metadata_sha256"):
            problems.append("android: lock and dependency-verification identities are required")
        if not receipt.get("gradle_launcher_jvm_resolved") or not receipt.get("gradle_daemon_jvm_resolved"):
            problems.append("android: Gradle launcher/daemon JVM identities are required")
        if not receipt.get("android_sdk_root_resolved") or not receipt.get("java_home_resolved"):
            problems.append("android: canonical Android/JDK roots are required")
        required_tasks = {":app:assembleDebug", ":app:testDebugUnitTest", ":app:lintDebug", ":app:build"}
        if not required_tasks.issubset(receipt.get("task_graph", [])):
            problems.append("android: exact default build task graph is incomplete")
        try:
            _sdk_environment.validate_jvm_identity(_jvm_identity(receipt))
        except (KeyError, OSError, _sdk_environment.SdkEnvironmentError) as exc:
            problems.append(f"android: JVM identity incoherent: {exc}")
        expected_launcher = (
            f'{receipt.get("gradle_launcher_jvm_version_resolved", "")} '
            f'({receipt.get("gradle_launcher_jvm_vendor_resolved", "")} '
            f'{receipt.get("gradle_launcher_jvm_runtime_version_resolved", "")})'
        )
        if receipt.get("gradle_launcher_jvm_resolved") != expected_launcher:
            problems.append("android: raw Gradle launcher identity diverged from typed fields")
        if not str(receipt.get("gradle_daemon_jvm_resolved", "")).startswith(
            str(receipt.get("gradle_daemon_jvm_home_resolved", "")) + " ("
        ):
            problems.append("android: raw Gradle daemon identity diverged from typed fields")
    elif kind == "qt":
        expected = spec["toolchain"]
        checks = {
            "qt_version": str(expected["qt_version"]),
            "qt_version_input": str(expected["qt_version"]),
            "configure_command": defaults["configure"], "build_command": defaults["build"],
            "test_command": defaults["test"], "cache_key_prefix": "qt-ci-v1",
        }
        if receipt.get("test_count", 0) < 1 or not receipt.get("test_log_sha256"):
            problems.append("qt: evidence needs a log digest and at least one CTest test")
        if str(expected["aqtinstall_version"]) not in str(receipt.get("aqt_version", "")):
            problems.append("qt: wrong aqtinstall version")
    else:
        return [f"unknown SDK receipt kind {kind!r}"]
    for key, expected_value in checks.items():
        if receipt.get(key) != expected_value:
            problems.append(f"{kind}: {key} must equal {expected_value!r}")
    for key in ("test_log_sha256", "build_log_sha256"):
        if key in receipt and not _is_sha(receipt[key]):
            problems.append(f"{kind}: {key} is not SHA-256")
    return problems


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _contract_problems(*, require_generated: bool = True) -> list[str]:
    problems: list[str] = []
    spec = strict_load(SPEC_PATH)
    fixtures = spec.get("fixtures", {})
    if set(fixtures) != {"flutter", "android", "qt"}:
        problems.append("SDK spec must define exactly flutter/android/qt")
        return problems
    try:
        expected_manifest = generate_sdk_runtime_manifest.render()
    except (OSError, UnicodeError, ValueError) as exc:
        problems.append(f"SDK byte manifest source contract failed: {exc}")
        expected_manifest = b""
    if require_generated and (
        not MANIFEST.is_file() or MANIFEST.read_bytes() != expected_manifest
    ):
        problems.append("SDK byte manifest is missing or stale")
    estate = load_yaml(WORKFLOWS / "runtime-fixtures-languages.yml")
    jobs = estate.get("jobs", {})
    for kind, data in fixtures.items():
        workflow = ROOT / data["workflow"]
        call = _workflow_call(workflow)
        inputs = call.get("inputs", {})
        expected_defaults = data["default_commands"]
        keys = {
            "flutter": {"pub_get_command": "resolve", "test_command": "test"},
            "android": {"build_command": "build"},
            "qt": {"configure_command": "configure", "build_command": "build", "test_command": "test"},
        }[kind]
        for input_name, command_name in keys.items():
            if inputs.get(input_name, {}).get("default") != expected_defaults[command_name]:
                problems.append(f"{kind}: reusable default {input_name} drifted")
        caller_name = f"fixture-{('dart-flutter-ci' if kind == 'flutter' else 'kotlin-android-ci' if kind == 'android' else 'qt-ci')}"
        observer_name = f"observe-{caller_name.removeprefix('fixture-')}"
        caller = jobs.get(caller_name, {})
        observer = jobs.get(observer_name, {})
        if caller.get("uses") != data["workflow"].replace(".github", "./.github"):
            problems.append(f"{kind}: live caller is missing or points at wrong reusable")
        passed = caller.get("with", {})
        if passed.get("runner") != "ubuntu-latest" or passed.get("working_directory") != data["working_directory"]:
            problems.append(f"{kind}: caller must select exact standard runner and fixture root")
        if any(name in passed for name in keys):
            problems.append(f"{kind}: caller overrides a documented default command")
        if observer.get("if") != "always()" or observer.get("needs") != caller_name:
            problems.append(f"{kind}: observer must run always and depend directly on caller")
    android_root = ROOT / fixtures["android"]["working_directory"]
    wrapper = android_root / "gradle/wrapper/gradle-wrapper.jar"
    wrapper_props = (android_root / "gradle/wrapper/gradle-wrapper.properties").read_text(encoding="utf-8")
    android_tools = fixtures["android"]["toolchain"]
    if _digest(wrapper) != android_tools["gradle_wrapper_jar_sha256"]:
        problems.append("android: wrapper JAR digest drift")
    if f"distributionSha256Sum={android_tools['gradle_distribution_sha256']}" not in wrapper_props:
        problems.append("android: wrapper distribution digest drift")
    lockfiles = sorted(android_root.rglob("*.lockfile"))
    if require_generated and not lockfiles:
        problems.append("android: exact default build produced no dependency locks")
    for lockfile in lockfiles:
        try:
            _gradle_lockfile.parse_gradle_95_lockfile(lockfile)
        except _gradle_lockfile.GradleLockfileError as exc:
            problems.append(str(exc))
    provenance = android_root / "gradle/provenance-manifest.json"
    metadata = android_root / "gradle/verification-metadata.xml"
    if require_generated and (not provenance.is_file() or not metadata.is_file()):
        problems.append("android: generated provenance or verification metadata is missing")
    elif provenance.is_file() and metadata.is_file():
        try:
            proof = json.loads(provenance.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"android: invalid provenance receipt: {exc}")
        else:
            required_tasks = {":app:assembleDebug", ":app:testDebugUnitTest", ":app:lintDebug", ":app:build"}
            if proof.get("default_command") != "./gradlew build" \
                    or not required_tasks.issubset(proof.get("task_graph", [])):
                problems.append("android: provenance was generated from a narrower task graph")
            if proof.get("verification_metadata_sha256") != _digest(metadata):
                problems.append("android: provenance metadata digest is stale")
    return problems + _negative_selftests(fixtures)


def _jvm_identity(receipt: dict[str, Any]) -> _sdk_environment.JvmIdentity:
    return _sdk_environment.JvmIdentity(
        requested_major=str(receipt["java_version_input"]),
        java_home=str(receipt["java_home_resolved"]),
        java_version=str(receipt["java_version_resolved"]),
        java_runtime_version=str(receipt["java_runtime_version_resolved"]),
        java_vendor=str(receipt["java_vendor_resolved"]),
        java_vm_name=str(receipt["java_vm_name_resolved"]),
        launcher_version=str(receipt["gradle_launcher_jvm_version_resolved"]),
        launcher_runtime_version=str(receipt["gradle_launcher_jvm_runtime_version_resolved"]),
        launcher_vendor=str(receipt["gradle_launcher_jvm_vendor_resolved"]),
        launcher_vm_name=str(receipt["gradle_launcher_jvm_vm_name_resolved"]),
        daemon_home=str(receipt["gradle_daemon_jvm_home_resolved"]),
        daemon_version=str(receipt["gradle_daemon_jvm_version_resolved"]),
        daemon_runtime_version=str(receipt["gradle_daemon_jvm_runtime_version_resolved"]),
        daemon_vendor=str(receipt["gradle_daemon_jvm_vendor_resolved"]),
        daemon_vm_name=str(receipt["gradle_daemon_jvm_vm_name_resolved"]),
    )


def _negative_selftests(fixtures: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    valid_common = {"os": "Linux", "runner_arch": "X64", "caller_sha": "a" * 40}
    samples = {
        "flutter": {**valid_common, "workflow_sha256": _digest(ROOT / fixtures["flutter"]["workflow"]),
                    "flutter_version": "3.47.0", "dart_version": "3.13.0",
                    "flutter_revision": fixtures["flutter"]["toolchain"]["framework_revision"],
                    "pub_get_command": "flutter pub get", "test_command": "flutter test",
                    "pubspec_lock_sha256": "b" * 64, "test_log_sha256": "c" * 64, "test_count": 1,
                    "cache_key": "flutter-cache-3.47.0", "pub_cache_key": "flutter-pub-3.47.0"},
        "android": {**valid_common, "workflow_sha256": _digest(ROOT / fixtures["android"]["workflow"]),
                    "build_command": "./gradlew build", "cache_provider": "basic", "gradle_version": "9.5.0",
                    "java_version_input": "21", "setup_android": "false", "wrapper_jar_sha256": fixtures["android"]["toolchain"]["gradle_wrapper_jar_sha256"],
                    "sdk_platforms": ["android-37"], "sdk_build_tools": ["36.0.0"], "test_count": 1,
                    "apk_sha256": ["d" * 64], "lock_sha256": {"app/gradle.lockfile": "e" * 64},
                    "verification_metadata_sha256": "f" * 64,
                    "java_version_resolved": "21.0.11", "java_runtime_version_resolved": "21.0.11+0",
                    "java_vendor_resolved": "Fixture", "java_vm_name_resolved": "Fixture VM",
                    "gradle_launcher_jvm_resolved": "21.0.11 (Fixture 21.0.11+0)",
                    "gradle_launcher_jvm_version_resolved": "21.0.11",
                    "gradle_launcher_jvm_runtime_version_resolved": "21.0.11+0",
                    "gradle_launcher_jvm_vendor_resolved": "Fixture",
                    "gradle_launcher_jvm_vm_name_resolved": "Fixture VM",
                    "gradle_daemon_jvm_resolved": "/opt/jdk-21 (no JDK specified, using current Java home)",
                    "gradle_daemon_jvm_home_resolved": "/opt/jdk-21",
                    "gradle_daemon_jvm_version_resolved": "21.0.11",
                    "gradle_daemon_jvm_runtime_version_resolved": "21.0.11+0",
                    "gradle_daemon_jvm_vendor_resolved": "Fixture",
                    "gradle_daemon_jvm_vm_name_resolved": "Fixture VM",
                    "android_sdk_root_resolved": "/opt/android", "java_home_resolved": "/opt/jdk-21",
                    "task_graph": [":app:assembleDebug", ":app:testDebugUnitTest", ":app:lintDebug", ":app:build"]},
        "qt": {**valid_common, "workflow_sha256": _digest(ROOT / fixtures["qt"]["workflow"]),
               "qt_version": "6.8.4", "qt_version_input": "6.8.4", "aqt_version": "aqtinstall(aqt) v3.3.0",
               "configure_command": "cmake -S . -B build -DCMAKE_BUILD_TYPE=Release",
               "build_command": "cmake --build build --parallel", "test_command": "ctest --test-dir build --output-on-failure",
               "cache_key_prefix": "qt-ci-v1", "test_count": 1, "test_log_sha256": "a" * 64},
    }
    for kind, sample in samples.items():
        if _receipt_problems(kind, sample, fixtures[kind]):
            problems.append(f"{kind}: valid receipt selftest rejected")
        for field in ("workflow_sha256", "caller_sha", "test_count"):
            broken = dict(sample)
            broken[field] = 0 if field == "test_count" else "wrong"
            if not _receipt_problems(kind, broken, fixtures[kind]):
                problems.append(f"{kind}: negative {field} substitution was accepted")
        targeted = {
            "flutter": ("test_command", "cache_key", "pub_cache_key"),
            "android": ("build_command", "cache_provider", "gradle_launcher_jvm_resolved", "task_graph"),
            "qt": ("configure_command", "cache_key_prefix", "test_command"),
        }[kind]
        for field in targeted:
            broken = dict(sample)
            broken[field] = [] if field == "task_graph" else "substituted"
            if not _receipt_problems(kind, broken, fixtures[kind]):
                problems.append(f"{kind}: negative {field} drift was accepted")
        if kind == "android":
            identity_fields = (
                "java_version_input", "java_home_resolved", "java_version_resolved",
                "java_runtime_version_resolved", "java_vendor_resolved", "java_vm_name_resolved",
                "gradle_launcher_jvm_version_resolved",
                "gradle_launcher_jvm_runtime_version_resolved",
                "gradle_launcher_jvm_vendor_resolved", "gradle_launcher_jvm_vm_name_resolved",
                "gradle_daemon_jvm_home_resolved", "gradle_daemon_jvm_version_resolved",
                "gradle_daemon_jvm_runtime_version_resolved",
                "gradle_daemon_jvm_vendor_resolved", "gradle_daemon_jvm_vm_name_resolved",
            )
            for field in identity_fields:
                broken = dict(sample)
                broken[field] = "substituted"
                if not _receipt_problems(kind, broken, fixtures[kind]):
                    problems.append(f"android: JVM identity negative {field!r} was accepted")
    canonical = "\n".join((*_gradle_lockfile.HEADER, "a:b:1=alpha,beta", "empty=gamma", ""))
    mutations = {
        "missing-empty": canonical.replace("empty=gamma\n", ""),
        "duplicate-empty": canonical + "empty=gamma\n",
        "misplaced-empty": canonical.replace("a:b:1=alpha,beta\nempty=gamma", "empty=gamma\na:b:1=alpha,beta"),
        "nonlexical-config": canonical.replace("alpha,beta", "beta,alpha"),
        "truncated": canonical.rstrip("\n"),
    }
    with tempfile.TemporaryDirectory() as raw:
        for label, body in mutations.items():
            path = Path(raw) / label
            path.write_text(body, encoding="utf-8")
            try:
                _gradle_lockfile.parse_gradle_95_lockfile(path)
            except _gradle_lockfile.GradleLockfileError:
                continue
            problems.append(f"Gradle lock negative {label!r} was accepted")
    problems.extend(_sdk_environment_selftests())
    return problems


def _sdk_environment_selftests() -> list[str]:
    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="sdk-environment-contract-") as raw:
        root = Path(raw)
        java_home = root / "jdk-21"
        java = java_home / "bin/java"
        java.parent.mkdir(parents=True)
        java.write_text("fixture\n", encoding="utf-8")
        sdk = root / "android-sdk"
        manager = sdk / "cmdline-tools/latest/bin/sdkmanager"
        manager.parent.mkdir(parents=True)
        manager.write_text("fixture\n", encoding="utf-8")
        (sdk / "platforms/android-37").mkdir(parents=True)
        (sdk / "build-tools/36.0.0").mkdir(parents=True)
        props = {"java.home": str(java_home), "java.version": "21.0.11",
                 "java.runtime.version": "21.0.11+0"}
        ambient = {"JAVA_HOME": "/hostile/java", "ANDROID_HOME": "/hostile/a",
                   "ANDROID_SDK_ROOT": "/hostile/b", "ANDROID_NDK_HOME": "/leak"}
        try:
            result = _sdk_environment.derive_android_environment(
                {"PATH": "/clean"}, ambient, java_executable=java,
                java_properties=props, sdkmanager_executable=manager,
                java_major="21", compile_sdk="37", build_tools="36.0.0",
            )
        except _sdk_environment.SdkEnvironmentError as exc:
            problems.append(f"valid SDK environment shape rejected: {exc}")
            return problems
        if result["JAVA_HOME"] != str(java_home.resolve()) \
                or result["ANDROID_HOME"] != str(sdk.resolve()) \
                or result["ANDROID_SDK_ROOT"] != str(sdk.resolve()) \
                or "ANDROID_NDK_HOME" in result:
            problems.append("SDK transition inherited mismatched roots or leaked child env")
        receipt = json.loads(result[_sdk_environment.EVIDENCE_NAME])
        if receipt.get("stripped_ambient") != list(_sdk_environment.SDK_NAMES):
            problems.append("SDK transition stripped-input evidence drifted")

        cases: list[tuple[str, Path, dict[str, str], Path, int | None]] = []
        wrong = dict(props); wrong["java.version"] = "17.0.19"
        cases.append(("wrong-version", java, wrong, manager, None))
        missing = dict(props); missing["java.home"] = str(root / "missing-jdk")
        cases.append(("missing", java, missing, manager, None))
        alias = root / "jdk-alias"
        alias.symlink_to(java_home, target_is_directory=True)
        aliased = dict(props); aliased["java.home"] = str(alias)
        cases.append(("symlink-alias", java, aliased, manager, None))
        ancestor = root / "alternate-ancestor"
        ancestor.symlink_to(root, target_is_directory=True)
        alternate = dict(props)
        alternate["java.home"] = str(ancestor / "jdk-21")
        cases.append(("alternate-ancestor", java, alternate, manager, None))
        cases.append(("unowned", java, props, manager, os.getuid() + 1))
        for label, executable, identity, sdk_executable, uid in cases:
            try:
                _sdk_environment.derive_android_environment(
                    {}, ambient, java_executable=executable,
                    java_properties=identity, sdkmanager_executable=sdk_executable,
                    java_major="21", compile_sdk="37", build_tools="36.0.0",
                    uid=uid,
                )
            except _sdk_environment.SdkEnvironmentError:
                continue
            problems.append(f"SDK environment negative {label!r} was accepted")
        sdk.chmod(0o775)
        try:
            _sdk_environment.derive_android_environment(
                {}, ambient, java_executable=java, java_properties=props,
                sdkmanager_executable=manager, java_major="21",
                compile_sdk="37", build_tools="36.0.0",
            )
        except _sdk_environment.SdkEnvironmentError:
            pass
        else:
            problems.append("SDK environment negative 'group-writable' was accepted")
        sdk.chmod(0o755)
    return problems


def check() -> list[str]:
    return _contract_problems(require_generated=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", choices=["flutter", "android", "qt"])
    parser.add_argument("--static", action="store_true")
    args = parser.parse_args()
    spec = strict_load(SPEC_PATH)["fixtures"]
    if args.receipt:
        try:
            receipt = json.loads(os.environ["SDK_RUNTIME_EVIDENCE"])
        except (KeyError, json.JSONDecodeError) as exc:
            print(f"sdk-runtime-evidence: invalid/missing JSON: {exc}")
            return 1
        problems = _receipt_problems(args.receipt, receipt, spec[args.receipt])
    else:
        problems = _contract_problems(require_generated=not args.static)
    if problems:
        print("check_sdk_runtime_fixtures: FAIL")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("check_sdk_runtime_fixtures: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
