//! Deterministic, authority-free objective compilation.
//!
//! This crate accepts only typed structured evidence. It never interprets free
//! text as authority, relaxes hard constraints, selects an action, or executes
//! an external effect.

#![recursion_limit = "512"]
#![forbid(unsafe_code)]

mod admission_profile_json;
mod compiler;
mod error;
mod error_policy;
mod feasibility;
mod feasibility_model;
mod model;
mod objective_admission;
mod objective_function_v1;
mod scalar_adapter;
mod source_envelope_json;
mod source_envelope_json_dto;
mod source_envelope_json_shape;
mod source_envelope_v1;
mod source_envelope_validation;
mod validated_admission;

pub use admission_profile_json::MAX_OBJECTIVE_ADMISSION_PROFILE_JSON_BYTES;
pub use admission_profile_json::ObjectiveAdmissionProfileJsonError;
pub use admission_profile_json::decode_admission_profile_json_v1;
pub use compiler::canonical_native_objective_conflict_bytes_v1;
pub use compiler::canonical_native_objective_semantic_bytes_v1;
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
#[cfg(feature = "qualification-legacy-compile")]
pub use model::ObjectiveSourceEnvelope;
pub use model::PredicateTerminality;
pub use model::SoftDirection;
pub use model::SoftPreference;
pub use model::SourceTrust;
pub use model::SuccessPredicate;
pub use objective_admission::AdmittedObjectiveV1;
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
pub use objective_admission::admit_objective_v1;
pub use objective_admission::canonical_objective_intent_digest_v1;
pub use objective_admission::compile_admitted_objective_v1;
pub use objective_function_v1::DecodedObjectiveFunctionV1;
pub use objective_function_v1::MAX_OBJECTIVE_FUNCTION_V1_BYTES;
pub use objective_function_v1::ObjectiveFunctionV1Artifact;
pub use objective_function_v1::ObjectiveFunctionV1Error;
pub use objective_function_v1::decode_objective_function_v1;
pub use objective_function_v1::encode_authenticated_objective_function_v1;
#[cfg(test)]
pub(crate) use objective_function_v1::encode_objective_function_v1;
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
pub use validated_admission::ObjectiveAdmissionProofV1;
pub use validated_admission::ProofBearingObjectiveCompileV1;
pub use validated_admission::ValidatedAdmissionProfileV1;
pub use validated_admission::ValidatedObjectiveAdmissionV1;
pub use validated_admission::admit_validated_objective_v1;
pub use validated_admission::compile_authoritative_objective_v1;
pub use validated_admission::compile_validated_objective_v1;
pub use validated_admission::preflight_validate_objective_v1;

#[cfg(feature = "qualification-legacy-compile")]
/// Qualification-only compatibility entrypoint for pre-admitted legacy fixtures.
///
/// Product callers must never use this API: it does not authenticate source
/// context, bind an admission profile, or establish freshness. The feature is
/// intentionally off by default so ordinary downstream code cannot bypass the
/// admitted-objective type boundary accidentally.
pub fn compile_prevalidated_legacy_objective_v1(
    source: ObjectiveSourceEnvelope,
) -> Result<Result<ObjectiveCompileReceipt, ObjectiveConflictReceipt>, ObjectiveError> {
    crate::compiler::compile(source)
}
