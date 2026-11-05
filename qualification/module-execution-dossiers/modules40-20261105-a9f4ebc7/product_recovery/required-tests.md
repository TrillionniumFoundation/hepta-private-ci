# Required test audit for the original four-package suite

Total: **49** required named tests. This list is an audit subset, not a runner filter.

## protocol and host authority wire

- `codex-hepta-agent-protocol` / `codex_hepta_agent_protocol`: `tests::run_lifecycle_wire_round_trip_is_strict_and_bounded`
- `codex-hepta-agent-protocol` / `codex_hepta_agent_protocol`: `tests::health_wire_round_trip_is_strict_and_bounded`
- `codex-hepta-agent-protocol` / `codex_hepta_agent_protocol`: `tests::host_turn_authority_binding_is_strict_and_fail_closed`

## bound original snapshot and ABA

- `codex-hepta-agentd` / `codex_hepta_agentd`: `lane_b_runtime::bound::tests::reused_run_ids_cannot_redirect_bound_mutations_or_idempotent_acknowledgements`
- `codex-hepta-agentd` / `codex_hepta_agentd`: `lane_b_runtime::bound::tests::exact_bound_transitions_compare_revision_before_any_idempotent_return`

## overflow must preserve unresolved state

- `codex-hepta-agentd` / `codex_hepta_agentd`: `lane_b_runtime::fault_tests::exhausted_recovered_revision_keeps_unresolved_reservation`
- `codex-hepta-agentd` / `codex_hepta_agentd`: `lane_b_runtime::fault_tests::acknowledgement_deadline_overflow_preserves_dispatched_record`
- `codex-hepta-agentd` / `codex_hepta_agentd`: `lane_b_runtime::fault_tests::last_representable_terminal_transition_still_reconciles`

## canonical original identity, generation, fence and trust

- `codex-hepta-agentd` / `codex_hepta_agentd`: `intelligence_product::tests::signed::canonical_runtime::running_canonical_admission_preserves_the_recovered_run_start`
- `codex-hepta-agentd` / `codex_hepta_agentd`: `intelligence_product::tests::signed::canonical_runtime::canonical_recovery_rejects_old_generation_fence_and_signature_before_provider`
- `codex-hepta-agentd` / `codex_hepta_agentd`: `intelligence_product::tests::signed::canonical_runtime::canonical_body_does_not_alias_the_run_lifecycle_generation`
- `codex-hepta-agentd` / `codex_hepta_agentd`: `intelligence_product::tests::signed::canonical_runtime::owner_transition_during_canonical_preparation_never_refreshes_the_old_run`

## original deadline cap

- `codex-hepta-agentd` / `codex_hepta_agentd`: `intelligence_product::runner::run_start::tests::preparation_budget_is_capped_by_the_original_deadline`

## Desktop original issuer and writer joint fence

- `codex-hepta-agentd` / `codex_hepta_agentd`: `deployment_issuer::desktop::tests::desktop_policy_two_successors_keep_one_original_issuer_then_revocation_fences_the_pair`
- `codex-hepta-agentd` / `codex_hepta_agentd`: `deployment_issuer::desktop::tests::desktop_policy_expired_or_revoked_writer_keeps_both_original_slots`
- `codex-hepta-agentd` / `codex_hepta_agentd`: `deployment_issuer::desktop::tests::desktop_policy_pair_cas_preserves_original_owner_and_reconciles_exact_lost_ack`

## public apply/recover refusal before authority use

- `codex-hepta-runtime` / `codex_hepta_runtime`: `organs::tests::public_governed_topology_denies_before_grant_consumption_or_callbacks`
- `codex-hepta-runtime` / `codex_hepta_runtime`: `organs::tests::public_topology_recovery_denies_before_grant_consumption_or_callbacks`
- `codex-hepta-runtime` / `codex_hepta_runtime`: `organs::tests::revoked_final_use_never_mutates_the_live_topology`

## terminal qualification and full immutable binding

- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::control::intelligence_recovery::tests::terminal_publication_preserves_local_boundary_and_authority_loss`
- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::control::intelligence_recovery::tests::current_revision_does_not_relax_original_snapshot_binding`

## worker crash between durable terminal and Agentd acknowledgement

- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::control::intelligence_recovery::tests::process::settled_terminal_survives_worker_loss_before_agentd_publication`
- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::control::intelligence_recovery::tests::process::retained_app_server_terminal_reconciles_current_agentd_revision`

## real thread/read recovery without provider replay

- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::recovery::tests::real_agentd_reconciles_reopened_worker_without_replaying_provider`
- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::recovery::tests::real_agentd_reconciles_failed_terminal_without_replaying_provider`
- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::recovery::tests::real_agentd_reconciles_interrupted_terminal_without_replaying_provider`

## process loss before cleanup retains timeout, usage and owner loss

- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::failure_tests::worker_loss_before_cleanup_preserves_timeout_usage_and_owner_loss`

## strict retained assignment and irreversible boundaries

- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::recovery::reconciliation_tests::reopened_terminal_reconciliation_preserves_usage_and_irreversible_boundaries`
- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::recovery::reconciliation_tests::reopened_cancellation_intent_never_upgrades_a_completed_turn_to_success`
- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::recovery::reconciliation_tests::terminal_reconciliation_rejects_cross_request_and_cross_turn_usage`

## durable journal never replays a completed or rejected request

- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::control::tests::reopened_dispatch_and_completed_duplicate_never_connect_to_provider`
- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::control::tests::pre_dispatch_cancellation_and_connection_failure_release_without_usage_claims`
- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::control::tests::reopened_explicit_dispatch_rejection_never_connects_or_becomes_unknown`
- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::control::tests::intelligence_handoff_is_committed_to_native_admission_identity`

## complete bounded message output without terminal or usage fabrication

- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::native_output::tests::full_message_without_deltas_preserves_terminal_usage_and_local_boundary`
- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::native_output::tests::completed_items_replace_partial_text_once_in_item_order`
- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::native_output::tests::completed_text_and_deltas_share_an_atomic_byte_limit`
- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::native_output::tests::empty_messages_and_item_ids_cannot_grow_unbounded_metadata`

## CLI original snapshot required

- `codex-hepta-infer-worker-host` / `hepta-infer-worker`: `tests::snapshot_input_roundtrips_and_never_fills_missing_identity`

## retained real context, final-use, owner-loss and terminal boundaries

- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::tests::owner_loss_stays_denied_after_interrupt_grace_observes_completed`
- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::tests::owner_timeout_and_terminal_first_selection_cannot_authorize_success`
- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::tests::success_requires_both_matching_completion_and_final_ready_owner`
- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::tests::late_completed_cannot_upgrade_cancelled_or_timed_out_boundary`
- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::tests::cognitive_final_use_revalidation_follows_durable_dispatch_and_precedes_turn_start`
- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::tests::real_agentd_worker_accepts_fresh_context_and_rejects_final_use_tombstone`
- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::tests::lost_turn_start_ack_reconciles_only_the_exact_in_progress_thread`
- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::tests::only_the_bound_turn_can_complete_the_native_request`
- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::tests::actual_usage_is_bound_monotonic_and_survives_terminal_failure`
- `codex-hepta-infer-worker-host` / `codex_hepta_infer_worker_host`: `native_app_server::tests::final_use_fence_rejects_owner_ingress_cancel_and_deadline_drift`

