"""Data gates for the one unfinished SQLx fixture continuation.

No resolver, subprocess, network, repository mutation, or native qualification
is performed by importing this module. Its file-copy helper is create-only.
"""

import hashlib
import math
import os
from pathlib import Path, PurePosixPath

REPO = "TrillionniumFoundation/hepta-private-ci"
PARENT = "b4fa4fdd1d05603c1a091930b70f83ec1af73797"
PARENT_TREE = "73e1ccd4245498fb583326667884953dbdfccbf3"
REUSE_SHA = "cf3e3d8c41332737d013699ded3c334411a9dfdcea02d222e75cf87b696d9e1f"
PEER_PATH = "scripts/hepta_chrono_hooks_cli_native_inputs_v2.json"
FIXTURES = (
    ("default", "qualification/sqlx_temporal_default_v1"),
    ("compatibility", "qualification/sqlx_temporal_explicit_chrono_v1"),
)
MAIN_LOCKS = {
    "codex-rs/Cargo.lock": {
        "bytes": 421756,
        "sha256": "bc8b1abe42bdb85aa10a9ba2a0c3f022af07bc08e38ac50e94442e58806f9ae1",
    },
    "MODULE.bazel.lock": {
        "bytes": 1792663,
        "sha256": "288cc0b12854164157ba9cd9b94f1c236af99f3cf532b2bedf2605f589e47892",
    },
}
RELATION_BASELINE = {
    "bytes": 421800,
    "sha256": "d30163218a74e0d8246e709a82c2547fa3306515728b4b9784d0df4034b6c312",
    "git_blob": "076ccdef0072f87ac64a2a020677b52de529b1bd",
}
CEILINGS = {
    "checkout_seconds": 120,
    "tool_preparation_seconds": 180,
    "generation_seconds": 900,
    "whole_job_seconds": 1320,
}
SPENT = {
    "checkout_seconds": 13.027237997,
    "tool_preparation_seconds": 15.091586110999998,
    "generation_seconds": 50.812052642000005,
    "whole_job_seconds": 98,
}
TARGET = "aarch64-unknown-linux-gnu"
COMMAND_CAPS = (300, 60, 90, 60, 90)


def require(value, message):
    if not value:
        raise ValueError(message)


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def validate_reuse(review):
    require(
        review["schema"] == "root-hepta7114-partial-main-lock-reuse-acceptance-v1"
        and review["accepted"] is True
        and review["reviewer"] == "root"
        and review["repository"] == REPO,
        "independent partial-main reuse acceptance is missing",
    )
    origin = review["origin"]
    require(
        (
            origin["head"],
            origin["tree"],
            origin["run_id"],
            origin["attempt"],
            origin["job_id"],
            origin["artifact_id"],
        )
        == (PARENT, PARENT_TREE, 45738227995, 1, 139636557660, 15083760351)
        and origin["original_job_status"] == "failure"
        and origin["original_generation_status"] == "FAIL"
        and origin["original_failure_label"] == "default-lock-generate-offline-once"
        and origin["original_failure_returncode"] == 101,
        "original failed attempt identity or failure was rewritten",
    )
    require(
        {
            path: {key: row[key] for key in ("bytes", "sha256")}
            for path, row in review["main_locks"].items()
        }
        == MAIN_LOCKS
        and review["main_metadata"]["sha256"]
        == "837c6d8b6266dc1a495040b58d5d56e57bfffaf8c3c58f9f64cceb040db84e60",
        "accepted main bytes or original graph changed",
    )
    require(
        review["execution_authorization"] is False
        and review["separate_continuation_engineering_admission_required"] is True
        and review["qualification"]["main_lock_reuse"] is True
        and all(
            value is False
            for key, value in review["qualification"].items()
            if key != "main_lock_reuse"
        )
        and review["permitted_reuse"][
            "repeat_main_update_metadata_bazel_or_twelve_controls"
        ]
        is False,
        "reuse was widened into execution or qualification",
    )
    cost = review["cost"]
    require(
        cost["original_generation_seconds"] == SPENT["generation_seconds"]
        and cost["original_complete_job_seconds"] == SPENT["whole_job_seconds"]
        and cost["original_queue_seconds"] == 4120
        and cost["original_whole_at_workflow_readback_seconds"] == 79.133119422,
        "original failure or queue cost changed",
    )
    return cost


def validate_budget(budget, spent):
    require(spent == SPENT, "spent original phase costs changed")
    require(
        isinstance(budget, dict) and budget.keys() == CEILINGS.keys(),
        "continuation budget is missing or has foreign fields",
    )
    for key, ceiling in CEILINGS.items():
        require(
            finite_number(budget[key])
            and budget[key] >= 30
            and budget[key] + spent[key] <= ceiling + 1e-9,
            "continuation exceeds remaining original allowance: " + key,
        )
    require(
        sum(
            budget[key]
            for key in (
                "checkout_seconds",
                "tool_preparation_seconds",
                "generation_seconds",
            )
        )
        + 120
        <= budget["whole_job_seconds"],
        "whole continuation leaves no collection and upload allowance",
    )
    return {key: CEILINGS[key] - spent[key] for key in CEILINGS}


