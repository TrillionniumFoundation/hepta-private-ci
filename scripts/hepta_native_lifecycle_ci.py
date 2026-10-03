"""Verify the new lifecycle source subject; never emit frozen ui.native acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

from hepta_ci_exec import git, identity

BASE = "711859f23b73ad89af4d23e75fe0ed4a461e7979"
BASE_REF = "work/ui-rust-scifi-audit-20261002"
WORKFLOW = ".github/workflows/ui-native-lifecycle-source.yml"
CHECKS = ("compile", "inventory-command", "tests", "clippy", "format")
COMMANDS = {
    "compile": [
        "cargo",
        "+1.95.0",
        "build",
        "--manifest-path",
        "apps/hepta-native/Cargo.toml",
        "--locked",
        "--workspace",
        "--all-targets",
    ],
    "inventory-command": [
        "bash",
        "-euo",
        "pipefail",
        "-c",
        'cargo +1.95.0 nextest list --manifest-path apps/hepta-native/Cargo.toml --locked --workspace --all-targets --config-file .github/config/native-lifecycle-nextest.toml --profile native-lifecycle --message-format json > "$NATIVE_EVIDENCE/inventory.json"',
    ],
    "tests": [
        "just",
        "test",
        "--manifest-path",
        "../apps/hepta-native/Cargo.toml",
        "--locked",
        "--workspace",
        "--all-targets",
        "--config-file",
        "../.github/config/native-lifecycle-nextest.toml",
        "--profile",
        "native-lifecycle",
        "--retries",
        "0",
    ],
    "clippy": [
        "cargo",
        "+1.95.0",
        "clippy",
        "--manifest-path",
        "apps/hepta-native/Cargo.toml",
        "--locked",
        "--workspace",
        "--all-targets",
        "--all-features",
        "--",
        "-D",
        "warnings",
    ],
    "format": [
        "python3",
        "scripts/hepta_ui_native_format.py",
        "--manifest-path",
        "apps/hepta-native/Cargo.toml",
    ],
}
IGNORED = {
    ("hepta-native", "storage_qualification_tests::storage_active_scale_qualification"),
    (
        "hepta-native",
        "storage_qualification_tests::storage_retirement_scale_qualification",
    ),
    (
        "hepta-native",
        "storage_qualification_tests::process_samples::storage_process_sample_worker",
    ),
    (
        "hepta-native",
        "ui::shell_view::visual_capture_tests::capture_fixture_native_screens",
    ),
}
REQUIRED = {
    (
        "hepta-native",
        "ui::tests::readiness_failure_cancels_waiting_task_and_retains_admitted_task",
    ),
    (
        "hepta-native",
        "host_lifecycle::readiness::tests::readiness_requires_later_callback_and_resets",
    ),
    (
        "hepta-native",
        "host_lifecycle::readiness::tests::readiness_binds_every_view_axis",
    ),
    (
        "hepta-native",
        "host_lifecycle::tests::shutdown_cancels_waiting_mutation_but_retains_admitted_owner_until_join",
    ),
    (
        "hepta-native",
        "host_lifecycle::shutdown::tests::activation_requires_successful_close_and_no_shutdown_failure",
    ),
    (
        "hepta-native",
        "host_lifecycle::shutdown::tests::repeat_close_cannot_extend_the_deadline_or_authorize_an_update",
    ),
    (
        "hepta-native",
        "updater::tests::helper_acknowledgement_is_durable_before_success",
    ),
    (
        "hepta-native",
        "ui::input_event_tests::diagnostic_render_failure_invalidates_presentation_binding_and_readiness",
    ),
    (
        "hepta-native::update_handoff",
        "restart_binding_rejects_smoke_profiles_and_detects_argument_changes",
    ),
    (
        "hepta-native::update_product",
        "updater_does_not_accept_exit_zero_as_product_startup",
    ),
    (
        "hepta-native::shutdown_recovery",
        "failed_close_keeps_identity_without_usable_view_and_retries_same_owner",
    ),
    (
        "hepta-native::shutdown_recovery",
        "reconnect_cannot_acquire_replacement_before_old_owner_is_closed",
    ),
}
REQUIRED.update(
    ("hepta-native", "host_lifecycle::task::tests::" + name)
    for name in (
        "cancelled_waiting_task_never_enters_the_runtime",
        "cancelled_runtime_lock_waiter_exits_without_owner_entry",
        "runtime_lock_wait_has_a_bounded_pre_admission_deadline",
        "acquiring_the_runtime_lock_does_not_consume_admission",
        "admitted_task_is_not_interrupted_or_detached_by_cancellation",
        "panic_is_joined_and_wakes_the_ui_without_manufacturing_success",
        "cancellation_and_admission_have_one_winner_under_race",
        "a_task_cannot_enter_its_runtime_owner_twice",
    )
)


REQUIRED.update(
    ("hepta-native", "host_lifecycle::controller::tests::" + name)
    for name in (
        "mutation_and_history_are_serialized_while_picker_is_independent",
        "completion_wake_does_not_release_the_lane_before_join",
        "shutdown_drains_admitted_owner_and_cancelled_picker_before_close",
        "failed_spawn_preserves_empty_slots_and_close_retry",
        "panic_completion_is_joined_once_and_retains_failure",
    )
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def verify_event(event: dict, env: dict) -> dict:
    pr = event.get("pull_request", {})
    if env.get("GITHUB_EVENT_NAME") != "pull_request" or event.get("number") != 1338:
        raise ValueError("only the original PR #1338 is this validation subject")
    if (
        pr.get("base", {}).get("ref") != BASE_REF
        or pr.get("base", {}).get("sha") != BASE
    ):
        raise ValueError("PR base differs from the reviewed lifecycle parent")
    source = pr.get("head", {}).get("sha", "")
    if not re.fullmatch(r"[0-9a-f]{40}", source) or source == "0" * 40:
        raise ValueError("source must be a complete nonzero commit SHA")
    if env.get("SOURCE_SHA") != source or env.get("BASE_SHA") != BASE:
        raise ValueError("environment source/base differs from the event")
    for name in ("WORKFLOW_SHA", "TESTED_SHA"):
        if not re.fullmatch(r"[0-9a-f]{40}", env.get(name, "")):
            raise ValueError(f"invalid {name}")
    for name in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        if not env.get(name, "").isdigit() or int(env[name]) < 1:
            raise ValueError(f"invalid {name}")
    if env.get("HEPTA_CI_LANE") not in {"source-head", "base-merge"}:
        raise ValueError("unknown lifecycle lane")
    return {
        "sourceSha": source,
        "baseSha": BASE,
        "testedSha": env["TESTED_SHA"],
        "workflowSha": env["WORKFLOW_SHA"],
        "lane": env["HEPTA_CI_LANE"],
        "runId": env["GITHUB_RUN_ID"],
        "runAttempt": env["GITHUB_RUN_ATTEMPT"],
    }


def subject() -> dict:
    value = verify_event(
        json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text()), os.environ
    )
    observed = identity()
    if observed["dirty"] or observed["commit"] != value["testedSha"]:
        raise ValueError("source checkout must be clean and exactly identified")
    if value["lane"] == "source-head":
        if observed["commit"] != value["sourceSha"]:
            raise ValueError("head lane differs from the PR head")
    else:
        tree = git("merge-tree", "--write-tree", BASE, value["sourceSha"])
        merge = (
            subprocess.check_output(
                ["git", "commit-tree", tree, "-p", BASE, "-p", value["sourceSha"]],
                input=b"Synthetic native lifecycle merge for PR 1338\n",
                env={
                    **os.environ,
                    "GIT_AUTHOR_NAME": "Native lifecycle CI",
                    "GIT_COMMITTER_NAME": "Native lifecycle CI",
                    "GIT_AUTHOR_EMAIL": "native-lifecycle@invalid",
                    "GIT_COMMITTER_EMAIL": "native-lifecycle@invalid",
                    "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
                    "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
                },
            )
            .decode()
            .strip()
        )
        if observed["commit"] != merge or observed["parents"] != [
            BASE,
            value["sourceSha"],
        ]:
            raise ValueError("merge is not the canonical ordered-parent subject")
    workflow = subprocess.check_output(
        ["git", "show", f"{value['workflowSha']}:{WORKFLOW}"]
    )
    if workflow != Path(WORKFLOW).read_bytes():
        raise ValueError("executed workflow bytes differ from tested source")
    runner = {
        name: os.environ.get(name, "")
        for name in ("RUNNER_OS", "RUNNER_ARCH", "ImageOS", "ImageVersion")
    }
    if runner["RUNNER_OS"] != "Linux" or not all(runner.values()):
        raise ValueError("complete Linux runner identity is required")
    return {**value, "git": observed, "workflowSha256": sha(workflow), "runner": runner}


def verify_tests(inventory: dict, junit: Path) -> dict:
    expected, ignored = set(), set()
    for binary, suite in inventory["rust-suites"].items():
        if suite.get("status") != "listed":
            raise ValueError(f"unlisted suite: {binary}")
        for name, case in suite["testcases"].items():
            key = (binary, name)
            if case["ignored"] is True:
                ignored.add(key)
            elif case["ignored"] is False and case["filter-match"] == {
                "status": "matches"
            }:
                expected.add(key)
            else:
                raise ValueError(f"ordinary test filtered out: {key}")
    if ignored != IGNORED or inventory["test-count"] != len(expected) + len(ignored):
        raise ValueError(
            "ignored tests or inventory count changed; review scope explicitly"
        )
    if not REQUIRED <= expected:
        raise ValueError(
            f"required lifecycle cases absent: {sorted(REQUIRED - expected)}"
        )
    passed, seen = set(), set()
    document = ET.parse(junit).getroot()
    if document.tag != "testsuites" or any(
        int(document.get(key, "0")) for key in ("failures", "errors")
    ):
        raise ValueError("JUnit root does not report a successful nextest run")
    for case in document.iter("testcase"):
        key = (case.get("classname"), case.get("name"))
        if key in seen:
            raise ValueError(f"duplicate JUnit case: {key}")
        seen.add(key)
        if any(child.tag not in {"system-out", "system-err"} for child in case):
            if len(case) == 1 and case[0].tag == "skipped" and key in ignored:
                continue
            raise ValueError(f"test failed, skipped or retried: {key}")
        passed.add(key)
    if passed != expected:
        raise ValueError(
            f"executed tests differ from inventory: missing={sorted(expected - passed)}, extra={sorted(passed - expected)}"
        )
    return {
        "passed": len(passed),
        "ignored": [list(key) for key in sorted(ignored)],
        "requiredPassed": [list(key) for key in sorted(REQUIRED)],
    }


def verify_record(record: dict, bound: dict, directory: Path, label: str) -> None:
    pairs = {
        "source_sha": "sourceSha",
        "base_sha": "baseSha",
        "tested_sha": "testedSha",
        "lane": "lane",
        "run_id": "runId",
        "run_attempt": "runAttempt",
    }
    if any(record.get(key) != bound[value] for key, value in pairs.items()):
        raise ValueError("execution record belongs to another subject or run")
    if record.get("command") != COMMANDS[label]:
        raise ValueError("execution command differs from the declared native check")
    if (
        record.get("status") != "passed"
        or record.get("exit_code") != 0
        or record.get("command_exit_code") != 0
        or record.get("before") != bound["git"]
        or record.get("after") != bound["git"]
    ):
        raise ValueError("execution did not pass on unchanged exact source")
    name = record.get("log_file", "")
    if (
        not name
        or Path(name).name != name
        or sha((directory / name).read_bytes()) != record.get("log_sha256")
    ):
        raise ValueError("execution log missing or changed")


def verify_asset_inputs(directory: Path, root: Path) -> dict:
    """Bind additional all-feature compiler input to deterministic regeneration."""
    receipt = json.loads((directory / "native-assets-verification.json").read_text())
    inputs = json.loads((directory / "native-assets-input.json").read_text())
    rust = (directory / "native-assets.rs").read_bytes()
    native = root / "apps/hepta-native"
    catalog_path = native / "resources/NATIVE-ASSETS.json"
    catalog = json.loads(catalog_path.read_text())
    sources = {
        "manifestSha256": native / "Cargo.toml",
        "lockSha256": native / "Cargo.lock",
        "catalogSha256": catalog_path,
        "generatorSha256": native / "tools/generate-native-assets.py",
        "helperSha256": native / "tools/build-robrix-native.py",
    }
    if (
        receipt.get("schema") != "hepta.native-assets-verification.v1"
        or receipt.get("regeneratedBytesMatch") is not True
        or receipt.get("rendererQualified") is not False
        or receipt.get("sourceRoot") != str(root)
        or receipt.get("sdkRevision") != catalog["makepadRevision"]
        or any(
            receipt.get(key) != sha(path.read_bytes()) for key, path in sources.items()
        )
    ):
        raise ValueError("asset regeneration receipt differs from the bound source")
    if (
        receipt.get("assetRustSha256") != sha(rust)
        or receipt.get("assetInputJsonSha256")
        != sha((directory / "native-assets-input.json").read_bytes())
        or inputs.get("schema") != "hepta.native-assets-build-input.v1"
        or inputs.get("generatedRustSha256") != sha(rust)
        or inputs.get("catalogSha256") != sha(catalog_path.read_bytes())
        or inputs.get("makepadRevision") != catalog["makepadRevision"]
        or inputs.get("noticeFiles") != catalog["noticeFileSha256"]
    ):
        raise ValueError("retained compiler asset input was missing or changed")
    projected = [
        {key: asset[key] for key in ("logical", "bytes", "sha256", "license_group")}
        for asset in inputs["assets"]
    ]
    if projected != catalog["assets"] or len({a["logical"] for a in projected}) != 28:
        raise ValueError("embedded asset inventory differs from the fixed catalog")
    source = catalog["liberationSource"]
    if (
        any(
            inputs["liberationSource"].get(key) != value
            for key, value in source.items()
        )
        or receipt.get("liberationSourceSha256") != source["sha256"]
    ):
        raise ValueError("embedded corresponding source archive differs")
    return {
        "assetCount": len(projected),
        "assetBytes": sum(asset["bytes"] for asset in projected),
        "assetRustSha256": sha(rust),
        "correspondingSourceSha256": source["sha256"],
        "regeneratedInputVerified": True,
        "nativeRendererObserved": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("bind", "seal"))
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    root = Path(git("rev-parse", "--show-toplevel")).resolve()
    if not args.out.is_absolute() or args.out.resolve().is_relative_to(root):
        raise ValueError("evidence must be outside the checkout")
    current = subject()
    if args.action == "bind":
        args.out.mkdir(parents=True, exist_ok=False)
        write(args.out / "subject.json", current)
        return
    bound = json.loads((args.out / "subject.json").read_text())
    if current != bound:
        raise ValueError("source subject changed after binding")
    for label in CHECKS:
        verify_record(
            json.loads((args.out / f"{label}.json").read_text()), bound, args.out, label
        )
    coverage = verify_tests(
        json.loads((args.out / "inventory.json").read_text()), args.out / "junit.xml"
    )
    asset_inputs = verify_asset_inputs(args.out, root)
    tests = json.loads((args.out / "tests.json").read_text())
    if (
        tests["observed_passed_tests"] != coverage["passed"]
        or tests["observed_failed_tests"] != 0
    ):
        raise ValueError("terminal test summary differs from JUnit coverage")
    files = [
        "subject.json",
        "inventory.json",
        "junit.xml",
        "tools.txt",
        "native-assets-verification.json",
        "native-assets-input.json",
        "native-assets.rs",
        *(f"{label}.json" for label in CHECKS),
    ]
    write(
        args.out / "source-validation.json",
        {
            "schema": "hepta.native-lifecycle-source-validation.v1",
            **bound,
            "ordinaryNativeSourceValidationPassed": True,
            "tests": coverage,
            "assetInputs": asset_inputs,
            "files": {name: sha((args.out / name).read_bytes()) for name in files},
            "nativeGuiObserved": False,
            "installedPackageObserved": False,
            "crossPlatformAcceptance": False,
            "makepadAcceptance": False,
            "frozenUiNativeQualification": False,
            "releaseAuthorized": False,
        },
    )


if __name__ == "__main__":
    main()
