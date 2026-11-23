#!/usr/bin/env python3
"""Format repository sources or check that they are already formatted."""

import argparse
import hashlib
import os
import shlex
import subprocess
import sys
import json

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 uses Cargo for Rust edition metadata.
    tomllib = None
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

# These exact upstream bytes are syntax-highlighting test inputs, not Rust
# implementation. Some deliberately contain invalid syntax. The original Git
# blob IDs and commits are recorded in the vendor's HEPTA_VERBATIM_FIXTURES.json.
# Any change needs a new explicit review; neither a directory nor a glob is exempt.
VERBATIM_FIXTURE_PREFIX = "codex-rs/third_party/syntect-5.3.0-maintained-codec/testdata"
VERBATIM_FIXTURES = {
    f"{VERBATIM_FIXTURE_PREFIX}/Packages/Rust/syntax_test_rust.rs": (
        "12cc528a46e2681af786bd1a024b64517a616ab9191829f81aa548b18c14d9f3",
        37068,
    ),
    f"{VERBATIM_FIXTURE_PREFIX}/issue28.rs": (
        "2f660b2c5a8739bbe90545cb45f218fae6a7d2a902e044274042092aee605017",
        28,
    ),
    f"{VERBATIM_FIXTURE_PREFIX}/issue33.rs": (
        "579e35846711308d28bd6cb02476a0b1c96ae2aede50105e6bc8dbc0a80ced8f",
        215,
    ),
    f"{VERBATIM_FIXTURE_PREFIX}/parser.rs": (
        "8b21ecd498165716362abea58cc8904ba8b9b02c8983d45cb501194585a93ae6",
        243245,
    ),
    f"{VERBATIM_FIXTURE_PREFIX}/spacegray/fileicons-test/rust.rs": (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        0,
    ),
}


# These two exact original Rust source records are retained evidence. Their
# containing publication packages and original Git identities are recorded in
# HEPTA_VERBATIM_SOURCE_RECORDS.json. Neighboring Rust files remain source inputs.
ORIGINAL_EVIDENCE_PREFIX = "qualification/memory-cell-mem8-ci-followup"
ORIGINAL_EVIDENCE_FILES = {
    "qualification/memory-cell-mem8-ci-followup/pending-model-wire-cache/model_list.rs": (
        "1136589db852ba45ce9bee975dd10fcf7a48a24c832aca5c0b8019db5a987177",
        14469,
    ),
    "qualification/memory-cell-mem8-ci-followup/v17/memory-coverage-diagnostic-preparation/cognitive_runtime_tests.rs": (
        "5ecb8bce0adb6d0151eb1ed23405489757354482f70b1b33d1232b35afc85d3c",
        17873,
    ),
}


# PR 2909, source 5993cb909547070e4b56ca9465996a5a946fafca, archived four
# files. Its omitted workspace manifest (Git blob d2703b590935ab17316e6c258657c0ce5ab7412a)
# lists hepta-control-plane and sets workspace.package.edition to 2024.
WAL_PROJECTION = "AUDIT/2026-10-20-agent-continuation/cell_p0/sources/2909/codex-rs"
WAL_RUSTFMT_CONFIG = "scripts/format_provenance/cell-p0-2909/rustfmt.toml"
WAL_RUST_SOURCES = {
    f"{WAL_PROJECTION}/hepta-control-plane/src/scope_lane_wal.rs": "cfd1d6a58f8e8e878b4ada517af6d9770d6fcf69efabd88afcb41056fdc29ca2",
    f"{WAL_PROJECTION}/hepta-control-plane/src/scope_lane_wal_tests.rs": "c6fdee03df0c9dc6455c2a108c836fb0022415cc0b52e33e7b775dd9b3113268",
}
WAL_FORMAT_INPUTS = {
    **WAL_RUST_SOURCES,
    f"{WAL_PROJECTION}/hepta-control-plane/Cargo.toml": "e3aab0b702f89e12d8bdc90b31fc15f823d66f6114b611c8948688e97eea2fe6",
    f"{WAL_PROJECTION}/Cargo.lock": "17bef7bc25e239f0a9ba7dfe8aef6a5ca0c8ef4b5c01d32994132cae153e6384",
    WAL_RUSTFMT_CONFIG: "384d5d8a1366a86cd6fc01aecde2b0a5806a9e77073ff53abd97b4f6cad94d1c",
}


