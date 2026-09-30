#!/usr/bin/env python3
"""Avoid unrelated all-feature metadata downloads for scoped workspace tests.

Cargo still builds the requested targets and features. Dependency-graph filters,
workspace runs and reused builds retain nextest's normal metadata path.
"""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def scoped_packages(args):
    packages = []
    for index, arg in enumerate(args):
        if arg == "--":
            break
        if arg in {"-p", "--package"}:
            if index + 1 >= len(args):
                return []
            packages.append(args[index + 1])
        elif arg.startswith("--package="):
            packages.append(arg.split("=", 1)[1])
        elif arg.startswith("-p") and not arg.startswith("--"):
            packages.append(arg[2:])
    return packages


def use_scoped_metadata(args, cwd):
    if os.environ.get("HEPTA_NEXTTEST_FULL_METADATA") == "1":
        return False
    if not scoped_packages(args):
        return False
    full_metadata_options = {
        "--workspace",
        "--all",
        "--all-features",
        "--exclude",
        "-E",
        "--filterset",
        "--cargo-metadata",
        "--binaries-metadata",
        "--archive-file",
        "--workspace-remap",
        "--manifest-path",
        "--config-file",
        "--tool-config-file",
        "--user-config-file",
        "--config",
        "-Z",
        "--help",
        "-h",
        "--unit-graph",
    }
    for arg in args[: args.index("--") if "--" in args else len(args)]:
        option = arg.split("=", 1)[0]
        if option in full_metadata_options or arg.startswith(("-E", "-Z")):
            return False
    # Graph-based overrides need resolved dependencies, even without -E.
    repo_config = Path(__file__).resolve().parents[1] / "codex-rs/.config/nextest.toml"
    user_config = Path(
        os.environ.get(
            "NEXTEST_USER_CONFIG_FILE",
            Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
            / "nextest/config.toml",
        )
    )
    for config in (cwd / ".config/nextest.toml", repo_config, user_config):
        if config.is_file() and re.search(r"\b(?:rdeps|deps)\s*\(", config.read_text()):
            return False
    return True


def run(args):
    command = ["cargo", "nextest", "run", "--no-fail-fast", *args]
    if not use_scoped_metadata(args, Path.cwd()):
        return subprocess.call(command)
    metadata_command = ["cargo", "metadata", "--no-deps", "--format-version=1"]
    for index, arg in enumerate(args):
        if arg == "--":
            break
        if arg in {"--locked", "--offline", "--frozen"}:
            metadata_command.append(arg)
        elif arg == "--manifest-path" and index + 1 < len(args):
            metadata_command.extend([arg, args[index + 1]])
        elif arg.startswith("--manifest-path="):
            metadata_command.append(arg)
    with tempfile.TemporaryDirectory(prefix="hepta-nextest-") as directory:
        metadata_path = Path(directory) / "metadata.json"
        with metadata_path.open("wb") as output:
            status = subprocess.call(metadata_command, stdout=output)
        if status:
            return status
        metadata = json.loads(metadata_path.read_text())
        workspace_config = Path(metadata["workspace_root"]) / ".config/nextest.toml"
        if workspace_config.is_file() and re.search(
            r"\b(?:rdeps|deps)\s*\(", workspace_config.read_text()
        ):
            return subprocess.call(command)
        workspace_members = set(metadata["workspace_members"])
        names = {
            p["name"] for p in metadata["packages"] if p["id"] in workspace_members
        }
        # Cargo package IDs, globs and external dependencies retain Cargo's
        # ordinary selection semantics rather than approximating them here.
        if not all(package in names for package in scoped_packages(args)):
            return subprocess.call(command)
        separator = command.index("--") if "--" in command else len(command)
        command[separator:separator] = ["--cargo-metadata", str(metadata_path)]
        return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
