//! Authoritative learning.operator surface.
//!
//! Default consumers receive an explicit, reviewed allowlist. Raw structural
//! fitters and caller-authored verification inputs remain available only under
//! the non-default `qualification-unverified-input` feature and are grouped in
//! `compatibility`. Adding a new public item now requires an intentional edit to
//! this file instead of leaking through a wildcard re-export.
#![forbid(unsafe_code)]

#[path = "lib.rs"]
mod legacy;

// Explicit default surface required by the current read-only product adapters,
// owner-authenticated training path and independently pinned V2 loader.
pub use legacy::ApplicabilityDecisionV1;
pub use legacy::AuthenticatedApplicabilityAdmissionV2;
pub use legacy::AuthenticatedOperatorError;
pub use legacy::AuthenticatedOperatorRegularityAdmissionV2;
pub use legacy::BellmanOperatorArtifact;
pub use legacy::BellmanReferenceCellV1;
pub use legacy::BellmanReferencePlanV1;
pub use legacy::BellmanReferenceReceiptV1;
pub use legacy::BellmanReferenceTargetV1;
pub use legacy::BellmanTarget;
pub use legacy::ClassifyOperatorAdmissionFailure;
pub use legacy::DatasetSnapshot;
pub use legacy::Error;
pub use legacy::FrozenTerminalCellV1;
pub use legacy::GreedyReferenceActionV1;
pub use legacy::LearnedOperatorError;
pub use legacy::LoadedTabularOperatorV1;
pub use legacy::LoadedTabularOperatorV2;
pub use legacy::MAX_SIGNED_OPERATOR_ROWS;
pub use legacy::OperatorAdmissionStageV1;
pub use legacy::OperatorApplicabilityCertificateV1;
pub use legacy::OperatorClosureError;
pub use legacy::OperatorDatasetBindingError;
pub use legacy::OperatorErrorComponentV1;
pub use legacy::OperatorFailureDispositionV1;
pub use legacy::OperatorFailureScopeV1;
pub use legacy::OperatorRecoveryActionV1;
pub use legacy::OperatorRegularityAdmissionV1;
pub use legacy::OperatorRegularityAssessmentV1;
pub use legacy::OperatorSensorCoreManifestV1;
pub use legacy::OwnerDatasetFailureV1;
pub use legacy::OwnerDatasetOperationV1;
pub use legacy::PreparedTerminalCellV3;
pub use legacy::RegularityProfile;
pub use legacy::SensorCoreDesignV1;
pub use legacy::SensorPointV1;
pub use legacy::SignedOperatorEvidenceV2;
pub use legacy::StrictLearnedOperatorError;
pub use legacy::TABULAR_ARTIFACT_SCHEMA_V1;
pub use legacy::TABULAR_PAYLOAD_SCHEMA_V1;
pub use legacy::TabularOperatorArtifactV1;
pub use legacy::TabularOperatorCellV1;
pub use legacy::TabularOperatorPlanV1;
pub use legacy::TabularOperatorPredictionV1;
pub use legacy::TabularOperatorSampleV1;
pub use legacy::TabularPayloadError;
pub use legacy::TabularPayloadPinV1;
pub use legacy::TabularPayloadPinV2;
pub use legacy::TabularWorldModelV1;
pub use legacy::TerminalCellError;
pub use legacy::TerminalCellProfileV1;
pub use legacy::TrainingRequest;
pub use legacy::Transition;
pub use legacy::TransitionBranchV1;
pub use legacy::TransitionEstimateV1;
pub use legacy::ValidatedTabularOperatorV1;
pub use legacy::VerifiedTabularOperatorPlanV3;
pub use legacy::VerifiedTerminalCellV3;
pub use legacy::VerifiedWorldModelDatasetV3;
pub use legacy::WorldModelError;
pub use legacy::WorldModelPredictionV1;
pub use legacy::WorldModelSampleV1;
pub use legacy::admit_operator_regularity;
pub use legacy::admit_operator_regularity_with_signed_evidence_v2;
pub use legacy::build_sensor_core;
pub use legacy::build_targets;
pub use legacy::encode_tabular_payload_v1;
pub use legacy::evaluate_bellman_reference;
pub use legacy::fit_tabular_operator_verified_v3;
pub use legacy::fit_terminal_cell_from_owner_v1;
pub use legacy::fit_terminal_cell_verified_v3;
pub use legacy::fit_transition_model_verified_v3;
pub use legacy::freeze_terminal_cell_from_owner_v1;
pub use legacy::preflight_signed_tabular_v3;
pub use legacy::prepare_terminal_cell_from_owner_v3;
pub use legacy::tabular_training_signing_payload_v2;
pub use legacy::validate_applicability_certificate;
pub use legacy::validate_applicability_with_signed_evidence_v2;
pub use legacy::validate_tabular_artifact_v1;
pub use legacy::verify_tabular_operator_plan_v3;
pub use legacy::verify_world_model_dataset_v3;
pub use legacy::world_model_training_signing_payload_v2;

