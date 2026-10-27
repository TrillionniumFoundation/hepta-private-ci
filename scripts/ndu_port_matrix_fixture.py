#!/usr/bin/env python3
"""Produce Matrix 0.18 data in the fixed old checkout; reopen only a sealed copy."""

import argparse
import json
import os
from pathlib import Path
import shutil
import tomllib
import xml.etree.ElementTree as ET

from ndu_port_candidate_common import OLD_SOURCE
from ndu_port_candidate_common import RECIPE
from ndu_port_candidate_common import Recorder
from ndu_port_candidate_common import changed_paths
from ndu_port_candidate_common import check_checkout
from ndu_port_candidate_common import check_toolchain
from ndu_port_candidate_common import checksum
from ndu_port_candidate_common import copy_files
from ndu_port_candidate_common import describe
from ndu_port_candidate_common import load_recipe
from ndu_port_candidate_common import patch_paths
from ndu_port_candidate_common import prepare_nextest_storage
from ndu_port_candidate_common import tree_files


SCHEMA = "hepta.ci.matrix-old-fixture.v1"
TEST_PATH = "codex-rs/hepta-matrix-sdk/tests/store_version_migration.rs"
OLD_PACKAGES = ("matrix-sdk", "matrix-sdk-crypto", "matrix-sdk-sqlite")


def verify_old_packages(lock):
    packages = tomllib.loads(lock.read_text())["package"]
    for name in OLD_PACKAGES:
        versions = [row["version"] for row in packages if row["name"] == name]
        if versions != ["0.18.0"]:
            raise ValueError(
                f"Old fixture must resolve exactly {name} 0.18.0, got {versions}"
            )


def parse_phase_junit(path, expected):
    report = ET.parse(path).getroot()
    cases = list(report.iter("testcase"))
    if len(cases) != 1 or cases[0].get("name") != expected:
        raise ValueError("The exact migration test must be the only executed testcase")
    if cases[0].get("classname") != "codex-hepta-matrix-sdk::store_version_migration":
        raise ValueError("Migration testcase came from a different test binary")
    rejected = {
        "failure",
        "error",
        "skipped",
        "flakyFailure",
        "flakyError",
        "rerunFailure",
        "rerunError",
    }
    if any(node.tag in rejected for node in report.iter()):
        raise ValueError("Skipped, failed or retried migration tests are not a pass")
    if report.get("tests") != "1" or any(
        int(report.get(name, "0")) for name in ("failures", "errors", "skipped")
    ):
        raise ValueError("Migration requires one executed pass and no failures/skips")
    return {"name": expected, "executed": 1, "passed": 1, "failed": 0, "skipped": 0}


