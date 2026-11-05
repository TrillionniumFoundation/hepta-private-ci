import hashlib
import json
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
prefix = "authbus_dispatch::tests::"
expected = {
    "qualification-growth": {
        "qualification_tests::claim_query_rejects_more_than_512_references",
        "qualification_tests::ordinary_append_rejects_historical_projection_drift_without_consuming_replay",
    },
    "effect-pq-product": {
        "pq_effect_survives_owned_agentd_kill_after_provider_fsync_without_resend",
    },
    "effect-pq-owner": {
        "automation_effect_host::pq::tests::ordinary_loader_denies_classical_schema_and_contract_or_policy_substitution",
        "automation_effect_host::pq::tests::initial_feed_is_authenticated_before_any_local_authority_or_frontier_write",
        "automation_effect_host::pq::tests::current_clock_frontier_and_pq_grant_are_mandatory_before_contact",
        "automation_effect_host::pq::tests::revoked_equal_number_drift_expired_feed_and_new_epoch_do_not_contact_provider",
        "automation_effect_host::pq::tests::generation_change_after_store_await_refuses_contact_and_keeps_consumed_nonce",
        "automation_effect_host::pq::tests::signed_revocation_after_store_await_obeys_active_effect_fence_and_never_sends",
        "automation_effect_host::pq::tests::ordinary_dispatch_and_new_generation_recovery_keep_one_stable_operation",
        "automation_effect_host::pq::tests::recovery_requires_current_signed_exact_historical_policy_and_same_provider",
        "automation_effect_host::pq::tests::historical_policy_does_not_connect_old_trust_services_or_follow_its_references",
        "automation_effect_host::pq::tests::reconcile_rechecks_generation_after_store_await_without_reclassifying_unknown",
        "automation_effect_host::pq::tests::pon_schema4_binds_native_binary_and_original_limits_without_running_a_node",
    },
    "effect-pq-contract": {
        "provider_effect::pq_tests::pq_contract_binds_profile_root_epoch_and_complete_authority_scope",
    },
    "effect-settled-absence": {
        "owner_recovery_tests::settled_absence_fact_read_survives_reopen_and_new_owner_without_redispatch",
        "owner_recovery_tests::settled_absence_fact_read_rejects_unknown_unsettled_and_corrupt_evidence",
    },
    "dispatcher": {prefix + name for name in (
        "lost_queue_reply_recovers_from_sqlite_using_lookup_only_and_exact_receipt",
        "abandoned_first_claim_without_admission_is_quarantined_after_lookup_missing",
        "revocation_during_queue_request_prevents_success_ack",
        "ready_generation_and_owner_private_trust_are_required_before_admission",
        "matching_receipt_metadata_with_different_queue_input_never_acknowledges",
        "pq::pq_text_producer_recovers_through_existing_dispatch_and_rejects_wire_and_config_downgrade",
        "pq::pq_text_owner_resumes_after_revocation_rotation_and_rejected_config_rollback",
        "lease_delay::trust_refresh_sqlite_wait_cannot_authorize_transport_with_an_expired_lease",
        "policy_rollback::pq_removed_thread_cannot_return_through_owner_file_rollback_after_reopen",
        "policy_rollback::pq_owner_requires_explicit_nonzero_policy_revision_and_accepts_set_ordering",
        "policy_rollback::pq_bound_policy_refuses_renewal_without_policy_snapshot",
        "policy_rollback::pq_policy_change_fences_stale_renewal_and_current_policy_restores_dispatch",
        "checkpoint_sync::concurrent_checkpoint_syncs_share_owner_lock_and_preserve_rollback_rejection",
        "checkpoint_sync::cancelled_checkpoint_sync_waiter_and_owner_release_exclusive_admission",
    )},
    "product": {
        "signed_text_crosses_real_queue_once_and_current_trust_rejects_invalid_ingress",
        "pq_signed_text_crosses_real_queue_after_rejection_without_downgrade",
        "real_agentd_without_explicit_trust_rejects_signed_text",
    },
    "recovery-owner": {
        "recovery_effect_frontier_tests::" + name for name in (
            "recovery_snapshot_commits_intent_unknown_and_original_operation_receipt",
            "recovery_snapshot_distinguishes_a_valid_effect_only_database_rollback",
            "recovery_snapshot_commits_ack_provenance_and_cross_table_order",
            "recovery_snapshot_commits_effect_history_after_the_first_page",
            "recovery_snapshot_refuses_changed_json_with_retained_record_digests",
            "recovery_snapshot_refuses_effect_projection_drift_with_retained_payloads",
            "recovery_snapshot_refuses_canonical_ack_bound_to_a_different_payload",
            "recovery_snapshot_refuses_orphan_effect_observations",
            "recovery_snapshot_refuses_repeated_effect_sequence_after_schema_drift",
            "recovery_snapshot_refuses_repeated_effect_sequence_at_page_boundary",
        )
    } | {
        "provider_effect_recovery_provenance_tests::" + name for name in (
            "recovery_provenance_rejects_late_dispatch_after_status_without_uncertainty",
            "recovery_provenance_preserves_dispatch_then_authoritative_status",
        )
    } | {
        "recovery_invocation_frontier_tests::" + name for name in (
            "recovery_snapshot_commits_pending_invocations_and_terminal_states",
            "recovery_snapshot_commits_invocations_after_the_first_page",
            "recovery_snapshot_revalidates_invocation_payloads_and_projected_columns",
            "recovery_snapshot_requires_the_terminals_authoritative_intent",
            "recovery_snapshot_refuses_duplicate_terminal_hidden_at_page_boundary",
            "recovery_snapshot_refuses_invocation_column_type_corruption_without_panicking",
            "recovery_snapshot_binds_invocation_sequence_and_recording_time",
        )
    } | {
        "recovery_invocation_schema_tests::" + name for name in (
            "recovery_invocation_schema_accepts_current_migration_keys",
            "recovery_invocation_schema_refuses_non_rowid_or_composite_sequences",
            "recovery_invocation_schema_requires_exact_unconditional_column_uniqueness",
        )
    },
    "recovery-signed": {
        "evidence_frontier::tests::" + name for name in (
            "recovery_frontier_refuses_valid_classical_v1_and_v2_signatures",
            "recovery_frontier_authenticates_both_effect_fields",
            "recovery_frontier_pq_survives_store_close_and_reopen",
            "recovery_frontier_read_only_preflight_never_binds_or_changes_the_image",
            "recovery_frontier_cannot_be_omitted_at_the_ordinary_agentd_run_entry",
            "recovery_frontier_rejects_wrong_domain_and_profile",
            "recovery_frontier_enforces_root_scope_epoch_revocation_and_generation_floor",
            "recovery_frontier_rejects_wrong_key_pin_and_noncanonical_signature",
            "recovery_frontier_root_rotation_retires_the_old_key",
            "recovery_frontier_refuses_valid_pq_v3_and_relabelled_v2_snapshots",
            "recovery_frontier_pq_rejects_invocation_only_database_rollbacks",
        )
    },
    "recovery-product": {
        "real_agentd_composes_authenticated_evidence_writer_query_verifier_and_terminal_observer",
        "signed_recovery_frontier_allows_exact_current_database",
        "signed_recovery_frontier_rejects_valid_older_database_image",
        "signed_recovery_frontier_rejects_effect_only_database_rollback",
    },
}
observations = {}
for name, names in expected.items():
    try:
        record = json.loads((root / (name + ".json")).read_text())
        raw = (root / record["log_file"]).read_bytes()
        text = re.sub(r"\x1b\[[0-9;]*m", "", raw.decode("utf-8"))
        cases = re.findall(r"^test ([A-Za-z0-9_:]+) \.\.\. (ok|ignored|FAILED)\s*$", text, re.M)
        passed = [test for test, result in cases if result == "ok"]
        valid = (record["status"] == "passed" and record["command_exit_code"] == 0
                 and record["log_sha256"] == hashlib.sha256(raw).hexdigest()
                 and record["observed_passed_tests"] == len(names)
                 and record["observed_failed_tests"] == 0
                 and len(cases) == len(names) and len(passed) == len(names)
                 and set(passed) == names)
        observations[name] = {"passed": valid, "expected": sorted(names), "observed": cases}
    except (OSError, ValueError, KeyError) as error:
        observations[name] = {"passed": False, "error": str(error)}
(root / "selected-tests.json").write_text(json.dumps(observations, indent=2) + "\n")
if not all(item["passed"] for item in observations.values()):
    raise SystemExit("Every selected native test must execute and pass exactly once")