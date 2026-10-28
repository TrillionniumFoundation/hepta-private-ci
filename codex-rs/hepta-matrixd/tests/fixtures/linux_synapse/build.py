"""Two sequential cold Cargo targets; preserve executable bytes before reclamation."""

import json
import os
from pathlib import Path
import shutil
import time

from .commands import Commands
from .contract import TARGET, TEST_BINARY_ID, load_contract
from .files import copy_file, describe, read_json, verify, write_json
from .dependencies import SEED_SCHEMA, copy_seed, dependency_inventory
from .inputs import build_environment, elf_closure
from .inputs import observe_inputs, sealed_path_environment, source_clean


def compiler_artifacts(path):
    artifacts = []
    for line in path.read_text().splitlines():
        value = json.loads(line)
        if value.get("reason") == "compiler-artifact" and value.get("executable"):
            artifacts.append(value)
    return artifacts


def select_executable(artifacts, name, kind, target):
    selected = [
        item
        for item in artifacts
        if item["target"]["name"] == name and item["target"]["kind"] == [kind]
    ]
    if len(selected) != 1:
        raise ValueError(f"Expected one actual compiler artifact for {name}")
    item = selected[0]
    executable = Path(item["executable"])
    if (
        not executable.is_relative_to(target)
        or executable.resolve(strict=True) != executable
    ):
        raise ValueError("Compiler executable escaped the cold physical target")
    if item["fresh"] or bool(item["profile"]["test"]) != (kind == "test"):
        raise ValueError(
            "Requested executable was not produced by this cold profile/target"
        )
    return item


def preserved_artifact(item, target, frozen):
    source = Path(item["executable"])
    relative = source.relative_to(target)
    destination = frozen / relative
    copy_file(source, destination, executable=True)
    return {
        "path": str(destination),
        **describe(destination),
        "original_path": str(source),
        "compiler_artifact": item,
    }


