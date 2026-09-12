//! Compile-time linkage contract for every Lane E operation registered in the
//! closed-world implementation matrix. The test intentionally performs no
//! authority-bearing action; it proves that mapped symbols are public and
//! available to a real cross-crate consumer.

#[test]
fn lane_e_public_operation_surface_is_linkable() {
    let _ = codex_hepta_learning_ledger::verify_independent_roles;
    let _ = codex_hepta_learning_ledger::validate_authenticated_outcome;
    let _ = codex_hepta_learning_ledger::validate_candidate_set_completeness;
    let _ = codex_hepta_learning_ledger::finalize_credit_batch;
    let _ = codex_hepta_learning_ledger::freeze_dataset;
    let _ = codex_hepta_learning_ledger::append_shadow_decision;
    let _ = codex_hepta_learning_ledger::freeze_dataset_receipt_v3;
    let _ = codex_hepta_learning_ledger::verify_dataset_snapshot_receipt_v3;

    let _ = codex_hepta_bellman_operator::build_targets;
    let _ = codex_hepta_bellman_operator::validate_applicability_certificate;
    let _ = codex_hepta_bellman_operator::build_sensor_core;
    let _ = codex_hepta_bellman_operator::evaluate_bellman_reference;
    let _ = codex_hepta_bellman_operator::admit_operator_regularity;
    let _ = codex_hepta_bellman_operator::fit_transition_model;
    let _ = codex_hepta_bellman_operator::predict_transition;
    let _ = codex_hepta_bellman_operator::fit_tabular_operator;
    let _ = codex_hepta_bellman_operator::predict_tabular_operator;
    let _ = codex_hepta_bellman_operator::fit_tabular_operator_strict_v2;
    let _ = codex_hepta_bellman_operator::predict_tabular_operator_indexed_v2;

    let _ = codex_hepta_intelligence_eval::estimate_ope;
    let _ = codex_hepta_intelligence_eval::estimate_cluster_intervals;
    let _ = codex_hepta_intelligence_eval::estimate_sequential;
    let _ = codex_hepta_intelligence_eval::fit_temporal_fold;
    let _ = codex_hepta_intelligence_eval::evaluate_temporal_holdout;
    let _ = codex_hepta_intelligence_eval::freeze_cross_fold_plan;
    let _ = codex_hepta_intelligence_eval::FinalHoldoutRegistry::consume;
    let _ = codex_hepta_intelligence_eval::decide_independently;
    let _ = codex_hepta_intelligence_eval::FinalHoldoutJournalV1::consume;
    let _ = codex_hepta_intelligence_eval::FinalHoldoutJournalV1::from_snapshot;

    let _ = codex_hepta_learning_artifacts::write_candidate_payload;
    let _ = codex_hepta_learning_artifacts::write_registry_snapshot;
    let _ = codex_hepta_learning_artifacts::read_candidate_payload;
    let _ = codex_hepta_learning_artifacts::read_registry_snapshot;
    let _ = codex_hepta_learning_artifacts::validate_artifact_manifest_v2;
    let _ = codex_hepta_learning_artifacts::DatasetWithdrawalRegistry::append;
    let _ = codex_hepta_learning_artifacts::DatasetWithdrawalRegistry::admit_manifest;
    let _ = codex_hepta_learning_artifacts::validate_registry_head_witness;
    let _ = codex_hepta_learning_artifacts::validate_artifact_lifecycle_transition;
    let _ = codex_hepta_learning_artifacts::load_pinned_candidate;
    let _ = codex_hepta_learning_artifacts::admit_manifest_at_withdrawal_head_v3;
    let _ = codex_hepta_learning_artifacts::validate_artifact_publication_v3;
    let _ = codex_hepta_learning_artifacts::verify_artifact_admission_v3;
    let _ = codex_hepta_learning_artifacts::ArtifactLifecycleJournalV2::append;
    let _ = codex_hepta_learning_artifacts::ArtifactLifecycleJournalV2::from_snapshot;
}