def validate_peer(peer, spec):
    expected = spec["native_peer_expected_activated"]
    require(
        type(expected) is bool and peer["activated"] is expected,
        "peer activation differs from this Root admission",
    )
    require(
        peer["schema"] == "hepta.chrono-hooks-cli-native-reconstruction-inputs.v2"
        and peer["parent"] == peer["proposed_parent"] == PARENT
        and peer["branch"] == spec["branch"]
        and peer["publication_paths"] == spec["source_delta_paths"]
        and peer["lock_generation_source"] == PARENT
        and peer["lock_acceptance_review_sha256"] == REUSE_SHA,
        "peer source identity or original lock acceptance differs",
    )
    require(
        (
            peer["native_cap_seconds"],
            peer["whole_job_cap_seconds"],
            peer["exact_count"],
            peer["new_count"],
            peer["retained_count"],
        )
        == (2400, 3600, 48, 33, 15)
        and peer["roster_sha256"]
        == "573a66ecb204d62424187681155d1024e0608a57d22d3301c63b813ab93be09d"
        and {
            key: peer["tooling"][key]
            for key in (
                "rust",
                "cargo",
                "nextest",
                "just",
                "runner",
                "version_command_cap_seconds",
                "retries",
                "test_threads",
            )
        }
        == {
            "rust": "1.96.0",
            "cargo": "1.96.0",
            "nextest": "0.9.103",
            "just": "1.51.0",
            "runner": "ubuntu-24.04-arm",
            "version_command_cap_seconds": 5,
            "retries": 0,
            "test_threads": 1,
        },
        "peer exact controls, toolchain or cap changed",
    )
    require(
        isinstance(peer["activation_blockers"], list)
        and (
            peer["activation_blockers"] == []
            if expected
            else bool(peer["activation_blockers"])
        ),
        "peer activation and blockers disagree",
    )


def resolution_inputs(tree):
    return {
        path: row
        for path, row in tree.items()
        if PurePosixPath(path).name
        in ("Cargo.toml", "rust-toolchain", "rust-toolchain.toml")
        or (
            PurePosixPath(path).name in ("config", "config.toml")
            and PurePosixPath(path).parent.name == ".cargo"
        )
    }


def automatic_target_paths(tree):
    bases = {
        PurePosixPath(path).parent
        for path in tree
        if PurePosixPath(path).name == "Cargo.toml"
    }
    found = set()
    for path in tree:
        actual = PurePosixPath(path)
        for base in actual.parents:
            if base not in bases:
                continue
            rel = actual.relative_to(base)
            parts = rel.parts
            if (
                rel.as_posix() in ("src/lib.rs", "src/main.rs", "build.rs")
                or (
                    len(parts) in (2, 3)
                    and parts[0] in ("tests", "examples", "benches")
                    and (
                        parts[-1] == "main.rs"
                        if len(parts) == 3
                        else parts[-1].endswith(".rs")
                    )
                )
                or (
                    len(parts) in (3, 4)
                    and parts[:2] == ("src", "bin")
                    and (
                        parts[-1] == "main.rs"
                        if len(parts) == 4
                        else parts[-1].endswith(".rs")
                    )
                )
            ):
                found.add(path)
    return sorted(found)


def validate_manifest_equivalence(parent, current):
    require(
        resolution_inputs(parent) == resolution_inputs(current),
        "Cargo manifests, configuration or toolchain changed after original graph",
    )
    require(
        automatic_target_paths(parent) == automatic_target_paths(current),
        "Cargo automatically discovered target inventory changed",
    )
    return {
        "resolution_inputs": len(resolution_inputs(parent)),
        "automatic_target_paths": automatic_target_paths(current),
        "original_main_graph_reused_only": True,
    }


def command_plan(cargo, work):
    main = str(work / "codex-rs/Cargo.toml")
    rows = [
        (
            "main-cache-fetch-locked-once",
            cargo + ["fetch", "--locked", "--manifest-path", main],
            COMMAND_CAPS[0],
        )
    ]
    for index, (label, relative) in enumerate(FIXTURES):
        manifest = str(work / relative / "Cargo.toml")
        rows.extend(
            (
                (
                    label + "-seeded-update-workspace-offline-once",
                    cargo
                    + [
                        "update",
                        "--workspace",
                        "--offline",
                        "--manifest-path",
                        manifest,
                    ],
                    COMMAND_CAPS[1 + index * 2],
                ),
                (
                    label + "-locked-filtered-graph-offline-once",
                    cargo
                    + [
                        "metadata",
                        "--manifest-path",
                        manifest,
                        "--locked",
                        "--offline",
                        "--filter-platform",
                        TARGET,
                        "--format-version",
                        "1",
                    ],
                    COMMAND_CAPS[2 + index * 2],
                ),
            )
        )
    return rows


def validate_completed_commands(rows, plan, cargo):
    observed = [row for row in rows if row["argv"][: len(cargo)] == cargo]
    require(len(observed) == len(plan), "actual Cargo command count differs")
    for row, (label, argv, cap) in zip(observed, plan):
        require(
            row["label"] == label and row["argv"] == argv,
            "actual Cargo command identity or order differs",
        )
        result = row["execution"]
        require(
            result["returncode"] == 0
            and result["timed_out"] is False
            and result["output_limit_exceeded"] is False
            and finite_number(row["elapsed_seconds"])
            and 0 <= row["elapsed_seconds"] <= cap,
            "actual Cargo command failed or exceeded its cap: " + label,
        )
    return [
        {"label": row["label"], "elapsed_seconds": row["elapsed_seconds"]}
        for row in observed
    ]


def copy_seed(raw, destination, expected):
    require(
        pin(raw) == expected and expected["bytes"] > 0,
        "fixture seed is not the exact accepted main lock",
    )
    with destination.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    require(pin(destination.read_bytes()) == expected, "fixture seed copy differs")
    return {
        "source": expected,
        "destination": str(destination),
        "copy_mode": "create-only independent regular file",
    }
