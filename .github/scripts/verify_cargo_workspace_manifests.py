#!/usr/bin/env python3

"""Check workspace metadata; Cargo owns feature and dependency syntax.

Feature declarations are build configuration, not runtime grants. Real profile
activation and Cargo/Bazel parity remain separate executable checks. This gate
does not require editing a parallel feature-name allowlist for normal development.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CARGO_RS_ROOT = ROOT / "codex-rs"
WORKSPACE_PACKAGE_FIELDS = ("version", "edition", "license")
TOP_LEVEL_NAME_EXCEPTIONS = {"windows-sandbox-rs": "codex-windows-sandbox"}
UTILITY_NAME_EXCEPTIONS = {"path-utils": "codex-utils-path"}


def cargo_manifest_errors(workspace: Path) -> list[str]:
    """Ask Cargo to parse the actual graph without builds, downloads or lock writes.

    --no-deps checks manifests and feature syntax, not resolved external features
    or profile compilation. Those remain the native/Bazel checks' responsibility.
    """
    try:
        result = subprocess.run(
            [
                "cargo",
                "metadata",
                "--locked",
                "--offline",
                "--no-deps",
                "--format-version=1",
                "--manifest-path",
                str(workspace / "Cargo.toml"),
            ],
            cwd=workspace,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        return [f"Cargo manifest validation unavailable: {error}"]
    return (
        []
        if result.returncode == 0
        else [result.stderr.strip() or "Cargo manifest validation failed"]
    )


def main() -> int:
    failures_by_path = {}
    for path in manifests_to_verify():
        try:
            errors = manifest_errors(path)
        except (OSError, ValueError) as error:
            errors = [str(error)]
        if errors:
            failures_by_path[manifest_key(path)] = errors
    cargo_errors = cargo_manifest_errors(CARGO_RS_ROOT)
    if cargo_errors:
        failures_by_path.setdefault("codex-rs/Cargo.toml", []).extend(cargo_errors)
    if not failures_by_path:
        return 0
    print(
        "Cargo manifests must inherit workspace metadata/lints, use canonical package names, and pass Cargo manifest validation."
    )
    for path, errors in sorted(failures_by_path.items()):
        print(f"{path}:")
        for error in errors:
            print(f"  - {error}")
    return 1


def manifest_errors(path: Path) -> list[str]:
    manifest = load_manifest(path)
    # cargo-fuzz crates intentionally use a nested standalone workspace so they
    # do not become members of the product workspace. Their isolated manifest
    # cannot inherit package metadata or workspace lints from codex-rs without
    # changing that build topology. Keep the exception structural and narrow:
    # only a manifest under a `fuzz` directory with cargo-fuzz metadata and its
    # own workspace root is exempt from product-workspace inheritance checks.
    if is_isolated_cargo_fuzz_workspace(path, manifest):
        return []
    package = manifest.get("package")
    if not isinstance(package, dict) and path != CARGO_RS_ROOT / "Cargo.toml":
        return []

    errors = []
    if isinstance(package, dict):
        for field in WORKSPACE_PACKAGE_FIELDS:
            if not is_workspace_reference(package.get(field)):
                errors.append(f"set `{field}.workspace = true` in `[package]`")

        lints = manifest.get("lints")
        if not (isinstance(lints, dict) and lints.get("workspace") is True):
            errors.append("add `[lints]` with `workspace = true`")

        expected_name = expected_package_name(path)
        if expected_name is not None:
            actual_name = package.get("name")
            if actual_name != expected_name:
                errors.append(
                    f"set `[package].name` to `{expected_name}` (found `{actual_name}`)"
                )

    return errors


def is_isolated_cargo_fuzz_workspace(path: Path, manifest: dict) -> bool:
    try:
        relative = path.relative_to(CARGO_RS_ROOT)
    except ValueError:
        return False
    # Only <workspace-crate>/fuzz/Cargo.toml is an isolated cargo-fuzz root.
    if (
        len(relative.parts) != 3
        or relative.parts[1] != "fuzz"
        or relative.parts[2] != "Cargo.toml"
        or not isinstance(manifest.get("workspace"), dict)
    ):
        return False
    package = manifest.get("package")
    if not isinstance(package, dict):
        return False
    metadata = package.get("metadata")
    return isinstance(metadata, dict) and metadata.get("cargo-fuzz") is True


def expected_package_name(path: Path) -> str | None:
    parts = path.relative_to(CARGO_RS_ROOT).parts
    if len(parts) == 2 and parts[1] == "Cargo.toml":
        directory = parts[0]
        return TOP_LEVEL_NAME_EXCEPTIONS.get(
            directory,
            directory if directory.startswith("codex-") else f"codex-{directory}",
        )
    if len(parts) == 3 and parts[0] == "utils" and parts[2] == "Cargo.toml":
        directory = parts[1]
        return UTILITY_NAME_EXCEPTIONS.get(directory, f"codex-utils-{directory}")
    return None


def is_workspace_reference(value: object) -> bool:
    return isinstance(value, dict) and value.get("workspace") is True


def manifest_key(path: Path) -> str:
    return str(path.relative_to(ROOT))


def load_manifest(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def cargo_manifests() -> list[Path]:
    # Git's source inventory excludes build outputs and ignored environments.
    # Include ordinary untracked additions so local preflight sees new crates.
    raw = subprocess.check_output(
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            "codex-rs/**/Cargo.toml",
        ],
        cwd=ROOT,
    )
    return sorted(
        {
            ROOT / value.decode("utf-8")
            for value in raw.split(b"\0")
            if value
            and "third_party" not in Path(value.decode("utf-8")).parts
            and (ROOT / value.decode("utf-8")).is_file()
        }
    )


def manifests_to_verify() -> list[Path]:
    return [CARGO_RS_ROOT / "Cargo.toml", *cargo_manifests()]


if __name__ == "__main__":
    sys.exit(main())
