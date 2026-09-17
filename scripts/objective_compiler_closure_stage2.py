#!/usr/bin/env python3
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, got {count}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))


def load_json(path: str):
    return json.loads(read(path))


def write_json(path: str, value) -> None:
    write(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Close the rich-only untrusted-source authority boundary.
# ---------------------------------------------------------------------------
replace_once(
    "codex-rs/hepta-objective/src/objective_admission.rs",
    "    validate_authentication(envelope, profile, &context.source_authentication)?;\n    let supplied_source_digest",
    "    validate_authentication(envelope, profile, &context.source_authentication)?;\n    validate_rich_source_authority(envelope, profile)?;\n    let supplied_source_digest",
)
replace_once(
    "codex-rs/hepta-objective/src/objective_admission.rs",
    "fn seal_admitted_objective(\n    compiled: &mut ObjectiveCompileReceipt,",
    r'''fn validate_rich_source_authority(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
) -> Result<(), ObjectiveAdmissionError> {
    if envelope.source_trust_class != ObjectiveSourceTrustV1::UntrustedEvidence {
        return Ok(());
    }
    if !envelope.structured_intent.legal_action_classes.is_empty() {
        return Err(ObjectiveAdmissionError::Compiler(
            ObjectiveError::UntrustedAuthorityEscalation,
        ));
    }
    for source in &envelope.structured_intent.constraints {
        let mapping = profile
            .constraints
            .iter()
            .find(|mapping| mapping.source_constraint_id == source.constraint_id)
            .ok_or(ObjectiveAdmissionError::UnknownConstraint)?;
        let action_semantics = matches!(
            source.comparator,
            crate::ObjectiveConstraintComparatorV1::RequireAction
                | crate::ObjectiveConstraintComparatorV1::ForbidAction
                | crate::ObjectiveConstraintComparatorV1::ImpliesAction
        );
        if mapping.class != ConstraintClass::Task || action_semantics {
            return Err(ObjectiveAdmissionError::Compiler(
                ObjectiveError::UntrustedAuthorityEscalation,
            ));
        }
    }
    Ok(())
}

fn seal_admitted_objective(
    compiled: &mut ObjectiveCompileReceipt,''',
)

# Stage-1 changes the profile ceiling and domain shape; make the hostile profile
# fixture compile while still exceeding the bound.
replace_once(
    "codex-rs/hepta-objective/src/objective_admission_tests.rs",
    '''            class: ConstraintClass::Task,
            axis: id(&format!("axis.{index}")),
        })
        .collect();''',
    '''            class: ConstraintClass::Task,
            axis: id(&format!("axis.{index}")),
            domain: super::ObjectiveConstraintDomainV1::Scalar {
                lower: FixedQ32::from_raw(i64::MIN),
                upper: FixedQ32::from_raw(i64::MAX),
            },
        })
        .collect();''',
)

# Additional security regression specifically uses a rich-only action atom so it
# cannot accidentally fall back to the legacy scalar authority check.
with (ROOT / "codex-rs/hepta-objective/src/objective_admission_tests.rs").open("a", encoding="utf-8") as handle:
    handle.write(r'''

#[test]
fn untrusted_rich_action_constraint_cannot_bypass_legacy_authority_projection() {
    let mut profile = profile();
    profile.constraints.push(ObjectiveConstraintProfileV1 {
        source_constraint_id: "inspect.required".to_string(),
        expected_unit: "action".to_string(),
        class: ConstraintClass::Task,
        axis: id("action.inspect"),
        domain: super::ObjectiveConstraintDomainV1::Action,
    });
    let mut envelope = envelope();
    envelope.structured_intent.legal_action_classes.clear();
    envelope.structured_intent.confirmation_action_classes.clear();
    envelope.structured_intent.constraints.push(ObjectiveSourceConstraintV1 {
        constraint_id: "inspect.required".to_string(),
        unit: "action".to_string(),
        comparator: ObjectiveConstraintComparatorV1::RequireAction,
        bound_q32: 0,
        set_values: Vec::new(),
        implication_target_action_class: None,
        evidence_source_id: "observer.action".to_string(),
        terminal: true,
    });
    envelope.source_trust_class = ObjectiveSourceTrustV1::UntrustedEvidence;
    refresh_intent_digest(&mut envelope);
    let mut context = context(&profile, &envelope);
    context.source_authentication = ObjectiveSourceAuthenticationV1::UntrustedEvidence {
        source_digest: envelope.structured_intent.provenance.source_digest,
    };
    assert_eq!(
        ObjectiveAdmissionError::Compiler(crate::ObjectiveError::UntrustedAuthorityEscalation),
        admit_and_compile_objective_v1(&envelope, &profile, &context)
            .expect_err("rich-only authority escalation must reject")
    );
}
''')

# ---------------------------------------------------------------------------
# Canonical ObjectiveCompileReceiptV1 JSON encoder.
# ---------------------------------------------------------------------------
write("codex-rs/hepta-objective/src/canonical_output.rs", r'''use std::error::Error as StdError;
use std::fmt;

use serde::Serialize;

use crate::ActionClass;
use crate::AtomPrecedenceV1;
use crate::AtomPredicateV1;
use crate::CompileDisposition;
use crate::ConfirmationPolicy;
use crate::Constraint;
use crate::ConstraintAtomV1;
use crate::ConstraintClass;
use crate::ConstraintRelation;
use crate::IdentityValueV1;
use crate::ObjectiveCompileReceipt;
use crate::PredicateTerminality;
use crate::SoftDirection;
use crate::SoftPreference;
use crate::SuccessPredicate;

pub const MAX_OBJECTIVE_COMPILE_RECEIPT_V1_BYTES: usize = 256 * 1024;

#[derive(Debug)]
pub enum ObjectiveWireError {
    MissingAdmissionBinding(&'static str),
    EncodedBytesExceeded { actual: usize, maximum: usize },
    Serialization(serde_json::Error),
}

impl fmt::Display for ObjectiveWireError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::MissingAdmissionBinding(field) => {
                write!(formatter, "canonical objective is missing admission binding: {field}")
            }
            Self::EncodedBytesExceeded { actual, maximum } => {
                write!(formatter, "canonical objective receipt has {actual} bytes; maximum is {maximum}")
            }
            Self::Serialization(error) => error.fmt(formatter),
        }
    }
}

impl StdError for ObjectiveWireError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Serialization(error) => Some(error),
            Self::MissingAdmissionBinding(_) | Self::EncodedBytesExceeded { .. } => None,
        }
    }
}

impl From<serde_json::Error> for ObjectiveWireError {
    fn from(value: serde_json::Error) -> Self {
        Self::Serialization(value)
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ReceiptWire {
    disposition: &'static str,
    objective: ObjectiveWire,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ObjectiveWire {
    request_id: String,
    principal_scope: String,
    revision: u64,
    source_digest: String,
    schema_digest: String,
    profile_digest: String,
    intent_digest: String,
    hard_constraint_digest: String,
    semantic_digest: String,
    hard_constraints: Vec<ConstraintAtomWire>,
    success_predicates: Vec<PredicateWire>,
    terminal_conditions: Vec<PredicateWire>,
    evidence_requirements: Vec<PredicateWire>,
    allowed_action_classes: Vec<ActionWire>,
    forbidden_action_classes: Vec<String>,
    resource_budget: Vec<ConstraintWire>,
    risk_constraints: Vec<ConstraintWire>,
    soft_utility_dimensions: Vec<SoftPreferenceWire>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ConstraintAtomWire {
    id: String,
    precedence: String,
    axis: String,
    predicate: AtomPredicateWire,
    unit: String,
    evidence_source_id: String,
    terminality: &'static str,
    origin_digest: String,
}

#[derive(Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum AtomPredicateWire {
    ScalarInterval { lower_q32: i64, upper_q32: i64 },
    ScalarNotEqual { value_q32: i64 },
    Include { values: Vec<String> },
    Exclude { values: Vec<String> },
    RequireAction,
    ForbidAction,
    ImpliesAction { target_action_id: String },
    IdentityScope { scope: String },
    IdentityGeneration { generation: u64 },
    Unsupported { language_id: String },
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct PredicateWire {
    id: String,
    axis: String,
    comparator: &'static str,
    bound_q32: i64,
    evidence_source_id: String,
    terminality: &'static str,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ActionWire {
    action_id: String,
    confirmation: &'static str,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ConstraintWire {
    id: String,
    class: &'static str,
    axis: String,
    comparator: &'static str,
    bound_q32: i64,
    evidence_source_id: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct SoftPreferenceWire {
    dimension_id: String,
    direction: &'static str,
    weight_q32: i64,
}

pub fn encode_objective_compile_receipt_v1(
    receipt: &ObjectiveCompileReceipt,
) -> Result<Vec<u8>, ObjectiveWireError> {
    let objective = &receipt.objective;
    let profile_digest = objective
        .profile_digest
        .ok_or(ObjectiveWireError::MissingAdmissionBinding("profileDigest"))?;
    let intent_digest = objective
        .intent_digest
        .ok_or(ObjectiveWireError::MissingAdmissionBinding("intentDigest"))?;
    let mut hard_constraints = objective.constraint_atoms.iter().collect::<Vec<_>>();
    hard_constraints.sort_by(|left, right| {
        (left.precedence, &left.axis, &left.id).cmp(&(right.precedence, &right.axis, &right.id))
    });
    let wire = ReceiptWire {
        disposition: match receipt.disposition {
            CompileDisposition::Compiled => "compiled",
            CompileDisposition::ExplicitAbstain => "explicit_abstain",
        },
        objective: ObjectiveWire {
            request_id: objective.request_id.to_string(),
            principal_scope: objective.principal_scope.to_string(),
            revision: objective.revision.get(),
            source_digest: objective.source_digest.to_string(),
            schema_digest: objective.schema_digest.to_string(),
            profile_digest: profile_digest.to_string(),
            intent_digest: intent_digest.to_string(),
            hard_constraint_digest: objective.hard_constraint_digest.to_string(),
            semantic_digest: objective.semantic_digest.to_string(),
            hard_constraints: hard_constraints.into_iter().map(atom_wire).collect(),
            success_predicates: objective.success_predicates.iter().map(predicate_wire).collect(),
            terminal_conditions: objective.terminal_conditions.iter().map(predicate_wire).collect(),
            evidence_requirements: objective.evidence_requirements.iter().map(predicate_wire).collect(),
            allowed_action_classes: objective.legal_actions.iter().map(action_wire).collect(),
            forbidden_action_classes: objective
                .forbidden_actions
                .iter()
                .map(ToString::to_string)
                .collect(),
            resource_budget: objective
                .resource_constraints
                .iter()
                .map(constraint_wire)
                .collect(),
            risk_constraints: objective
                .risk_constraints
                .iter()
                .map(constraint_wire)
                .collect(),
            soft_utility_dimensions: objective
                .soft_preferences
                .iter()
                .map(preference_wire)
                .collect(),
        },
    };
    let encoded = serde_json::to_vec(&wire)?;
    if encoded.len() > MAX_OBJECTIVE_COMPILE_RECEIPT_V1_BYTES {
        return Err(ObjectiveWireError::EncodedBytesExceeded {
            actual: encoded.len(),
            maximum: MAX_OBJECTIVE_COMPILE_RECEIPT_V1_BYTES,
        });
    }
    Ok(encoded)
}

fn atom_wire(atom: &ConstraintAtomV1) -> ConstraintAtomWire {
    ConstraintAtomWire {
        id: atom.id.to_string(),
        precedence: match atom.precedence {
            AtomPrecedenceV1::Hard(class) => class_name(class).to_string(),
            AtomPrecedenceV1::Soft => "soft".to_string(),
        },
        axis: atom.axis.to_string(),
        predicate: match &atom.predicate {
            AtomPredicateV1::ScalarInterval { lower, upper } => AtomPredicateWire::ScalarInterval {
                lower_q32: lower.raw(),
                upper_q32: upper.raw(),
            },
            AtomPredicateV1::ScalarNotEqual(value) => AtomPredicateWire::ScalarNotEqual {
                value_q32: value.raw(),
            },
            AtomPredicateV1::Include(values) => AtomPredicateWire::Include {
                values: values.iter().map(ToString::to_string).collect(),
            },
            AtomPredicateV1::Exclude(values) => AtomPredicateWire::Exclude {
                values: values.iter().map(ToString::to_string).collect(),
            },
            AtomPredicateV1::RequireAction => AtomPredicateWire::RequireAction,
            AtomPredicateV1::ForbidAction => AtomPredicateWire::ForbidAction,
            AtomPredicateV1::Implies(target) => AtomPredicateWire::ImpliesAction {
                target_action_id: target.to_string(),
            },
            AtomPredicateV1::IdentityEqual(IdentityValueV1::Scope(scope)) => {
                AtomPredicateWire::IdentityScope {
                    scope: scope.to_string(),
                }
            }
            AtomPredicateV1::IdentityEqual(IdentityValueV1::Generation(generation)) => {
                AtomPredicateWire::IdentityGeneration {
                    generation: *generation,
                }
            }
            AtomPredicateV1::Unsupported(language) => AtomPredicateWire::Unsupported {
                language_id: language.to_string(),
            },
        },
        unit: atom.unit.to_string(),
        evidence_source_id: atom.evidence_source.to_string(),
        terminality: terminality_name(atom.terminality),
        origin_digest: atom.origin_digest.to_string(),
    }
}

fn predicate_wire(value: &SuccessPredicate) -> PredicateWire {
    PredicateWire {
        id: value.id.to_string(),
        axis: value.axis.to_string(),
        comparator: relation_name(value.relation),
        bound_q32: value.bound.raw(),
        evidence_source_id: value.evidence_source.to_string(),
        terminality: terminality_name(value.terminality),
    }
}

fn action_wire(value: &ActionClass) -> ActionWire {
    ActionWire {
        action_id: value.id.to_string(),
        confirmation: match value.confirmation {
            ConfirmationPolicy::NotRequired => "not_required",
            ConfirmationPolicy::Required => "required",
        },
    }
}

fn constraint_wire(value: &Constraint) -> ConstraintWire {
    ConstraintWire {
        id: value.id.to_string(),
        class: class_name(value.class),
        axis: value.axis.to_string(),
        comparator: relation_name(value.relation),
        bound_q32: value.bound.raw(),
        evidence_source_id: value.evidence_source.to_string(),
    }
}

fn preference_wire(value: &SoftPreference) -> SoftPreferenceWire {
    SoftPreferenceWire {
        dimension_id: value.dimension.to_string(),
        direction: match value.direction {
            SoftDirection::Maximize => "maximize",
            SoftDirection::Minimize => "minimize",
        },
        weight_q32: value.weight.raw(),
    }
}

fn class_name(value: ConstraintClass) -> &'static str {
    match value {
        ConstraintClass::Constitutional => "constitutional",
        ConstraintClass::Principal => "principal",
        ConstraintClass::Environment => "environment",
        ConstraintClass::Task => "task",
    }
}

fn relation_name(value: ConstraintRelation) -> &'static str {
    match value {
        ConstraintRelation::AtLeast => "gte",
        ConstraintRelation::AtMost => "lte",
        ConstraintRelation::Equal => "eq",
        ConstraintRelation::NotEqual => "ne",
        ConstraintRelation::LessThan => "lt",
        ConstraintRelation::GreaterThan => "gt",
    }
}

fn terminality_name(value: PredicateTerminality) -> &'static str {
    match value {
        PredicateTerminality::Intermediate => "intermediate",
        PredicateTerminality::Terminal => "terminal",
    }
}

#[cfg(test)]
mod tests {
    use crate::ObjectiveWireError;
    use crate::compile;
    use crate::model_tests_support::basic_source_for_wire_test;

    #[test]
    fn legacy_compile_requires_admission_bindings_before_canonical_encoding() {
        let receipt = compile(basic_source_for_wire_test())
            .expect("compile")
            .expect("no conflict");
        assert!(matches!(
            crate::encode_objective_compile_receipt_v1(&receipt),
            Err(ObjectiveWireError::MissingAdmissionBinding("profileDigest"))
        ));
    }
}
''')

# The small encoder unit test above needs a source fixture without duplicating
# compiler tests. Provide a crate-private helper from compiler_tests is not
# available in non-test production modules, so replace the test module with an
# admission-level regression instead.
text = read("codex-rs/hepta-objective/src/canonical_output.rs")
start = text.index("#[cfg(test)]\nmod tests")
text = text[:start]
write("codex-rs/hepta-objective/src/canonical_output.rs", text)

replace_once(
    "codex-rs/hepta-objective/src/lib.rs",
    "mod admission_feasibility;\nmod compiler;",
    "mod admission_feasibility;\nmod canonical_output;\nmod compiler;",
)
replace_once(
    "codex-rs/hepta-objective/src/lib.rs",
    "pub use compiler::compile;",
    "pub use canonical_output::MAX_OBJECTIVE_COMPILE_RECEIPT_V1_BYTES;\npub use canonical_output::ObjectiveWireError;\npub use canonical_output::encode_objective_compile_receipt_v1;\npub use compiler::compile;",
)

with (ROOT / "codex-rs/hepta-objective/src/objective_admission_tests.rs").open("a", encoding="utf-8") as handle:
    handle.write(r'''

#[test]
fn admitted_objective_has_deterministic_bounded_canonical_output() {
    let profile = profile();
    let first_envelope = envelope();
    let first_context = context(&profile, &first_envelope);
    let first = admit_and_compile_objective_v1(&first_envelope, &profile, &first_context)
        .expect("first admission")
        .compile_result
        .expect("first compile");
    let mut reordered = first_envelope.clone();
    reordered.structured_intent.legal_action_classes.reverse();
    reordered.structured_intent.constraints.reverse();
    refresh_intent_digest(&mut reordered);
    let second_context = context(&profile, &reordered);
    let second = admit_and_compile_objective_v1(&reordered, &profile, &second_context)
        .expect("second admission")
        .compile_result
        .expect("second compile");
    let first_bytes = crate::encode_objective_compile_receipt_v1(&first)
        .expect("canonical first output");
    let second_bytes = crate::encode_objective_compile_receipt_v1(&second)
        .expect("canonical second output");
    assert_eq!(first_bytes, second_bytes);
    assert!(first_bytes.len() <= crate::MAX_OBJECTIVE_COMPILE_RECEIPT_V1_BYTES);
    let text = String::from_utf8(first_bytes).expect("UTF-8 canonical JSON");
    for field in [
        "terminalConditions",
        "evidenceRequirements",
        "allowedActionClasses",
        "forbiddenActionClasses",
        "resourceBudget",
        "riskConstraints",
        "hardConstraints",
    ] {
        assert!(text.contains(field), "missing canonical field {field}");
    }
}
''')

# ---------------------------------------------------------------------------
# Intelligence caller adapter: it owns no facts; an injected owner port must
# atomically persist objective + run snapshot. This closes the repository-side
# callsite while preserving the external production-writer boundary.
# ---------------------------------------------------------------------------
write("codex-rs/hepta-intelligence/src/objective_publication.rs", r'''use std::error::Error as StdError;
use std::fmt;

use codex_hepta_objective::ObjectiveAdmissionContextV1;
use codex_hepta_objective::ObjectiveAdmissionError;
use codex_hepta_objective::ObjectiveAdmissionProfileV1;
use codex_hepta_objective::ObjectiveAdmissionReceiptV1;
use codex_hepta_objective::ObjectiveCompileReceipt;
use codex_hepta_objective::ObjectiveConflictReceipt;
use codex_hepta_objective::ObjectiveSourceEnvelopeV1;
use codex_hepta_objective::ObjectiveWireError;
use codex_hepta_objective::RunStartSnapshotV1;
use codex_hepta_objective::admit_and_compile_objective_v1;
use codex_hepta_objective::encode_objective_compile_receipt_v1;
use codex_hepta_types::Digest32;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectivePublicationRecordV1 {
    pub admission: ObjectiveAdmissionReceiptV1,
    pub objective: ObjectiveCompileReceipt,
    pub run_snapshot: RunStartSnapshotV1,
    pub canonical_objective_bytes: Vec<u8>,
    pub publication_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ObjectivePublicationWriteV1 {
    Created,
    IdenticalReplay,
    Conflict { existing_publication_digest: Digest32 },
}

/// Port owned by the durable product host. `intelligence.control` remains an
/// ephemeral façade and cannot fabricate persistence; one call must atomically
/// commit the complete record or commit nothing.
pub trait ObjectivePublicationPortV1 {
    type Error: StdError;

    fn publish_atomic(
        &mut self,
        record: &ObjectivePublicationRecordV1,
    ) -> Result<ObjectivePublicationWriteV1, Self::Error>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ObjectiveCallerOutcomeV1 {
    Published {
        record: ObjectivePublicationRecordV1,
        write: ObjectivePublicationWriteV1,
    },
    ObjectiveConflict {
        admission: ObjectiveAdmissionReceiptV1,
        conflict: ObjectiveConflictReceipt,
    },
    PublicationConflict {
        record: ObjectivePublicationRecordV1,
        existing_publication_digest: Digest32,
    },
}

#[derive(Debug)]
pub enum ObjectiveCallerError {
    Admission(ObjectiveAdmissionError),
    CanonicalOutput(ObjectiveWireError),
    MissingRunSnapshot,
    Publication(String),
}

impl fmt::Display for ObjectiveCallerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Admission(error) => error.fmt(formatter),
            Self::CanonicalOutput(error) => error.fmt(formatter),
            Self::MissingRunSnapshot => formatter.write_str("compiled objective is missing RunStartSnapshotV1"),
            Self::Publication(error) => write!(formatter, "objective publication failed: {error}"),
        }
    }
}

impl StdError for ObjectiveCallerError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Admission(error) => Some(error),
            Self::CanonicalOutput(error) => Some(error),
            Self::MissingRunSnapshot | Self::Publication(_) => None,
        }
    }
}

pub fn admit_compile_and_publish_objective_v1<P: ObjectivePublicationPortV1>(
    port: &mut P,
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
) -> Result<ObjectiveCallerOutcomeV1, ObjectiveCallerError> {
    let outcome = admit_and_compile_objective_v1(envelope, profile, context)
        .map_err(ObjectiveCallerError::Admission)?;
    let admission = outcome.receipt;
    let objective = match outcome.compile_result {
        Ok(objective) => objective,
        Err(conflict) => {
            return Ok(ObjectiveCallerOutcomeV1::ObjectiveConflict {
                admission,
                conflict,
            });
        }
    };
    let run_snapshot = outcome
        .run_snapshot
        .ok_or(ObjectiveCallerError::MissingRunSnapshot)?;
    if run_snapshot.objective_digest != objective.objective.semantic_digest
        || run_snapshot.profile_digest != admission.profile_digest
        || run_snapshot.intent_digest != admission.intent_digest
        || run_snapshot.admitted_source_digest != admission.admitted_source_digest
    {
        return Err(ObjectiveCallerError::MissingRunSnapshot);
    }
    let canonical_objective_bytes = encode_objective_compile_receipt_v1(&objective)
        .map_err(ObjectiveCallerError::CanonicalOutput)?;
    let mut bytes = b"hepta.objective.publication.v1".to_vec();
    bytes.extend_from_slice(admission.admitted_source_digest.as_array());
    bytes.extend_from_slice(objective.objective.semantic_digest.as_array());
    bytes.extend_from_slice(run_snapshot.snapshot_digest.as_array());
    bytes.extend_from_slice(&canonical_objective_bytes);
    let record = ObjectivePublicationRecordV1 {
        admission,
        objective,
        run_snapshot,
        canonical_objective_bytes,
        publication_digest: Digest32::of_bytes(&bytes),
    };
    let write = port
        .publish_atomic(&record)
        .map_err(|error| ObjectiveCallerError::Publication(error.to_string()))?;
    match write {
        ObjectivePublicationWriteV1::Conflict {
            existing_publication_digest,
        } => Ok(ObjectiveCallerOutcomeV1::PublicationConflict {
            record,
            existing_publication_digest,
        }),
        write => Ok(ObjectiveCallerOutcomeV1::Published { record, write }),
    }
}
''')
replace_once(
    "codex-rs/hepta-intelligence/src/lib.rs",
    "mod vertical;\n",
    "mod objective_publication;\nmod vertical;\n",
)
replace_once(
    "codex-rs/hepta-intelligence/src/lib.rs",
    "pub use vertical::ReadOnlyUtilityContribution;",
    "pub use objective_publication::ObjectiveCallerError;\npub use objective_publication::ObjectiveCallerOutcomeV1;\npub use objective_publication::ObjectivePublicationPortV1;\npub use objective_publication::ObjectivePublicationRecordV1;\npub use objective_publication::ObjectivePublicationWriteV1;\npub use objective_publication::admit_compile_and_publish_objective_v1;\npub use vertical::ReadOnlyUtilityContribution;",
)

# ---------------------------------------------------------------------------
# ExplicitAbstain is a successful vertical outcome, not an error.
# ---------------------------------------------------------------------------
replace_once(
    "codex-rs/hepta-intelligence/src/vertical.rs",
    "use codex_hepta_objective::ObjectiveSourceEnvelopeV1;",
    "use codex_hepta_objective::ObjectiveSourceEnvelopeV1;\nuse codex_hepta_objective::RunStartSnapshotV1;",
)
replace_once(
    "codex-rs/hepta-intelligence/src/vertical.rs",
    '''pub struct ReadOnlyVerticalReceipt {
    pub objective_admission: ObjectiveAdmissionReceiptV1,
    pub objective: ObjectiveCompileReceipt,''',
    '''pub struct ReadOnlyVerticalReceipt {
    pub objective_admission: ObjectiveAdmissionReceiptV1,
    pub objective: ObjectiveCompileReceipt,''',
)
# Insert the new outcome types immediately after the normal receipt.
replace_once(
    "codex-rs/hepta-intelligence/src/vertical.rs",
    '''    pub authority: AuthorityPosture,
}

#[derive(Debug)]
pub enum ReadOnlyVerticalError {''',
    '''    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReadOnlyVerticalAbstainReceiptV1 {
    pub objective_admission: ObjectiveAdmissionReceiptV1,
    pub objective: ObjectiveCompileReceipt,
    pub run_snapshot: RunStartSnapshotV1,
    pub vertical_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ReadOnlyVerticalOutcomeV1 {
    Evaluated(ReadOnlyVerticalReceipt),
    ExplicitAbstain(ReadOnlyVerticalAbstainReceiptV1),
}

#[derive(Debug)]
pub enum ReadOnlyVerticalError {''',
)
replace_once(
    "codex-rs/hepta-intelligence/src/vertical.rs",
    "    ObjectiveConflict(Digest32),\n    ObjectiveExplicitAbstain,",
    "    ObjectiveConflict(Digest32),\n    MissingObjectiveRunSnapshot,",
)
replace_once(
    "codex-rs/hepta-intelligence/src/vertical.rs",
    "            Self::ObjectiveConflict(_)\n            | Self::ObjectiveExplicitAbstain\n            | Self::AuthorityEscalation",
    "            Self::ObjectiveConflict(_)\n            | Self::MissingObjectiveRunSnapshot\n            | Self::AuthorityEscalation",
)
replace_once(
    "codex-rs/hepta-intelligence/src/vertical.rs",
    ") -> Result<ReadOnlyVerticalReceipt, ReadOnlyVerticalError> {",
    ") -> Result<ReadOnlyVerticalOutcomeV1, ReadOnlyVerticalError> {",
)
# Replace the objective extraction block.
replace_once(
    "codex-rs/hepta-intelligence/src/vertical.rs",
    '''    let objective_admission = objective_outcome.receipt;
    let objective = objective_outcome
        .compile_result
        .map_err(|conflict| ReadOnlyVerticalError::ObjectiveConflict(conflict.conflict_digest))?;
    if objective.disposition != CompileDisposition::Compiled {
        return Err(ReadOnlyVerticalError::ObjectiveExplicitAbstain);
    }
    let objective_digest = objective.objective.semantic_digest;''',
    '''    let objective_admission = objective_outcome.receipt;
    let objective = objective_outcome
        .compile_result
        .map_err(|conflict| ReadOnlyVerticalError::ObjectiveConflict(conflict.conflict_digest))?;
    let run_snapshot = objective_outcome
        .run_snapshot
        .ok_or(ReadOnlyVerticalError::MissingObjectiveRunSnapshot)?;
    if objective.disposition == CompileDisposition::ExplicitAbstain {
        let mut bytes = b"hepta.intelligence.read-only-vertical.abstain.v1".to_vec();
        bytes.extend_from_slice(objective_admission.profile_digest.as_array());
        bytes.extend_from_slice(objective_admission.intent_digest.as_array());
        bytes.extend_from_slice(objective.objective.semantic_digest.as_array());
        bytes.extend_from_slice(run_snapshot.snapshot_digest.as_array());
        return Ok(ReadOnlyVerticalOutcomeV1::ExplicitAbstain(
            ReadOnlyVerticalAbstainReceiptV1 {
                objective_admission,
                objective,
                run_snapshot,
                vertical_digest: Digest32::of_bytes(&bytes),
                authority: AuthorityPosture::DENY_ALL,
            },
        ));
    }
    let objective_digest = objective.objective.semantic_digest;''',
)
replace_once(
    "codex-rs/hepta-intelligence/src/vertical.rs",
    "    Ok(ReadOnlyVerticalReceipt {",
    "    Ok(ReadOnlyVerticalOutcomeV1::Evaluated(ReadOnlyVerticalReceipt {",
)
replace_once(
    "codex-rs/hepta-intelligence/src/vertical.rs",
    "        authority: AuthorityPosture::DENY_ALL,\n    })\n}",
    "        authority: AuthorityPosture::DENY_ALL,\n    }))\n}",
)

replace_once(
    "codex-rs/hepta-intelligence/src/lib.rs",
    "pub use vertical::ReadOnlyVerticalError;\npub use vertical::ReadOnlyVerticalReceipt;",
    "pub use vertical::ReadOnlyVerticalAbstainReceiptV1;\npub use vertical::ReadOnlyVerticalError;\npub use vertical::ReadOnlyVerticalOutcomeV1;\npub use vertical::ReadOnlyVerticalReceipt;",
)

# Positive vertical tests unwrap the new outcome. Error tests are unchanged.
replace_once(
    "codex-rs/hepta-intelligence/src/vertical_tests.rs",
    "use crate::ReadOnlyVerticalError;\nuse crate::ReadOnlyVerticalRequest;",
    "use crate::ReadOnlyVerticalError;\nuse crate::ReadOnlyVerticalOutcomeV1;\nuse crate::ReadOnlyVerticalRequest;",
)
replace_once(
    "codex-rs/hepta-intelligence/src/vertical_tests.rs",
    '''fn id(value: &str) -> StableId {
    must(StableId::new(value.to_string()))
}''',
    '''fn evaluated(
    result: Result<crate::ReadOnlyVerticalOutcomeV1, crate::ReadOnlyVerticalError>,
) -> crate::ReadOnlyVerticalReceipt {
    match must(result) {
        ReadOnlyVerticalOutcomeV1::Evaluated(receipt) => receipt,
        ReadOnlyVerticalOutcomeV1::ExplicitAbstain(receipt) => {
            panic!("unexpected explicit abstain: {receipt:?}")
        }
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value.to_string()))
}''',
)
text = read("codex-rs/hepta-intelligence/src/vertical_tests.rs")
text = text.replace(
    "must(run_read_only_vertical(vertical_request()))",
    "evaluated(run_read_only_vertical(vertical_request()))",
)
text = text.replace(
    "must(run_read_only_vertical(first))",
    "evaluated(run_read_only_vertical(first))",
)
text = text.replace(
    "must(run_read_only_vertical(second))",
    "evaluated(run_read_only_vertical(second))",
)
write("codex-rs/hepta-intelligence/src/vertical_tests.rs", text)

with (ROOT / "codex-rs/hepta-intelligence/src/vertical_tests.rs").open("a", encoding="utf-8") as handle:
    handle.write(r'''

#[test]
fn vertical_explicit_abstain_is_a_successful_non_error_outcome() {
    let mut request = vertical_request();
    request.objective_envelope.structured_intent.legal_action_classes.clear();
    request
        .objective_envelope
        .structured_intent
        .confirmation_action_classes
        .clear();
    request.objective_envelope.intent_digest = must(canonical_objective_intent_digest_v1(
        &request.objective_envelope,
    ));
    let outcome = must(run_read_only_vertical(request));
    let ReadOnlyVerticalOutcomeV1::ExplicitAbstain(receipt) = outcome else {
        panic!("expected explicit abstain outcome");
    };
    assert_eq!(
        receipt.objective.disposition,
        codex_hepta_objective::CompileDisposition::ExplicitAbstain
    );
    assert!(!receipt.authority.grants_any());
    assert_eq!(
        receipt.run_snapshot.objective_digest,
        receipt.objective.objective.semantic_digest
    );
}

#[derive(Debug)]
struct TestPublicationError;

impl std::fmt::Display for TestPublicationError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str("test publication error")
    }
}

impl std::error::Error for TestPublicationError {}

#[derive(Default)]
struct TestPublicationPort {
    record: Option<crate::ObjectivePublicationRecordV1>,
}

impl crate::ObjectivePublicationPortV1 for TestPublicationPort {
    type Error = TestPublicationError;

    fn publish_atomic(
        &mut self,
        record: &crate::ObjectivePublicationRecordV1,
    ) -> Result<crate::ObjectivePublicationWriteV1, Self::Error> {
        match &self.record {
            None => {
                self.record = Some(record.clone());
                Ok(crate::ObjectivePublicationWriteV1::Created)
            }
            Some(existing) if existing.publication_digest == record.publication_digest => {
                Ok(crate::ObjectivePublicationWriteV1::IdenticalReplay)
            }
            Some(existing) => Ok(crate::ObjectivePublicationWriteV1::Conflict {
                existing_publication_digest: existing.publication_digest,
            }),
        }
    }
}

#[test]
fn objective_caller_publishes_objective_and_snapshot_atomically_and_replays_idempotently() {
    let profile = objective_profile();
    let envelope = objective_envelope();
    let context = objective_context(&profile, &envelope);
    let mut port = TestPublicationPort::default();
    let first = must(crate::admit_compile_and_publish_objective_v1(
        &mut port, &envelope, &profile, &context,
    ));
    let crate::ObjectiveCallerOutcomeV1::Published { record, write } = first else {
        panic!("expected publication");
    };
    assert_eq!(write, crate::ObjectivePublicationWriteV1::Created);
    assert!(!record.canonical_objective_bytes.is_empty());
    assert_eq!(
        record.run_snapshot.objective_digest,
        record.objective.objective.semantic_digest
    );
    let second = must(crate::admit_compile_and_publish_objective_v1(
        &mut port, &envelope, &profile, &context,
    ));
    assert!(matches!(
        second,
        crate::ObjectiveCallerOutcomeV1::Published {
            write: crate::ObjectivePublicationWriteV1::IdenticalReplay,
            ..
        }
    ));
    assert_eq!(port.record.as_ref().map(|value| value.publication_digest), Some(record.publication_digest));
}
''')

# ---------------------------------------------------------------------------
# Split OBJ-E007 into retryable feasibility availability and non-retryable
# locale/temporal input failures.
# ---------------------------------------------------------------------------
registry = load_json("docs/contracts/OBJECTIVE_ERRORS.json")
errors = registry["errors"]
e007 = next(row for row in errors if row["code"] == "OBJ-E007")
e007["stableMeaning"] = "bounded feasibility budget is unavailable"
e007["outcomeClass"] = "unavailable"
e007["retryable"] = True
e007["rustVariants"] = ["ObjectiveError::FeasibilityBudgetExhausted"]
errors[:] = [row for row in errors if row["code"] not in {"OBJ-E010", "OBJ-E011"}]
errors.extend([
    {
        "code": "OBJ-E010",
        "stableMeaning": "locale is not permitted by the selected admission profile",
        "outcomeClass": "rejected",
        "retryable": False,
        "rustVariants": ["ObjectiveAdmissionError::LocaleNotAllowed"],
    },
    {
        "code": "OBJ-E011",
        "stableMeaning": "objective observation or deadline is stale, future, missing, inconsistent or expired",
        "outcomeClass": "rejected",
        "retryable": False,
        "rustVariants": [
            "ObjectiveAdmissionError::SourceFromFuture",
            "ObjectiveAdmissionError::SourceStale",
            "ObjectiveAdmissionError::DeadlineMissing",
            "ObjectiveAdmissionError::DeadlineBeforeObservation",
            "ObjectiveAdmissionError::DeadlineExpired",
        ],
    },
])
errors.sort(key=lambda row: int(row["code"].split("E")[1]))
write_json("docs/contracts/OBJECTIVE_ERRORS.json", registry)

# ---------------------------------------------------------------------------
# Protocol registry: rich operand shape, true source ceilings, zero-action abstain.
# ---------------------------------------------------------------------------
protocols = load_json("docs/readiness/PROTOCOLS.json")
objective_protocol = next(row for row in protocols["protocols"] if row["id"] == "ObjectiveSourceEnvelopeV1")
structured = next(field for field in objective_protocol["fields"] if field["name"] == "structuredIntent")
props = structured["properties"]
legal = next(field for field in props if field["name"] == "legalActionClasses")
legal["minItems"] = 0
constraints = next(field for field in props if field["name"] == "constraints")
constraints["maxItems"] = 246
item = constraints["items"]
item["maxProperties"] = max(item.get("maxProperties", 0), 8)
item_props = item["properties"]
comparator = next(field for field in item_props if field["name"] == "comparator")
for value in ["require_action", "forbid_action", "implies_action"]:
    if value not in comparator["values"]:
        comparator["values"].append(value)
if not any(field["name"] == "setValues" for field in item_props):
    item_props.append({
        "name": "setValues",
        "type": "bounded_array",
        "required": False,
        "maxBytes": 16384,
        "minItems": 0,
        "maxItems": 128,
        "uniqueItems": True,
        "items": {"type": "utf8", "maxBytes": 128},
    })
if not any(field["name"] == "implicationTargetActionClass" for field in item_props):
    item_props.append({
        "name": "implicationTargetActionClass",
        "type": "utf8",
        "required": False,
        "maxBytes": 128,
    })
for invariant in [
    "success_terminal_evidence_total_lte_128",
    "source_constraint_slots_reserve_10_generated_resource_risk_atoms",
    "enum_and_action_predicate_operands_are_shape_checked",
    "empty_legal_action_set_compiles_to_intrinsic_abstain",
]:
    if invariant not in objective_protocol["invariants"]:
        objective_protocol["invariants"].append(invariant)
write_json("docs/readiness/PROTOCOLS.json", protocols)

# ---------------------------------------------------------------------------
# Execution and qualification docs describe the now-real call graph and bounds.
# ---------------------------------------------------------------------------
path = "docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md"
text = read(path)
text = text.replace(
    "-> normalize and map every represented semantic field\n-> check_feasibility_v1\n-> compile",
    "-> normalize and map every represented semantic field\n-> build RegisteredGrammarV1 + ConstraintAtomV1\n-> check_feasibility_v1\n-> compile_prevalidated legacy projection\n-> encode_objective_compile_receipt_v1",
)
text = text.replace(
    "The canonical IR contains no raw credentials, unrestricted external text, hidden model state or executable code.",
    "The canonical IR contains no raw credentials, unrestricted external text, hidden model state or executable code. Constraint operands are explicit: scalar comparators use `boundQ32`; `in`/`not_in` use bounded `setValues`; `implies_action` uses one `implicationTargetActionClass`; require/forbid action predicates carry no additional operand.",
)
text = text.replace(
    "Pilot ceilings are `<=256` constraints, `<=128` success predicates, `<=127` caller actions when abstain is implicit, `<=128` compiled actions including abstain, `<=64` soft dimensions and `<=257` conflict-oracle calls.",
    "Pilot ceilings are `<=246` source constraints plus exactly 10 generated resource/risk atoms (`<=256` feasibility atoms total), `successPredicates + terminalConditions + evidenceRequirements <=128`, `<=127` caller actions when abstain is implicit, `<=128` compiled actions including abstain, `<=64` soft dimensions and `<=257` conflict-oracle calls.",
)
text = text.replace(
    "| `OBJ-E007` | freshness, deadline or feasibility budget unavailable | unavailable |\n| `OBJ-E008` | terminality or durable semantic-identity conflict | conflict |\n| `OBJ-E009` | untrusted evidence attempts authority escalation | security rejected |",
    "| `OBJ-E007` | bounded feasibility budget unavailable | unavailable / retryable |\n| `OBJ-E008` | terminality or durable semantic-identity conflict | conflict |\n| `OBJ-E009` | untrusted evidence attempts authority escalation | security rejected |\n| `OBJ-E010` | locale not permitted by selected profile | rejected / non-retryable |\n| `OBJ-E011` | stale/future/missing/inconsistent/expired observation or deadline | rejected / non-retryable |",
)
text = text.replace(
    "Admission profiles are bounded to 256 constraint mappings, 128 predicate mappings, 128 action mappings, 64 soft dimensions, 128 evidence mappings, 64 abstention rules and 256 KiB of encoded profile semantics; risk and rollback levels must be monotone.",
    "Admission profiles are bounded to 246 source-constraint mappings (reserving 10 generated resource/risk atoms), 128 predicate mappings, 128 action mappings, 64 soft dimensions, 128 evidence mappings, 64 abstention rules and 256 KiB of the exact canonical profile semantic bytes used for its digest; risk and rollback levels must be monotone.",
)
text = text.replace(
    "The compiler owns no domain-fact store. The owning caller persists the immutable `ObjectiveFunctionV1`, `RunStartSnapshotV1` and admission/compile receipts.",
    "The compiler owns no domain-fact store. `intelligence.control::admit_compile_and_publish_objective_v1` is the repository-side authenticated caller adapter; it hands one `ObjectivePublicationRecordV1` containing canonical `ObjectiveCompileReceiptV1` bytes plus `RunStartSnapshotV1` to an injected owner `ObjectivePublicationPortV1` for one atomic durable write. The product host/store remains separately selected and qualified.",
)
write(path, text)

path = "qualification/module-execution-dossiers/detail/objective.compiler.md"
text = read(path)
text = text.replace(
    "admit_and_compile_objective_v1(envelope, profile, authenticated_context)\ncheck_feasibility_v1(grammar, atoms, budget)\ncompile(native_envelope)",
    "admit_and_compile_objective_v1(envelope, profile, authenticated_context)\nbuild RegisteredGrammarV1 + ConstraintAtomV1\ncheck_feasibility_v1(grammar, atoms, budget)\ncompile_prevalidated(native_projection)\nencode_objective_compile_receipt_v1(receipt)",
)
text = text.replace(
    "Admission validates source authentication, principal scope, schema, normalization, profile, source and intent digests before mapping every represented field. Unknown or unrepresentable semantics fail closed.",
    "Admission validates source authentication, principal scope, schema, normalization, profile, source and intent digests before mapping every represented field. Rich scalar `ne/lt/gt`, finite-enum include/exclude and positive action require/forbid/implies atoms enter the registered feasibility engine directly; the legacy scalar projection is compiled only after rich feasibility succeeds. Unknown or unrepresentable semantics fail closed.",
)
text = text.replace(
    "- **Remaining work:** Authenticate actual source context and compose the production caller; conflict-oracle budgets and target latency need separate measurements from ordinary compilation.",
    "- **Remaining work:** Bind the implemented `ObjectivePublicationPortV1` caller adapter to the selected authenticated product-host owner store; conflict-oracle budgets and target latency need separate named-host measurements. Independent acceptance, activation and release remain external gates.",
)
write(path, text)

# Semantic conformance verifier must follow the exact canonical-byte bound helper.
replace_once(
    "scripts/hepta-lane-d-semantic-conformance.py",
    '        "profile_encoded_size",',
    '        "profile_semantic_bytes",',
)

# ---------------------------------------------------------------------------
# Implementation maps: add the real encoder/caller operations, but do not
# falsely claim production activation or independent acceptance.
# ---------------------------------------------------------------------------
obj_map = load_json("docs/modules/objective.compiler/IMPLEMENTATION_MAP.json")
if not any(op["operation"] == "encode_objective_compile_receipt_v1" for op in obj_map["operations"]):
    obj_map["operations"].append({
        "operation": "encode_objective_compile_receipt_v1",
        "nativeSymbol": "codex_hepta_objective::encode_objective_compile_receipt_v1",
        "sourcePath": "codex-rs/hepta-objective/src/canonical_output.rs",
        "inputs": ["ObjectiveCompileReceiptV1"],
        "outputs": ["bounded canonical JSON bytes"],
        "state": "source_implemented_not_product_composed",
        "authority": "none",
        "tests": [{
            "path": "codex-rs/hepta-objective/src/objective_admission_tests.rs",
            "symbol": "admitted_objective_has_deterministic_bounded_canonical_output",
        }],
        "designOperation": "encode_objective_compile_receipt_v1",
        "mappingClass": "owner_native",
        "delegatedCallees": [],
        "sourcePathExists": True,
    })
obj_map["productCallerState"] = "caller_adapter_implemented_host_not_composed"
obj_map["repositoryControlledGaps"] = [
    "Bind ObjectivePublicationPortV1 to the authenticated product-host owner store.",
    "Run exact-head and deterministic synthetic-merge tests before changing the production claim boundary.",
]
write_json("docs/modules/objective.compiler/IMPLEMENTATION_MAP.json", obj_map)

intel_map = load_json("docs/modules/intelligence.control/IMPLEMENTATION_MAP.json")
if not any(op["operation"] == "admit_compile_and_publish_objective_v1" for op in intel_map["operations"]):
    intel_map["operations"].append({
        "operation": "admit_compile_and_publish_objective_v1",
        "nativeSymbol": "admit_compile_and_publish_objective_v1",
        "sourcePath": "codex-rs/hepta-intelligence/src/objective_publication.rs",
        "state": "source_implemented_not_product_composed",
        "authority": "none",
        "tests": [{
            "path": "codex-rs/hepta-intelligence/src/vertical_tests.rs",
            "symbol": "objective_caller_publishes_objective_and_snapshot_atomically_and_replays_idempotently",
        }],
        "sourcePathExists": True,
        "designOperation": "admit_compile_and_publish_objective_v1",
        "mappingClass": "owner_native",
        "delegatedCallees": ["objective.compiler"],
    })
intel_map["productCallerState"] = "objective_publication_adapter_implemented_host_not_composed"
intel_map["repositoryControlledGaps"] = [
    "Bind ObjectivePublicationPortV1 to the authenticated owner store selected by the product host.",
    "Run exact-head and deterministic synthetic-merge tests before changing the production claim boundary.",
]
write_json("docs/modules/intelligence.control/IMPLEMENTATION_MAP.json", intel_map)

maturity = load_json("docs/readiness/LANE_D_MATURITY.json")
obj = next(row for row in maturity["modules"] if row["module"] == "objective.compiler")
obj["dimensions"]["richFeasibilityAdmission"] = {
    "state": "candidate_implemented",
    "evidence": [
        "admission_feasibility::evaluate",
        "rich_enum_and_action_implication_are_feasible_on_the_admission_path",
    ],
}
obj["dimensions"]["canonicalOutputEncoding"] = {
    "state": "candidate_implemented",
    "evidence": [
        "encode_objective_compile_receipt_v1",
        "admitted_objective_has_deterministic_bounded_canonical_output",
    ],
}
# Exact-head/product/activation truth boundary intentionally remains pending/not established.
write_json("docs/readiness/LANE_D_MATURITY.json", maturity)

# Intelligence guide records the adapter without assigning it durable ownership.
path = "docs/modules/intelligence.control/TECHNICAL.md"
text = read(path)
needle = "The registered primary source is [codex-rs/hepta-intelligence/src/vertical.rs]"
if needle in text and "ObjectivePublicationPortV1" not in text:
    text = text.replace(
        needle,
        "The objective publication boundary is implemented in `codex-rs/hepta-intelligence/src/objective_publication.rs`: `admit_compile_and_publish_objective_v1` consumes authenticated objective admission and hands an immutable objective/run-snapshot bundle to an injected `ObjectivePublicationPortV1`. The façade still owns no durable fact and cannot self-assert that the product host committed the bundle.\n\n" + needle,
        1,
    )
write(path, text)

print("objective compiler stage2 closure applied")
