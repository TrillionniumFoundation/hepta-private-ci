//! Deterministic, authority-free objective compilation.
//!
//! This crate accepts only typed structured evidence. It never interprets free
//! text as authority, relaxes hard constraints, selects an action, or executes
//! an external effect.

#![forbid(unsafe_code)]

mod admission_profile_json;
mod compiler;
mod error;
mod feasibility;
mod feasibility_model;
mod model;
mod objective_admission;
mod publication;
mod scalar_adapter;
mod source_envelope_json;
mod source_envelope_json_dto;
mod source_envelope_json_shape;
mod source_envelope_v1;
mod source_envelope_validation;

pub use admission_profile_json::MAX_OBJECTIVE_ADMISSION_PROFILE_JSON_BYTES;
pub use admission_profile_json::ObjectiveAdmissionProfileJsonError;
pub use admission_profile_json::decode_admission_profile_json_v1;
pub use error::ObjectiveError;
pub use feasibility::check_feasibility_v1;
pub use feasibility_model::AtomPrecedenceV1;
pub use feasibility_model::AtomPredicateV1;
pub use feasibility_model::ConstraintAtomV1;
pub use feasibility_model::FeasibilityOutcomeV1;
pub use feasibility_model::FeasibilityReceiptV1;
pub use feasibility_model::FeasibleAssignmentV1;
pub use feasibility_model::IdentityValueV1;
pub use feasibility_model::OracleBudgetV1;
pub use feasibility_model::RegisteredAxisV1;
pub use feasibility_model::RegisteredDomainV1;
pub use feasibility_model::RegisteredGrammarV1;
pub use model::ActionClass;
pub use model::CompileDisposition;
pub use model::ConfirmationPolicy;
pub use model::Constraint;
pub use model::ConstraintClass;
pub use model::ConstraintRelation;
pub use model::ObjectiveCompileReceipt;
pub use model::ObjectiveConflictReceipt;
pub use model::ObjectiveFunction;
pub use model::ObjectiveSourceEnvelope;
pub use model::PredicateTerminality;
pub use model::SoftDirection;
pub use model::SoftPreference;
pub use model::SourceTrust;
pub use model::SuccessPredicate;

/// Qualification-only compatibility entrypoint for already validated legacy native envelopes.
///
/// Normal/product callers must enter through `admit_and_compile_objective_v1`, which binds
/// authenticated source context, principal scope, profile, freshness and semantic digests.
/// This function intentionally requires an explicit non-default Cargo feature so downstream
/// code cannot accidentally bypass admission.
#[cfg(feature = "qualification-legacy-objective-compile")]
pub fn compile_prevalidated_legacy_objective(
    source: ObjectiveSourceEnvelope,
) -> Result<Result<ObjectiveCompileReceipt, ObjectiveConflictReceipt>, ObjectiveError> {
    compiler::compile(compiler::AdmittedObjectiveSource::from_prevalidated_legacy(source))
}
pub use objective_admission::ObjectiveAbstentionRuleProfileV1;
pub use objective_admission::ObjectiveActionProfileV1;
pub use objective_admission::ObjectiveAdmissionContextV1;
pub use objective_admission::ObjectiveAdmissionError;
pub use objective_admission::ObjectiveAdmissionOutcomeV1;
pub use objective_admission::ObjectiveAdmissionProfileV1;
pub use objective_admission::ObjectiveAdmissionReceiptV1;
pub use objective_admission::ObjectiveConstraintProfileV1;
pub use objective_admission::ObjectiveEvidenceProfileV1;
pub use objective_admission::ObjectivePredicateProfileV1;
pub use objective_admission::ObjectiveResourceAxisProfileV1;
pub use objective_admission::ObjectiveResourceProfileV1;
pub use objective_admission::ObjectiveRiskProfileV1;
pub use objective_admission::ObjectiveSoftDimensionProfileV1;
pub use objective_admission::ObjectiveSourceAuthenticationV1;
pub use objective_admission::admit_and_compile_objective_v1;
pub use objective_admission::canonical_objective_intent_digest_v1;
pub use publication::ObjectiveRunPublicationError;
pub use publication::ObjectiveRunPublicationV1;
pub use publication::RunStartBindingsV1;
pub use publication::RunStartSnapshotV1;
pub use publication::objective_run_publication_digest_v1;
pub use source_envelope_json::MAX_OBJECTIVE_SOURCE_JSON_INPUT_BYTES;
pub use source_envelope_json::ObjectiveSourceJsonError;
pub use source_envelope_json::decode_source_envelope_json_v1;
pub use source_envelope_v1::ObjectiveConstraintComparatorV1;
pub use source_envelope_v1::ObjectiveEvidenceRequirementV1;
pub use source_envelope_v1::ObjectivePredicateComparatorV1;
pub use source_envelope_v1::ObjectiveProvenanceV1;
pub use source_envelope_v1::ObjectiveResourcesV1;
pub use source_envelope_v1::ObjectiveRiskClassV1;
pub use source_envelope_v1::ObjectiveRiskV1;
pub use source_envelope_v1::ObjectiveRollbackClassV1;
pub use source_envelope_v1::ObjectiveSoftDimensionV1;
pub use source_envelope_v1::ObjectiveSoftDirectionV1;
pub use source_envelope_v1::ObjectiveSourceConstraintV1;
pub use source_envelope_v1::ObjectiveSourceEnvelopeV1;
pub use source_envelope_v1::ObjectiveSourcePredicateV1;
pub use source_envelope_v1::ObjectiveSourceTrustV1;
pub use source_envelope_v1::ObjectiveStructuredIntentV1;
pub use source_envelope_validation::ObjectiveStructureError;
