#!/usr/bin/env python3
"""Same-run native image transfer and installed-image controls, not qualification.

GitHub artifact transport and the exact checked-out workflow are trusted. These
records bind observed source/binary bytes and commands; they do not authenticate
an adversarial compiler, runner, transient mutation or a model/FinalUse result.
"""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys

if __package__:
    from .hepta_ci_candidate import candidate_plan
    from .hepta_ci_exec import git, identity, observed_test_counts
else:
    from hepta_ci_candidate import candidate_plan
    from hepta_ci_exec import git, identity, observed_test_counts


MAXIMUM_IMAGE = 512 * 1024 * 1024
REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
WORKFLOW = ".github/workflows/hepta-pon-native-pair.yml"
CLI_COMMAND = [
    "just",
    "test",
    "--locked",
    "-p",
    "codex-hepta-infer-worker-host",
    "--test",
    "cell_host_cli",
    "--no-capture",
]
BUILD_COMMAND = [
    "cargo",
    "+1.95.0",
    "build",
    "--locked",
    "--release",
    "--manifest-path",
    "trillionnium/Cargo.toml",
    "-p",
    "trnm-data-availability",
    "--bin",
    "trnm-cell",
]
FILES = {
    "native.gz",
    "Cargo.lock",
    "candidate-tuple.json",
    "cli-process.json",
    "cli-process.log",
    "cargo-metadata.json",
    "rustc-version.txt",
}
BUILD_ENVIRONMENT = (
    "RUSTUP_TOOLCHAIN",
    "CARGO_TARGET_DIR",
    "CARGO_BUILD_JOBS",
    "CARGO_BUILD_TARGET",
    "CARGO_INCREMENTAL",
    "CARGO_PROFILE_TEST_DEBUG",
    "CARGO_PROFILE_DEV_DEBUG",
    "RUSTFLAGS",
    "CARGO_ENCODED_RUSTFLAGS",
    "RUSTC_WRAPPER",
    "RUSTC_WORKSPACE_WRAPPER",
    "RUSTY_V8_ARCHIVE",
    "RUSTY_V8_MIRROR",
)


def require(value, message):
    if not value:
        raise ValueError(message)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def read(path):
    return json.loads(path.read_text(), object_pairs_hook=unique)


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def file_record(path):
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode), "regular non-symlink file required")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.lstat()
    require(
        all(
            getattr(before, key) == getattr(after, key)
            for key in (
                "st_mode",
                "st_dev",
                "st_ino",
                "st_size",
                "st_mtime_ns",
                "st_ctime_ns",
            )
        ),
        "file changed while hashing",
    )
    return {"bytes": before.st_size, "sha256": digest.hexdigest()}


def native_record(path):
    record = file_record(path)
    require(0 < record["bytes"] <= MAXIMUM_IMAGE, "original image size bound")
    with path.open("rb") as stream:
        header = stream.read(20)
    require(
        header[:6] == b"\x7fELF\x02\x01" and header[18:20] == b"\x3e\x00",
        "actual native x64 ELF required",
    )
    require(os.access(path, os.X_OK), "actual native image must be executable")
    return record


def ci(job):
    require(
        os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
        and os.environ.get("RUNNER_OS") == "Linux"
        and os.environ.get("RUNNER_ARCH") == "X64"
        and sys.platform == "linux"
        and platform.machine() == "x86_64"
        and os.geteuid() != 0,
        "actual nonroot GitHub-hosted native x64 required",
    )
    keys = (
        "GITHUB_REPOSITORY",
        "GITHUB_RUN_ID",
        "GITHUB_RUN_ATTEMPT",
        "GITHUB_WORKFLOW_REF",
        "GITHUB_WORKFLOW_SHA",
        "GITHUB_SHA",
    )
    value = {key: os.environ.get(key) for key in keys}
    require(
        value["GITHUB_REPOSITORY"] == REPOSITORY
        and os.environ.get("GITHUB_JOB") == job,
        "unexpected producer/consumer job",
    )
    require(
        all(
            re.fullmatch(r"[1-9][0-9]*", value[key] or "")
            for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")
        ),
        "missing CI run identity",
    )
    require(
        isinstance(value["GITHUB_WORKFLOW_REF"], str)
        and value["GITHUB_WORKFLOW_REF"].startswith(REPOSITORY + "/" + WORKFLOW + "@")
        and all(
            re.fullmatch(r"[0-9a-f]{40}", value[key] or "")
            for key in ("GITHUB_WORKFLOW_SHA", "GITHUB_SHA")
        ),
        "missing workflow identity",
    )
    return dict(
        value, producer_job="cell-host-v2", runner_os="Linux", runner_arch="X64"
    )