mod budget;
pub use budget::OperatorResourceBudgetV1;
pub use budget::OperatorResourceKindV1;
pub use budget::OperatorWorkErrorV1;
pub use budget::OperatorWorkSnapshotV1;
pub use budget::WorkControlV1;
pub use budget::with_work_control_v1;
pub(crate) use budget::OperatorWorkMeter;
pub(crate) use budget::checked_add;
pub(crate) use budget::checked_mul;
pub(crate) use budget::checked_u64;
pub(crate) use budget::sort_work;

mod profiles;
pub use profiles::OperatorProfileErrorV1;
pub use profiles::TrainingProfileV1;
pub use profiles::WorldModelProfileV1;

mod sensor_core_v2;
pub use sensor_core_v2::OperatorSensorCoreBuildReceiptV2;
pub use sensor_core_v2::SensorCoreBuildErrorV2;
pub use sensor_core_v2::SensorCoreExecutionProfileV2;
pub use sensor_core_v2::build_sensor_core_v2;

mod sensor_core_qualification;
pub use sensor_core_qualification::QualifiedSensorCoreBuildReceiptV1;
pub use sensor_core_qualification::SensorCoreSelectionModeV1;
pub use sensor_core_qualification::build_sensor_core_qualified_v1;

mod tabular_v2;
pub use tabular_v2::BudgetedTabularFitErrorV2;
#[cfg(feature = "qualification-unverified-input")]
pub use tabular_v2::TabularFitReceiptV2;
#[cfg(feature = "qualification-unverified-input")]
pub use tabular_v2::fit_tabular_operator_bounded_v2;

mod world_model_v2;
pub use world_model_v2::TransitionBranchV2;
pub use world_model_v2::WorldModelPredictionV2;
#[cfg(feature = "qualification-unverified-input")]
pub use world_model_v2::TransitionEstimateV2;
#[cfg(feature = "qualification-unverified-input")]
pub use world_model_v2::WORLD_MODEL_ARTIFACT_SCHEMA_V2;
#[cfg(feature = "qualification-unverified-input")]
pub use world_model_v2::WorldModelArtifactV2;
#[cfg(feature = "qualification-unverified-input")]
pub use world_model_v2::WorldModelPlanV2;
#[cfg(feature = "qualification-unverified-input")]
pub use world_model_v2::WorldModelUsePinV2;
pub use world_model_v2::WorldModelV2Error;
#[cfg(feature = "qualification-unverified-input")]
pub use world_model_v2::fit_world_model_v2;
#[cfg(feature = "qualification-unverified-input")]
pub use world_model_v2::predict_world_model_v2;

