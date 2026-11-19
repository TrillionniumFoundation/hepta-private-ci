#!/usr/bin/env python3
"""Prepare the existing V8 pair for native Hepta CI or an explicit local command."""

import os
import subprocess
import sys
from pathlib import Path


def resolve_v8_environment(repo_root: Path) -> dict[str, str]:
    # Import only after the entrypoint validates CODEX_REPO_ROOT. Reuse the
    # packaging resolver so archive/binding selection and checksum checks do
    # not acquire a second, divergent implementation in workflow YAML.
    from codex_package.targets import TARGET_SPECS
    from codex_package.v8 import resolve_codex_v8_cargo_env

    version = subprocess.check_output(
        ["rustc", "-vV"], cwd=repo_root / "codex-rs", text=True, timeout=60
    )
    hosts = [
        line.removeprefix("host: ").strip()
        for line in version.splitlines()
        if line.startswith("host: ")
    ]
    if len(hosts) != 1 or hosts[0] not in TARGET_SPECS:
        raise RuntimeError(f"Expected one supported Rust host, found {hosts!r}")

    overrides = resolve_codex_v8_cargo_env(TARGET_SPECS[hosts[0]])
    allowed = {"RUSTY_V8_ARCHIVE", "RUSTY_V8_SRC_BINDING_PATH"}
    if overrides and set(overrides) != allowed:
        raise RuntimeError("V8 resolver must return an archive and binding together")
    # Validate the complete result before exporting it or launching a child.
    for value in overrides.values():
        if not isinstance(value, str) or not value or any(c in value for c in "\r\n\0"):
            raise RuntimeError(
                "V8 artifact path cannot be empty or contain control characters"
            )
    return overrides


def configure_v8(repo_root: Path, environment_file: Path) -> None:
    overrides = resolve_v8_environment(repo_root)
    if overrides:
        with environment_file.open("a", encoding="utf-8", newline="\n") as output:
            output.write(
                "".join(
                    f"{name}={value}\n" for name, value in sorted(overrides.items())
                )
            )


def run_with_v8(repo_root: Path, command: list[str]) -> int:
    if not command:
        raise RuntimeError("--run requires an explicit command")
    environment = os.environ.copy()
    environment.update(resolve_v8_environment(repo_root))
    return subprocess.call(command, cwd=repo_root / "codex-rs", env=environment)


def main() -> int:
    arguments = sys.argv[1:]
    if arguments and (arguments[0] != "--run" or len(arguments) == 1):
        raise RuntimeError("Usage: hepta_ci_v8.py [--run COMMAND [ARG ...]]")
    root = os.environ.get("CODEX_REPO_ROOT")
    destination = os.environ.get("GITHUB_ENV")
    if not root or (not arguments and not destination):
        raise RuntimeError(
            "CODEX_REPO_ROOT is required; CI export also requires GITHUB_ENV"
        )
    repo_root = Path(root).resolve(strict=True)
    if not (repo_root / "codex-rs" / "Cargo.lock").is_file():
        raise RuntimeError("CODEX_REPO_ROOT does not contain the locked Rust workspace")
    if arguments:
        return run_with_v8(repo_root, arguments[1:])
    configure_v8(repo_root, Path(destination))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