def candidate():
    require(
        os.environ.get("HEPTA_CI_LANE") == "source-head", "source-head artifact only"
    )
    return candidate_plan(
        source=os.environ["SOURCE_SHA"],
        tested=os.environ["TESTED_SHA"],
        base=os.environ["BASE_SHA"],
        lane="source-head",
    )


def receipt(
    path, source, tests, *, command=None, exact=False, log_path=None, repository=None
):
    value = read(path)
    require(
        all(
            type(value.get(key)) is int
            for key in (
                "exit_code",
                "command_exit_code",
                "minimum_tests",
                "observed_passed_tests",
                "observed_failed_tests",
            )
        )
        and value["minimum_tests"] >= tests,
        "typed actual command counts required",
    )
    require(
        value.get("status") == "passed"
        and value.get("exit_code") == 0
        and value.get("command_exit_code") == 0
        and value.get("timed_out") is False
        and value.get("output_limit_exceeded") is False,
        "actual command did not pass",
    )
    require(
        value.get("source_sha") == source["source_sha"]
        and value.get("tested_sha") == source["tested_sha"]
        and value.get("base_sha") == (source["base_sha"] or "")
        and value.get("lane") == "source-head",
        "command source tuple mismatch",
    )
    expected = {
        "commit": source["tested_sha"],
        "tree": source["tested_tree"],
        "parents": git(
            "show", "-s", "--format=%P", source["tested_sha"], repository=repository
        ).split(),
        "dirty": False,
    }
    require(
        value.get("before") == value.get("after") == expected,
        "command source bytes changed",
    )
    require(
        value.get("run_id") == os.environ["GITHUB_RUN_ID"]
        and value.get("run_attempt") == os.environ["GITHUB_RUN_ATTEMPT"],
        "cross-run command",
    )
    if command is not None:
        require(value.get("command") == command, "unexpected native command")
    name = value.get("log_file", "")
    require(
        Path(name).name == name and name not in {"", ".", ".."},
        "unsafe command log path",
    )
    log = log_path if log_path is not None else path.parent / name
    require(
        file_record(log)
        == {"bytes": value.get("log_bytes"), "sha256": value.get("log_sha256")},
        "command log bytes mismatch",
    )
    text = log.read_text(errors="replace")
    passed, failed = observed_test_counts(text)
    require(
        passed == value.get("observed_passed_tests")
        and failed == 0
        and value.get("observed_failed_tests") == 0
        and (passed == tests if exact else passed >= tests),
        "zero, missing or failed controls",
    )
    if exact:
        summaries = re.findall(
            r"Ran (\d+) tests? in [^\n]+\n\s*\n?(OK|FAILED)([^\n]*)", text
        )
        require(
            summaries == [(str(tests), "OK", "")],
            "skipped or incomplete installed controls",
        )
        require(
            len(re.findall(r"^test_\S+ \([^\n]+\) \.\.\. ok$", text, re.M)) == tests,
            "each real unittest must be observed passing",
        )
    return value, log


