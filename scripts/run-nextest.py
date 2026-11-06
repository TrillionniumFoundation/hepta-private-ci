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


# Cross-package runtime dependencies already declared by these crates' Bazel
# targets and exercised by their Rust fixtures. Cargo/nextest only exposes a
# package's own binaries, even when every workspace package was built.
# Platform-specific targets retain their own Rust cfgs; Cargo, not this runner,
# chooses the requested target. Do not infer an OS or an output directory here.
RUNTIME_TEST_HELPERS = {
    "codex-core": (
        ("codex-cli", "codex"),
        ("codex-code-mode-host", "codex-code-mode-host"),
        ("codex-linux-sandbox", "codex-linux-sandbox"),
        ("codex-rmcp-client", "test_stdio_server"),
        ("codex-rmcp-client", "test_streamable_http_server"),
        ("codex-shell-escalation", "codex-execve-wrapper"),
        ("codex-windows-sandbox", "codex-command-runner"),
        ("codex-windows-sandbox", "codex-windows-sandbox-setup"),
    ),
    "codex-app-server": (
        ("codex-cli", "codex"),
        ("codex-code-mode-host", "codex-code-mode-host"),
        ("codex-rmcp-client", "test_stdio_server"),
    ),
    "codex-rmcp-client": (("codex-cli", "codex"),),
    "codex-tui": (("codex-cli", "codex"),),
    "codex-cli": (
        ("codex-windows-sandbox", "codex-command-runner"),
        ("codex-windows-sandbox", "codex-windows-sandbox-setup"),
    ),
    "codex-exec-server": (
        ("codex-bwrap", "bwrap"),
        ("codex-windows-sandbox", "codex-command-runner"),
        ("codex-windows-sandbox", "codex-windows-sandbox-setup"),
    ),
}


class RuntimeHelperError(Exception):
    def __init__(self, message, status=2):
        super().__init__(message)
        self.status = status


