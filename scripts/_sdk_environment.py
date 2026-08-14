#!/usr/bin/env python3
"""Typed, fail-closed SDK toolchain environment transition."""
from __future__ import annotations

import json
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

SDK_NAMES = ("ANDROID_HOME", "ANDROID_SDK_ROOT", "JAVA_HOME")
EVIDENCE_NAME = "NDDEV_SDK_ENV_RECEIPT"


class SdkEnvironmentError(ValueError):
    """Observed SDK roots do not satisfy the pinned fixture contract."""


@dataclass(frozen=True)
class OwnershipFacts:
    """The two `stat` fields the root trust rule is a function of."""

    uid: int
    mode: int


def ownership_problem(
    facts: OwnershipFacts, *, trusted_uid: int, allow_group_write: bool = False,
) -> str | None:
    """Return why a root is untrusted, or None when it is trusted.

    Kept pure — a function of two integers rather than of a live directory —
    because the rule it encodes cannot otherwise be tested honestly. Building
    the cases out of real temporary directories makes the outcome a function of
    the ambient environment instead of the rule: under `umask 002` a freshly
    created directory is `0o775`, so the *valid* case failed on developer
    machines while passing on runners, and under `root` every file is uid 0, so
    the *unowned* case could not be constructed at all and the negative test
    inverted. Both are ambient state leaking into a blocking gate.

    The rule is strict by default: root and the current user are trusted owners,
    and any group or world write bit disqualifies a root regardless of who owns
    it. `allow_group_write` is the one documented relaxation, and it exists
    because running this on a GitHub-hosted runner is what discovered that the
    hosted tool cache -- where `actions/setup-java` installs the JDK -- is group
    writable, so the strict rule refuses every hosted runner. A caller that
    relaxes it must say why, in the same spirit as a ruleset that deliberately
    runs below `active`. World-writable is never allowed, under any flag.
    """
    if facts.uid not in {0, trusted_uid}:
        return f"has an unowned uid {facts.uid} (mode {facts.mode & 0o7777:04o})"
    if facts.mode & stat.S_IWOTH:
        return f"is world writable (mode {facts.mode & 0o7777:04o})"
    if facts.mode & stat.S_IWGRP and not allow_group_write:
        return f"is group writable (mode {facts.mode & 0o7777:04o})"
    return None


@dataclass(frozen=True)
class JvmIdentity:
    requested_major: str
    java_home: str
    java_version: str
    java_runtime_version: str
    java_vendor: str
    java_vm_name: str
    launcher_version: str
    launcher_runtime_version: str
    launcher_vendor: str
    launcher_vm_name: str
    daemon_home: str
    daemon_version: str
    daemon_runtime_version: str
    daemon_vendor: str
    daemon_vm_name: str


def validate_jvm_identity(identity: JvmIdentity) -> None:
    """Require requested, observed, launcher and daemon identities to coincide."""
    if not identity.requested_major.isdigit():
        raise SdkEnvironmentError("requested Java major is not numeric")
    for label, value in (
        ("observed", identity.java_version),
        ("runtime", identity.java_runtime_version),
        ("launcher", identity.launcher_version),
        ("launcher runtime", identity.launcher_runtime_version),
        ("daemon", identity.daemon_version),
        ("daemon runtime", identity.daemon_runtime_version),
    ):
        if not value.startswith(identity.requested_major + "."):
            raise SdkEnvironmentError(f"{label} Java identity does not match requested major")
    if not all((identity.java_vendor, identity.java_vm_name, identity.launcher_vendor,
                identity.launcher_vm_name, identity.daemon_vendor, identity.daemon_vm_name)):
        raise SdkEnvironmentError("JVM vendor/name identity is incomplete")
    if (
        identity.launcher_version != identity.java_version
        or identity.launcher_runtime_version != identity.java_runtime_version
        or identity.launcher_vendor != identity.java_vendor
        or identity.launcher_vm_name != identity.java_vm_name
        or identity.daemon_version != identity.java_version
        or identity.daemon_runtime_version != identity.java_runtime_version
        or identity.daemon_vendor != identity.java_vendor
        or identity.daemon_vm_name != identity.java_vm_name
        or Path(identity.daemon_home) != Path(identity.java_home)
    ):
        raise SdkEnvironmentError("observed, launcher, and daemon JVM identities diverged")


