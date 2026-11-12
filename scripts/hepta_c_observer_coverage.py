"""Exact original learning-owner subsets in one complete native report."""

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import stat
import re
import xml.etree.ElementTree as ET

from hepta_ci_junit import NoDoctypeTreeBuilder

PACKAGE = "codex-hepta-agentd"
PREFIX = "circuit_next_use_receipt_owner::tests::"
INGRESS = "runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::"
NEXT_USE_CASES = (
    PREFIX
    + "original_observer_configuration_rejects_substituted_custody_before_journal_creation",
    PREFIX
    + "original_observer_predecessors_require_bound_signed_roles_and_independent_custody",
    PREFIX + "original_observer_deadline_and_saved_signature_window_never_renew",
    PREFIX + "original_observer_pending_claim_reopens_without_signing_or_rewriting",
    INGRESS
    + "q24_ordinary_original_observer_attests_and_recovers_exact_completed_next_use",
    INGRESS
    + "q24_ordinary_original_observer_refuses_uncommitted_or_withdrawn_next_use",
)
MATERIAL_PREFIX = "cell_q24_material_receipt_owner::tests::"
MATERIAL_CASES = tuple(
    MATERIAL_PREFIX + name
    for name in (
        "original_material_pair_signs_recovers_and_feeds_actual_no_update_training",
        "original_material_pair_rejects_changed_custody_prefix_and_valid_freeze_resigning",
        "original_material_pair_withdrawal_refuses_cached_material_without_dataset_claim",
        "original_material_pair_pending_claim_reopens_without_signing_or_replacing_bytes",
        "original_material_pair_expired_work_only_reads_original_completed_windows",
        "original_material_pair_partial_creation_never_finishes_missing_dataset_during_recovery",
    )
)
SELECTION_PREFIX = (
    "runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::"
    "observer_support::selection_owner::"
)
SELECTION_CASES = tuple(
    SELECTION_PREFIX + name
    for name in (
        "q24_original_selector_attests_actual_publication_and_recovers_exact_signature",
        "q24_original_selector_refuses_withdrawn_publication_before_claim",
        "q24_original_selector_refuses_valid_training_renewal_live_and_cold",
        "q24_original_selector_preserves_pending_and_recovers_completed_lost_ack",
        "q24_original_selector_rejects_substituted_custody_before_store_creation",
        "q24_original_selector_rejects_another_real_completion_with_same_run_and_manifest",
    )
)
MODEL_SELECTION_PREFIX = (
    "runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::"
)
MODEL_SELECTION_CASES = tuple(
    MODEL_SELECTION_PREFIX + name
    for name in (
        "q24_source_bound_model_selector_attests_and_recovers_exact_adoption",
        "q24_source_bound_model_selector_refuses_withdrawn_training_source",
        "q24_source_bound_model_selector_refuses_withdrawn_version_publication",
        "q24_source_bound_model_selector_refuses_valid_predecessor_resigning",
        "q24_source_bound_model_selector_pending_claim_survives_recovery",
        "q24_source_bound_model_selector_fences_changed_execution_bytes",
    )
)
TRAINING_LANE_PREFIX = (
    "neuron_generation_update_bootstrap::adopted_learning::composed_tests::"
    "training::owner::model_proposal::training_lane::"
)
TRAINING_LANE_CASES = tuple(
    TRAINING_LANE_PREFIX + name
    for name in (
        "original_training_model_lane_retains_custody_and_exact_generator_evidence",
        "original_training_model_lane_preserves_pending_and_lost_ack",
        "original_training_model_lane_fences_physical_mutation_after_bytes_restore",
    )
)
SOURCE_PREFIX = "cell_q24_material_receipt_owner::tests::support::training_source::"
SOURCE_CASES = tuple(
    SOURCE_PREFIX + name
    for name in (
        "source_bound_training_preserves_frozen_rule_and_recovers_exact_no_update",
        "source_bound_training_rejects_identical_legacy_batch_before_admission",
        "source_bound_training_withdrawal_before_claim_fences_without_no_update",
        "source_bound_training_withdrawal_after_claim_preserves_pending_without_signature",
        "source_bound_capture_rejects_valid_freeze_resigning_with_identical_training_bytes",
        "source_bound_training_cold_identity_rejects_valid_material_signature_renewal",
    )
)
TRAINING_COMMAND_PREFIX = SOURCE_PREFIX + "command::"
TRAINING_COMMAND_CASES = tuple(
    TRAINING_COMMAND_PREFIX + name
    for name in (
        "original_training_command_executes_and_produces_actual_evidence_readback",
        "original_training_command_recovers_same_job_and_full_signature_read_only",
        "original_training_command_lost_ack_reads_existing_completion_without_reexecution",
        "original_training_command_withdrawal_after_claim_preserves_pending_without_signature",
        "original_training_command_wrong_context_cannot_claim_or_consume_admission",
        "original_training_command_public_bootstrap_refuses_same_process_custody",
    )
)
MATERIAL_SERVICE_PREFIX = "learning_iteration_evidence_client::material::tests::"
MATERIAL_SERVICE_CASES = tuple(
    MATERIAL_SERVICE_PREFIX + "material_readback_service_" + name
    for name in (
        "returns_original_signatures_and_cold_rereads",
        "refuses_request_rebinding_and_replay_without_writes",
        "refuses_withdrawn_source_and_busy_ledger",
        "never_finishes_missing_dataset",
        "rejects_same_uid_peer_and_widened_transport",
        "failed_frame_permanently_consumes_channel",
    )
)
REMOTE_MATERIAL_PREFIX = "learning_iteration_evidence_client::material::source::tests::"
REMOTE_MATERIAL_CASES = tuple(
    REMOTE_MATERIAL_PREFIX + name
    for name in (
        "material_source_peer_reconstructs_exact_sealed_material_and_cold_rereads",
        "material_source_peer_rejects_raw_batch_provenance_and_frozen_optimizer_rebinding",
        "material_source_peer_pins_complete_material_and_freeze_signatures",
        "material_source_service_refuses_withdrawn_missing_or_busy_originals",
        "material_source_service_refuses_request_payload_rebinding_and_public_custody_bypass",
        "material_source_peer_consumes_wrong_purpose_or_failed_frames",
    )
)
MATERIAL_COMMAND_PREFIX = (
    "learning_iteration_evidence_client::material::command::serving::tests::"
)
MATERIAL_COMMAND_CASES = tuple(
    MATERIAL_COMMAND_PREFIX + name
    for name in (
        "material_command_executes_original_experience_then_dataset_without_uploads",
        "material_command_lost_ack_recovers_original_signatures_and_shared_admission",
        "material_command_missing_predecessor_and_cold_missing_never_execute",
        "material_command_pending_claim_and_withdrawal_never_complete_or_rearm",
        "material_command_wrong_context_role_or_custody_never_claims",
        "material_command_pins_original_signatures_and_consumes_invalid_replies",
    )
)
TRANSPORT_CASES = (
    "learning_iteration_evidence_client::tests::"
    "original_receipt_fixture_retains_peer_during_owner_work_between_frames",
)
EXECUTION_PACKAGE = "codex-hepta-intelligence-eval"
EXECUTION_PREFIX = "product_runner::tests::execution_tests::original_evidence::"
EXECUTION_CASES = tuple(
    EXECUTION_PREFIX + name
    for name in (
        "original_execution_evidence_survives_recovery_without_work_or_renewal",
        "original_execution_evidence_rechecks_expiry_after_owner_reads",
        "equal_execution_with_validly_renewed_signature_has_different_original_evidence",
        "original_execution_evidence_missing_and_pending_never_claim",
    )
)
EXECUTION_OWNER_PREFIX = "neuron_cell_evaluation_execution_store::tests::"
EXECUTION_OWNER_CASES = tuple(
    EXECUTION_OWNER_PREFIX + name
    for name in (
        "original_execution_owner_preserves_missing_pending_and_completed_after_recovery",
        "original_execution_owner_creation_and_recovery_never_repair_partial_anchors",
        "original_execution_owner_lost_claim_ack_preserves_pending_or_uncertainty",
        "original_execution_owner_lost_completion_ack_preserves_completed_or_uncertainty",
        "original_execution_owner_physical_corruption_fences_even_after_restore",
        "original_execution_owner_readback_port_rejects_writes_keys_and_unwitnessed_tail",
    )
)
HOLDOUT_CURRENT_CASES = (
    "fenced_holdout_file::tests::physical_current::holdout_current_same_length_mutation_fences_after_restore",
    "fenced_holdout_file::tests::physical_current::holdout_current_rehashed_history_cannot_preserve_cached_frontier",
    "fenced_holdout_file::tests::physical_current::holdout_current_preserves_cursor_lock_and_fences_read_errors",
    "fenced_holdout_file::tests::physical_current::holdout_current_cold_recovery_and_non_target_calls_preserve_original_bytes",
    "product_runner::tests::execution_tests::holdout_current::holdout_current_lost_cas_ack_preserves_pending_without_provider_replay",
    "product_runner::tests::execution_tests::holdout_current::holdout_current_completed_execution_readback_requires_physical_original",
)
QUALIFICATION_OWNER_CASES = (
    "runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::qualification_owner::original_qualification_publishes_and_recovers_exact_completed_decision",
    "runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::qualification_owner::original_qualification_missing_and_pending_never_publish_during_recovery",
    "runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::qualification_owner::original_qualification_lost_completion_ack_preserves_uncertainty_and_exact_recovery",
    "runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::qualification_owner::original_qualification_rejects_context_and_valid_signature_renewal",
    "runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::qualification_owner::original_qualification_current_corruption_stays_fenced_after_restore",
    "runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::qualification_owner::original_qualification_requires_physical_execution_and_holdout_before_claim",
)
PUBLISHED_READ_PREFIX = SELECTION_PREFIX + "published_read::"
PUBLISHED_READ_CASES = tuple(
    PUBLISHED_READ_PREFIX + name
    for name in (
        "q24_remote_selection_reads_original_publication_before_c_and_recovers_signature",
        "q24_remote_c_requires_actual_completion_and_original_selector_signature",
        "q24_remote_current_refuses_withdrawal_after_a_successful_read",
        "q24_remote_context_pins_full_signatures_and_refuses_uploaded_observations",
        "q24_remote_read_consumes_late_and_wrong_nonce_responses_without_effects",
        "q24_remote_read_refuses_expired_original_window_and_same_process_bootstrap",
    )
)
SOURCE_CURRENT_PREFIX = "circuit_task::source::tests::physical_current::"
SOURCE_CURRENT_CASES = tuple(
    SOURCE_CURRENT_PREFIX + name
    for name in (
        "original_source_current_fences_same_length_mutation_after_restore",
        "original_source_current_fences_truncation_and_extra_tail_without_repair",
        "original_source_input_read_is_readonly_and_requires_live_original_configuration",
    )
)
SELECTOR_COMMAND_PREFIX = PUBLISHED_READ_PREFIX + "command_owner::"
SELECTOR_COMMAND_CASES = tuple(
    SELECTOR_COMMAND_PREFIX + name
    for name in (
        "q24_selector_command_binds_opaque_training_result_and_shared_dispatch",
        "q24_selector_command_lost_ack_recovers_original_signature_readonly",
        "q24_selector_command_recovered_missing_never_dispatches",
        "q24_selector_command_rejects_wrong_context_and_valid_renewal_before_dispatch",
        "q24_selector_command_evidence_readback_detects_live_withdrawal",
        "q24_selector_command_keeps_original_expiry_and_external_custody",
    )
)
DEFERRED_TRAINING_PREFIX = (
    "learning_iteration_evidence_client::training_command::bootstrap::tests::"
)
DEFERRED_TRAINING_CASES = tuple(
    DEFERRED_TRAINING_PREFIX + name
    for name in (
        "deferred_training_uses_actual_material_cut_and_original_source_without_precreation",
        "deferred_training_lost_ack_recovers_same_job_and_original_signature",
        "deferred_training_missing_dataset_or_partial_owners_never_bootstrap_replacements",
        "deferred_training_wrong_context_does_not_consume_original_custody",
        "deferred_training_failed_source_or_pending_claim_never_rearms",
        "deferred_training_attenuation_and_prebound_transport_preserve_original_custody",
    )
)
INITIAL_TRAINING_CONNECTION_CASES = tuple(
    DEFERRED_TRAINING_PREFIX + "command_connection::" + name
    for name in (
        "deferred_training_connection_rejects_experience_and_valid_other_freeze_context",
        "deferred_training_connection_preserves_expiry_and_readonly_cold_original_signature",
    )
)

