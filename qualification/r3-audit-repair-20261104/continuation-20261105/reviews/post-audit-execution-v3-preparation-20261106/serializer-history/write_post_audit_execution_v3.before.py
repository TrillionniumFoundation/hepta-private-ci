#!/usr/bin/env python3
"""Assemble the current audit narrative's machine companion from fixed local evidence.

This is documentation preparation only. It runs no product code or CI and must
not be used to replace a reviewed/frozen final document with different bytes.
"""

from collections import Counter
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
PREFIX = "qualification/r3-audit-repair-20261104/continuation-20261105/"


def identity(body):
    return {
        "bytes": len(body),
        "git_blob": hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest(),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def read(name):
    return json.loads((ROOT / name).read_bytes())


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: write_post_audit_execution_v3.py FINAL_COMPONENT_CONFIG FINAL_CI_REVIEW_JSON")
    ledger_path = "documents/continuation-blocker-progress-v8.json"
    ledger_body = (ROOT / ledger_path).read_bytes()
    assert identity(ledger_body)["git_blob"] == "ea5ad333eacf2f49326a8f80a39e94ad771d818d"
    ledger = json.loads(ledger_body)
    fields = ("id", "name", "status", "closure_class", "original_exit_condition_zh")
    contracts = [{key: row[key] for key in fields} for row in ledger["items"]]
    counts = dict(Counter(row["closure_class"] for row in contracts))
    assert counts == {"CLOSED_SCOPED": 16, "OPEN": 6, "SCIENTIFIC_HOLD": 1}
    report_path = "third-post-audit-documents/POST_AUDIT_EXECUTION_UPDATE_V3.zh-CN.md"
    report_body = (ROOT / report_path).read_bytes()
    current = read("integration-840-format-publication/publication-verified.json")
    assert current["target_base"] == "63652be658ebed8d3052eb789b951793384fd5e4"
    assert current["all_blockers_closed"] is False
    config = read(sys.argv[1])
    ci = read(sys.argv[2])
    assert ci["current_product_head"] == current["head"]
    assert ci["whole_candidate_qualified"] is False
    initial = read("second-post-audit-documents/post-audit-execution-v2.json")
    arg0 = read("integration-arg0-fixture-publication/publication-verified.json")
    observation = read("integration-pty-supervisor-publication/publication-verified.json")
    native_old = read("integration-ci-review/ci-increment-20261106T0930-delivery/registry.actual.json")
    fmt_source = read("integration-ci-review/fmt-candidate-840e8b5/source-map.json")
    metadata = read("fourth-audit-current-cut/METADATA-REVIEW.json")
    research = read("pr4930-fa-increment-readonly-20261106/delta-review.json")
    machine = {
        "schema": "hepta-post-audit-execution-v3-source-bound-increment",
        "recorded_utc": ci["latest_observation_utc"],
        "recorded_utc_scope": "Latest bounded included observation; each source, publication and run retains its own time and qualification.",
        "fixed_predecessor_commit": "f7bb5019d311dacc142f20cacdcf19889109b4ba",
        "fixed_predecessor_tree": "d7716cca653bf7795307b052352e8671cd9fd944",
        "original_ledger": {"path": "continuation-blocker-progress-v8.json", **identity(ledger_body)},
        "original_blocker_contracts": contracts,
        "counts": counts,
        "closure_transitions_in_this_increment": [],
        "original_23_ids_literal_exits_and_closure_classes_unchanged": True,
        "all_blockers_closed": False,
        "whole_candidate_qualified": False,
        "report": {"path": "POST_AUDIT_EXECUTION_UPDATE_V3.zh-CN.md", **identity(report_body)},
        "actual_product_publication": current,
        "prior_publications_preserved": {
            "initial_combined": initial["actual_product_publication"],
            "native_holdout_format": read("integration-fmt-publication/publication-verified.json"),
            "arg0_fixture": arg0,
            "PTY_observation_and_Supervisor_connection": observation,
        },
        "comparison_denominators": {
            "initial_2d_against_67": {"paths": 230, "scope": "historical initial composition only"},
            "840_against_aaf": {"paths": 6, "old_leaves_modified": 4, "new_leaves": 2, "old_leaves_unchanged": 10798, "total_leaves": 10804},
            "formatter_successor_against_840": {"paths": 3, "old_leaves_unchanged": 10801, "total_leaves": 10804},
            "current_PR_against_636": {"paths": current["changed_files_against_target_base"], "commits": current["commits_against_target_base"]},
            "main_732_to_840_ancestry": read("fourth-audit-current-cut/main-to-product.summary.json"),
            "denominators_are_not_added_or_interchanged": True,
        },
        "complete_metadata_census_historical_cut": {
            "PR_window_UTC": ["2026-11-06T03:31:39Z", "2026-11-06T03:35:10Z"],
            "open_PRs": 3555, "Draft": 3506, "non_Draft": 49,
            "main_base": 360, "other_base": 3195, "distinct_base_refs": 2220,
            "PR_pages_then_empty": 36,
            "branch_window_UTC": ["2026-11-06T03:42:06Z", "2026-11-06T03:43:26Z"],
            "branches": 5333, "distinct_branch_commits": 4946, "branch_pages_then_empty": 54,
            "old_1103_census_is_subset": True,
            "newly_visible_2452_are_not_claimed_daily_growth": True,
            "full_metadata_coverage_is_not_all_PR_line_by_line_source_review": True,
            "not_a_current_realtime_total": True,
        },
        "current_bounded_metadata_cut": metadata,
        "dependency_lock_and_vendor": {
            "prior_complete_native_record": initial["cargo_actual_artifact"],
            "actual_integrated_product_input": True,
            "native_generation_and_deny_not_product_compile_or_test": True,
            "new_source_acceptance_transferred_from_old_donor": False,
        },
        "original_holdout_native": {
            "source_head": "4a1410f332e4a34564feafbc4dcb2e808c7f6c5f",
            "source_tree": "605720504e547296dca1c78914fee5ed6d29844d",
            "run": 42176273058, "job": 127755476318, "conclusion": "failure",
            "artifact": 13486100626, "archive_bytes": 379045,
            "archive_sha256": "e7d981ea110d109c40b5e290ba23e6f5c9262c01debacd5b728d94c5d4a45813",
            "archive_members": 3, "console_bytes": 4329523, "inner_log_bytes": 2284485,
            "executed": 17800, "PASS_including_two_flaky": 17796, "FAIL": 3, "TIMEOUT": 1, "skipped": 49,
            "exit": 100, "outer_timed_out": False, "outer_truncated": False,
            "holdout_cases_PASS": 6, "arg0_missing_fixture_FAIL": 3,
            "paired_Supervisor_TIME_OUT": 1, "two_original_attempt_seconds": [60.005, 60.008],
            "selected_packages": 127, "changed_packages": 20, "full_workspace": False,
            "old_actual_registry": "23e67ce20a439e2968eb63ae4e9a74a214ccd081",
            "qualification_transferred_to_new_source": False,
        },
        "holdout_format_failure_and_native_result": {
            "old_2d_failure_job": 127779715942,
            "exact_fix_paths": 2, "exact_native_formatter_blocks": 3,
            "old_fix_all_nonwhitespace_bytes_equal": True,
            "successful_source": native_old["source"],
            "actual_scope": native_old["ac18"],
            "cargo_deny_API_success_does_not_supply_missing_full_log": True,
            "latest_head_native_acceptance_transferred": False,
        },
        "arg0_fixture_repair": {
            "actual_commit": arg0["head"], "actual_tree": arg0["tree"],
            "independent_review": "cd7ed2f2a033882671a24258e1d360863039e5d0",
            "Linux_only": True, "changed_paths": 3,
            "prebuild_command": ["cargo", "build", "--locked", "-p", "codex-arg0", "--bin", "test_arg0_preflight"],
            "record_output_mode": "Original exclusive recorder writes separate preparation and suite records.",
            "ordinary_stdout_mode": "Independent running/final JSON appears in original stdout, retained by outer scoped recorder.",
            "full_nextest": "Original Linux target/profile helper artifact carries the already declared normal-main helper.",
            "original_planner_suite_arguments_budgets_assertions_unchanged": True,
            "arbitrary_manual_just_test_automatically_prepared": False,
            "offline_Python_regressions": 36, "original_Python_regressions_retained": 29,
            "real_recorder_fake_command_controls": 11, "Bash_fake_Cargo_controls": 3,
            "offline_controls_are_not_native_Rust_acceptance": True,
            "registry": "08e8e7ea26909d95392a0eddc157f75e308e2e9c",
        },
        "supervisor_connection_repair": {
            "initial_actual_commit": observation["head"],
            "private_candidate_tree_on_ac18": "44e8f7176037a5455476c068ad6ad8d692868769",
            "independent_review": "35b07140231fa056026ca00088930873a4812b55",
            "changed_paths": 3, "bounded_connect_callers": 3,
            "new_connection_stage_ms": 200, "read_and_write_timeout_ms_retained": 200,
            "adoption_attempts_retained": 3, "retry_spacing_ms_retained": 50,
            "Linux_EAGAIN_returns_original_error_without_internal_retry_or_fake_success": True,
            "identity_ACK_signal_permissions_unchanged": True,
            "new_owned_socket_test_sources": 6,
            "original_paired_test_blob": "c03bdba974ea48281cd839b9161eb0ccdc38b892",
            "entire_handshake_or_recovery_deadline_claimed": False,
            "old_60s_timeout_cause": "UNKNOWN",
            "stage_clock_starts_after_PairFleet_new": True,
            "binary_hash_integrity_checks_not_removed": True,
        },
        "PTY_original_evidence_and_observation": {
            "complete_v3_failure_record": initial["b21_actual_failed_native_evidence"],
            "8075_run": 42167168039, "8075_job": 127729084043,
            "8075_actual_merge": "b88f625afe17975db80b152283ef2e19cc50e41f",
            "8075_actual_tree": "c1249a173ac346d0f1230fe56451b97d4e13c601",
            "8075_job_conclusion": "cancelled", "cancellation_cause": "UNKNOWN",
            "8075_original_log_bytes": 1093592,
            "8075_PTY_cases": {"total": 31, "PASS": 27, "FAIL": 4},
            "original_contract_case_count_literal": 30,
            "observed_31_cases_do_not_replace_original_contract": True,
            "drop_failures_occurred_before_explicit_Drop": True,
            "8075_zero_read_and_older_2050048_read_are_distinct_executions": True,
            "CPython_tag": "v3.14.7", "CPython_commit": "823f0323ee6ec1402088b73bce1a38473cac36dc",
            "prepare_TCSADRAIN_is_not_TCIFLUSH": True,
            "FIFO_payload_then_original_single_newline_VEOF_unchanged": True,
            "queue_enqueue_does_not_prove_physical_write_completion": True,
            "observation_commit": observation["first_commit"],
            "observation_independent_review": "4f14ab769aa1d95a4e46249f345323beaeeaf68c",
            "author_freeze_members": 23, "test_only_observations": True,
            "four_existing_test_observation_points": 4,
            "original_reader_child_programs_budgets_assertions_unchanged": True,
            "diagnostics_FD_ownership": "Weak; snapshot's temporary upgrade may briefly pin the FD.",
            "Relaxed_fields_are_atomic_protocol_snapshot": False,
            "actual_failure_cause": "UNKNOWN", "B21": "OPEN",
        },
        "840_native_format_failure_and_mechanical_successor": {
            "run": 42197896368, "actual_executed_head": "840e8b5dbffca017753cdf87482ce325938f313c",
            "actual_executed_tree": "b38cc55050c74f8765bdee397a24066c100a179a",
            "Ubuntu_job": 127825647336, "Windows_job": 127825647542,
            "both_jobs_conclusion": "failure", "reported_failure_stage": "formatter",
            "Linux_formatter_blocks": 8, "Windows_formatter_blocks": 5,
            "Windows_blocks_equal_Linux_Supervisor_subset": True,
            "source_map": fmt_source,
            "whitespace_only_claimed": False,
            "explicit_punctuation_removals": ["single-expression closure opening brace", "single-expression closure closing brace", "Termios final field optional trailing comma"],
            "all_other_compact_characters_and_quoted_literals_and_comments_retained": True,
            "per_platform_restart_recovery_selected_cases": 3,
            "per_platform_agent_protocol_selected_cases": 14,
            "selected_cases_skipped": 0,
            "strict_Supervisor_Clippy_step_success": True,
            "six_new_Unix_tests_or_original_paired_selected_by_this_run": False,
            "current_successor_qualification": "PENDING_OWN_ORIGINAL_CI",
        },
        "B11_boundary_reassessment": {
            "registry": "59a15073eef10c61e2b3731611c4c41342deb1cd",
            "native13": {"PASS": 147, "FAIL": 7, "ignored": 2, "strict_failures": 3, "subsequent_poison_failures": 4},
            "explicit_helper_call_is_not_mandatory_boundary_for_raw_token_or_native_child": True,
            "Low_to_Medium": "Four outside writes denied; names remain.",
            "Low_to_other_Low_cohort": "Overwrite/create denied; file/directory deletion physically succeeded.",
            "physical_deletion_observation": "Before closing the observer handle: DeletePending=1 and links=0; after closing it: names absent.",
            "observed_thread_token_fields": {"integrity_RID": 4096, "attributes": 96, "mandatory_policy": 3},
            "three_token_fields_are_full_token_identity": False,
            "MIC_eight_row_stage_descendants_spawned": 0,
            "later_Neither_child_module_is_separate_stage": True,
            "inside_objects_explicitly_Low_do_not_prove_unrelabelled_root_loader_IPC_ConPTY_child_compatibility": True,
            "Untrusted_and_unmeasured_alternatives": "UNKNOWN",
            "production_permission_repair_claimed": False,
            "next_contract": "Mandatory object/operation authorization for DELETE, parent DELETE_CHILD, effective tokens and inherited/duplicated handles across valid child lifetime while retaining legitimate IO; escalate only a concrete expansion outside the original allowed scope.",
        },
        "B16": {
            "Foundation_unique_positive": 24, "positive_PASS_occurrences": 27,
            "unique_valid_negative": 9, "negative_expected_failure_occurrences": 10,
            "restorations": 4,
            "ordinary_UI_issuer_provider_same_source_real_acceptance": False,
            "old_driver_same_key_tool_timeouts": 3,
            "old_driver_job_identity": "UNKNOWN",
            "fourth_replay_new_key_or_PID_guess": False,
        },
        "B18_and_parallel_V13_increment": {
            "scientific_status": "SCIENTIFIC_HOLD",
            "independent_new_2x2_D_minus_B_adopted": False,
            "author_NDU_report": {"decision": "NO_GO", "cells": 144, "wins": 0, "ties": 143, "losses": 1, "scope": "Author's bounded report; not a new root-run scientific acceptance."},
            "PR4930_readonly_increment": research,
            "V13_partial_projection_is_full_repository_native_qualification": False,
            "V13_120_train_outputs_are_independent_quality_PASS": False,
            "V13_DENY_ALL_or_cold_receipt_reopen_grants_product_authority": False,
        },
        "B19": {
            "fixed_Hepta_source_prefix": "09de43ba", "fixed_Chain_source_prefix": "254033da",
            "sample_raw_bytes": 49508, "sample_hex_bytes": 99016, "raw_bound": 65536,
            "external_binary_build_provenance_qualified": False,
            "original_paired_native_accepted": False,
            "Bao_Chain_HIA_independent_real_consumers_accepted": False,
            "commit_string_is_binary_build_provenance": False,
        },
        "private_capacity_and_execution_constraints": {
            "private_full_catalog": 19563, "eligible": 19506, "ignored": 57,
            "original_disk_gate_GB": 64, "original_RAM_gate_GiB": 32, "jobs": 4,
            "prior_25GB_preparation_failure_preserved": True,
            "new_independent_capacity_evidence_available": False,
            "capacity_query_or_private_run_performed_this_increment": False,
            "manual_CI_dispatch_rerun_cancel": False,
            "local_Rust_Cargo_fmt_just_execution_claimed": False,
        },
        "same_source_automatic_CI": ci,
        "next_gates_zh": {row["id"]: row["original_exit_condition_zh"] for row in contracts if row["closure_class"] != "CLOSED_SCOPED"},
        "direction": {
            "modules": 40, "contracts": 205, "protocols": 58, "domains": 67, "work_packages": 91,
            "work_package_statuses": {"source_implemented": 25, "execution_pending": 20, "semantic_pending": 2, "planned": 43, "external": 1},
            "status_distribution_is_completion_percentage": False,
            "ordinary_flow": ["normal UI/API", "protected Root and signed Objective/FinalUse", "bounded Memory/Context", "Agentd lifecycle", "Codex Session/thread/turn/model/tools", "observable cancellable recoverable physical effects"],
            "priority": ["P0 single candidate and original engineering gates", "P1 real ordinary product closure", "P2 measured 64/256/1024/4096 logical slots", "P3 frozen-budget strong shadow baseline", "P4 read-only causal analysis", "P5 long-term learning forget/revoke/rollback", "P6 bounded engineering evolution", "P7 embodied real goals", "P8 external consumers"],
            "logical_slots_equal_simultaneous_OS_processes": False,
            "optimizer_or_research_worker_self_grants_authority": False,
        },
        "evidence_registries": [{key: component[key] for key in ("name", "schema", "prefix", "registry_blob")} for component in config["components"]],
        "evidence_index": "evidence-index-v13-addendum.json",
        "preservation": {"old_C3_leaves_retained": 15230, "only_old_paths_updated": ["LATEST.md", "LATEST.zh-CN.md"], "old_latest_bytes_archived": True, "old_failures_partial_stages_and_tool_errors_not_rewritten": True},
    }
    body = (json.dumps(machine, ensure_ascii=False, indent=2) + "\n").encode()
    output = ROOT / "third-post-audit-documents/post-audit-execution-v3.json"
    if output.exists() and output.read_bytes() != body:
        raise SystemExit("Refusing to overwrite different existing machine companion; preserve/review a new draft explicitly.")
    output.write_bytes(body)
    print(json.dumps({"machine": identity(body), "report": identity(report_body), "current_head": current["head"], "counts": counts}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
