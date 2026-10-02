#!/usr/bin/env python3
"""Check cargo-fmt's full local dependency scope in Windows-safe batches.

`cargo fmt --all` recursively includes the workspaces of path dependencies.
Its single rustfmt command per edition can exceed Windows' command-line limit.
Retain that complete target set, but bound each rustfmt invocation instead.
"""

import argparse
import json
from pathlib import Path
import subprocess


TOOLCHAIN = "1.95.0"
MAX_COMMAND_UNITS = 16_000


def collect_targets(manifest: Path) -> dict[Path, str]:
    pending = [manifest.resolve()]
    visited: set[Path] = set()
    targets: dict[Path, str] = {}
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        metadata = json.loads(
            subprocess.check_output(
                [
                    "cargo",
                    f"+{TOOLCHAIN}",
                    "metadata",
                    "--offline",
                    "--no-deps",
                    "--format-version=1",
                    "--manifest-path",
                    str(current),
                ],
                text=True,
                encoding="utf-8",
            )
        )
        visited.add(current)
        # Cargo returns every workspace member even for a member manifest.
        # Mark them together, then follow every external local dependency.
        packages = metadata["packages"]
        visited.update(Path(p["manifest_path"]).resolve() for p in packages)
        for package in packages:
            for target in package["targets"]:
                path = Path(target["src_path"]).resolve()
                edition = target["edition"]
                if path in targets and targets[path] != edition:
                    raise ValueError(f"conflicting Rust editions for {path}")
                targets[path] = edition
            for dependency in package["dependencies"]:
                if dependency.get("path") is not None:
                    pending.append((Path(dependency["path"]) / "Cargo.toml").resolve())
    if not targets:
        raise ValueError("Cargo metadata contains no formatting targets")
    return targets


def command_units(command: list[str]) -> int:
    # CreateProcessW counts UTF-16 code units, including quoting and terminator.
    return len(subprocess.list2cmdline(command).encode("utf-16-le")) // 2 + 1


def format_commands(targets: dict[Path, str]) -> list[list[str]]:
    commands = []
    for edition in sorted(set(targets.values())):
        prefix = [
            "rustup",
            "run",
            TOOLCHAIN,
            "rustfmt",
            "--check",
            "--edition",
            edition,
        ]
        command = prefix.copy()
        for path in sorted(path for path in targets if targets[path] == edition):
            argument = str(path)
            if command_units([*prefix, argument]) > MAX_COMMAND_UNITS:
                raise ValueError(f"formatting target exceeds command limit: {path}")
            if command_units([*command, argument]) > MAX_COMMAND_UNITS:
                commands.append(command)
                command = prefix.copy()
            command.append(argument)
        commands.append(command)
    return commands


def check_format(manifest: Path) -> int:
    targets = collect_targets(manifest)
    commands = format_commands(targets)
    print(
        f"Checking {len(targets)} Cargo targets in {len(commands)} batches", flush=True
    )
    failed = False
    for command in commands:
        if subprocess.run(command, check=False).returncode != 0:
            failed = True
    return int(failed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-path", type=Path, required=True)
    return check_format(parser.parse_args().manifest_path)


if __name__ == "__main__":
    raise SystemExit(main())