NEXT_USE_COMMAND_PREFIX = "runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::selection_owner::published_read::command_owner::next_use_command::"
NEXT_USE_COMMAND_CASES = tuple(
    NEXT_USE_COMMAND_PREFIX + name
    for name in (
        "q24_next_use_command_attests_actual_different_c_and_shares_dispatch",
        "q24_next_use_command_lost_ack_recovers_exact_original_signature_readonly",
        "q24_next_use_command_early_dispatch_never_runs_c_or_resets_admission",
        "q24_next_use_command_pins_both_original_signatures_before_dispatch",
        "q24_next_use_command_readback_refuses_actual_publication_withdrawal",
        "q24_next_use_command_preserves_original_expiry_and_external_custody",
    )
)

CANDIDATE_MATERIAL_PREFIX = (
    "learning_iteration_evidence_client::training_command::bootstrap::tests::"
    "candidate_material::"
)
CANDIDATE_MATERIAL_CASES = tuple(
    CANDIDATE_MATERIAL_PREFIX + name
    for name in (
        "original_candidate_material_reconstructs_actual_pages_and_cold_original_signature",
        "original_candidate_material_readonly_preserves_no_update_missing_and_pending",
        "original_candidate_material_refuses_pages_renewal_window_withdrawal_and_cancel",
    )
)