def verify_wal_format_inputs() -> None:
    """Bind the four archived source bytes and original formatting rules before planning."""
    root = REPO_ROOT.resolve()
    for name, expected in WAL_FORMAT_INPUTS.items():
        path = root / name
        try:
            if (
                not path.is_relative_to(root)
                or path.resolve(strict=True) != path
                or not path.is_file()
            ):
                raise ValueError(
                    f"archived WAL input is not a regular original: {name}"
                )
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError(f"archived WAL input changed: {name}")
        except (OSError, RuntimeError) as error:
            raise ValueError(f"cannot verify archived WAL input: {name}") from error


def verified_original_evidence_paths() -> frozenset[str]:
    """Validate exact archived source bytes before any full or scoped format."""
    root = REPO_ROOT.resolve()
    prefix = Path(ORIGINAL_EVIDENCE_PREFIX)
    for relative, (expected_sha256, expected_size) in ORIGINAL_EVIDENCE_FILES.items():
        path = Path(relative)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in relative
            or path.as_posix() != relative
            or not path.is_relative_to(prefix)
        ):
            raise ValueError(
                f"original evidence path escapes its fixed prefix: {relative!r}"
            )
        source = root / path
        try:
            resolved = source.resolve(strict=True)
            if not resolved.is_relative_to(root / prefix) or any(
                parent.is_symlink()
                for parent in (source, *source.parents)
                if parent.is_relative_to(root)
            ):
                raise ValueError(
                    f"original evidence path escapes or aliases: {relative!r}"
                )
            if not source.is_file() or source.stat().st_size != expected_size:
                raise ValueError(f"original evidence bytes changed: {relative!r}")
            if hashlib.sha256(source.read_bytes()).hexdigest() != expected_sha256:
                raise ValueError(f"original evidence bytes changed: {relative!r}")
        except OSError as error:
            raise ValueError(
                f"cannot verify original evidence {relative!r}: {error}"
            ) from error
    return frozenset(ORIGINAL_EVIDENCE_FILES)


def verified_verbatim_fixture_paths() -> frozenset[str]:
    """Identify exact test-input bytes, rejecting drift before any formatter runs."""
    root = REPO_ROOT.resolve()
    prefix = Path(VERBATIM_FIXTURE_PREFIX)
    for relative, (expected_sha256, expected_size) in VERBATIM_FIXTURES.items():
        path = Path(relative)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in relative
            or path.as_posix() != relative
            or not path.is_relative_to(prefix)
        ):
            raise ValueError(
                f"verbatim fixture path escapes its fixed prefix: {relative!r}"
            )
        source = root / path
        try:
            resolved = source.resolve(strict=True)
            if not resolved.is_relative_to(root / prefix) or any(
                parent.is_symlink()
                for parent in (source, *source.parents)
                if parent.is_relative_to(root)
            ):
                raise ValueError(
                    f"verbatim fixture path escapes or aliases: {relative!r}"
                )
            if not source.is_file() or source.stat().st_size != expected_size:
                raise ValueError(f"verbatim fixture bytes changed: {relative!r}")
            if hashlib.sha256(source.read_bytes()).hexdigest() != expected_sha256:
                raise ValueError(f"verbatim fixture bytes changed: {relative!r}")
        except OSError as error:
            raise ValueError(
                f"cannot verify verbatim fixture {relative!r}: {error}"
            ) from error
    verify_wal_format_inputs()
    return frozenset(VERBATIM_FIXTURES) | verified_original_evidence_paths()


@dataclass(frozen=True)
class Command:
    args: tuple[str, ...]
    cwd: Path = REPO_ROOT


@dataclass(frozen=True)
class FormatterGroup:
    name: str
    commands: tuple[Command, ...]


@dataclass(frozen=True)
class FormatterResult:
    name: str
    output: str
    returncode: int


def just_formatter_group(*, check: bool) -> FormatterGroup:
    args = ["just", "--unstable", "--fmt"]
    if check:
        args.append("--check")
    return FormatterGroup("Just", (Command(tuple(args)),))


def rust_formatter_group(*, check: bool) -> FormatterGroup:
    args = ["cargo", "fmt", "--", "--config", "imports_granularity=Item"]
    if check:
        args.append("--check")
    command = Command(tuple(args), REPO_ROOT / "codex-rs")
    return FormatterGroup("Rust", (command,))


