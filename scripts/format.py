#!/usr/bin/env python3
"""Format repository sources or check that they are already formatted."""

import argparse
import hashlib
import os
import runpy
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


# These exact original Rust source records are retained evidence. Their package
# identities are recorded in HEPTA_VERBATIM_SOURCE_RECORDS.json, the immutable
# continuation-20261021 relocation record, and the frozen AUDIT packaging manifest.
# Neighboring Rust remains source input; only listed paths with exact bytes qualify.
ORIGINAL_EVIDENCE_PREFIX = "qualification/memory-cell-mem8-ci-followup"
AUDIT_ORIGINAL_EVIDENCE_PREFIX = "AUDIT/2026-10-20-agent-continuation"
RELOCATED_READER_EVIDENCE_PREFIX = (
    "qualification/main-consolidation/historical-continuations/"
    "continuation-20261021/research/reader-2969/source"
)
SEALED_READER_RUST = (
    f"{RELOCATED_READER_EVIDENCE_PREFIX}/codex-rs/hepta-ndu/src/recursive.rs"
)
RAW_EVIDENCE_RESTORER = "qa/repository-consolidation/20261115/restore_raw_evidence.py"
PREFORMAT_RESEARCH_EVIDENCE_PREFIX = "research/rrsnn_v4/hepta"
RELOCATED_BROKER_EVIDENCE_PREFIX = (
    "qualification/main-consolidation/historical-continuations/"
    "continuation-20261021/os/broker-review"
)
ORIGINAL_EVIDENCE_FILES = {
    "qualification/memory-cell-mem8-ci-followup/pending-model-wire-cache/model_list.rs": (
        "1136589db852ba45ce9bee975dd10fcf7a48a24c832aca5c0b8019db5a987177",
        14469,
    ),
    "qualification/memory-cell-mem8-ci-followup/v17/memory-coverage-diagnostic-preparation/cognitive_runtime_tests.rs": (
        "5ecb8bce0adb6d0151eb1ed23405489757354482f70b1b33d1232b35afc85d3c",
        17873,
    ),
    f"{RELOCATED_BROKER_EVIDENCE_PREFIX}/broker-original.rs": (
        "bbde2c304566567b9bd12e6214bcf0d52a3f96f3dc889352e14926072617aba5",
        37712,
    ),
    f"{RELOCATED_BROKER_EVIDENCE_PREFIX}/session-identity.rs": (
        "d815d6235357a57fc40a8fca5b710e46dfd0d273f93bcadd8a61026a59777231",
        3802,
    ),
    f"{RELOCATED_BROKER_EVIDENCE_PREFIX}/session_admission_repro.rs": (
        "00c6368be54a58ada1fda01d74294c78cd7d415ed24d25f70de295ff7876f87a",
        1796,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/cell_p0/sources/2909/codex-rs/hepta-control-plane/src/scope_lane_wal.rs": (
        "cfd1d6a58f8e8e878b4ada517af6d9770d6fcf69efabd88afcb41056fdc29ca2",
        26123,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/cell_p0/sources/2909/codex-rs/hepta-control-plane/src/scope_lane_wal_tests.rs": (
        "c6fdee03df0c9dc6455c2a108c836fb0022415cc0b52e33e7b775dd9b3113268",
        10566,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p1_p4_audit/sources/2684/codex-rs/hepta-operator-acceptance/src/cell_split_execution_cli.rs": (
        "db150bdc03c882bd08224cf6ff746afbfa25ffc89fdce9de5389251d9874cbff",
        25235,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p1_p4_audit/sources/2684/codex-rs/hepta-operator-acceptance/src/cell_split_execution_owner.rs": (
        "8a7736079fe7a346081efba412d5653b046cb55bda54b400edc2ff7419844a36",
        59043,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p1_p4_audit/sources/2684/codex-rs/hepta-operator-acceptance/src/cell_split_target_host_runtime.rs": (
        "31335055c1f3ebf5a92b32c2e6ef754432d27058035c83e33230f9a1a2e7b358",
        34984,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p1_p4_audit/sources/2695/codex-rs/hepta-ndu/src/group.rs": (
        "5c680358e812b46e5c78b4b2f94f52d020dfedd87f7da5011f14f1696006790b",
        13547,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p1_p4_audit/sources/2695/codex-rs/hepta-ndu/src/shadow_system2.rs": (
        "8c795ae8f3aeac7aac03f2964a814eb2cd349005a751fd52cdf39035918f339f",
        13845,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p1_p4_audit/sources/2695/codex-rs/hepta-neuron/src/shared_encoder.rs": (
        "10ff449054491168612e3d0700f7dd82b56818b2125b744a22a47fbd7b934bc6",
        9741,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p1_p4_audit/sources/2734/codex-rs/hepta-infer-worker-host/src/neuron_microbatch.rs": (
        "511322c003983900d5e4e2c971dc51a334fd3efa2f223f814fcafe3ed9adb73e",
        9057,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p1_p4_audit/sources/2734/codex-rs/hepta-intelligence-eval/src/fenced_holdout.rs": (
        "da730741b87b34a0896594ab65b3226b93cbcf9c57b27d7f1c44d32f94b6c4c5",
        12242,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p1_p4_audit/sources/2734/codex-rs/hepta-intelligence-eval/src/longitudinal_time.rs": (
        "d455220de2b728faa2e06b497da87000b41cf28b2f8cd9953d5af84ee70b0d44",
        8146,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p1_p4_audit/sources/2734/codex-rs/hepta-intelligence-eval/src/product_runner.rs": (
        "15e82c5fb2b58ec0fffbb74e2b05be75ede0f3d0e21603b95e047edd6ca9fcf4",
        36095,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p1_p4_audit/sources/2734/codex-rs/hepta-intelligence-eval/src/self_evolution_selection.rs": (
        "0749241ab62235eac257ccf244aebc3e6be3eabbb9eafc667f4c02dde648eb3c",
        27089,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p1_p4_audit/sources/2734/codex-rs/hepta-intelligence/src/cell_ndu_selection.rs": (
        "657fc27ef2086ceaf14f292c4aef81db2b7bf92761acff5ecf277de71dc4e456",
        25839,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p1_p4_audit/sources/2734/codex-rs/hepta-neuron/src/data_plane.rs": (
        "56b7ce6462f357e9659f6688ac3efca804805c61be89d92e18191fc6c00275f7",
        36052,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p1_p4_audit/sources/2734/codex-rs/hepta-supervisor/src/cell_split.rs": (
        "a597c6e5bf42d1f03e4c3a0cf421e2869dcaa944383cff97578887b941576c41",
        91281,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p1_p4_audit/sources/2918/codex-rs/hepta-infer-worker-host/src/bin/hepta-infer-worker.rs": (
        "86e3f2be9c9b40b1d7d01f9364dcffd06dd1c65b1f644e165314d21d5db19758",
        6596,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p1_p4_audit/sources/2918/codex-rs/hepta-infer-worker-host/src/bin/hepta-neuron-microbatch-qualification.rs": (
        "2e196c3ee20db3bf7b296442f2b4dec9bae03d2f925691656f13319449ee8fc0",
        9578,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p1_p4_audit/sources/2918/codex-rs/hepta-infer-worker-host/src/neuron_microbatch.rs": (
        "805d7a1ac669ba802a936603192204ff1b5724ef821cfbe4e7375d10458b0097",
        19061,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p1_p4_audit/sources/2918/codex-rs/hepta-neuron/src/metrics.rs": (
        "5de92b54cfbe9038e1fb46f18f3c854a84370ef9009e4af0e2fffefbc8895650",
        13601,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p1_p4_audit/sources/2918/codex-rs/hepta-neuron/src/runtime.rs": (
        "cb86aa9c25494ad58f86be5930ad7289c020f5b3d9a09aa8170f48cf10f2d202",
        21630,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p5_inventory/hepta/sources/1311/codex-rs/hepta-automation/src/model.rs": (
        "9765d311fa215a7c3c9a9cbb23d8d016a3df67567248fd9b2da151bc942992e9",
        7617,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p5_inventory/hepta/sources/1311/codex-rs/hepta-automation/src/scheduler.rs": (
        "94292337b0c78ece37e6811599ff0c7807228e01315c31164a1587435f3833f9",
        10594,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p5_inventory/hepta/sources/996/codex-rs/hepta-memory/src/cognitive_store.rs": (
        "ef1b54636a57ce15830e6ea19c117d9eea23f7a93a06ce3e5cce6a6378ff6bdc",
        70512,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p5_inventory/organ/pr210/ui/broker/src/lib.rs": (
        "82931bd6f7512754296224eab7c6a29394a5989a0775f8bf0d041a77dbb7496f",
        36961,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p5_inventory/organ/source/kernel/asterinas/kernel/core/src/device/misc/hepta_control.rs": (
        "3a2dd825cbe6c09db0b3cce6f5cc58c6c9b0c7b817b2b28766e3470a3283f5f5",
        9456,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p5_inventory/organ/source/kernel/asterinas/kernel/core/src/fs/fs_impls/cgroupfs/controller/cpu.rs": (
        "b78cf58b0dabd34b3055748d4fc8a7e59ce37d90d092b32b72e06fee8814c4d0",
        42658,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p5_inventory/organ/source/libs/os-control/src/native.rs": (
        "1967c2db5c7292127a5cb4a76c3448a9764710b4c44ebeb40a610dba6e16fd81",
        8844,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p5_inventory/organ/source/services/hepta-os/src/client.rs": (
        "8669dc6c1e48c43108f3c2e1f8602e7602ac45e3e74239f638cdf92a3a99f5e8",
        14515,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p5_inventory/organ/source/services/hepta-os/src/lib.rs": (
        "3904ceed5853d3ea930ea329faa78f5611ee6cf5f90178919a8f2d8db7c39162",
        7492,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/p5_inventory/organ/source/services/hepta-os/src/objective/mod.rs": (
        "4475f5267ed20fbc97fdfe82fe6300f80574e75f6f2da5679f21c213b94b7f09",
        17623,
    ),
    f"{AUDIT_ORIGINAL_EVIDENCE_PREFIX}/ui_p0/upstream-web-network.rs": (
        "24dffe35dba1218adaa6d9ab9a12f51631f796e8d9f31114ecb973db34417b14",
        16476,
    ),
    # The sealed continuation manifest preserves this fourth historical Rust file.
    SEALED_READER_RUST: (
        "8f5b71cbbc217d4b07a0d4797944eedf5d3c3bd3884cd6fbcb304a48318102fb",
        5219,
    ),
    # bootstrap_format_supersession.json keeps the tested preformat source distinct.
    f"{PREFORMAT_RESEARCH_EVIDENCE_PREFIX}/bootstrap_runtime_preformat.rs": (
        "df98ccc5ca1d7c87f4e1ab5bf99aca9b3190b2bab4e00e758c0caeed6d2aa154",
        18942,
    ),
}