ORDINARY_NO_UPDATE_MATERIAL_CASES = tuple(
    MATERIAL_COMMAND_PREFIX + "ordinary_stage::" + name
    for name in (
        "ordinary_stage_without_resident_gate_never_dispatches_original_material",
        "ordinary_stage_recovery_keeps_original_missing_uncertain_without_claim",
    )
)
C_COMPLETION_READINESS_CASES = tuple(
    NEXT_USE_COMMAND_PREFIX + "readiness::" + name
    for name in (
        "q24_readiness_waits_for_actual_c_without_consuming_observer_dispatch",
        "q24_readiness_withdrawal_is_fatal_and_never_becomes_pending",
        "q24_readiness_completed_identity_cannot_revert_or_change_publication",
        "q24_readiness_requires_original_selection_and_consumes_wrong_purpose",
    )
)

PHYSICAL_CELL_PACKAGE = "codex-hepta-neuron"
PHYSICAL_CELL_PREFIX = "cell_generation_journal::tests::physical_current::"
PHYSICAL_CELL_CASES = tuple(
    PHYSICAL_CELL_PREFIX + name
    for name in (
        "physical_current_preserves_complete_bytes_cursor_state_and_append_owner",
        "physical_current_rejects_short_tail_extra_tail_and_truncation_without_repair",
        "physical_current_rejects_valid_same_length_rehashed_history_and_cannot_rearm",
        "physical_current_rejects_header_change_and_preserves_cursor_after_restore",
        "physical_current_fences_witness_change_between_original_descriptor_reads",
    )
)

