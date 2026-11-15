"""Qualify the cipher offload against the original native Matrix fixtures."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import time


SOURCE_SHA256 = {
    "MODULE.bazel.lock": "97b30244d34794606e6b8217012e8e49eb8aba0821758bf07b125989516555bc",
    "codex-rs/Cargo.toml": "503190d567cc63ca5d8682459746e9a13f8985fbd66603431dc51bd4ce58eea9",
    "MODULE.bazel": "2319432da8b2aa84b090cfc95627e17105e7d5b9adbae80ef1c212c37e02fe9e",
    "codex-rs/Cargo.lock": "133e931e09b2dcfe95f6ded92d3db16fb1103eade317c085ed4758dbccad34df",
    "codex-rs/BUILD.bazel": "f9994442316003cae141ed91060c9a7bf098c15059f247b1c031964792fc79ad",
    "codex-rs/hepta-matrix-sdk/BUILD.bazel": "4b52bb2153b9f0df7a8c14fe440552dface4771d8908a640ba6c2b4cd347e26e",
    "codex-rs/hepta-matrix-sdk/src/sdk.rs": "3061024c6e84abd962b3933f2e974d744aba6d7f1ea2a0020720dd632e9268e5",
    "codex-rs/hepta-matrix-sdk/tests/cipher_task.rs": "bbb91970e90afecb8183ae04b4848a901a5cf600c522f3b5a68d362268c067a2",
    "codex-rs/hepta-matrix-sdk/tests/storage_upgrade.rs": "0c8afc74027288ca994f9ab06a4026a795bee625c99ab2d15f0f469bc3bff274",
    "codex-rs/third_party/matrix-sdk-sqlite-0.19.1/Cargo.toml": "d49d8a311537884a46382ee84c27497d05890f6234c6bdbad89618888acd9a84",
    "codex-rs/third_party/matrix-sdk-sqlite-0.19.1/Cargo.toml.orig": "32703affb6d6e862341145a99f23fcf1de948c36997dfd53d093d05b3d47e821",
    "codex-rs/third_party/matrix-sdk-sqlite-0.19.1/HEPTA-PATCH.md": "9c7b9f3310ab91c498e0820c204d32957e0a262edae1d7519a9a7fb62dbabddf",
    "codex-rs/third_party/matrix-sdk-sqlite-0.19.1/src/cipher_task.rs": "a17fbc98523da681d8e619b49d718d9b61435d3260a6ba1b0110c7b6cfd7f06b",
    "codex-rs/third_party/matrix-sdk-sqlite-0.19.1/src/connection.rs": "893957181ce82046d0375a934a2f1782c6485b447ffb281e25b964b6a0627de6",
    "codex-rs/third_party/matrix-sdk-sqlite-0.19.1/src/crypto_store.rs": "33f4d434c17b8da20fde72f0add8edcb37076d413bf6e7b776c715f7e6330d24",
    "codex-rs/third_party/matrix-sdk-sqlite-0.19.1/src/error.rs": "b8c0e9bcf3156c05366ae10e1dc5567666c4ab36cf1185c39ca339b8b6c21816",
    "codex-rs/third_party/matrix-sdk-sqlite-0.19.1/src/event_cache_store.rs": "c563506ec52f1389a557d7b0fb49ab895c781f8b993e94073c6a1c0e9e2c8a1e",
    "codex-rs/third_party/matrix-sdk-sqlite-0.19.1/src/lib.rs": "f14202a5088870d7e1471cdb0398aef7cfacbc64d465e5bb9888f4ab15dd85de",
    "codex-rs/third_party/matrix-sdk-sqlite-0.19.1/src/media_store.rs": "d27efeb8d30cede965533dbf66242da214f944cab887379feb251bf9a9b9ee00",
    "codex-rs/third_party/matrix-sdk-sqlite-0.19.1/src/state_store.rs": "1ff989781d3c2c95d996ce186477b5b77f7bd120c88d3b4bf46de9fb33bb5871",
    "codex-rs/third_party/matrix-sdk-sqlite-0.19.1/src/store_cipher.rs": "d032c672979ffc39654ad5549992861757458f2c9df2090783f8e8d326e6f93b",
    "codex-rs/third_party/matrix-sdk-sqlite-0.19.1/src/utils.rs": "058549d75953098a5326348087f92ee1d0bd7619735aeb80dcec1489078073b2"
}
OWNER_CASES = {
    "//codex-rs/hepta-matrix-sdk:hepta-matrix-sdk-cipher_task-test": [
        "cancelling_a_queued_cipher_releases_its_capture_without_running_it",
        "cancelling_a_running_cipher_drops_its_unclaimed_result",
        "cipher_worker_panic_is_a_join_error",
        "completed_cipher_returns_its_exact_result"
    ],
    "//codex-rs/hepta-matrix-sdk:hepta-matrix-sdk-durable_transport-test": [
        "duplicate_sync_event_is_exactly_idempotent",
        "exact_room_sender_and_mention_gate_precedes_persistence",
        "expired_crash_lease_reuses_the_stable_transaction_after_reopen",
        "malformed_remote_event_is_nonfatal_and_does_not_block_the_next_event",
        "post_send_ack_loss_reuses_txn_and_commits_same_synapse_event_id",
        "retry_preserves_stable_transaction_and_shutdown_is_bounded",
        "sdk_store_paths_are_private_and_per_agent",
        "transient_failures_use_bounded_backoff_and_then_become_terminal"
    ],
    "//codex-rs/hepta-matrix-sdk:hepta-matrix-sdk-handler_context-test": [
        "handler_context_keeps_types_replacements_and_per_event_clones"
    ],
    "//codex-rs/hepta-matrix-sdk:hepta-matrix-sdk-storage_upgrade-test": [
        "legacy_encrypted_storage_migrates_and_reopens_with_the_same_identity",
        "wrong_passphrase_preserves_the_existing_encrypted_store"
    ],
    "//codex-rs/hepta-matrix-sdk:hepta-matrix-sdk-unit-tests": [
        "gap_fill::tests::chunk_and_state_identity_scope_failures_leave_accepted_evidence_unchanged",
        "gap_fill::tests::duplicate_or_null_scope_fields_are_rejected_in_both_raw_page_vectors",
        "gap_fill::tests::empty_page_continues_and_exact_target_preserves_page_and_event_order",
        "gap_fill::tests::exact_total_event_limit_can_reach_target_without_truncation",
        "gap_fill::tests::invalid_plan_cannot_start_or_manufacture_zero_length_completion",
        "gap_fill::tests::page_and_accumulated_count_and_byte_limits_include_ancillary_state",
        "gap_fill::tests::request_scope_drift_and_discontinuous_or_cyclic_pages_are_atomic_rejections",
        "gap_fill::tests::sdk_bundled_event_is_included_in_raw_byte_bounds",
        "gap_fill::tests::sdk_bundled_metadata_is_dropped_instead_of_retained_outside_raw_bounds",
        "gap_fill::tests::transcript_binds_scope_limits_order_raw_bytes_state_and_terminal_evidence",
        "gap_fill::tests::visibility_and_page_limit_are_terminal_incomplete_observations",
        "sdk::tests::bounded_sync_keeps_ciphertext_needed_for_sdk_decryption",
        "sdk::tests::logical_stream_revision_uses_matrix_replace_content",
        "sdk::tests::missing_hepta_checkpoint_never_reuses_the_sdk_cursor",
        "sdk::tests::send_status_classification_bounds_permanent_and_transient_errors",
        "sync::tests::incomplete_or_conflicting_response_leaves_all_rooms_and_cursor_unchanged",
        "sync::tests::membership_and_tombstone_state_fence_without_enrolling_replacements",
        "sync::tests::message_policy_and_repeated_page_keep_exact_ingress_counts",
        "sync::tests::nested_redaction_and_missing_target_never_reenter_ingress",
        "sync::tests::redaction_room_version_and_decision_payload_identity_are_enforced",
        "sync::tests::unchanged_observation_requires_full_normalization_and_current_durable_checkpoint",
        "sync::tests::v1_redaction_commits_before_replay_and_survives_reopen"
    ]
}
PACKAGE = "//codex-rs/hepta-matrix-sdk:hepta-matrix-sdk"
PAIR_TARGET = PACKAGE + "-storage_upgrade-test"
CIPHER_TARGET = PACKAGE + "-cipher_task-test"
PAIR_CASES = (
    "legacy_encrypted_storage_migrates_and_reopens_with_the_same_identity",
    "wrong_passphrase_preserves_the_existing_encrypted_store",
)
WRAPPER = "./.github/scripts/run-bazel-ci.sh"


def sha256(content):
    return hashlib.sha256(content).hexdigest()


def verify_sources(repo):
    actual = {
        relative: sha256((repo / relative).read_bytes())
        for relative in SOURCE_SHA256
    }
    if actual != SOURCE_SHA256:
        raise RuntimeError("The source differs from the qualified cipher candidate")
    return actual


def successful_execution(log, expected_groups, exit_code):
    """Require every named case and the exact per-binary successful counts."""
    log = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", log)
    names = set(re.findall(r"(?m)^test ([^\s]+) \.\.\.", log))
    summaries = re.findall(
        r"(?m)^test result: ok\. (\d+) passed; 0 failed; 0 ignored; 0 measured;",
        log,
    )
    expected_names = {case for group in expected_groups for case in group}
    expected_counts = sorted(len(group) for group in expected_groups)
    return {
        "observed_names": sorted(names),
        "observed_success_counts": sorted(map(int, summaries)),
        "successful_execution_verified": (
            exit_code == 0
            and names == expected_names
            and sorted(map(int, summaries)) == expected_counts
        ),
    }


def compiler_flags(arguments):
    """Project public compiler settings, without environment values."""
    result = []
    index = 0
    while index < len(arguments):
        arg = arguments[index]
        if arg in ("--crate-name", "--target", "--edition", "--cfg", "-C"):
            if index + 1 >= len(arguments):
                raise ValueError("Incomplete compiler argument")
            value = arguments[index + 1]
            if arg != "-C" or value.startswith((
                "opt-level=", "debuginfo=", "target-", "debug-assertions=",
                "overflow-checks=", "codegen-units=",
            )):
                result.extend((arg, value))
            index += 2
            continue
        if arg.startswith((
            "--crate-name=", "--target=", "--edition=", "--cfg=",
            "-Copt-level=", "-Cdebuginfo=", "-Ctarget-",
            "-Cdebug-assertions=", "-Coverflow-checks=", "-Ccodegen-units=",
        )):
            result.append(arg)
        index += 1
    return result


def action_projection(raw):
    """Ignore wrapper status lines and retain only selected Rust action data."""
    decoder = json.JSONDecoder()
    document = None
    for offset, byte in enumerate(raw):
        if byte != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(raw, offset)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and "actions" in candidate:
            document = candidate
            break
    if document is None:
        raise ValueError("Bazel did not emit an aquery action graph")
    labels = {str(row["id"]): row["label"] for row in document.get("targets", [])}
    result = []
    for action in document["actions"]:
        if action.get("mnemonic") != "Rustc":
            continue
        label = labels.get(str(action.get("targetId")), "")
        if not re.search(r"matrix.sdk.store.encryption|matrix.sdk.sqlite|pbkdf2|hmac|sha2", label):
            continue
        arguments = action.get("arguments", [])
        result.append({
            "label": label,
            "mnemonic": action["mnemonic"],
            "flags": compiler_flags(arguments),
            "environment_names": sorted(row["key"] for row in action.get("environmentVariables", [])),
            "parameter_file_flags": [
                compiler_flags(row.get("arguments", []))
                for row in action.get("paramFiles", [])
            ],
            "argument_sha256": sha256(json.dumps(arguments).encode()),
        })
    if not result:
        raise ValueError("No relevant Rust compiler actions were present")
    return {"actions": result, "includes_environment_values": False}


def verify_crypto_optimization(projection):
    """Require the two production KDF libraries to retain checks when optimized."""
    expected = {
        "matrix-sdk-store-encryption-0.19.1",
        "sha2-0.11.0",
    }
    observed = set()
    for action in projection["actions"]:
        package = next((
            name for name in expected
            if f"crates__{name}//:" in action["label"]
        ), None)
        if package is None:
            continue
        arguments = list(action["flags"])
        for parameters in action["parameter_file_flags"]:
            arguments.extend(parameters)
        codegen = {}
        index = 0
        while index < len(arguments):
            arg = arguments[index]
            if arg == "-C":
                index += 1
                if index == len(arguments):
                    raise ValueError("Incomplete codegen option")
                arg = arguments[index]
            elif arg.startswith("-C"):
                arg = arg[2:]
            else:
                index += 1
                continue
            key, separator, value = arg.partition("=")
            if separator:
                codegen.setdefault(key, []).append(value)
            index += 1
        if set(codegen.get("opt-level", [])) != {"3"} or any(
            not codegen.get(check)
            or any(value not in ("yes", "on", "true", "1") for value in codegen[check])
            for check in ("debug-assertions", "overflow-checks")
        ):
            raise ValueError(f"Missing checked production crypto optimization: {package}")
        observed.add(package)
    if observed != expected:
        raise ValueError("The two production crypto compiler actions are required")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--check-source", action="store_true")
    options = parser.parse_args()
    repo = options.repo.resolve()
    sources = verify_sources(repo)
    if options.check_source:
        print(json.dumps(sources, sort_keys=True))
        return
    if options.report_dir is None:
        parser.error("--report-dir is required")
    if platform.system() != "Darwin":
        raise RuntimeError("This qualification requires native macOS")
    out = options.report_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    commands = []

    def save(name, value):
        (out / name).write_text(json.dumps(value, indent=2) + "\n")

    def run(name, arguments, capture_actions=False):
        verify_sources(repo)
        log = out / f"{name}.log"
        started = time.monotonic()
        with log.open("wb") as stream:
            result = subprocess.run(
                arguments,
                cwd=repo,
                stdout=subprocess.PIPE if capture_actions else stream,
                stderr=stream if capture_actions else subprocess.STDOUT,
            )
        row = {
            "name": name,
            "argv": arguments,
            "exit": result.returncode,
            "seconds": round(time.monotonic() - started, 3),
            "sha256": sha256(log.read_bytes()),
            "bytes": log.stat().st_size,
        }
        if capture_actions and result.returncode == 0:
            try:
                projection = action_projection(result.stdout.decode())
                verify_crypto_optimization(projection)
                save("compiler-actions.json", projection)
                row["action_projection_verified"] = True
            except (ValueError, KeyError, UnicodeDecodeError) as error:
                row["action_projection_verified"] = False
                row["projection_error"] = str(error)
        commands.append(row)
        save("results.json", commands)
        print(json.dumps(row), flush=True)
        verify_sources(repo)
        return result.returncode

    def test(name, targets, groups, extra=()):
        result = run(name, [
            WRAPPER, "--print-failed-action-summary", "--print-failed-test-logs", "--",
            "test", "--nocache_test_results", "--flaky_test_attempts=1",
            "--test_output=all", "--test_arg=--nocapture",
            f"--build_event_json_file={out / (name + '.bep.json')}",
            *extra, "--", *targets,
        ])
        commands[-1].update(successful_execution(
            (out / f"{name}.log").read_text(errors="replace"), groups, result,
        ))
        save("results.json", commands)

    subprocess.run(["git", "diff", "--exit-code"], cwd=repo, check=True)
    save("source.json", {
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
        "tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=repo, text=True).strip(),
        "source_sha256": sources,
        "original_failure_head": "57e489472a03515438df8ed7a0fabec882404f02",
        "deep_diagnostic_head": "a88f75d39308e6f3eddd046277a6e434f16d2b0f",
        "deep_diagnostic_run": 43677083468,
        "previous_cipher_candidate_head": "9b9da8d527663012827ab558d77584780bb1ba87",
        "previous_cipher_candidate_run": 43681457607,
        "runner_os_version": platform.mac_ver()[0],
        "machine": platform.machine(),
        "tmpdir": os.environ.get("TMPDIR"),
        "runner_name": os.environ.get("RUNNER_NAME"),
        "sources_modified_during_qualification": False,
    })
    run("runner", ["/bin/sh", "-c", "uname -a; sw_vers; sysctl hw.logicalcpu hw.physicalcpu hw.memsize; uptime"])
    run("compiler-actions", [
        WRAPPER, "--", "aquery", "--output=jsonproto",
        "--include_artifacts=false", "--include_param_files=true", "--",
        f'mnemonic("Rustc", deps({PAIR_TARGET}))',
    ], capture_actions=True)
    test("original-pair", [PAIR_TARGET], [PAIR_CASES])
    for index, case in enumerate(PAIR_CASES):
        test(f"original-single-{index + 1}", [PAIR_TARGET], [[case]], [
            f"--test_arg={case}", "--test_arg=--exact", "--test_arg=--test-threads=1",
        ])
    test("cipher-cancellation", [CIPHER_TARGET], [OWNER_CASES[CIPHER_TARGET]])
    test("owner", list(OWNER_CASES), list(OWNER_CASES.values()))
    strict_targets = [PACKAGE, PACKAGE + "-unit-tests-bin"] + [
        target for target in OWNER_CASES if target != PACKAGE + "-unit-tests"
    ]
    run("strict", [
        WRAPPER, "--print-failed-action-summary", "--", "build", "--config=clippy",
        "--@rules_rust//rust/settings:clippy_flag=--deny=warnings", "--", *strict_targets,
    ])
    run("source-clean", ["git", "diff", "--exit-code"])
    save("source-after.json", verify_sources(repo))
    passed = all(
        row["exit"] == 0
        and row.get("successful_execution_verified", True)
        and row.get("action_projection_verified", True)
        for row in commands
    )
    save("complete.json", {
        "complete": True,
        "all_commands_passed": passed,
        "source_unchanged": True,
        "original_5_second_startup_and_pbkdf2_200000_unchanged": True,
        "original_pair_and_each_single_required": True,
        "tmpdir_not_overridden": True,
        "test_retries": 0,
        "checked_production_crypto_optimization_required": True,
        "full_workspace_qualified": False,
    })
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
