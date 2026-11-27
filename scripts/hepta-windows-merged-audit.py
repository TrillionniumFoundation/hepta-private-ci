"""Run the unchanged normal Windows package tests on one exact audit commit."""

from __future__ import annotations

import collections
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

PRODUCT_SOURCE = "8d5de7c7c25903760a9d188366d1d0d4226dec68"
PARENT = "a82cd3b920aca90947a95459c9f5e810fc799d48"
WINDOWS_METHODS = [
    "acl::tests::complete_denies_compare_mapped_masks_and_require_every_right",
    "acl::tests::complete_denies_require_effective_recursive_scope_and_precede_allows",
    "acl::tests::complete_file_denies_require_direct_scope",
    "acl::tests::native_file_and_directory_denies_retain_full_masks_and_are_idempotent",
    "acl::tests::partial_read_deny_is_repaired_before_native_file_data_access",
    "acl::tests::deny_ace_update_failure_is_an_error",
    "acl::tests::normalized_deny_pair_requires_every_right_in_effective_and_recursive_scopes",
    "acl::tests::fresh_write_deny_preserves_generic_read_and_denies_data_mutation",
    "acl::tests::normalized_deny_pair_cannot_combine_wrong_identity_or_nonrecursive_scope",
    "acl::tests::native_normalized_directory_and_file_denies_repeat_without_any_acl_change",
    "acl::tests::acl_repair_rejects_replaced_path_with_different_object_type",
    "token::tests::elevated_token_includes_network_proxy_restricting_sid",
    "token::tests::workspace_token_refusal_leaves_existing_files_unchanged",
    "token::tests::workspace_token_refuses_multiple_capabilities_before_native_access",
    "token::tests::workspace_token_refuses_empty_and_unrelated_capability_sets",
    "token::tests::read_authority_probe::full_restriction_preserves_prepared_read_and_mutation_boundaries",
    "token::tests::mic_probe::mic_labels_preserve_original_outside_and_protected_child_oracles",
]
PRIVATE_METHODS = [
    "actual_private_root_allows_compatible_second_owner_open_before_lock",
    "actual_directory_context_poison_never_recovers_into_success",
    "actual_writable_directory_syncs_new_entry_without_noop_or_fallback",
    "actual_parent_write_sharing_conflict_is_not_retried_or_repaired",
    "actual_parent_flush_uses_held_id_after_former_path_is_replaced",
    "actual_new_directory_has_exact_protected_owner_dacl_on_original_handle",
    "create_only_collision_never_adopts_or_overwrites_existing_state",
    "changed_child_descriptor_cannot_be_repaired_into_same_fresh_role",
    "actual_cold_candidate_preserves_existing_bytes_and_shared_identity",
    "actual_cold_candidate_never_creates_missing_or_adopts_changed_dacl",
    "ancestor_parser_distinguishes_new_sibling_creation_from_existing_mutation",
    "inherited_effective_mutator_is_not_treated_as_inherit_only",
    "unknown_owner_and_ace_forms_do_not_grant_namespace_admission",
    "missing_truncated_and_unbounded_acl_are_refused",
    "exact_trustedinstaller_owner_and_maintenance_ace_are_namespace_only",
    "nearby_service_sids_never_gain_namespace_owner_or_mutator_trust",
    "trustedinstaller_owned_namespace_keeps_foreign_mutation_and_shape_refusals",
    "actual_original_io_keeps_marker_and_payload_bytes_across_cold_open",
    "actual_private_journal_reopens_original_bytes_and_appends_under_same_lock",
    "actual_private_file_extent_error_refuses_later_writes_without_growth",
    "actual_read_only_private_file_cannot_write_truncate_or_create_missing",
    "actual_locked_read_keeps_ancestry_alive_and_missing_is_only_observation",
    "actual_locked_read_size_error_fences_later_larger_read_without_reset",
    "actual_locked_read_descriptor_change_is_not_absence_or_repairable",
    "actual_locked_read_rejects_real_hardlink_without_adopting_it",
    "actual_locked_stage_replaces_synced_original_without_path_reopen",
    "actual_locked_stage_share_conflict_never_replaces_or_repairs_state",
    "actual_ancestor_chain_revalidates_and_reopens_without_touching_state",
    "actual_parent_delete_child_rights_reject_live_and_cold_anchor",
    "actual_canonical_drive_prefix_preserves_held_ancestry_and_store_creation",
    "actual_elevated_primary_owner_remains_live",
    "same_user_impersonation_cannot_mint_primary_owner",
    "primary_owner_stays_refused_after_impersonation_is_restored",
    "real_restricted_primary_token_is_refused",
    "actual_marker_sharing_error_is_rejection_not_state_locked_and_stays_refused",
    "actual_owner_lock_refuses_shared_context_poison_without_recovery",
    "native_owner_only_readback_is_valid_for_file_and_directory",
    "native_rejects_existing_unsafe_dacls_without_repair",
    "native_rejects_wrong_expected_sid_and_unsafe_object_shapes",
    "native_readback_parser_rejects_altered_forms_and_every_truncation",
    "native_unqueryable_thread_token_never_falls_back_to_process_user",
    "native_owner_lock_child",
    "actual_second_process_reports_state_locked_then_owner_drop_releases",
    "actual_natural_process_exit_releases_original_os_lock_without_destructor",
    "actual_cold_missing_marker_and_nonempty_marker_never_reset",
    "native_same_effective_token_revalidates",
    "native_same_sid_replacement_is_refused_and_cannot_revive",
    "native_held_token_modification_is_refused",
    "native_degraded_and_unqueryable_thread_tokens_never_fall_back",
    "native_local_ntfs_file_and_directory_report_same_volume",
    "native_nondisk_handle_is_rejected",
    "native_volume_observation_stays_bound_to_renamed_held_object",
    "native_directory_volume_observation_stays_bound_after_rename",
]
WORKFLOW = ".github/workflows/hepta-windows-merged-audit.yml"
SCRIPT = "scripts/hepta-windows-merged-audit.py"
ROOT = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
OUT = Path(os.environ["RUNNER_TEMP"]) / "hepta-windows-merged-audit"
HEAD = os.environ["EXPECTED_HEAD"]
ENV = dict(os.environ)
ENV.update(
    {
        "PYTHONDONTWRITEBYTECODE": "1",
        "CARGO_TERM_COLOR": "never",
        "NEXTEST_PROFILE": "local",
        "NO_COLOR": "1",
        "CARGO_TARGET_DIR": str(
            Path(os.environ["RUNNER_TEMP"]) / "hepta-windows-merged-target"
        ),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
)
for key in list(ENV):
    if key == "GIT_CONFIG_COUNT" or key.startswith(
        ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")
    ):
        del ENV[key]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def write_json(path, value):
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def git(*args, allowed=(0,)):
    hooks = OUT / "empty-hooks"
    hooks.mkdir(exist_ok=True)
    result = subprocess.run(
        [
            "git",
            "--no-pager",
            "-c",
            "core.hooksPath=" + str(hooks),
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.longpaths=true",
            *args,
        ],
        cwd=ROOT,
        env=ENV,
        capture_output=True,
        check=False,
    )
    require(
        result.returncode in allowed,
        "Git source check failed: "
        + repr(args)
        + "\n"
        + result.stderr.decode("utf-8", errors="replace"),
    )
    return result


def identity(data):
    return {
        "bytes": len(data),
        "oid": hashlib.sha1(
            b"blob " + str(len(data)).encode() + b"\0" + data
        ).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def source_snapshot():
    require(
        sys.platform == "win32" and os.environ.get("RUNNER_OS") == "Windows",
        "Native Windows is required; another platform cannot qualify these methods",
    )
    require(
        re.fullmatch(r"[0-9a-f]{40}", HEAD) is not None, "Exact audit commit required"
    )
    require(git("rev-parse", "HEAD").stdout.decode().strip() == HEAD, "Wrong checkout")
    require(
        git("rev-parse", "HEAD^").stdout.decode().strip() == PARENT,
        "Wrong source parent",
    )
    changes = set(
        filter(
            None,
            git(
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                "-z",
                PRODUCT_SOURCE,
                HEAD,
            )
            .stdout.decode()
            .split("\0"),
        )
    )
    require(
        changes == {SCRIPT, WORKFLOW}, "Audit commit changes the frozen product source"
    )
    filters = git(
        "config",
        "--null",
        "--get-regexp",
        r"^filter\..*\.(clean|process)$",
        allowed=(0, 1),
    )
    require(filters.returncode == 1 and not filters.stdout, "Unexpected source filters")
    status = git("status", "--porcelain=v1", "--untracked-files=all").stdout
    require(not status, "Source/index changed: " + repr(status))
    fixed = {
        SCRIPT,
        WORKFLOW,
        "justfile",
        "scripts/run-nextest.py",
        "scripts/just-shell.py",
        "codex-rs/.config/nextest.toml",
    }
    records = {}
    for row in git("ls-tree", "-r", "-z", HEAD).stdout.split(b"\0"):
        if not row:
            continue
        header, path_bytes = row.split(b"\t", 1)
        mode, kind, oid = header.decode("ascii").split()
        name = path_bytes.decode("utf-8")
        p = Path(name)
        selected = name in fixed or (
            name.startswith("codex-rs/")
            and (
                name.endswith((".rs", ".sql"))
                or p.name
                in {"Cargo.toml", "Cargo.lock", "BUILD.bazel", "rust-toolchain.toml"}
            )
        )
        if not selected:
            continue
        require(
            kind == "blob" and mode in {"100644", "100755"},
            "Unexpected source kind: " + name,
        )
        target = ROOT / name
        require(not target.is_symlink(), "Source symlink: " + name)
        with target.open("rb") as stream:
            before = os.fstat(stream.fileno())
            require(
                stat.S_ISREG(before.st_mode) and before.st_size <= 16 * 1024 * 1024,
                "Source is not a bounded regular file: " + name,
            )
            data = stream.read(16 * 1024 * 1024 + 1)
            after = os.fstat(stream.fileno())
        require(
            (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            == (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ),
            "Source changed during read: " + name,
        )
        observed = identity(data)
        require(
            observed["oid"] == oid,
            "Raw source differs from the exact Git tree: " + name,
        )
        observed["mode"] = mode
        records[name] = observed
    require(fixed <= set(records), "Missing source control or runner input")
    for package in ("windows-sandbox-rs", "utils/windows-private-state"):
        require(
            "codex-rs/" + package + "/Cargo.toml" in records,
            "Missing package " + package,
        )
    require("codex-rs/Cargo.lock" in records, "Missing normal resolver lock")
    return {
        "head": HEAD,
        "source_parent": PRODUCT_SOURCE,
        "harness_parent": PARENT,
        "sources": records,
        "index_worktree_clean": True,
    }


def command(name, argv, cwd=ROOT):
    started = time.monotonic()
    with (
        (OUT / (name + ".stdout")).open("wb") as stdout,
        (OUT / (name + ".stderr")).open("wb") as stderr,
    ):
        result = subprocess.run(
            argv, cwd=cwd, env=ENV, stdout=stdout, stderr=stderr, check=False
        )
    record = {
        "name": name,
        "argv": argv,
        "cwd": str(cwd),
        "exit_code": result.returncode,
        "seconds": time.monotonic() - started,
        "natural_terminal": True,
    }
    write_json(OUT / (name + ".command.json"), record)
    return record


def collect_results():
    report = ROOT / "codex-rs" / "target" / "nextest" / "local" / "junit.xml"
    raw = report.read_bytes()
    (OUT / "windows-packages.junit.xml").write_bytes(raw)
    root = ET.fromstring(raw)
    cases = list(root.iter("testcase"))
    observations = []
    forbidden = {
        "failure",
        "error",
        "skipped",
        "flakyFailure",
        "flakyError",
        "rerunFailure",
        "rerunError",
    }
    for case in cases:
        observations.append(
            {
                "name": case.get("name"),
                "classname": case.get("classname"),
                "status": case.get("status", "run"),
                "time": case.get("time"),
                "failure_or_skip_tags": [
                    child.tag for child in case.iter() if child.tag in forbidden
                ],
            }
        )
    names = collections.Counter(row["name"] for row in observations)
    missing_original = [name for name in WINDOWS_METHODS if names[name] != 1]
    missing_private = [
        name
        for name in PRIVATE_METHODS
        if sum(
            count
            for actual, count in names.items()
            if actual == name or actual.endswith("::" + name)
        )
        != 1
    ]
    result = {
        "actual_test_cases": observations,
        "case_count": len(cases),
        "original_windows_required": WINDOWS_METHODS,
        "missing_or_duplicate_original": missing_original,
        "private_state_required": PRIVATE_METHODS,
        "missing_or_duplicate_private": missing_private,
        "junit_sha256": hashlib.sha256(raw).hexdigest(),
    }
    write_json(OUT / "actual-results.json", result)
    require(
        not missing_original and not missing_private,
        "Required native methods were not executed once",
    )
    require(
        not any(
            row["failure_or_skip_tags"] or row["status"] == "notrun"
            for row in observations
        ),
        "Actual test failures, skips, or retries are retained",
    )
    require(
        len(cases) >= len(WINDOWS_METHODS) + len(PRIVATE_METHODS),
        "Incomplete native test census",
    )
    return result


def main():
    phase = sys.argv[1]
    require(phase in {"preflight", "run", "postflight"}, "Invalid validation phase")
    if phase == "preflight":
        OUT.mkdir(exist_ok=False)
        write_json(OUT / "preflight.json", source_snapshot())
        return
    before = json.loads((OUT / "preflight.json").read_text(encoding="utf-8"))
    if phase == "postflight":
        after = source_snapshot()
        write_json(OUT / "postflight.json", after)
        require(after == before, "Source changed during native validation")
        return
    state = {
        "status": "RUNNING",
        "head": HEAD,
        "source_parent": PRODUCT_SOURCE,
        "harness_parent": PARENT,
        "commands": [],
        "permission_qualification": False,
    }
    errors = []
    try:
        require(source_snapshot() == before, "Source changed after tool installation")
        for name, argv, expected in [
            ("just-version", ["just", "--version"], r"^just 1\.51\.0\s*$"),
            (
                "nextest-version",
                ["cargo", "+1.96.0", "nextest", "--version"],
                r"^cargo-nextest 0\.9\.103(?:\s|$)",
            ),
        ]:
            record = command(name, argv, ROOT / "codex-rs")
            state["commands"].append(record)
            require(
                record["exit_code"] == 0
                and re.search(
                    expected, (OUT / (name + ".stdout")).read_text(encoding="utf-8")
                ),
                "Unexpected standard runner version",
            )
        record = command(
            "windows-packages",
            [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-windows-sandbox",
                "-p",
                "codex-utils-windows-private-state",
                "--test-threads",
                "1",
                "--no-tests",
                "fail",
                "--retries",
                "0",
                "--status-level",
                "pass",
                "--final-status-level",
                "fail",
            ],
            ROOT / "codex-rs",
        )
        state["commands"].append(record)
        if record["exit_code"] != 0:
            errors.append(
                "Normal just test failed with exit " + str(record["exit_code"])
            )
        try:
            result = collect_results()
            state["actual_case_count"] = result["case_count"]
        except Exception as exc:
            errors.append(type(exc).__name__ + ": " + str(exc))
    except Exception as exc:
        errors.append(type(exc).__name__ + ": " + str(exc))
    finally:
        try:
            after = source_snapshot()
            write_json(OUT / "source-after.json", after)
            require(after == before, "Source changed during normal tests")
            state["source_unchanged"] = True
        except Exception as exc:
            errors.append(type(exc).__name__ + ": " + str(exc))
        state["status"] = "FAIL" if errors else "PASS"
        state["errors"] = errors
        write_json(OUT / "state.json", state)
    require(not errors, "; ".join(errors))


if __name__ == "__main__":
    main()