def runtime_build_options(args):
    """Separate Cargo build inputs from nextest configuration without guessing."""
    options = {
        "packages": [], "exclude": [], "workspace": False,
        "manifest": None, "cargo": [], "metadata": [], "unsupported": [],
        "targets": [], "profile": None, "release": False, "bypass": False,
    }
    cargo_values = {
        "--target": "--target", "--target-dir": "--target-dir",
        "--cargo-profile": "--profile", "--build-jobs": "--jobs",
        "--features": "--features", "-F": "--features",
        "--config": "--config", "--manifest-path": "--manifest-path",
    }
    test_values = {
        "-E", "--filterset", "-P", "--profile", "--test", "--bin",
        "--example", "--bench", "--config-file", "--tool-config-file",
        "--user-config-file", "--cargo-message-format", "--message-format",
        "--message-format-version", "--test-threads", "--retries",
        "--status-level", "--final-status-level", "--failure-output", "-j",
        "--success-output", "--no-tests", "--partition", "--color",
    }
    test_flags = {
        "--lib", "--bins", "--tests", "--examples", "--benches",
        "--all-targets", "--no-fail-fast", "--fail-fast", "--no-run",
        "--no-capture", "--nocapture", "--hide-progress-bar",
        "--override-version-check", "--ignore-default-filter", "--verbose",
        "-v", "--quiet", "-q",
    }
    reuse_values = {
        "--archive-file", "--archive-format", "--binaries-metadata",
        "--cargo-metadata", "--workspace-remap", "--target-dir-remap",
        "--extract-to",
    }
    values = set(cargo_values) | test_values | reuse_values | {
        "-p", "--package", "--exclude", "--run-ignored",
    }
    index = 0
    while index < len(args) and args[index] != "--":
        arg = args[index]
        key, equal, value = arg.partition("=")
        for short in ("-p", "-F", "-E", "-P", "-j"):
            if arg.startswith(short) and arg != short:
                key, equal, value = short, "=", arg[len(short):].removeprefix("=")
                break
        if key in values:
            if not equal:
                index += 1
                negative_jobs = (
                    index < len(args) and key in {"--build-jobs", "--test-threads", "-j"}
                    and re.fullmatch(r"-\d+", args[index])
                )
                if index >= len(args) or (args[index].startswith("-") and not negative_jobs):
                    # Let nextest report its original malformed CLI diagnostic.
                    options["bypass"] = True
                    return options
                value = args[index]
            if not value:
                options["bypass"] = True
                return options
            if key in {"-p", "--package"}:
                options["packages"].append(value)
            elif key == "--exclude":
                options["exclude"].append(value)
            elif key in cargo_values:
                options["cargo"].extend([cargo_values[key], value])
                if key in {"--manifest-path", "--config"}:
                    options["metadata"].extend([key, value])
                if key == "--manifest-path":
                    if options["manifest"] is not None:
                        options["unsupported"].append("multiple --manifest-path values")
                    options["manifest"] = value
                elif key == "--target":
                    options["targets"].append(value)
                elif key == "--cargo-profile":
                    if options["profile"] is not None:
                        options["unsupported"].append("multiple Cargo profiles")
                    options["profile"] = value
            elif key in reuse_values:
                # Reused builds already own their binary metadata and path
                # remapping. Retain the original runner's pass-through path.
                options["bypass"] = True
        elif key in {"--workspace", "--all"} and not equal:
            options["workspace"] = True
        elif key in {"--locked", "--offline", "--frozen"} and not equal:
            options["cargo"].append(key)
            options["metadata"].append(key)
        elif key in {"--all-features", "--no-default-features"} and not equal:
            options["cargo"].append(key)
        elif key in {"--release", "-r"} and not equal:
            options["release"] = True
            options["cargo"].append("--release")
        elif key == "--timings":
            options["cargo"].append(arg)
        elif key in {"--help", "-h", "--version", "-V", "--unit-graph"}:
            options["bypass"] = True
        elif key in test_flags and not equal:
            pass
        elif arg.startswith("-"):
            options["unsupported"].append(arg)
        index += 1
    if len(options["targets"]) > 1:
        options["unsupported"].append("multiple target triples")
    if options["release"] and options["profile"] is not None:
        options["unsupported"].append("--release with --cargo-profile")
    if options["workspace"] and options["packages"]:
        options["bypass"] = True
    if options["exclude"] and not options["workspace"]:
        options["bypass"] = True
    return options


def selected_workspace_packages(metadata, options):
    members = set(metadata["workspace_members"])
    packages = {p["id"]: p for p in metadata["packages"] if p["id"] in members}

    def resolve(selector):
        matches = [
            p["id"] for p in packages.values()
            if selector in {p["id"], p["name"], f'{p["name"]}@{p["version"]}'}
        ]
        # Cargo retains ownership of globs, external packages and other package
        # ID syntax. Do not narrow those previously supported invocations here.
        return matches[0] if len(matches) == 1 else None

    if options["workspace"]:
        selected = members
    elif options["packages"]:
        selected = {resolve(selector) for selector in options["packages"]}
        if None in selected:
            return packages, None
    else:
        manifest = options["manifest"]
        if manifest is None:
            manifest = next(
                (p / "Cargo.toml" for p in (Path.cwd(), *Path.cwd().parents)
                 if (p / "Cargo.toml").is_file()), None,
            )
        manifest = Path(manifest).resolve() if manifest is not None else None
        if manifest is not None and manifest.parent != Path(metadata["workspace_root"]).resolve():
            selected = {p["id"] for p in packages.values()
                        if Path(p["manifest_path"]).resolve() == manifest}
            if len(selected) != 1:
                return packages, None
        else:
            defaults = metadata.get("workspace_default_members")
            if defaults is None or not set(defaults) <= members:
                raise RuntimeHelperError("Cargo metadata lacks valid workspace default members")
            selected = set(defaults)
    excluded = {resolve(selector) for selector in options["exclude"]}
    if None in excluded:
        return packages, None
    selected -= excluded
    return packages, selected


