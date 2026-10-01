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


class GraphFreeFilter:
    """Recognize a bounded, graph-free subset of nextest's filterset grammar.

    This only selects a metadata strategy. Nextest still parses and evaluates
    the original expression. Unknown predicates, default-filter expansion and
    opaque syntax keep full metadata. Matcher contents are never predicates.
    """

    matchers = {"test", "package", "binary", "binary_id", "kind", "platform"}

    def __init__(self, expression):
        self.expression = expression
        self.offset = 0

    def skip_space(self):
        while (
            self.offset < len(self.expression)
            and self.expression[self.offset].isspace()
        ):
            self.offset += 1

    def token(self, token):
        self.skip_space()
        if not self.expression.startswith(token, self.offset):
            return False
        end = self.offset + len(token)
        if token.isalpha() and end < len(self.expression):
            if self.expression[end].isalnum() or self.expression[end] == "_":
                return False
        self.offset = end
        return True

    def expression_node(self, depth=0):
        if depth > 64 or not self.atom(depth):
            return False
        while any(
            self.token(operator) for operator in ("&", "|", "+", "-", "and", "or")
        ):
            if not self.atom(depth):
                return False
        return True

    def atom(self, depth):
        if self.token("!") or self.token("not"):
            return self.atom(depth + 1) if depth < 64 else False
        if self.token("("):
            return self.expression_node(depth + 1) and self.token(")")
        self.skip_space()
        start = self.offset
        while self.offset < len(self.expression) and (
            self.expression[self.offset].isalnum()
            or self.expression[self.offset] == "_"
        ):
            self.offset += 1
        name = self.expression[start : self.offset]
        if name not in self.matchers | {"all", "none"} or not self.token("("):
            return False
        if name in {"all", "none"}:
            return self.token(")")
        return self.matcher() and self.token(")")

    def matcher(self):
        self.skip_space()
        start = self.offset
        if self.offset < len(self.expression) and self.expression[self.offset] == "/":
            # Regex parentheses, commas and words such as deps are matcher data.
            self.offset += 1
            escaped = False
            while self.offset < len(self.expression):
                char = self.expression[self.offset]
                self.offset += 1
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == "/":
                    return self.offset > start + 2
            return False
        while self.offset < len(self.expression):
            char = self.expression[self.offset]
            if char == ")":
                return bool(self.expression[start : self.offset].strip().lstrip("=~#"))
            if char in "(,":
                return False
            self.offset += 1
            if char != "\\":
                continue
            if self.offset >= len(self.expression):
                return False
            escape = self.expression[self.offset]
            self.offset += 1
            if escape in "nrt\\/),":
                continue
            if escape != "u" or not self.expression.startswith("{", self.offset):
                return False
            end = self.expression.find("}", self.offset + 1)
            digits = self.expression[self.offset + 1 : end] if end >= 0 else ""
            if not re.fullmatch(r"[0-9a-fA-F]{1,6}", digits):
                return False
            scalar = int(digits, 16)
            if scalar > 0x10FFFF or 0xD800 <= scalar <= 0xDFFF:
                return False
            self.offset = end + 1
        return False

    def recognized(self):
        if not self.expression or len(self.expression) > 16384:
            return False
        if not self.expression_node():
            return False
        self.skip_space()
        return self.offset == len(self.expression)


def graph_free_filter(expression):
    return GraphFreeFilter(expression).recognized()


def filtersets(args):
    """Extract explicit -E forms without interpreting arguments after --."""
    expressions = []
    index = 0
    while index < len(args) and args[index] != "--":
        arg = args[index]
        if arg in {"-E", "--filterset"}:
            index += 1
            if index >= len(args) or args[index] == "--":
                return None
            expressions.append(args[index])
        elif arg.startswith("--filterset="):
            expressions.append(arg.split("=", 1)[1])
        elif arg.startswith("-E"):
            expressions.append(arg[2:].removeprefix("="))
        index += 1
    return expressions


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
    expressions = filtersets(args)
    if expressions is None or not all(
        graph_free_filter(expression) for expression in expressions
    ):
        return False
    full_metadata_options = {
        "--workspace",
        "--all",
        "--all-features",
        "--exclude",
        "--cargo-metadata",
        "--binaries-metadata",
        "--archive-file",
        "--workspace-remap",
        "--config-file",
        "--tool-config-file",
        "--user-config-file",
        "--config",
        "-Z",
        "--help",
        "-h",
        "--unit-graph",
    }
    cargo_args = args[: args.index("--") if "--" in args else len(args)]
    for index, arg in enumerate(cargo_args):
        option = arg.split("=", 1)[0]
        if option in full_metadata_options or arg.startswith("-Z"):
            return False
        if arg == "--manifest-path" and (
            index + 1 == len(cargo_args) or cargo_args[index + 1].startswith("-")
        ):
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
        # Nextest derives its build manifest from the supplied metadata and
        # rejects combining --manifest-path with --cargo-metadata. Keep the
        # original arguments for fallback; remove only this resolved selector.
        build_args = []
        arguments = iter(args)
        for arg in arguments:
            if arg == "--":
                build_args.extend([arg, *arguments])
                break
            if arg == "--manifest-path":
                next(arguments)
            elif not arg.startswith("--manifest-path="):
                build_args.append(arg)
        command = ["cargo", "nextest", "run", "--no-fail-fast", *build_args]
        separator = command.index("--") if "--" in command else len(command)
        command[separator:separator] = ["--cargo-metadata", str(metadata_path)]
        return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