def is_starlark_file(path: Path) -> bool:
    name = path.name
    # BUILD.json and similar metadata are retained execution records, not
    # Starlark sources. Keep them out of both full and changed-file formatting.
    if path.suffix == ".json":
        return False
    return (
        name in {"BUILD", "WORKSPACE", "MODULE.bazel"}
        or name.startswith(("BUILD.", "WORKSPACE."))
        or name.endswith((".BUILD.bazel", ".MODULE.bazel", ".bzl", ".sky"))
        or ".bzl." in name
        or ".sky." in name
    )


def buildifier_formatter_group(
    *, check: bool, paths: list[str] | None = None
) -> FormatterGroup:
    verbatim = verified_verbatim_fixture_paths()
    repository_files = (
        [os.fsencode(path) for path in paths]
        if paths is not None
        else subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=REPO_ROOT,
        ).split(b"\0")
    )
    buildifier_files: list[str] = []
    for encoded_path in repository_files:
        if not encoded_path:
            continue
        path = Path(os.fsdecode(encoded_path))
        if path.as_posix() not in verbatim and is_starlark_file(path):
            buildifier_files.append(path.as_posix())
    buildifier_files.sort()

    # Invoke DotSlash explicitly because Windows does not honor shebangs.
    buildifier_args = [
        "dotslash",
        str(REPO_ROOT / "tools" / "buildifier"),
        "-mode=check" if check else "-mode=fix",
        "-lint=off",
        *buildifier_files,
    ]
    return FormatterGroup("Bazel/Starlark", (Command(tuple(buildifier_args)),))


def python_sdk_formatter_group(
    *, check: bool, paths: list[str] | None = None
) -> FormatterGroup:
    # Each `--project` retains its local dependency and Ruff configuration context.
    uv_run_args = [
        "uv",
        "run",
        "--frozen",
        "--project",
        "sdk/python",
        "--only-group",
        "format",
    ]
    format_args = [
        *uv_run_args,
        "ruff",
        "format",
    ]
    if check:
        format_args.append("--check")
        # `ruff check --diff` reports lint-driven rewrites without changing files.
        # It is the check-mode counterpart of `--fix --fix-only`, not a full lint gate.
        lint_args = ["ruff", "check", "--diff"]
    else:
        # Ruff's lint fixer and formatter are separate passes: the first applies
        # fixable lint rewrites, while the second formats source layout.
        lint_args = ["ruff", "check", "--fix", "--fix-only"]

    return FormatterGroup(
        "Python SDK",
        (
            Command(
                (
                    *uv_run_args,
                    *lint_args,
                    *(paths if paths is not None else ["sdk/python"]),
                )
            ),
            Command((*format_args, *(paths if paths is not None else ["sdk/python"]))),
        ),
    )


def python_scripts_formatter_group(
    *, check: bool, paths: list[str] | None = None
) -> FormatterGroup:
    # The SDK and internal scripts intentionally use separate project roots so
    # uv and Ruff retain each project's configuration context.
    args = [
        "uv",
        "run",
        "--frozen",
        "--project",
        "scripts",
        "ruff",
        "format",
    ]
    if check:
        args.append("--check")
    args.extend(paths if paths is not None else ["scripts", ".github"])
    return FormatterGroup("Python scripts", (Command(tuple(args)),))


def formatter_groups(*, check: bool) -> tuple[FormatterGroup, ...]:
    verified_verbatim_fixture_paths()
    return (
        just_formatter_group(check=check),
        rust_formatter_group(check=check),
        buildifier_formatter_group(check=check),
        python_sdk_formatter_group(check=check),
        python_scripts_formatter_group(check=check),
    )