def helper_env_keys(name):
    names = [name] if "-" not in name else [name, name.replace("-", "_")]
    return [f"{prefix}_{variant}" for prefix in ("CARGO_BIN_EXE", "NEXTEST_BIN_EXE")
            for variant in names]


def helper_executable(value, label):
    path = Path(value)
    if not path.is_absolute() or not path.is_file():
        raise RuntimeHelperError(f"{label} must name an existing absolute executable file: {value!r}")
    if os.name != "nt" and not os.access(path, os.X_OK):
        raise RuntimeHelperError(f"{label} is not executable on this host: {value!r}")
    return str(path)


def helper_cargo_arguments(options, packages, selected):
    """Keep feature selection on the test scope when adding binary owners."""
    original = [packages[package_id] for package_id in sorted(selected)]
    by_name = {package["name"]: package for package in original}
    arguments = []
    features = set()
    values = iter(options["cargo"])
    for value in values:
        if value == "--all-features":
            features.update(f'{p["name"]}/{feature}'
                            for p in original for feature in p["features"])
        elif value == "--features":
            for feature in re.split(r"[\s,]+", next(values).strip()):
                if not feature:
                    continue
                if "/" in feature:
                    owner, _, name = feature.partition("/")
                    if owner not in by_name or name not in by_name[owner]["features"]:
                        raise RuntimeHelperError(
                            "runtime helper features must name a declared feature of an "
                            f"originally selected workspace package: {feature!r}"
                        )
                    features.add(feature)
                else:
                    matches = [p for p in original if feature in p["features"]]
                    if not matches:
                        raise RuntimeHelperError(f"feature absent from selected test packages: {feature!r}")
                    features.update(f'{p["name"]}/{feature}' for p in matches)
        else:
            arguments.append(value)
    if features:
        arguments.extend(["--features", ",".join(sorted(features))])
    return arguments


def helper_artifacts(output, expected):
    """Accept Cargo's actual non-test executable receipts, bound to their owners."""
    found = {key: set() for key in expected}
    finished = []
    for line in output.splitlines():
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as error:
            raise RuntimeHelperError("Cargo helper build emitted non-JSON artifact output") from error
        if not isinstance(message, dict):
            raise RuntimeHelperError("Cargo helper artifact message must be a JSON object")
        if message.get("reason") == "build-finished":
            finished.append(message.get("success"))
        if message.get("reason") != "compiler-artifact":
            continue
        target = message.get("target", {})
        if not isinstance(target, dict) or not isinstance(message.get("profile", {}), dict):
            raise RuntimeHelperError("Cargo helper artifact has invalid target/profile metadata")
        key = (message.get("package_id"), target.get("name"))
        if key not in expected or message.get("profile", {}).get("test") is not False:
            continue
        if target.get("kind") != ["bin"] or target.get("src_path") != expected[key]["src_path"]:
            raise RuntimeHelperError(f"Cargo helper target identity mismatch: {key[1]}")
        executable = message.get("executable")
        if not isinstance(executable, str):
            raise RuntimeHelperError(f"Cargo helper artifact has no executable: {key[1]}")
        found[key].add(helper_executable(executable, f"Cargo artifact {key[1]}"))
    if finished != [True]:
        raise RuntimeHelperError("Cargo helper build lacks one successful build-finished receipt")
    for key, paths in found.items():
        if len(paths) != 1:
            raise RuntimeHelperError(f"Cargo helper executable is missing or ambiguous: {key[1]}")
    return {key: next(iter(paths)) for key, paths in found.items()}


def emit_cargo_diagnostics(output):
    """Keep Cargo's real errors visible while consuming its artifact stream."""
    for line in output.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            if line.strip():
                print(line, file=sys.stderr)
            continue
        if isinstance(message, dict) and message.get("reason") == "compiler-message":
            diagnostic = message.get("message", {})
            rendered = diagnostic.get("rendered") or diagnostic.get("message")
            if rendered:
                print(rendered, file=sys.stderr, end="" if rendered.endswith("\n") else "\n")


