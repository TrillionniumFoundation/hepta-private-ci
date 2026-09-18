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
mod objective_admission_gate;
mod objective_function_v1;
mod run_start;
mod retry_policy;
mod scalar_adapter;
mod source_envelope_json;
mod source_envelope_json_dto;
mod source_envelope_json_shape;
mod source_envelope_v1;
mod source_envelope_validation;

/// Qualification-only compatibility entrypoint for already normalized legacy envelopes.
///
/// This bypasses authenticated source admission by design and is therefore not
/// available unless the consumer explicitly enables `legacy-objective-compile`.
/// Product callers must use `admit_and_compile_objective_v1`.
#[cfg(feature = "legacy-objective-compile")]
pub fn compile_prevalidated_legacy_objective(
    source: model::ObjectiveSourceEnvelope,
) -> Result<
    Result<model::ObjectiveCompileReceipt, model::ObjectiveConflictReceipt>,
    error::ObjectiveError,
> {
    compiler::compile(source)
}

pub use admission_profile_json::MAX_OBJECTIVE_ADMISSION_PROFILE_JSON_BYTES;
pub use admission_profile_json::ObjectiveAdmissionProfileJsonError;
pub use admission_profile_json::decode_admission_profile_json_v1;
pub use compiler::validate_compiled_objective_v1;
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

/// Stable V1 Rust contract name for the native compile receipt. This alias fixes
/// the public type-name drift with `ObjectiveCompileReceiptV1`; it does not claim
/// that the native `ObjectiveFunction` is the canonical JSON wire projection.
pub type ObjectiveCompileReceiptV1 = ObjectiveCompileReceipt;

/// Stable V1 Rust contract name for the typed non-error conflict outcome.
pub type ObjectiveConflictReceiptV1 = ObjectiveConflictReceipt;

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
pub use objective_admission::canonical_objective_intent_digest_v1;
pub use objective_admission_gate::admit_and_compile_objective_v1;
pub use objective_function_v1::ObjectiveConstraintWireV1;
pub use objective_function_v1::ObjectiveFunctionV1;
pub use objective_function_v1::ObjectivePredicateWireV1;
pub use objective_function_v1::ObjectivePrincipalScopeWireV1;
pub use objective_function_v1::ObjectiveProjectionError;
pub use objective_function_v1::ObjectiveResourcesWireV1;
pub use objective_function_v1::ObjectiveSoftDimensionWireV1;
pub use objective_function_v1::project_objective_function_v1;
pub use run_start::RunStartSnapshotError;
pub use run_start::RunStartSnapshotV1;
pub use retry_policy::ObjectiveRetryDirectiveV1;
pub use retry_policy::objective_admission_blind_retry_safe_v1;
pub use retry_policy::objective_admission_retry_directive_v1;
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
pub use source_envelope_validation::MAX_OBJECTIVE_AGGREGATE_PREDICATES;
pub use source_envelope_validation::MAX_OBJECTIVE_CALLER_ACTIONS;
pub use source_envelope_validation::MAX_OBJECTIVE_SOURCE_CONSTRAINTS;
pub use source_envelope_validation::ObjectiveStructureError;
