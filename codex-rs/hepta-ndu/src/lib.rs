//! Deterministic, bounded NDU evaluation, preference, projection, and shadow-learning primitives.
#![forbid(unsafe_code)]

mod candidate_quarantine;
mod coefficient_profile;
mod conditional_moments;
mod covariance;
mod covariance_profile;
mod error;
mod evaluation_digest;
mod evaluator;
mod fbsde_training;
mod feature_evidence;
mod fixed;
mod hardening;
mod hierarchy;
mod model;
mod operational_metrics;
mod owner;
mod owner_binding;
mod preference;
mod projection_epoch;
mod projection_journal;
mod projection_store;
mod protocol;
mod recursive;
mod scoring;
mod validated_scalarization;
mod z_conversion;

pub use candidate_quarantine::{evaluate_candidates_with_quarantine, CandidateQuarantineReasonV1, NduEvaluationReceiptV3, QuarantinedCandidateV1};
pub use coefficient_profile::{admit_ndu_coefficient_profile, project_z_estimate_to_coefficient_q24, validate_ndu_coefficient_projection_v1, AdmittedNduCoefficientProfileV1, NduCoefficientProfileError, NduCoefficientProfileV1, NduCoefficientProjectionV1};
pub use conditional_moments::{estimate_conditional_moments, ConditionalMomentSampleV1, ConditionalMomentsV1};
pub use covariance::{solve_backward_regression, ZEstimateV1};
pub use covariance_profile::{admit_covariance_profile, AdmittedCovarianceProfileV1, CovarianceConventionV1, CovarianceError, NduCovarianceProfileV1};
pub use error::NduError;
pub use evaluator::{canonical_evaluation_policy_digest, canonical_scalarization_digest, canonical_utility_profile_digest, evaluate_candidates_with_policy, legacy_evaluation_policy};
#[allow(deprecated)]
pub use evaluator::evaluate_candidates;
pub use fbsde_training::{admit_ndu_fbsde_training_policy_v1, bind_ndu_fbsde_publication_v1, evaluate_ndu_fbsde_shadow_gate_v1, reference_evaluate_ndu_fbsde_v1, seal_ndu_fbsde_dataset_v1, train_discrete_ndu_fbsde_v1, AdmittedNduFbsdeTrainingPolicyV1, NduFbsdeDatasetSnapshotV1, NduFbsdeFoldV1, NduFbsdeMetricsV1, NduFbsdePublicationBindingV1, NduFbsdeReferenceReceiptV1, NduFbsdeShadowEvidenceV1, NduFbsdeShadowGateReceiptV1, NduFbsdeShadowPolicyV1, NduFbsdeShadowStageV1, NduFbsdeStepV1, NduFbsdeTimeSliceV1, NduFbsdeTrainingCandidateV1, NduFbsdeTrainingError, NduFbsdeTrainingPolicyV1, NduFbsdeTrajectoryV1};
pub use feature_evidence::{bind_contribution_evidence_v1, canonical_ndu_evidence_policy_digest_v1, NduActorScenarioV1, NduEvidenceErrorV1, NduEvidencePolicyV1, NduFeatureEvidenceV1, NduFeatureKindV1, NduFeatureOriginV1};
pub use fixed::mul_q32_ties_even;
pub use hardening::{validate_authoritative_staged_updates, NduAuditMetricsV1, NduAuthoritativeUpdateV1, NduDurableProjectionArtifactV2, NduFiltrationContractV1, NduGrantRefreshPort, NduHardeningError, NduHierarchySnapshotProofV1, NduImmutableTrainingDataBindingV1, NduProjectionArtifactKindV2, NduProjectionArtifactPort, NduProjectionCatalogActionV2, NduProjectionCatalogEntryV2, NduProjectionCatalogV2, NduRevocationPort, NduShadowPromotionPolicyV1, NduTrustedTimePort};
pub use hierarchy::{hierarchy_snapshot_digest, validate_staged_updates_against_snapshot, HierarchyNodeV1, HierarchySnapshotV1, HierarchyValidationErrorV1};
pub use model::{AggregationOperator, AxisAggregationRule, AxisDirection, AxisLimit, AxisValue, CandidateRejectionReason, CandidateUtility, ContributionSet, EvaluationDisposition, EvaluationPolicyV1, FeasibilityPosture, NduEvaluationReceipt, NduEvaluationReceiptV2, RejectedCandidate, RequiredOrganSet, ScalarizationProfile, SubjectClass, UtilityContribution, UtilityProfile};
pub use operational_metrics::{canonical_backup_policy_digest_v1, operational_metrics_snapshot_v1, operational_metrics_snapshot_v2, validate_backup_policy_v1, validate_restore_drill_receipt_v1, validate_restore_drill_receipt_v2, NduBackupPolicyV1, NduOperationalMetricSnapshotV1, NduOperationalMetricSnapshotV2, NduOperationalMetricsV1, NduOperationsError, NduRestoreDrillReceiptV1, NduRestoreDrillReceiptV2, NDU_LATENCY_BUCKET_UPPER_MICROS_V2, NDU_UNCERTAINTY_BUCKET_UPPER_RAW_V2};
pub use owner::{NduAuthenticatedEvaluationReceiptV1, NduAuthenticatedOwnerV1, NduOwnerContextV1, NduOwnerError, NduOwnerMutationV1, NduProductionPolicyV1};
pub use preference::{solve_preference_target, validate_staged_updates, NduSolverIterationReceipt, NduSolverTerminationReceipt, PreferenceState, SolveDisposition, UpdateGeneration};
pub use projection_epoch::{plan_projection_archive_retention_v1, verify_projection_archive_chain_v1, NduProjectionArchiveAcknowledgementV1, NduProjectionCheckpointV1, NduProjectionEpochArchiveV1, NduProjectionEpochError, NduProjectionEpochJournalV1, NduProjectionRetentionPolicyV1};
pub use projection_journal::{NduProjectionEntryV1, NduProjectionJournalError, NduProjectionJournalV1, NduProjectionKindV1};
pub use projection_store::{NduProjectionStoreError, NduProjectionStoreV1};
pub use protocol::{bind_solver_iteration_receipt_v1, solve_preference_target_with_context_v1, NduIterationContextV1, NduIterationReceiptV1};
pub use recursive::{evaluate_recursive_utility, RecursiveUtilityError, RecursiveUtilityPath, RecursiveUtilityReceipt, UtilityEvent};
pub use validated_scalarization::ValidatedScalarizationProfileV1;
pub use z_conversion::{admit_z_conversion_profile, convert_z_to_original_q24, AdmittedZConversionProfileV1, NduZConversionProfileV1, ZConversionError, ZCoordinateConventionV1, ZQ24ConversionReceiptV1};