def run_formatter_group(group: FormatterGroup) -> FormatterResult:
    """Run one formatter group sequentially and return its buffered output."""
    for command in group.commands:
        try:
            process = subprocess.run(
                command.args,
                cwd=command.cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        except OSError as error:
            output = f"$ {shlex.join(command.args)}\n{error}\n"
            return FormatterResult(group.name, output, 1)

        if process.returncode != 0:
            output = f"$ {shlex.join(command.args)}\n{process.stdout}"
            if process.stdout and not process.stdout.endswith("\n"):
                output += "\n"
            return FormatterResult(group.name, output, process.returncode)

    return FormatterResult(group.name, "", 0)


def changed_paths(base: str | None = None) -> list[str]:
    """Include staged, unstaged and untracked inputs; preserve literal filenames."""
    revision = "HEAD"
    if base is not None:
        revision = subprocess.check_output(
            ["git", "rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}"],
            cwd=REPO_ROOT,
            text=True,
        ).strip()
    commands = [
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=ACDMRT",
            "--no-renames",
            "-z",
            revision,
            "--",
        ],
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
    ]
    values = set()
    for command in commands:
        for raw in subprocess.check_output(command, cwd=REPO_ROOT).split(b"\0"):
            if not raw:
                continue
            value = os.fsdecode(raw)
            path = REPO_ROOT / value
            if not path.resolve().is_relative_to(REPO_ROOT.resolve()):
                raise ValueError(f"format input escapes repository: {value!r}")
            config_removed = not path.exists() and path.name in {
                "pyproject.toml",
                "ruff.toml",
                ".ruff.toml",
                "rustfmt.toml",
                ".rustfmt.toml",
            }
            if path.is_file() or config_removed:
                values.add(value)
    return sorted(values)


def rust_file_command(path: str, *, check: bool) -> Command:
    if path in WAL_RUST_SOURCES:
        verify_wal_format_inputs()
        # Keep the archived source in the command list and check its original bytes
        # in both modes. Other files still need their own enclosing Rust workspace.
        return Command(
            (
                "rustfmt",
                "--check",
                "--edition",
                "2024",
                "--config-path",
                str(REPO_ROOT / WAL_RUSTFMT_CONFIG),
                "--config",
                "skip_children=true",
                "--",
                str(REPO_ROOT / path),
            ),
            REPO_ROOT / "codex-rs",
        )
    manifest = next(
        (
            parent / "Cargo.toml"
            for parent in (REPO_ROOT / path).parents
            if (parent / "Cargo.toml").is_file() and parent.is_relative_to(REPO_ROOT)
        ),
        None,
    )
    edition = "2021"
    if manifest is not None and tomllib is None:
        metadata = json.loads(
            subprocess.check_output(
                [
                    "cargo",
                    "metadata",
                    "--no-deps",
                    "--format-version=1",
                    "--manifest-path",
                    str(manifest),
                ],
                cwd=REPO_ROOT,
                text=True,
            )
        )
        package = next(
            row
            for row in metadata["packages"]
            if Path(row["manifest_path"]) == manifest
        )
        edition = package["edition"]
    elif manifest is not None:
        package = tomllib.loads(manifest.read_text())["package"]
        edition = package.get("edition", "2015")
        if isinstance(edition, dict):
            if edition.get("workspace") is not True:
                raise ValueError(f"invalid inherited Rust edition in {manifest}")
            explicit = package.get("workspace")
            candidates = (
                [manifest.parent / explicit / "Cargo.toml"]
                if explicit is not None
                else [
                    parent / "Cargo.toml"
                    for parent in manifest.parents
                    if parent.is_relative_to(REPO_ROOT)
                ]
            )
            for candidate in candidates:
                if not candidate.resolve().is_relative_to(REPO_ROOT.resolve()):
                    raise ValueError("Rust workspace escapes repository")
                if not candidate.is_file():
                    continue
                document = tomllib.loads(candidate.read_text())
                if "workspace" in document:
                    edition = document["workspace"].get("package", {}).get("edition")
                    if not isinstance(edition, str):
                        raise ValueError(f"workspace edition missing in {candidate}")
                    break
            else:
                raise ValueError(f"owning Rust workspace missing for {manifest}")
    args = [
        "rustfmt",
        "--edition",
        str(edition),
        "--config",
        "imports_granularity=Item,skip_children=true",
    ]
    if check:
        args.append("--check")
    source = (REPO_ROOT / path).resolve()
    if not source.is_relative_to(REPO_ROOT.resolve()):
        raise ValueError("Rust formatting source escapes repository")
    # rustup selects a pinned toolchain from the process working directory,
    # not the filename passed to rustfmt. Preserve the owning crate's context.
    directory = manifest.parent if manifest is not None else source.parent
    return Command((*args, "--", str(source)), directory)


