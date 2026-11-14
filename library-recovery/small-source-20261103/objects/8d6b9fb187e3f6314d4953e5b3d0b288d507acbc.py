"""Fail-closed repository Cargo configuration source & process overrides.

Advisory static source check, not a substitute for hermetic cargo execution,
locked dependency checks, or independent signing/authority controls.
"""
from __future__ import annotations

from pathlib import Path
import tomllib

CELL_CRATES = (
    "hepta-types", "hepta-neuron", "hepta-intuition", "hepta-ndu", "hepta-plasticity",
    "hepta-infer-core", "hepta-cognitive-types",
)
CARGO_CONFIG_NAMES = ("config", "config.toml")
# Existing reviewed Windows target flags in codex-rs/.cargo/config.toml.
# This is a closed source-profile allowlist; arbitrary target rustflags can
# modify cfg decisions, link libraries, or alter the generated binary.
APPROVED_WINDOWS_RUSTFLAGS = {
    'cfg(all(windows, target_env = "msvc"))': [
        "-C", "link-arg=/STACK:8388608", "-C", "target-feature=+crt-static",
    ],
    "aarch64-pc-windows-msvc": [
        "-C", "link-arg=/STACK:8388608", "-C", "link-arg=/arm64hazardfree",
    ],
    'cfg(all(windows, target_env = "gnu"))': [
        "-C", "link-arg=-Wl,--stack,8388608",
    ],
}


def check_cargo_configuration_sources(root: Path) -> list[str]:
    """Deny repository-configured source rebinding and hidden executable hooks.

    Cargo may load .cargo/config.toml in ancestor directories of its invocation;
    also check protected member directories for per-crate invocations. This
    cannot inspect user CARGO_HOME, command-line --config, or process env.
    """
    violations: list[str] = []
    workspace_root = root / "codex-rs"
    directories = (root, workspace_root, *(workspace_root / name for name in CELL_CRATES))
    for directory in directories:
        cargo_dir = directory / ".cargo"
        rel = cargo_dir.relative_to(root).as_posix()
        if cargo_dir.is_symlink():
            violations.append(f"workspace: {rel} is a symbolic link")
            continue
        if not cargo_dir.exists():
            continue
        if not cargo_dir.is_dir():
            violations.append(f"workspace: {rel} must be a directory")
            continue
        for filename in CARGO_CONFIG_NAMES:
            config_file = cargo_dir / filename
            place = config_file.relative_to(root).as_posix()
            if config_file.is_symlink():
                violations.append(f"workspace: {place} is a symbolic link")
                continue
            if not config_file.exists():
                continue
            if not config_file.is_file():
                violations.append(f"workspace: {place} must be a regular config file")
                continue
            try:
                config = tomllib.loads(config_file.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
                violations.append(f"workspace: unreadable Cargo configuration {place}: {exc}")
                continue
            # These can replace even a manifest- and lock-allowed external crate.
            for key in ("source", "registry", "registries"):
                if key in config:
                    violations.append(f"workspace: {place} has unreviewed [{key}] source override")
            configured_env = config.get("env", {})
            if not isinstance(configured_env, dict):
                violations.append(f"workspace: {place} has malformed [env] configuration")
            else:
                # Arbitrary environment variables can change the compiler or
                # native libraries (LD_PRELOAD, PATH, CC, RUSTUP_TOOLCHAIN).
                # The checked-in baseline has no [env] entries.
                for key in configured_env:
                    violations.append(f"workspace: {place} configures unreviewed build environment {key!r}")
            build = config.get("build", {})
            if not isinstance(build, dict):
                violations.append(f"workspace: {place} has malformed [build] configuration")
            else:
                for key in ("rustc", "rustc-wrapper", "rustc-workspace-wrapper", "rustdoc", "rustflags", "rustdocflags", "target", "target-dir"):
                    if key in build:
                        violations.append(f"workspace: {place} defines unreviewed compiler executable {key}")
            targets = config.get("target", {})
            if not isinstance(targets, dict):
                violations.append(f"workspace: {place} has malformed [target] configuration")
            else:
                for triple, definition in targets.items():
                    if not isinstance(definition, dict):
                        violations.append(f"workspace: {place} has malformed target {triple!r}")
                    else:
                        for key in ("runner", "linker", "rustdocflags"):
                            if key in definition:
                                violations.append(f"workspace: {place} defines unreviewed target {triple!r} {key}")
                        if "rustflags" in definition and (
                            place != "codex-rs/.cargo/config.toml"
                            or triple not in APPROVED_WINDOWS_RUSTFLAGS
                            or definition["rustflags"] != APPROVED_WINDOWS_RUSTFLAGS[triple]
                        ):
                            violations.append(
                                f"workspace: {place} defines unreviewed target {triple!r} rustflags"
                            )
    return violations