RETAINED_PUBLICATION_PREFIX = INGRESS + "observer_support::retained_publication::"
RETAINED_PUBLICATION_CASES = tuple(
    RETAINED_PUBLICATION_PREFIX + name
    for name in (
        "retained_publication_uses_original_selection_and_real_distinct_task_c",
        "retained_publication_refuses_changed_full_training_signature_before_prepare",
        "retained_publication_rejects_same_content_even_with_a_new_run_and_task_digest",
        "retained_publication_never_converts_candidate_training_into_no_update",
        "retained_publication_refuses_another_final_use_purpose_and_only_reads_pending",
        "retained_publication_refuses_actual_artifact_withdrawal_before_final_use",
        "retained_publication_lost_ack_recovers_original_files_without_another_grant",
    )
)

ARTIFACT_PUBLICATION_READBACK_CASES = (
    "owner_service::publication_readback_tests::original_publication_readback_bounds_the_actual_transaction_scan",
    "owner_service::publication_readback_tests::original_publication_readback_observes_lost_reply_without_republishing",
    "owner_service::publication_readback_tests::original_publication_readback_leaves_pending_and_recovery_block_unchanged",
    "owner_service::publication_readback_tests::original_publication_readback_cold_reopens_exact_pending_without_completion",
    "owner_service::publication_readback_tests::original_publication_readback_refuses_missing_or_changed_expected_operation",
    "owner_service::publication_readback_tests::original_publication_readback_refuses_actual_checkpoint_or_current_damage",
    "owner_service::publication_readback_tests::original_publication_readback_uses_live_clock_not_an_old_request_timestamp",
)