def verified_original_evidence_paths() -> frozenset[str]:
    """Validate exact archived source bytes before any full or scoped format."""
    root = REPO_ROOT.resolve()
    prefixes = (
        Path(ORIGINAL_EVIDENCE_PREFIX),
        Path(RELOCATED_BROKER_EVIDENCE_PREFIX),
        Path(AUDIT_ORIGINAL_EVIDENCE_PREFIX),
        Path(RELOCATED_READER_EVIDENCE_PREFIX),
        Path(PREFORMAT_RESEARCH_EVIDENCE_PREFIX),
    )
    for relative, (expected_sha256, expected_size) in ORIGINAL_EVIDENCE_FILES.items():
        path = Path(relative)
        prefix = next(
            (candidate for candidate in prefixes if path.is_relative_to(candidate)),
            None,
        )
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in relative
            or path.as_posix() != relative
            or prefix is None
        ):
            raise ValueError(
                f"original evidence path escapes its fixed prefix: {relative!r}"
            )
        source = root / path
        try:
            if relative == SEALED_READER_RUST and not source.exists():
                # That exact historical Rust record can be stored in the
                # registered gzip archive; the original size and hash still apply.
                storage = runpy.run_path(str(root / RAW_EVIDENCE_RESTORER))
                storage["read_verified"](root, relative, expected_size, expected_sha256)
                continue
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
        except (KeyError, OSError) as error:
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