def run_phase(runner, name, fixture):
    manifest = str(runner.root / "codex-rs/Cargo.toml")
    storage = prepare_nextest_storage(runner)
    selection = [
        "--locked",
        "--cargo-profile",
        "ci-test",
        "-p",
        "codex-hepta-matrix-sdk",
        "--test",
        "store_version_migration",
        "--tool-config-file",
        storage["tool_config_argument"],
    ]
    listing = runner.json_command(
        f"{name}-binaries",
        [
            "cargo",
            "nextest",
            "list",
            "--manifest-path",
            manifest,
            *selection,
            "--list-type",
            "binaries-only",
            "--message-format",
            "json",
        ],
    )
    binaries = list(listing["rust-binaries"].values())
    if (
        len(binaries) != 1
        or binaries[0]["binary-name"] != "store_version_migration"
        or binaries[0]["kind"] != "test"
    ):
        raise ValueError("Expected exactly the actual migration test executable")
    binary = Path(binaries[0]["binary-path"])
    if binary.is_symlink() or not binary.is_file():
        raise ValueError("Migration executable is not a regular compiled file")
    digest = checksum(binary)
    saved = runner.output / "binaries" / digest
    saved.parent.mkdir(exist_ok=True)
    shutil.copyfile(binary, saved)
    if checksum(saved) != digest:
        raise ValueError("Saved executable differs from the compiled binary")
    target = Path(listing["rust-build-meta"]["target-directory"])
    store = Path(storage["directory"])
    reports = lambda: {
        path: (path.stat().st_mtime_ns, checksum(path))
        for path in store.glob("*/junit.xml")
    }
    before = reports()
    status = runner.run(
        name,
        [
            "just",
            "test",
            *selection,
            "--profile",
            "default",
            "--run-ignored",
            "only",
            "-E",
            f"test(={name})",
            "--retries",
            "0",
            "--no-tests",
            "fail",
        ],
        required=False,
        environment={"HEPTA_MATRIX_MIGRATION_FIXTURE": str(fixture.resolve())},
    )
    phase = {
        "name": name,
        "exit_code": status,
        "binary": str(saved.relative_to(runner.output)),
        "binary_sha256": digest,
        "binary_original_path": str(binary),
        "binary_unchanged_after_execution": checksum(binary) == digest,
        "command_index": len(runner.record["commands"]) - 1,
        "nextest_storage": storage,
        "cargo_target_directory": str(target),
        "store_config_unchanged_after_execution": describe(
            runner.output, (storage["config_file"],)
        )[storage["config_file"]]
        == storage["config"],
    }
    runner.record["migration_phase"] = phase
    fresh = [path for path, value in reports().items() if before.get(path) != value]
    phase["fresh_junit_count"] = len(fresh)
    phase["observed_junit_paths"] = [str(path) for path in fresh]
    for index, path in enumerate(fresh):
        shutil.copyfile(path, runner.output / f"{name}-{index}-junit.xml")
    phase["retained_junit_reports"] = describe(
        runner.output, [f"{name}-{index}-junit.xml" for index in range(len(fresh))]
    )
    runner.save()
    if (
        status
        or not phase["binary_unchanged_after_execution"]
        or not phase["store_config_unchanged_after_execution"]
        or fresh != [store / "default/junit.xml"]
    ):
        raise ValueError(
            "Migration command failed, executable changed or fresh JUnit is missing"
        )
    copied = runner.output / f"{name}-0-junit.xml"
    phase["junit"] = {"file": copied.name, "sha256": checksum(copied)}
    phase["observed_test"] = parse_phase_junit(copied, name)
    runner.save()
    return phase