def _canonical_root_path(path: Path) -> Path:
    """Resolve only the one documented Darwin namespace alias."""
    if sys.platform == "darwin" and path.parts[:2] == ("/", "var"):
        candidate = Path("/private").joinpath(*path.parts[1:])
        if not candidate.exists() or not os.path.samefile(path, candidate):
            raise SdkEnvironmentError("Darwin /var alias identity is incoherent")
        return candidate
    return path


def _trusted_root(path: Path, *, label: str, uid: int, allow_group_write: bool = False) -> Path:
    if not path.is_absolute() or not path.is_dir():
        raise SdkEnvironmentError(f"{label} must be an absolute regular directory")
    if path.is_symlink():
        raise SdkEnvironmentError(f"{label} must not be a symlink")
    canonical = _canonical_root_path(path)
    resolved = canonical.resolve(strict=True)
    if resolved != canonical:
        raise SdkEnvironmentError(f"{label} uses an untrusted ancestor alias")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open("/", flags)
    try:
        for component in resolved.parts[1:]:
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        info = os.fstat(descriptor)
        current = resolved.stat()
        if (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino):
            raise SdkEnvironmentError(f"{label} identity changed during validation")
    finally:
        os.close(descriptor)
    problem = ownership_problem(
        OwnershipFacts(info.st_uid, info.st_mode), trusted_uid=uid,
        allow_group_write=allow_group_write,
    )
    if problem is not None:
        raise SdkEnvironmentError(f"{label} {problem}")
    return resolved


def derive_android_environment(
    clean: Mapping[str, str], ambient: Mapping[str, str], *,
    java_executable: Path, java_properties: Mapping[str, str],
    sdkmanager_executable: Path, java_major: str,
    compile_sdk: str, build_tools: str, uid: int | None = None,
    allow_group_write: bool = False,
) -> dict[str, str]:
    """Derive owned roots from verified executables; never inherit SDK text."""
    owner = os.getuid() if uid is None else uid
    java_real = java_executable.resolve(strict=True)
    java_home = _trusted_root(
        Path(str(java_properties.get("java.home", ""))), label="JAVA_HOME", uid=owner,
        allow_group_write=allow_group_write,
    )
    if java_real != (java_home / "bin/java").resolve(strict=True):
        raise SdkEnvironmentError("java executable and observed java.home diverge")
    version = str(java_properties.get("java.version", ""))
    runtime = str(java_properties.get("java.runtime.version", ""))
    if not version.startswith(f"{java_major}.") or not runtime.startswith(f"{java_major}."):
        raise SdkEnvironmentError(
            f"observed Java {version!r}/{runtime!r} does not satisfy JDK {java_major}"
        )

    manager_real = sdkmanager_executable.resolve(strict=True)
    candidates = [parent for parent in manager_real.parents if (
        (parent / "platforms").is_dir() and (parent / "build-tools").is_dir()
    )]
    if len(candidates) != 1:
        raise SdkEnvironmentError("sdkmanager does not identify exactly one Android SDK root")
    android = _trusted_root(
        candidates[0], label="Android SDK root", uid=owner,
        allow_group_write=allow_group_write,
    )
    platform_names = {f"android-{compile_sdk}", f"android-{compile_sdk}.0"}
    if not any((android / "platforms" / name).is_dir() for name in platform_names):
        raise SdkEnvironmentError(f"Android platform {compile_sdk} is missing")
    if not (android / "build-tools" / build_tools).is_dir():
        raise SdkEnvironmentError(f"Android build-tools {build_tools} are missing")

    result = {str(key): str(value) for key, value in clean.items()}
    stripped = sorted(name for name in SDK_NAMES if name in ambient)
    result.update({
        "ANDROID_HOME": str(android),
        "ANDROID_SDK_ROOT": str(android),
        "JAVA_HOME": str(java_home),
        EVIDENCE_NAME: json.dumps({
            "android_root": str(android),
            "build_tools": build_tools,
            "compile_sdk": compile_sdk,
            "java_home": str(java_home),
            "java_runtime_version": runtime,
            "java_version": version,
            "group_writable_roots_allowed": allow_group_write,
            "stripped_ambient": stripped,
        }, sort_keys=True, separators=(",", ":")),
    })
    if result["ANDROID_HOME"] != result["ANDROID_SDK_ROOT"]:
        raise SdkEnvironmentError("canonical Android roots diverged")
    return result