def build_inside(plan_path, plan_sha):
    plan = read_json(plan_path, plan_sha)
    contract = load_contract(
        Path(plan["builder_seal"]["path"]), plan["builder_seal"]["sha256"]
    )
    source_seal = read_json(
        Path(plan["source_seal"]["path"]), plan["source_seal"]["sha256"]
    )
    source = Path(source_seal["source_root"])
    work = Path("/hepta-build")
    for name in ("home", "tmp", "frozen-test", "frozen-product"):
        (work / name).mkdir(mode=0o700, exist_ok=False)
    closed_path = sealed_path_environment(contract, work / "closed-bin")
    environment = build_environment(contract, work, closed_path)
    commands = Commands(work / "commands", contract["tools"], environment, source)
    record = {
        "schema": "hepta.synapse.linux.build.v1",
        "status": "started",
        "promotion_allowed": False,
        "layout": "sequential cold test target then cold product target; never two live caches",
        "build_environment": environment,
        "commands": [],
        "binaries": {},
    }
    write_json(work / "BUILD_STARTED.json", record)
    try:
        source_clean(commands, source_seal)
        before = observe_inputs(contract, commands, work)
        seed = read_json(
            Path(plan["seed_ledger"]["path"]), plan["seed_ledger"]["sha256"]
        )
        if seed.get("schema") != SEED_SCHEMA:
            raise ValueError("Unsupported offline dependency seed schema")
        copy_seed(Path("/hepta-seed"), work / "cargo-home", seed["files"])
        profile = ["--locked", "--offline", "--target", TARGET]
        target = work / "cold-test"
        target.mkdir(mode=0o700, exist_ok=False)
        test_started = time.monotonic()
        env = {"CARGO_TARGET_DIR": str(target)}
        _, test_json = commands.run(
            "cargo",
            [
                "build",
                "--manifest-path",
                str(source / "codex-rs/Cargo.toml"),
                *profile,
                "--profile",
                "test",
                "-p",
                "codex-hepta-matrixd",
                "--features",
                "real-synapse-e2e",
                "--test",
                "real_synapse_e2e",
                "--message-format=json-render-diagnostics",
            ],
            label="cold-test-build",
            environment=env,
        )
        artifacts = compiler_artifacts(test_json)
        selected = select_executable(artifacts, "real_synapse_e2e", "test", target)
        record["binaries"]["test"] = preserved_artifact(
            selected, target, work / "frozen-test"
        )
        # Keep every executable emitted by this requested cold build, including
        # Cargo's non-test package binary, without retaining regenerable objects.
        extra = []
        for item in artifacts:
            if item is not selected:
                extra.append(preserved_artifact(item, target, work / "frozen-test"))
        record["other_test_build_executables"] = extra
        _, metadata = commands.run(
            "cargo",
            [
                "metadata",
                "--manifest-path",
                str(source / "codex-rs/Cargo.toml"),
                "--locked",
                "--offline",
                "--format-version",
                "1",
                "--features",
                "codex-hepta-matrixd/real-synapse-e2e",
            ],
            label="cargo-metadata",
            environment=env,
        )
        copy_file(metadata, work / "cargo-metadata.json")
        _, binaries = commands.run(
            "cargo-nextest",
            [
                "nextest",
                "list",
                "--list-type",
                "binaries-only",
                "--message-format",
                "json",
                "--cargo-metadata",
                str(work / "cargo-metadata.json"),
                *profile,
                "--cargo-profile",
                "test",
                "-p",
                "codex-hepta-matrixd",
                "--features",
                "real-synapse-e2e",
                "--test",
                "real_synapse_e2e",
            ],
            label="frozen-test-binaries-metadata",
            environment=env,
        )
        listing = read_json(binaries)
        if set(listing["rust-binaries"]) != {TEST_BINARY_ID}:
            raise ValueError(
                "Nextest binary inventory is not exactly the original real Synapse test target"
            )
        binary = listing["rust-binaries"][TEST_BINARY_ID]
        if binary["binary-path"] != selected["executable"] or listing[
            "rust-build-meta"
        ]["target-directory"] != str(target):
            raise ValueError(
                "Nextest metadata does not refer to the just-preserved cold executable"
            )
        copy_file(binaries, work / "binaries-metadata.json")
        verify(
            Path(selected["executable"]),
            {key: record["binaries"]["test"][key] for key in ("bytes", "sha256")},
        )
        _, full_list = commands.run(
            "cargo-nextest",
            [
                "nextest",
                "list",
                "--cargo-metadata",
                str(work / "cargo-metadata.json"),
                "--binaries-metadata",
                str(work / "binaries-metadata.json"),
                "--message-format",
                "json",
            ],
            label="cold-full-test-inventory",
            environment=env,
        )
        complete = read_json(full_list)
        if set(complete["rust-suites"]) != {TEST_BINARY_ID}:
            raise ValueError("Cold test-case inventory includes an unexpected binary")
        record["testcase_inventory"] = {
            name: {"ignored": item["ignored"]}
            for name, item in complete["rust-suites"][TEST_BINARY_ID][
                "testcases"
            ].items()
        }
        copy_file(full_list, work / "full-test-inventory.json")
        record["cold_test_seconds"] = time.monotonic() - test_started
        record["cold_test_artifacts"] = {
            "cargo_json": {"path": str(test_json), **describe(test_json)},
            "metadata": describe(work / "cargo-metadata.json"),
            "binaries_metadata": describe(work / "binaries-metadata.json"),
            "full_test_inventory": describe(work / "full-test-inventory.json"),
        }
        write_json(work / "COLD_TEST_PRESERVED.json", record)
        shutil.rmtree(target)
        if target.exists():
            raise ValueError("Completed cold test target was not reclaimed")
        target = work / "cold-product"
        target.mkdir(mode=0o700, exist_ok=False)
        env = {"CARGO_TARGET_DIR": str(target)}
        product_started = time.monotonic()
        record["product_cargo_json"] = {}
        for key, package, features in (
            ("agentd", "codex-hepta-agentd", []),
            ("matrixd", "codex-hepta-matrixd", ["--features", "real-synapse-e2e"]),
        ):
            _, cargo_json = commands.run(
                "cargo",
                [
                    "build",
                    "--manifest-path",
                    str(source / "codex-rs/Cargo.toml"),
                    *profile,
                    "--profile",
                    "dev",
                    "-p",
                    package,
                    "--bin",
                    package,
                    *features,
                    "--message-format=json-render-diagnostics",
                ],
                label=f"cold-product-{key}",
                environment=env,
            )
            item = select_executable(
                compiler_artifacts(cargo_json), package, "bin", target
            )
            record["binaries"][key] = preserved_artifact(
                item, target, work / "frozen-product"
            )
            record["product_cargo_json"][key] = {
                "path": str(cargo_json),
                **describe(cargo_json),
            }
        record["cold_product_seconds"] = time.monotonic() - product_started
        record["executable_elf_closures"] = {
            key: elf_closure(commands, value["path"], "actual-" + key)
            for key, value in record["binaries"].items()
        }
        write_json(work / "COLD_PRODUCT_PRESERVED.json", record)
        shutil.rmtree(target)
        source_clean(commands, source_seal)
        if dependency_inventory(work / "cargo-home") != seed["files"]:
            raise ValueError(
                "A dependency input changed during the locked offline build"
            )
        final_directory = work / "input-readback"
        final_directory.mkdir(mode=0o700)
        after = observe_inputs(contract, commands, final_directory)
        for key in (
            "tools",
            "rust_sysroot",
            "tool_elf_closures",
            "rustc_vv",
            "cargo_version",
            "rustdoc_version",
            "nextest_version",
        ):
            if before[key] != after[key]:
                raise ValueError(
                    f"Actual image input changed during compilation: {key}"
                )
        record.update(
            status="built_not_executed",
            seed_unchanged=True,
            source_clean=True,
            both_cold_targets_reclaimed=True,
            inputs_before=describe(work / "INPUTS.json"),
            inputs_after=describe(final_directory / "INPUTS.json"),
        )
    except BaseException as error:
        record.update(
            status="failed", error_type=type(error).__name__, error=str(error)
        )
        raise
    finally:
        record["commands"] = commands.records
        write_json(work / "BUILD_RESULT.json", record)
    return record