def produce_old_fixture(runner, driver_root, driver_source):
    if Path(__file__).resolve() != driver_root / "scripts/ndu_port_matrix_fixture.py":
        raise ValueError("Baseline must use the checked-out new driver's exact script")
    if (
        driver_root == runner.root
        or driver_root.is_relative_to(runner.root)
        or runner.root.is_relative_to(driver_root)
    ):
        raise ValueError(
            "Old and new source checkouts must be independent sibling directories"
        )
    context = Recorder(
        driver_root,
        runner.output / "driver-context",
        "old-fixture-driver",
        toolchain="1.95.0",
    )
    check_checkout(context, driver_source)
    recipe = load_recipe(driver_root)
    context.record.update(
        status="driver_inputs_verified", recipe_sha256=checksum(driver_root / RECIPE)
    )
    context.save()
    runner.record.update(
        driver_source_commit=driver_source,
        recipe_sha256=checksum(driver_root / RECIPE),
        driver_inputs=describe(
            driver_root,
            (
                RECIPE,
                "scripts/ndu_port_matrix_fixture.py",
                "scripts/ndu_port_candidate_common.py",
            ),
        ),
    )
    shutil.copyfile(driver_root / RECIPE, runner.output / "recipe.json")
    patch = runner.output / "fixture-only.patch"
    shutil.copyfile(
        driver_root / recipe["matrix_baseline"]["fixture_patch_path"], patch
    )
    if checksum(patch) != recipe["matrix_baseline"]["fixture_patch_sha256"]:
        raise ValueError("Old fixture input patch changed while copying")
    check_checkout(runner, OLD_SOURCE)
    lock = runner.root / "codex-rs/Cargo.lock"
    verify_old_packages(lock)
    frozen_lock = describe(runner.root, ("codex-rs/Cargo.lock",))
    copy_files(runner.root, runner.output / "original-files", frozen_lock)
    runner.record["original_lock"] = frozen_lock
    if patch_paths(runner, patch) != {TEST_PATH}:
        raise ValueError(
            "Only the isolated migration fixture test may change the old source"
        )
    runner.run(
        "check-fixture-only-patch", ["git", "apply", "--check", "--index", str(patch)]
    )
    runner.run("apply-fixture-only-patch", ["git", "apply", "--index", str(patch)])
    frozen_test = describe(runner.root, (TEST_PATH,))
    source_tree = runner.text("compiled-source-tree", ["git", "write-tree"])
    runner.record["compiled_source_tree"] = source_tree
    source_archive = runner.output / "compiled-source.tar.gz"
    runner.run(
        "archive-compiled-source",
        [
            "git",
            "archive",
            "--format=tar.gz",
            f"--output={source_archive}",
            source_tree,
        ],
    )
    check_toolchain(runner, "1.95.0")
    runner.run("nextest-version", ["cargo", "nextest", "--version"])
    metadata = runner.json_command(
        "old-metadata",
        [
            "cargo",
            "metadata",
            "--manifest-path",
            str(runner.root / "codex-rs/Cargo.toml"),
            "--locked",
            "--format-version",
            "1",
        ],
    )
    for name in OLD_PACKAGES:
        if [x["version"] for x in metadata["packages"] if x["name"] == name] != [
            "0.18.0"
        ]:
            raise ValueError(
                "Old producer metadata selected a different Matrix package"
            )
    fixture = runner.output / "fixture"
    fixture.mkdir(exist_ok=False)
    phase = run_phase(runner, "prepare_old_version_fixture", fixture)
    if (
        describe(runner.root, frozen_lock) != frozen_lock
        or describe(runner.root, frozen_test) != frozen_test
    ):
        raise ValueError(
            "Old producer changed its original lock or fixture test source"
        )
    if changed_paths(runner) != {TEST_PATH} or runner.text(
        "old-source-unstaged", ["git", "diff", "--name-only"]
    ):
        raise ValueError("The compiled old checkout changed beyond the sole test patch")
    inventory = tree_files(fixture)
    if "expected.json" not in inventory or len(inventory) < 2:
        raise ValueError(
            "The old producer did not deliver both expected state and database files"
        )
    runner.record.update(
        fixture_files=inventory,
        sidecar_files=[
            name for name in inventory if name.endswith(("-wal", "-shm", "-journal"))
        ],
        fixture_capture="Complete file set after the nextest child process exited, including every surviving DB/WAL/SHM file.",
        baseline_versions={name: "0.18.0" for name in OLD_PACKAGES},
        artifacts=describe(
            runner.output,
            (
                "recipe.json",
                "fixture-only.patch",
                "compiled-source.tar.gz",
                "old-metadata.json",
                "original-files/codex-rs/Cargo.lock",
                phase["binary"],
                phase["junit"]["file"],
                phase["nextest_storage"]["config_file"],
            ),
        ),
        status="old_fixture_generated",
        qualification="Actual old source and old lock fixture producer only; no new-version migration pass is implied.",
    )