OWNER_GROUPS = (
    ("original_artifact_publication_readback", "codex-hepta-learning-artifacts", ARTIFACT_PUBLICATION_READBACK_CASES),
    ("original_retained_publication", PACKAGE, RETAINED_PUBLICATION_CASES),
    ("original_cell_physical_current", PHYSICAL_CELL_PACKAGE, PHYSICAL_CELL_CASES),
    ("next_use_observer", PACKAGE, NEXT_USE_CASES),
    ("material_observers", PACKAGE, MATERIAL_CASES),
    ("original_selector", PACKAGE, SELECTION_CASES),
    ("original_model_selector", PACKAGE, MODEL_SELECTION_CASES),
    ("original_qualification_owner", PACKAGE, QUALIFICATION_OWNER_CASES),
    ("original_execution_owner", PACKAGE, EXECUTION_OWNER_CASES),
    ("training_model_lane", PACKAGE, TRAINING_LANE_CASES),
    ("original_training_source", PACKAGE, SOURCE_CASES),
    ("original_training_command", PACKAGE, TRAINING_COMMAND_CASES),
    ("original_deferred_training", PACKAGE, DEFERRED_TRAINING_CASES),
    (
        "original_initial_training_connection",
        PACKAGE,
        INITIAL_TRAINING_CONNECTION_CASES,
    ),
    ("original_material_service", PACKAGE, MATERIAL_SERVICE_CASES),
    ("original_remote_material_source", PACKAGE, REMOTE_MATERIAL_CASES),
    ("original_material_command", PACKAGE, MATERIAL_COMMAND_CASES),
    ("original_peer_lifetime", PACKAGE, TRANSPORT_CASES),
    ("original_execution_evidence", EXECUTION_PACKAGE, EXECUTION_CASES),
    ("original_holdout_current", EXECUTION_PACKAGE, HOLDOUT_CURRENT_CASES),
    ("original_published_circuit_read", PACKAGE, PUBLISHED_READ_CASES),
    ("original_task_source_current", PACKAGE, SOURCE_CURRENT_CASES),
    ("original_selector_command", PACKAGE, SELECTOR_COMMAND_CASES),
    ("original_next_use_command", PACKAGE, NEXT_USE_COMMAND_CASES),
    ("original_candidate_material", PACKAGE, CANDIDATE_MATERIAL_CASES),
    ("ordinary_no_update_material_guard", PACKAGE, ORDINARY_NO_UPDATE_MATERIAL_CASES),
    ("original_c_completion_readiness", PACKAGE, C_COMPLETION_READINESS_CASES),
)
EXPECTED_CASES = tuple(
    (package, name) for _, package, names in OWNER_GROUPS for name in names
)
CASES = tuple(name for _, name in EXPECTED_CASES)

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
TERMINAL = re.compile(
    r"^\s*(PASS|FAIL|TIMEOUT|EXECFAIL|LEAK|SKIP)\s+\[[^\]\n]+\]\s+"
    r"(?:\(\s*\d+/\d+\)\s+)?(\S+)\s+(\S+)\s*$",
    re.MULTILINE,
)