def formatting_configuration_changed(path: str, base: str | None = None) -> bool:
    """Dependency metadata alone does not change Ruff rules or their scope."""
    if Path(path).name != "pyproject.toml" or tomllib is None:
        return True
    before = subprocess.run(
        ["git", "show", f"{base or 'HEAD'}:{path}"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    if before.returncode:
        return True
    try:
        previous_document = tomllib.loads(before.stdout)
        current_document = tomllib.loads((REPO_ROOT / path).read_text())
        previous = (
            previous_document.get("tool", {}).get("ruff", {}),
            previous_document.get("project", {}).get("requires-python"),
        )
        current = (
            current_document.get("tool", {}).get("ruff", {}),
            current_document.get("project", {}).get("requires-python"),
        )
    except (ValueError, OSError):
        return True
    return previous != current


def rust_configuration_scope(paths: list[str]) -> list[str]:
    """Expand changed Rust configuration to its subtree, never unrelated crates.

    Include tracked and untracked source, but never generated/ignored build
    output or deleted files. A removed configuration still changes its subtree.
    Explicit --all remains the Cargo-workspace formatting entry point.
    """
    roots = {
        Path(path).parent
        for path in paths
        if Path(path).name in {"rustfmt.toml", ".rustfmt.toml"}
    }
    selected = {path for path in paths if path.endswith(".rs")}
    if roots:
        inventory = subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=REPO_ROOT,
        )
        for raw in inventory.split(b"\0"):
            value = os.fsdecode(raw)
            source = Path(value)
            if source.suffix != ".rs" or not any(
                source.is_relative_to(root) for root in roots
            ):
                continue
            target = REPO_ROOT / source
            if not target.resolve().is_relative_to(REPO_ROOT.resolve()):
                raise ValueError(f"Rust format input escapes repository: {value!r}")
            if target.is_file():
                selected.add(value)
    return sorted(selected - verified_verbatim_fixture_paths())


def scoped_formatter_groups(
    paths: list[str], *, check: bool, base: str | None = None
) -> tuple[FormatterGroup, ...]:
    groups = []
    if "justfile" in paths:
        groups.append(just_formatter_group(check=check))
    rust = rust_configuration_scope(paths)
    if rust:
        groups.append(
            FormatterGroup(
                "Rust", tuple(rust_file_command(path, check=check) for path in rust)
            )
        )
    build = [path for path in paths if is_starlark_file(Path(path))]
    if build:
        groups.append(buildifier_formatter_group(check=check, paths=build))
    for roots, factory in (
        (("sdk/python",), python_sdk_formatter_group),
        (("scripts", ".github"), python_scripts_formatter_group),
    ):
        selected = [
            "./" + path
            for path in paths
            if any(path.startswith(directory + "/") for directory in roots)
            and path.endswith((".py", ".pyi"))
        ]
        directories = set()
        for path in paths:
            config = Path(path)
            if config.name not in {"pyproject.toml", "ruff.toml", ".ruff.toml"}:
                continue
            if config.parent == Path("."):
                owners = roots
            elif any(path.startswith(directory + "/") for directory in roots):
                owners = (config.parent.as_posix(),)
            else:
                continue
            if formatting_configuration_changed(path, base):
                directories.update(owners)
        # A nested configuration affects its subtree, not unrelated toolchains.
        scopes = sorted(
            value
            for value in directories
            if not any(
                value != other and value.startswith(other + "/")
                for other in directories
            )
        )
        selected = [
            path
            for path in selected
            if not any(path[2:].startswith(scope + "/") for scope in scopes)
        ]
        if scopes or selected:
            groups.append(factory(check=check, paths=[*scopes, *selected]))
    return tuple(groups)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="check formatting without modifying files",
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--all", action="store_true", help="format/check the full repository"
    )
    scope.add_argument(
        "--base",
        help="include committed changes since this exact base, plus local edits",
    )
    args = parser.parse_args()
    try:
        groups = (
            formatter_groups(check=args.check)
            if args.all
            else scoped_formatter_groups(
                changed_paths(args.base), check=args.check, base=args.base
            )
        )
    except (ValueError, subprocess.CalledProcessError) as error:
        parser.exit(2, f"Cannot determine formatting scope: {error}\n")
    if not groups:
        print(
            "No changed files need formatting. Use --all for a full repository check."
        )
        return 0

    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=len(groups)) as executor:
        futures = [executor.submit(run_formatter_group, group) for group in groups]
        for future in as_completed(futures):
            result = future.result()
            if result.returncode != 0:
                failures.append(result.name)
                print(f"==> {result.name} formatter failed", file=sys.stderr)
                print(result.output, end="", file=sys.stderr)

    if failures:
        print(f"Formatting failed: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