def consume_old_fixture(
    runner, recipe, artifact, expected_result, expected_driver_source
):
    if checksum(artifact / "RESULT.json") != expected_result:
        raise ValueError("Old fixture RESULT differs from the producer job hash")
    record = json.loads((artifact / "RESULT.json").read_text())
    if (
        record.get("schema") != SCHEMA
        or record.get("status") != "old_fixture_generated"
    ):
        raise ValueError("Artifact is not a successful independent old fixture")
    if (
        record["source_commit"] != OLD_SOURCE
        or record["driver_source_commit"] != expected_driver_source
    ):
        raise ValueError(
            "Old fixture source/driver differs from the fixed independent sources"
        )
    if record["toolchain"] != "1.95.0" or record["recipe_sha256"] != checksum(
        runner.root / RECIPE
    ):
        raise ValueError("Old fixture compiler or recipe differs")
    if record["baseline_versions"] != {name: "0.18.0" for name in OLD_PACKAGES}:
        raise ValueError("Old fixture did not use the original Matrix 0.18 packages")
    for key in ("github_run_id", "github_run_attempt"):
        if os.environ.get(key.upper()) and record.get(key) != os.environ[key.upper()]:
            raise ValueError("Old fixture came from another workflow run/attempt")
    if describe(artifact, record["artifacts"]) != record["artifacts"]:
        raise ValueError("Old source/lock/binary/artifact bytes differ")
    if (
        record["artifacts"]["fixture-only.patch"]["sha256"]
        != recipe["matrix_baseline"]["fixture_patch_sha256"]
    ):
        raise ValueError("Old fixture patch differs from the reviewed patch")
    verify_old_packages(artifact / "original-files/codex-rs/Cargo.lock")
    phase = record["migration_phase"]
    if phase["exit_code"] != 0 or phase["binary_unchanged_after_execution"] is not True:
        raise ValueError("Old producer did not retain a successful actual executable")
    parse_phase_junit(artifact / phase["junit"]["file"], "prepare_old_version_fixture")
    original = artifact / "fixture"
    if tree_files(original) != record["fixture_files"]:
        raise ValueError("Old database file set or bytes differ from the producer")
    working = runner.output / "writable-old-fixture"
    shutil.copytree(original, working)
    if tree_files(working) != record["fixture_files"]:
        raise ValueError("The independent writable copy differs before migration")
    for path in (original, *original.rglob("*")):
        path.chmod(path.stat().st_mode & ~0o222)
    working.chmod(working.stat().st_mode | 0o200)
    for path in working.rglob("*"):
        path.chmod(path.stat().st_mode | 0o200)
    runner.record["old_fixture_input"] = {
        "producer_result_sha256": expected_result,
        "old_source": OLD_SOURCE,
        "driver_source": expected_driver_source,
        "recipe_sha256": record["recipe_sha256"],
        "files_before_reopen": record["fixture_files"],
        "compiled_source_tree": record["compiled_source_tree"],
        "producer_binary_sha256": phase["binary_sha256"],
    }
    try:
        run_phase(runner, "reopen_old_version_fixture", working)
    finally:
        unchanged = tree_files(original) == record["fixture_files"]
        runner.record["old_fixture_input"][
            "producer_fixture_unchanged_after_reopen"
        ] = unchanged
        runner.record["old_fixture_input"]["files_after_reopen"] = tree_files(working)
        runner.save()
        if not unchanged:
            raise ValueError("Consumer changed the preserved original old fixture")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--driver-repository", type=Path, required=True)
    parser.add_argument("--expected-driver-source", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    runner = Recorder(
        args.repository, args.output, "matrix-old-producer", toolchain="1.95.0"
    )
    runner.record["schema"] = SCHEMA
    success = False
    try:
        produce_old_fixture(
            runner, args.driver_repository.resolve(), args.expected_driver_source
        )
        success = True
    except Exception as error:
        runner.record.update(
            status="failed", error_type=type(error).__name__, error=str(error)
        )
        fixture = runner.output / "fixture"
        if fixture.is_dir():
            runner.record["partial_fixture_files"] = tree_files(fixture)
    finally:
        runner.save()
    if success and os.environ.get("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
            stream.write(f"result_sha256={checksum(runner.output / 'RESULT.json')}\n")
    print(
        json.dumps(
            {
                "status": runner.record["status"],
                "result": str(runner.output / "RESULT.json"),
            }
        ),
        flush=True,
    )
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
