//! Deterministic, authority-free objective compilation.
//!
//! This crate accepts only typed structured evidence. It never interprets free
//! text as authority, relaxes hard constraints, selects an action, or executes
//! an external effect.

#![forbid(unsafe_code)]

mod compiler;
mod error;
mod feasibility;
mod feasibility_model;
mod model;
mod scalar_adapter;
mod source_envelope_v1;
mod source_envelope_validation;

pub use compiler::compile;
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