def assess_original_observer_coverage(log: str, xml: bytes) -> dict:
    if len(xml) > 64 * 1024 * 1024:
        raise ValueError("Observer JUnit exceeds its byte bound")
    if len(set(EXPECTED_CASES)) != len(EXPECTED_CASES) or len(set(CASES)) != len(CASES):
        raise ValueError("duplicate Observer inventory")
    expected = Counter(EXPECTED_CASES)
    document = ET.fromstring(xml, parser=ET.XMLParser(target=NoDoctypeTreeBuilder()))
    if document.tag not in ("testsuite", "testsuites"):
        raise ValueError("unexpected native JUnit root")
    suites = (
        [document] if document.tag == "testsuite" else document.findall("testsuite")
    )
    selected = [
        (suite, case)
        for suite in suites
        for case in suite.findall("testcase")
        if case.get("name") in CASES
    ]
    all_named = [
        case for case in document.iter("testcase") if case.get("name") in CASES
    ]
    observed = Counter(
        (case.get("classname"), case.get("name")) for _, case in selected
    )
    xml_ok = (
        len(selected) == len(all_named) == len(CASES)
        and observed == expected
        and all(
            suite.get("name") == case.get("classname")
            and not any(
                node.tag
                in (
                    "failure",
                    "error",
                    "skipped",
                    "flakyFailure",
                    "flakyError",
                    "rerunFailure",
                    "rerunError",
                )
                for node in case.iter()
            )
            for suite, case in selected
        )
    )
    clean_log = ANSI.sub("", log)
    summary = re.search(r"^\s*Summary\s+\[[^\]\n]+\]\s+", clean_log, re.MULTILINE)
    # Pinned nextest prints final-output status headers again after Summary.
    # Keep the whole log, but count only its original execution-status phase.
    rows = TERMINAL.findall(clean_log[: summary.start()]) if summary is not None else []
    named = [row for row in rows if row[2] in CASES]
    log_ok = Counter((package, name) for _, package, name in named) == expected and all(
        status == "PASS" for status, _, _ in named
    )
    return {
        "expected_count": len(CASES),
        "required_owner_groups": {name: len(cases) for name, _, cases in OWNER_GROUPS},
        "required_group_packages": {name: package for name, package, _ in OWNER_GROUPS},
        "expected": sorted(expected),
        "junit_observed": sorted(observed.elements(), key=repr),
        "terminal_rows": named,
        "terminal_phase": "before_first_nextest_summary",
        "exact_pass_coverage": xml_ok and log_ok,
    }


def assess_retained_original_observer_coverage(
    execution_path: Path, junit_path: Path
) -> dict:
    """Read the recorder's original bounded log, never a guessed log name."""
    encoded_record = execution_path.read_bytes()
    record = json.loads(encoded_record)
    if (
        record.get("status") != "passed"
        or any(
            type(record.get(field)) is not int or record[field] != 0
            for field in ("returncode", "command_exit_code", "exit_code")
        )
        or record.get("timed_out") is not False
        or record.get("output_limit_exceeded") is not False
    ):
        raise ValueError("Observer coverage requires a successful retained execution")
    name = record.get("log_file")
    if (
        not isinstance(name, str)
        or re.fullmatch(re.escape(execution_path.name) + r"\.[0-9a-f]{32}\.log", name)
        is None
    ):
        raise ValueError("retained execution log must be its exact relative basename")
    expected_size = record.get("log_bytes")
    expected_digest = record.get("log_sha256")
    if (
        type(expected_size) is not int
        or not 0 <= expected_size <= 64 * 1024 * 1024
        or not isinstance(expected_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None
    ):
        raise ValueError("retained execution lacks bounded original log identity")
    path = execution_path.parent / name

    def identity(value):
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )

    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("retained execution log is not an original regular file")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read(expected_size + 1)
        after = os.fstat(stream.fileno())
    current = path.lstat()
    if (
        identity(before) != identity(opened)
        or identity(opened) != identity(after)
        or identity(after) != identity(current)
        or len(raw) != expected_size
        or hashlib.sha256(raw).hexdigest() != expected_digest
    ):
        raise ValueError("retained original log bytes or identity changed")
    with junit_path.open("rb") as stream:
        xml = stream.read(64 * 1024 * 1024 + 1)
    if execution_path.read_bytes() != encoded_record:
        raise ValueError("retained execution record changed during coverage read")
    result = assess_original_observer_coverage(
        raw.decode("utf-8", errors="replace"), xml
    )
    return {
        "execution_record_sha256": hashlib.sha256(encoded_record).hexdigest(),
        "log_file": name,
        "log_bytes": len(raw),
        "log_sha256": expected_digest,
        **result,
    }