def pack(output, cli_receipt):
    run_identity, source, before = ci("cell-host-v2"), candidate(), identity()
    cli, log = receipt(cli_receipt, source, 3, command=CLI_COMMAND)
    require(cli["job"] == "cell-host-v2", "different native producer")
    metadata_raw = subprocess.check_output(
        [
            "cargo",
            "metadata",
            "--locked",
            "--offline",
            "--no-deps",
            "--format-version",
            "1",
            "--manifest-path",
            "codex-rs/Cargo.toml",
        ]
    )
    metadata = json.loads(metadata_raw)
    require(
        Path(metadata["workspace_root"]) == Path.cwd() / "codex-rs"
        and not os.environ.get("CARGO_BUILD_TARGET"),
        "unexpected native Cargo workspace/target",
    )
    binary = Path(metadata["target_directory"]) / "debug/hepta-neural-agentd"
    native = native_record(binary)
    compiler = subprocess.check_output(["rustc", "-vV"])
    require(
        b"release: 1.96.0\n" in compiler
        and b"host: x86_64-unknown-linux-gnu\n" in compiler,
        "original Hepta native compiler required",
    )
    output.mkdir(parents=True, exist_ok=False)
    with binary.open("rb") as original, (output / "native.gz").open("xb") as compressed:
        with gzip.GzipFile(fileobj=compressed, mode="wb", mtime=0) as stream:
            shutil.copyfileobj(original, stream)
    require(native_record(binary) == native, "native image changed during export")
    shutil.copyfile("codex-rs/Cargo.lock", output / "Cargo.lock")
    write(output / "candidate-tuple.json", source)
    shutil.copyfile(cli_receipt, output / "cli-process.json")
    shutil.copyfile(log, output / "cli-process.log")
    (output / "cargo-metadata.json").write_bytes(metadata_raw)
    (output / "rustc-version.txt").write_bytes(compiler)
    require(identity() == before, "producer checkout changed")
    write(
        output / "artifact.json",
        dict(
            schema="hepta-cell-native-image-v1",
            ci=run_identity,
            candidate=source,
            source_identity=before,
            binary=native,
            build_environment={key: os.environ.get(key) for key in BUILD_ENVIRONMENT},
            files={name: file_record(output / name) for name in sorted(FILES)},
            installed_controls_executed=False,
            model_qualified=False,
            pn0_closed=False,
        ),
    )


def verify(artifact, binary, output):
    current, source, before = ci("cell-installed-host-v3"), candidate(), identity()
    manifest = read(artifact / "artifact.json")
    require(
        set(path.name for path in artifact.iterdir()) == FILES | {"artifact.json"},
        "complete single artifact required",
    )
    require(
        manifest.get("schema") == "hepta-cell-native-image-v1"
        and manifest.get("ci") == current
        and manifest.get("candidate") == source
        and manifest.get("source_identity") == before,
        "artifact CI or source identity mismatch",
    )
    require(
        all(
            manifest.get(key) is False
            for key in ("installed_controls_executed", "model_qualified", "pn0_closed")
        ),
        "unsupported artifact claim",
    )
    require(
        manifest.get("files")
        == {name: file_record(artifact / name) for name in sorted(FILES)},
        "artifact files changed",
    )
    require(
        read(artifact / "candidate-tuple.json") == source
        and file_record(artifact / "Cargo.lock")
        == file_record(Path("codex-rs/Cargo.lock")),
        "artifact source or lock differs",
    )
    cli = read(artifact / "cli-process.json")
    receipt(
        artifact / "cli-process.json",
        source,
        3,
        command=CLI_COMMAND,
        log_path=artifact / "cli-process.log",
    )
    require(cli["job"] == "cell-host-v2", "wrong binary producer job")
    binary.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with gzip.open(artifact / "native.gz", "rb") as stream, binary.open("xb") as target:
        while chunk := stream.read(1024 * 1024):
            total += len(chunk)
            require(total <= MAXIMUM_IMAGE, "decompressed image exceeds original limit")
            target.write(chunk)
    binary.chmod(0o555)
    require(
        native_record(binary) == manifest["binary"], "decompressed native image differs"
    )
    require(identity() == before, "consumer checkout changed")
    write(
        output,
        dict(
            schema="hepta-cell-native-image-import-v1",
            ci=current,
            candidate=source,
            source_identity=before,
            binary=native_record(binary),
            artifact_manifest=file_record(artifact / "artifact.json"),
            producer=manifest,
            installed_controls_executed=False,
            model_qualified=False,
            pn0_closed=False,
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    export = actions.add_parser("pack")
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--cli-receipt", type=Path, required=True)
    receive = actions.add_parser("verify")
    receive.add_argument("--artifact", type=Path, required=True)
    receive.add_argument("--binary", type=Path, required=True)
    receive.add_argument("--output", type=Path, required=True)
    args = vars(parser.parse_args())
    action = args.pop("action")
    return {"pack": pack, "verify": verify}[action](**args) or 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as failure:
        print("installed-image control rejected: " + str(failure), file=sys.stderr)
        raise SystemExit(2)
