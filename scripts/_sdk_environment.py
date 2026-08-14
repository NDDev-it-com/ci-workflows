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


def _trusted_root(path: Path, *, label: str, uid: int) -> Path:
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
    if info.st_uid not in {0, uid}:
        raise SdkEnvironmentError(f"{label} has an unowned uid {info.st_uid}")
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise SdkEnvironmentError(f"{label} is group/world writable")
    return resolved


def derive_android_environment(
    clean: Mapping[str, str], ambient: Mapping[str, str], *,
    java_executable: Path, java_properties: Mapping[str, str],
    sdkmanager_executable: Path, java_major: str,
    compile_sdk: str, build_tools: str, uid: int | None = None,
) -> dict[str, str]:
    """Derive owned roots from verified executables; never inherit SDK text."""
    owner = os.getuid() if uid is None else uid
    java_real = java_executable.resolve(strict=True)
    java_home = _trusted_root(
        Path(str(java_properties.get("java.home", ""))), label="JAVA_HOME", uid=owner,
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
    android = _trusted_root(candidates[0], label="Android SDK root", uid=owner)
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
            "stripped_ambient": stripped,
        }, sort_keys=True, separators=(",", ":")),
    })
    if result["ANDROID_HOME"] != result["ANDROID_SDK_ROOT"]:
        raise SdkEnvironmentError("canonical Android roots diverged")
    return result
