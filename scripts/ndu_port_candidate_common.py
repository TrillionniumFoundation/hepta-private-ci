"""Exact-source and artifact guards for the independent dependency-port CI."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import time
import tomllib


SCHEMA = "hepta.ci.port-candidate.v1"
RECIPE = "experiments/multimodal_output_portfolio/closure_v2_20261027/ci/port-remediation/RECIPE.json"
LOCKS = ("codex-rs/Cargo.lock", "MODULE.bazel.lock")
POLICIES = (
    "codex-rs/deny.toml",
    ".github/workflows/cargo-deny.yml",
    "scripts/cargo_deny_diagnostics.py",
)
OLD_SOURCE = "6215cb6a87f29623d4beaad24cdf7bcb6bb4fb2c"
HEX256 = re.compile(r"[0-9a-f]{64}\Z")
PACKAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:@[A-Za-z0-9.+_-]+)?\Z")


def checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative_path(name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise ValueError(f"Invalid relative path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or path.as_posix() != name or ".." in path.parts:
        raise ValueError(f"Noncanonical relative path: {name!r}")
    if any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise ValueError("Control characters are not valid artifact paths")
    return name


def regular_path(root, name):
    path = root / relative_path(name)
    for component in (path, *path.parents):
        if component == root:
            break
        if component.is_symlink():
            raise ValueError(f"Symlink in bound file path: {name}")
    return path


def describe(root, names, *, allow_missing=False):
    result = {}
    for name in sorted(names):
        path = regular_path(root, name)
        if allow_missing and not path.exists():
            result[name] = None
        elif not path.is_file():
            raise ValueError(f"Expected a regular file: {name}")
        else:
            result[name] = {"bytes": path.stat().st_size, "sha256": checksum(path)}
    return result


def copy_files(root, destination, inventory):
    for name, description in inventory.items():
        if description is not None:
            target = destination / relative_path(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(regular_path(root, name), target)
    if describe(destination, inventory, allow_missing=True) != inventory:
        raise ValueError("Copied files differ from their source inventory")


def tree_files(root):
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"Expected a regular directory: {root}")
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Symlink in sealed directory: {path}")
        if path.is_file():
            files.append(path.relative_to(root).as_posix())
    return describe(root, files)


def verify_vendor(root, recipe):
    for name, inventory in recipe["vendor_dirs"].items():
        if tree_files(regular_path(root, name)) != inventory:
            raise ValueError(f"Vendor inventory differs, including extra files: {name}")


def load_recipe(root, name=RECIPE):
    path = regular_path(root, name)
    recipe = json.loads(path.read_text())
    if recipe.get("schema") != "hepta.port-remediation.recipe.v1":
        raise ValueError("Unrecognized port recipe schema")
    required = {
        "patch_path",
        "patch_sha256",
        "allowed_paths",
        "vendor_dirs",
        "expected_packages",
        "forbidden_packages",
        "cargo_updates",
        "matrix_baseline",
        "aws_qualification",
    }
    if not required <= recipe.keys():
        raise ValueError(f"Missing recipe fields: {sorted(required - recipe.keys())}")
    relative_path(recipe["patch_path"])
    if not HEX256.fullmatch(recipe["patch_sha256"]):
        raise ValueError("Invalid source patch SHA-256")
    allowed = recipe["allowed_paths"]
    if (
        not isinstance(allowed, list)
        or not allowed
        or len(set(allowed)) != len(allowed)
    ):
        raise ValueError("allowed_paths must be an exact nonempty set of file paths")
    for item in allowed:
        relative_path(item)
    if set(allowed) & set((*LOCKS, *POLICIES, name, recipe["patch_path"])):
        raise ValueError("Source patch cannot alter locks, policy, recipe or itself")
    if checksum(regular_path(root, recipe["patch_path"])) != recipe["patch_sha256"]:
        raise ValueError("Source patch differs from the recipe SHA-256")
    if not isinstance(recipe["vendor_dirs"], dict) or not recipe["vendor_dirs"]:
        raise ValueError("A nonempty exact vendor inventory is required")
    for directory, inventory in recipe["vendor_dirs"].items():
        relative_path(directory)
        if not inventory:
            raise ValueError("Empty vendor inventory")
        for item, description in inventory.items():
            relative_path(item)
            if (
                not HEX256.fullmatch(description["sha256"])
                or type(description["bytes"]) is not int
                or description["bytes"] < 0
            ):
                raise ValueError("Invalid vendor file description")
    for package in recipe["expected_packages"]:
        if not PACKAGE.fullmatch(package["name"]) or package["source"] not in {
            "path",
            "registry",
        }:
            raise ValueError("Invalid expected package")
        if not isinstance(package["version"], str) or not package["version"]:
            raise ValueError("Expected package version is required")
        if not isinstance(package.get("required_features", []), list):
            raise ValueError("required_features must be a list")
    if not all(
        isinstance(x, str) and PACKAGE.fullmatch(x) and "@" not in x
        for x in recipe["forbidden_packages"]
    ):
        raise ValueError("forbidden_packages must contain full package names")
    for update in recipe["cargo_updates"]:
        if set(update) - {"package", "precise"} or not PACKAGE.fullmatch(
            update["package"]
        ):
            raise ValueError("Only typed Cargo package updates are allowed")
        if "precise" in update and not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9.+_-]*", update["precise"]
        ):
            raise ValueError("Invalid precise Cargo version")
    baseline = recipe["matrix_baseline"]
    if baseline["source_sha"] != OLD_SOURCE:
        raise ValueError("Matrix fixture must use the fixed independent old source")
    relative_path(baseline["fixture_patch_path"])
    if not HEX256.fullmatch(baseline["fixture_patch_sha256"]):
        raise ValueError("Invalid Matrix fixture patch hash")
    if (
        checksum(regular_path(root, baseline["fixture_patch_path"]))
        != baseline["fixture_patch_sha256"]
    ):
        raise ValueError("Matrix fixture patch differs from recipe")
    aws = recipe["aws_qualification"]
    if aws["vendor_dir"] not in recipe["vendor_dirs"]:
        raise ValueError("AWS qualification must copy a sealed production vendor")
    if set(aws["resources"]) != {"Cargo.lock", ".config/nextest.toml"}:
        raise ValueError("Unexpected qualification overlay resources")
    if (aws["expected_total"], aws["expected_executed"], aws["expected_ignored"]) != (
        245,
        244,
        1,
    ) or aws["ignored_tests"] != ["ecs::tests::real_dns_lookup"]:
        raise ValueError(
            "AWS qualification cannot reduce the frozen upstream inventory"
        )
    resource_paths = {baseline["fixture_patch_path"]}
    for resource in aws["resources"].values():
        resource_name = relative_path(resource["path"])
        resource_paths.add(resource_name)
        if describe(root, (resource_name,))[resource_name] != {
            "bytes": resource["bytes"],
            "sha256": resource["sha256"],
        }:
            raise ValueError("Qualification resource differs from recipe")
    if resource_paths & set(allowed):
        raise ValueError("Source patch cannot mutate its qualification inputs")
    return recipe


class Recorder:
    """Retain each real command and failure, with separate machine-readable stdout."""

    def __init__(self, root, output, mode, *, toolchain="1.96.0"):
        self.root, self.output = root.resolve(), output.resolve()
        if self.output.is_relative_to(self.root):
            raise ValueError("Evidence must be outside the checkout")
        self.output.mkdir(parents=True, exist_ok=False)
        self.env = {"RUSTUP_TOOLCHAIN": toolchain}
        self.record = {
            "schema": SCHEMA,
            "mode": mode,
            "status": "running",
            "commands": [],
            "promotion_allowed": False,
            "toolchain": toolchain,
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "original_dependency_policy_unchanged": None,
        }
        self.save()

    def save(self):
        temporary = self.output / "RESULT.tmp"
        temporary.write_text(json.dumps(self.record, indent=2) + "\n")
        temporary.replace(self.output / "RESULT.json")

    def run(self, label, command, *, required=True, stdout=None, environment=None):
        log = self.output / f"{len(self.record['commands']):02d}-{label}.log"
        overrides = {**self.env, **(environment or {})}
        entry = {
            "command": command,
            "cwd": str(self.root),
            "environment_overrides": overrides,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "log": log.name,
            "exit_code": None,
            "required": required,
        }
        self.record["commands"].append(entry)
        self.save()
        started = time.monotonic()
        print(f"Running {label}: {' '.join(command)}", flush=True)
        try:
            with log.open("wb") as error_stream:
                if stdout is None:
                    completed = subprocess.run(
                        command,
                        cwd=self.root,
                        env={**os.environ, **overrides},
                        stdout=error_stream,
                        stderr=subprocess.STDOUT,
                    )
                else:
                    with stdout.open("wb") as output_stream:
                        completed = subprocess.run(
                            command,
                            cwd=self.root,
                            env={**os.environ, **overrides},
                            stdout=output_stream,
                            stderr=error_stream,
                        )
                    entry["stdout"] = {
                        "file": str(stdout.relative_to(self.output)),
                        "sha256": checksum(stdout),
                        "bytes": stdout.stat().st_size,
                    }
                entry["exit_code"] = completed.returncode
        except OSError as error:
            entry["launch_error"] = str(error)
            raise
        finally:
            entry["elapsed_seconds"] = time.monotonic() - started
            if log.exists():
                entry.update(log_sha256=checksum(log), log_bytes=log.stat().st_size)
            self.save()
        if required and entry["exit_code"]:
            raise RuntimeError(
                f"{label} failed with exit {entry['exit_code']}; see {log.name}"
            )
        return entry["exit_code"]

    def text(self, label, command):
        self.run(label, command)
        return (self.output / self.record["commands"][-1]["log"]).read_text().strip()

    def json_command(self, label, command):
        output = self.output / (label + ".json")
        self.run(label, command, stdout=output)
        return json.loads(output.read_text())


def check_checkout(runner, expected_source):
    source = runner.text("source-head", ["git", "rev-parse", "HEAD"])
    runner.record["source_commit"] = source
    if not re.fullmatch(r"[0-9a-f]{40}", expected_source) or source != expected_source:
        raise ValueError("Checkout HEAD differs from the exact requested source")
    if runner.text(
        "clean-checkout", ["git", "status", "--porcelain", "--untracked-files=all"]
    ):
        raise ValueError("A clean disposable full checkout is required")


def patch_paths(runner, patch):
    output = runner.text("patch-paths", ["git", "apply", "--numstat", "-z", str(patch)])
    names = []
    for row in output.split("\0"):
        if row:
            fields = row.split("\t", 2)
            if len(fields) != 3 or not fields[2]:
                raise ValueError("Renames or malformed patch paths are not accepted")
            names.append(relative_path(fields[2]))
    if len(set(names)) != len(names):
        raise ValueError("Duplicate patch paths")
    return set(names)


def changed_paths(runner):
    names = runner.text(
        "changed-paths", ["git", "diff", "--no-renames", "--name-only", "-z", "HEAD"]
    ).split("\0")
    if runner.text(
        "untracked-paths", ["git", "ls-files", "--others", "--exclude-standard", "-z"]
    ):
        raise ValueError("Untracked files appeared in the disposable checkout")
    return {relative_path(name) for name in names if name}


def check_toolchain(runner, version):
    keys = (
        "RUSTC",
        "RUSTC_WRAPPER",
        "RUSTC_WORKSPACE_WRAPPER",
        "CARGO_BUILD_RUSTC",
        "CARGO_BUILD_RUSTC_WRAPPER",
        "CARGO_BUILD_RUSTC_WORKSPACE_WRAPPER",
    )
    inherited = {key: os.environ[key] for key in keys if os.environ.get(key)}
    runner.record["inherited_compiler_overrides"] = inherited
    runner.save()
    if inherited:
        raise ValueError(
            "Inherited Cargo compiler/wrapper overrides need independent qualification"
        )
    configs = [
        runner.root / ".cargo/config",
        runner.root / ".cargo/config.toml",
        runner.root / "codex-rs/.cargo/config",
        runner.root / "codex-rs/.cargo/config.toml",
    ]
    cargo_home = Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo"))
    configs.extend((cargo_home / "config", cargo_home / "config.toml"))
    for config in configs:
        if config.is_file():
            data = tomllib.loads(config.read_text())
            if any(
                data.get("build", {}).get(key)
                for key in ("rustc", "rustc-wrapper", "rustc-workspace-wrapper")
            ) or set(data.get("env", {})) & set(keys):
                raise ValueError(
                    f"Cargo configuration overrides the bound compiler: {config}"
                )
    compiler = Path(
        runner.text(
            "bound-rustc-path", ["rustup", "which", "--toolchain", version, "rustc"]
        )
    )
    if not compiler.is_absolute() or not compiler.is_file():
        raise ValueError("Rustup did not identify a real compiler executable")
    runner.env["RUSTC"] = str(compiler)
    runner.record["cargo_compiler"] = {
        "path": str(compiler),
        "sha256": checksum(compiler),
    }
    output = runner.text("rustc-version", [str(compiler), "--version", "--verbose"])
    if not re.search(rf"^release: {re.escape(version)}$", output, re.MULTILINE):
        raise ValueError(f"Actual rustc release is not {version}")
    runner.record["rustc_verbose"] = output
    cargo = runner.text("cargo-version", ["cargo", "--version"])
    if not cargo.startswith(f"cargo {version} "):
        raise ValueError(f"Actual Cargo release is not {version}")
    runner.run("just-version", ["just", "--version"])