def runtime_helper_environment(args, metadata=None, environment=None):
    options = runtime_build_options(args)
    if options["bypass"]:
        return None
    environment = dict(os.environ if environment is None else environment)
    if metadata is None:
        result = subprocess.run(
            ["cargo", "metadata", "--no-deps", "--format-version=1", *options["metadata"]],
            stdout=subprocess.PIPE, text=True, check=False,
        )
        if result.returncode:
            emit_cargo_diagnostics(result.stdout)
            raise RuntimeHelperError("Cargo could not resolve runtime helper owners", result.returncode)
        try:
            metadata = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            emit_cargo_diagnostics(result.stdout)
            raise RuntimeHelperError("Cargo emitted invalid runtime helper metadata") from error
    members = set(metadata["workspace_members"])
    if not any(p["name"] in RUNTIME_TEST_HELPERS and p["id"] in members
               for p in metadata["packages"]):
        return None
    packages, selected = selected_workspace_packages(metadata, options)
    if selected is None:
        return None
    required = {helper for package_id in selected
                for helper in RUNTIME_TEST_HELPERS.get(packages[package_id]["name"], ())}
    if not required:
        return None
    expected = {}
    for owner, name in sorted(required):
        declared = [p for p in packages.values() if p["name"] == owner]
        if len(declared) != 1:
            raise RuntimeHelperError(f"runtime helper owner missing or ambiguous: {owner}")
        package = declared[0]
        targets = [t for t in package["targets"] if t["name"] == name and t["kind"] == ["bin"]]
        if len(targets) != 1:
            raise RuntimeHelperError(f"runtime helper target missing or ambiguous: {owner}/{name}")
        for key in helper_env_keys(name):
            if key in environment:
                # Match cargo_bin's precedence, including invalid explicit values.
                helper_executable(environment[key], key)
                break
        else:
            expected[(package["id"], name)] = targets[0]
    if not expected:
        return environment
    if options["unsupported"]:
        raise RuntimeHelperError(
            "runtime helper preparation does not support " + ", ".join(options["unsupported"])
            + "; use a source-build invocation with exact package/profile/target inputs "
            "or provide the declared helpers explicitly"
        )
    command = ["cargo", "build", *helper_cargo_arguments(options, packages, selected)]
    if options["profile"] is None and not options["release"]:
        command.extend(["--profile", "test"])
    # Retain the original package scope for feature selection; helper owners are
    # explicit build prerequisites, including when their own tests are excluded.
    for package_id in sorted(selected | {key[0] for key in expected}):
        command.extend(["--package", package_id])
    for name in sorted({key[1] for key in expected}):
        command.extend(["--bin", name])
    command.append("--message-format=json-render-diagnostics")
    print("Preparing declared runtime helpers: " + ", ".join(sorted(key[1] for key in expected)),
          file=sys.stderr, flush=True)
    result = subprocess.run(command, stdout=subprocess.PIPE, text=True, check=False, env=environment)
    emit_cargo_diagnostics(result.stdout)
    if result.returncode:
        raise RuntimeHelperError("Cargo runtime helper build failed", result.returncode)
    for (_, name), executable in helper_artifacts(result.stdout, expected).items():
        for key in helper_env_keys(name):
            if key.startswith("CARGO_BIN_EXE_"):
                environment[key] = executable
        print(f"Runtime helper {name}: {executable}", file=sys.stderr, flush=True)
    return environment


def run_nextest_command(command, args, metadata=None):
    try:
        environment = runtime_helper_environment(args, metadata)
    except RuntimeHelperError as error:
        print(f"error: {error}", file=sys.stderr)
        return error.status
    return subprocess.call(command, env=environment)


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
        return run_nextest_command(command, args)
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
            return run_nextest_command(command, args, metadata)
        workspace_members = set(metadata["workspace_members"])
        names = {
            p["name"] for p in metadata["packages"] if p["id"] in workspace_members
        }
        # Cargo package IDs, globs and external dependencies retain Cargo's
        # ordinary selection semantics rather than approximating them here.
        if not all(package in names for package in scoped_packages(args)):
            return run_nextest_command(command, args, metadata)
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
        return run_nextest_command(command, args, metadata)


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
