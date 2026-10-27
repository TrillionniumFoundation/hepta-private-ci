"""Execute frozen binaries through the repository's real just/nextest entry point."""

import json
from pathlib import Path
import time

from .commands import Commands
from .contract import TEST_BINARY_ID, TEST_NAME, load_contract
from .files import describe, read_json, verify, write_bytes, write_json
from .inputs import (
    build_environment,
    observe_inputs,
    sealed_path_environment,
    source_clean,
)
from .receipts import junit


def validate_test_listing(listing, build):
    suites = listing["rust-suites"]
    if set(suites) != {TEST_BINARY_ID}:
        raise ValueError("Executing test inventory contains an unexpected binary")
    suite = suites[TEST_BINARY_ID]
    inventory = {
        name: {"ignored": item["ignored"]} for name, item in suite["testcases"].items()
    }
    if inventory != build["testcase_inventory"]:
        raise ValueError(
            "Actual executable test-case inventory differs from the frozen cold build"
        )
    matched = {
        name
        for name, item in suite["testcases"].items()
        if item["filter-match"]["status"] == "matches"
    }
    if matched != {TEST_NAME} or suite["testcases"][TEST_NAME]["ignored"]:
        raise ValueError(
            "The exact filter must select only the original nonignored business test"
        )
    if any(
        item["filter-match"]["status"] not in {"matches", "mismatch"}
        for item in suite["testcases"].values()
    ):
        raise ValueError("Unknown nextest filter disposition")
    actual = suite["binary-path"]
    if actual != build["binaries"]["test"]["path"]:
        raise ValueError(
            "Nextest relocated execution path is not the preserved cold test binary"
        )
    verify(
        Path(actual),
        {key: build["binaries"]["test"][key] for key in ("bytes", "sha256")},
    )
    return {
        "actual_binary_path": actual,
        "total_cases_retained": len(inventory),
        "selected_cases": sorted(matched),
    }


def run_inside(plan_path, plan_sha):
    plan = read_json(plan_path, plan_sha)
    builder = load_contract(
        Path(plan["builder_seal"]["path"]), plan["builder_seal"]["sha256"]
    )
    source = read_json(Path(plan["source_seal"]["path"]), plan["source_seal"]["sha256"])
    build = read_json(
        Path(plan["build_result"]["path"]), plan["build_result"]["sha256"]
    )
    root, checkout = Path("/hepta-runtime"), Path(source["source_root"])
    for name in ("home", "tmp", "cargo-home"):
        (root / name).mkdir(mode=0o700, exist_ok=False)
    environment = build_environment(
        builder, root, sealed_path_environment(builder, root / "closed-bin")
    )
    environment.update(
        CARGO_TARGET_DIR="/hepta-build/frozen-test",
        HEPTA_R4_FIXTURE_MANIFEST=plan["fixture_manifest"]["path"],
        HEPTA_R4_COMPLETION_DIRECTORY=str(root / "completion"),
        HEPTA_R4_COMPLETION_NONCE_FILE=str(root / "credentials/completion-nonce"),
    )
    commands = Commands(root / "commands", builder["tools"], environment, checkout)
    record = {
        "schema": "hepta.synapse.linux.execution.v1",
        "status": "started",
        "scope": "native-linux-arm64",
        "promotion_allowed": False,
        "commands": [],
    }
    write_json(root / "EXECUTION_STARTED.json", record)
    try:
        source_clean(commands, source)
        observed = observe_inputs(builder, commands, root)
        verify(Path("/hepta-build/INPUTS.json"), build["inputs_before"])
        compiled_inputs = read_json(Path("/hepta-build/INPUTS.json"))
        for key in (
            "tools",
            "rust_sysroot",
            "tool_elf_closures",
            "rustc_vv",
            "cargo_version",
            "rustdoc_version",
            "nextest_version",
        ):
            if observed[key] != compiled_inputs[key]:
                raise ValueError(
                    "Runtime image/sysroot/tools differ from the actual cold build"
                )
        verify(
            Path(plan["fixture_manifest"]["path"]),
            {key: plan["fixture_manifest"][key] for key in ("bytes", "sha256")},
        )
        for binary in build["binaries"].values():
            verify(
                Path(binary["path"]), {key: binary[key] for key in ("bytes", "sha256")}
            )
        metadata_inputs = {
            "cargo-metadata.json": build["cold_test_artifacts"]["metadata"],
            "binaries-metadata.json": build["cold_test_artifacts"]["binaries_metadata"],
            "full-test-inventory.json": build["cold_test_artifacts"][
                "full_test_inventory"
            ],
        }
        for name, identity in metadata_inputs.items():
            verify(Path("/hepta-build") / name, identity)
        config = root / "nextest-linux.toml"
        store = root / "nextest-store"
        if store.exists():
            raise ValueError("JUnit/nextest store must be new for this one execution")
        write_bytes(
            config,
            (
                "[store]\ndir = " + json.dumps(str(store)) + "\n"
                "[profile.linux-synapse]\nretries = 0\ntest-threads = 1\n"
                'slow-timeout = { period = "60s", terminate-after = 20 }\n'
                '[profile.linux-synapse.junit]\npath = "junit.xml"\n'
            ).encode(),
        )
        selected = f"binary_id(={TEST_BINARY_ID}) & test(={TEST_NAME})"
        reused = [
            "--cargo-metadata",
            "/hepta-build/cargo-metadata.json",
            "--binaries-metadata",
            "/hepta-build/binaries-metadata.json",
            "--target-dir-remap",
            "/hepta-build/frozen-test",
            "--profile",
            "linux-synapse",
            "--tool-config-file",
            f"hepta-linux:{config}",
            "-E",
            selected,
        ]
        _, listing_path = commands.run(
            "cargo-nextest",
            ["nextest", "list", *reused, "--message-format", "json"],
            label="actual-frozen-test-list",
        )
        listing = read_json(listing_path)
        record["test_selection"] = validate_test_listing(listing, build)
        junit_path = store / "linux-synapse/junit.xml"
        if junit_path.exists():
            raise ValueError("A stale JUnit receipt exists before actual just test")
        started = time.time_ns()
        # Explicit profile overrides just's NEXTEST_PROFILE=local. Both reuse
        # metadata flags force the wrapper's ordinary nextest reuse path.
        commands.run(
            "just",
            [
                "--justfile",
                str(checkout / "justfile"),
                "test",
                *reused,
                "--retries",
                "0",
                "--test-threads",
                "1",
                "--no-tests",
                "fail",
            ],
            label="actual-just-test",
        )
        if not junit_path.is_file() or junit_path.stat().st_mtime_ns < started:
            raise ValueError(
                "The required fresh JUnit was not written by this execution"
            )
        record["junit"] = junit(junit_path)
        source_clean(commands, source)
        for binary in build["binaries"].values():
            verify(
                Path(binary["path"]), {key: binary[key] for key in ("bytes", "sha256")}
            )
        for name, identity in metadata_inputs.items():
            verify(Path("/hepta-build") / name, identity)
        record.update(
            status="business_test_passed_pending_external_teardown",
            source_clean=True,
            preserved_binaries_unchanged=True,
            runtime_inputs=describe(root / "INPUTS.json"),
        )
    except BaseException as error:
        record.update(
            status="failed", error_type=type(error).__name__, error=str(error)
        )
        raise
    finally:
        record["commands"] = commands.records
        write_json(root / "EXECUTION_RESULT.json", record)
    return record
