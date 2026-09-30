//! Authoritative learning.operator surface.
//!
//! The historical implementation remains available as a compatibility module.
//! Production qualification enters through the opaque, single-use final-use
//! capabilities in `final_use`; raw structural fitters are exported only by the
//! non-default `qualification-unverified-input` feature.
#![forbid(unsafe_code)]

#[path = "lib.rs"]
mod legacy;
pub use legacy::*;

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