/// Non-default compatibility surface for structural fitters and V2 caller-
/// authored verified inputs. These functions do not grant final-use authority.
#[cfg(feature = "qualification-unverified-input")]
pub mod compatibility {
    pub use super::legacy::VerifiedTabularOperatorPlanV2;
    pub use super::legacy::VerifiedWorldModelDatasetV2;
    pub use super::legacy::fit_tabular_operator;
    pub use super::legacy::fit_tabular_operator_strict_v2;
    pub use super::legacy::fit_tabular_operator_verified_v2;
    pub use super::legacy::fit_transition_model;
    pub use super::legacy::fit_transition_model_verified_v2;
    pub use super::legacy::predict_tabular_operator;
    pub use super::legacy::predict_tabular_operator_indexed_v2;
    pub use super::legacy::predict_transition;
    pub use super::legacy::train;
    pub use super::legacy::verify_tabular_operator_plan_v2;
    pub use super::legacy::verify_world_model_dataset_v2;
    pub use super::tabular_v2::TabularFitReceiptV2;
    pub use super::tabular_v2::fit_tabular_operator_bounded_v2;
    pub use super::world_model_v2::TransitionEstimateV2;
    pub use super::world_model_v2::WORLD_MODEL_ARTIFACT_SCHEMA_V2;
    pub use super::world_model_v2::WorldModelArtifactV2;
    pub use super::world_model_v2::WorldModelPlanV2;
    pub use super::world_model_v2::WorldModelUsePinV2;
    pub use super::world_model_v2::fit_world_model_v2;
    pub use super::world_model_v2::predict_world_model_v2;
}

// Feature-gated aliases keep existing qualification fixtures source-compatible
// while callers migrate to `compatibility::*`. They are absent from the default
// public API and cannot be used by ordinary product dependencies.
#[cfg(feature = "qualification-unverified-input")]
pub use compatibility::VerifiedTabularOperatorPlanV2;
#[cfg(feature = "qualification-unverified-input")]
pub use compatibility::VerifiedWorldModelDatasetV2;
#[cfg(feature = "qualification-unverified-input")]
pub use compatibility::fit_tabular_operator;
#[cfg(feature = "qualification-unverified-input")]
pub use compatibility::fit_tabular_operator_strict_v2;
#[cfg(feature = "qualification-unverified-input")]
pub use compatibility::fit_tabular_operator_verified_v2;
#[cfg(feature = "qualification-unverified-input")]
pub use compatibility::fit_transition_model;
#[cfg(feature = "qualification-unverified-input")]
pub use compatibility::fit_transition_model_verified_v2;
#[cfg(feature = "qualification-unverified-input")]
pub use compatibility::predict_tabular_operator;
#[cfg(feature = "qualification-unverified-input")]
pub use compatibility::predict_tabular_operator_indexed_v2;
#[cfg(feature = "qualification-unverified-input")]
pub use compatibility::predict_transition;
#[cfg(feature = "qualification-unverified-input")]
pub use compatibility::verify_tabular_operator_plan_v2;
#[cfg(feature = "qualification-unverified-input")]
pub use compatibility::verify_world_model_dataset_v2;

mod final_use;
pub use final_use::FinalUseErrorV1;
pub use final_use::FinalUseFenceV1;
pub use final_use::FinalUseTabularCandidateV1;
pub use final_use::FinalUseWitnessV1;
pub use final_use::FinalUseWorldModelCandidateV1;
pub use final_use::OpaquePinnedTabularArtifactV1;
pub use final_use::OpaquePinnedWorldModelV1;
pub use final_use::SelectionCurrentnessV1;
pub use final_use::TabularTrainingRequestV1;
pub use final_use::WorldModelTrainingRequestV1;

mod final_use_hardening;
pub use final_use_hardening::FinalUseTabularCapabilityV1;
pub use final_use_hardening::FinalUseWorldModelCapabilityV1;
pub use final_use_hardening::fit_tabular_final_use_v1;
pub use final_use_hardening::fit_world_model_final_use_v1;
pub use final_use_hardening::issue_tabular_final_use_capability_v1;
pub use final_use_hardening::issue_world_model_final_use_capability_v1;

#[cfg(test)]
mod authoritative_tests;
