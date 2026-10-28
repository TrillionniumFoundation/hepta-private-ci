"""Bind an existing consumer pass to a fixed post-qualification Clippy scope."""

import json
import os
from pathlib import Path
import shutil

from ndu_port_candidate_common import OLD_SOURCE
from ndu_port_candidate_common import SCHEMA
from ndu_port_candidate_common import candidate_source_mode
from ndu_port_candidate_common import checksum
from ndu_port_candidate_common import describe
from ndu_port_candidate_common import regular_path
from ndu_port_matrix_fixture import parse_phase_junit


GROUPS = {
    "matrix": {
        "tests": (
            "codex-hepta-matrix-protocol",
            "codex-hepta-matrix-store",
            "codex-hepta-matrix-sdk",
            "codex-hepta-matrixd",
        ),
        "packages": ("codex-hepta-matrix-sdk", "codex-hepta-matrixd"),
        "directories": ("codex-rs/hepta-matrix-sdk/", "codex-rs/hepta-matrixd/"),
        "features": ("--features", "codex-hepta-matrixd/real-synapse-e2e"),
    },
    "yaml": {
        "tests": (
            "codex-utils-yaml",
            "codex-skills",
            "codex-skills-extension",
            "codex-core-plugins",
            "codex-external-agent-migration",
        ),
        "packages": (
            "codex-utils-yaml",
            "codex-skills",
            "codex-skills-extension",
            "codex-core-plugins",
            "codex-external-agent-migration",
        ),
        "directories": (
            "codex-rs/utils/yaml/",
            "codex-rs/skills/",
            "codex-rs/ext/skills/",
            "codex-rs/core-plugins/",
            "codex-rs/external-agent-migration/",
        ),
        "features": (),
    },
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_tests(runner, path, group, candidate, expected_result):
    require(path.is_file() and not path.is_symlink(), "Consumer RESULT must be regular")
    result = json.loads(path.read_text())
    require(
        result.get("schema") == SCHEMA
        and result.get("mode") == "test"
        and result.get("status") == "targeted_tests_passed"
        and result.get("test_group") == group
        and result.get("failed_tests") == []
        and result.get("original_dependency_policy_unchanged") is True,
        "Only the completed successful original consumer is eligible",
    )
    for key, value in {
        "source_commit": candidate["source_commit"],
        "toolchain": "1.96.0",
        "candidate_result_sha256": expected_result,
        "recipe_sha256": candidate["recipe_sha256"],
        "candidate_patch_sha256": candidate["artifacts"]["candidate.patch"]["sha256"],
    }.items():
        require(
            result.get(key) == value, f"Consumer {key} is not bound to this candidate"
        )
    if candidate_source_mode(candidate) == "integrated":
        for key in ("source_mode", "source_tree", "integration"):
            require(
                result.get(key) == candidate[key], f"Consumer {key} binding differs"
            )
    for key in ("github_run_id", "github_run_attempt"):
        require(
            result.get(key) == candidate.get(key), "Consumer belongs to another run"
        )
    commands = result["commands"]
    retained = {"RESULT.json": {"bytes": path.stat().st_size, "sha256": checksum(path)}}
    for command in commands:
        require(command["exit_code"] == 0, "Consumer contains a failed command")
        name = command["log"]
        retained[name] = {
            "bytes": command["log_bytes"],
            "sha256": command["log_sha256"],
        }
        if "stdout" in command:
            item = command["stdout"]
            retained[item["file"]] = {key: item[key] for key in ("bytes", "sha256")}
    rows = result["test_results"]
    require(
        [row["package"] for row in rows] == list(GROUPS[group]["tests"]),
        "Consumer test package inventory differs",
    )
    for row in rows:
        command = commands[row["command_index"]]
        require(
            row["exit_code"] == 0
            and command["cwd"] == str(runner.root)
            and command["command"]
            == [
                "just",
                "test",
                "--locked",
                "--cargo-profile",
                "ci-test",
                "-p",
                row["package"],
            ],
            "Actual consumer test command differs",
        )
    if group == "matrix":
        old = result["old_fixture_input"]
        require(
            old["old_source"] == OLD_SOURCE
            and old["driver_source"] == candidate["source_commit"]
            and old["recipe_sha256"] == candidate["recipe_sha256"]
            and old["producer_fixture_unchanged_after_reopen"] is True
            and old["files_before_reopen"]
            and old["files_after_reopen"],
            "Independent old fixture reopen evidence is incomplete",
        )
        phase = result["migration_phase"]
        require(
            phase["name"] == "reopen_old_version_fixture"
            and phase["exit_code"] == 0
            and phase["binary_unchanged_after_execution"] is True
            and phase["store_config_unchanged_after_execution"] is True
            and phase["fresh_junit_count"] == 1,
            "Actual old fixture reopen did not pass",
        )
        storage = phase["nextest_storage"]
        require(
            phase["observed_junit_paths"]
            == [storage["directory"] + "/default/junit.xml"],
            "Reopen must have the exact fresh report path",
        )
        retained[storage["config_file"]] = storage["config"]
        reopen = commands[phase["command_index"]]
        require(
            reopen["cwd"] == str(runner.root)
            and reopen["command"]
            == [
                "just",
                "test",
                "--locked",
                "--cargo-profile",
                "ci-test",
                "-p",
                "codex-hepta-matrix-sdk",
                "--test",
                "store_version_migration",
                "--tool-config-file",
                storage["tool_config_argument"],
                "--profile",
                "default",
                "--run-ignored",
                "only",
                "-E",
                "test(=reopen_old_version_fixture)",
                "--retries",
                "0",
                "--no-tests",
                "fail",
            ],
            "Actual reopen command differs",
        )
        binary = regular_path(path.parent, phase["binary"])
        retained[phase["binary"]] = {
            "bytes": binary.stat().st_size,
            "sha256": phase["binary_sha256"],
        }
        junit = phase["junit"]["file"]
        report = regular_path(path.parent, junit)
        retained[junit] = {
            "bytes": report.stat().st_size,
            "sha256": phase["junit"]["sha256"],
        }
        parse_phase_junit(report, "reopen_old_version_fixture")
        require(
            Path(phase["cargo_target_directory"]).resolve()
            == Path(os.environ["CARGO_TARGET_DIR"]).resolve(),
            "Clippy must reuse the actual Matrix consumer target directory",
        )
    require(
        describe(path.parent, retained) == retained,
        "Original consumer evidence bytes changed",
    )
    shutil.copyfile(path, runner.output / "ORIGINAL_TEST_RESULT.json")
    runner.record.update(
        original_test_result_sha256=checksum(path), original_test_evidence=retained
    )
    return retained
