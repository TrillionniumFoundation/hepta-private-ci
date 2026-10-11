use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

use crate::ObjectiveSourceEnvelopeV1;

const NATIVE_MAX_CONSTRAINTS: usize = 256;
const GENERATED_RESOURCE_CONSTRAINTS: usize = 6;
const GENERATED_RISK_CONSTRAINTS: usize = 4;
const MAX_SOURCE_CONSTRAINTS: usize =
    NATIVE_MAX_CONSTRAINTS - GENERATED_RESOURCE_CONSTRAINTS - GENERATED_RISK_CONSTRAINTS;
const MAX_AGGREGATE_SUCCESS_PREDICATES: usize = 128;
const MAX_SOURCE_ACTIONS: usize = 128;

/// Structural errors contain field paths/counts, never unrestricted source text.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ObjectiveStructureError {
    CollectionCount {
        field: &'static str,
        actual: usize,
        minimum: usize,
        maximum: usize,
    },
    TextBytes {
        field: &'static str,
        actual: usize,
        maximum: usize,
    },
    DuplicateSemanticKey {
        field: &'static str,
        index: usize,
    },
}

impl fmt::Display for ObjectiveStructureError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::CollectionCount {
                field,
                actual,
                minimum,
                maximum,
            } => {
                write!(
                    formatter,
                    "{field} has {actual} items; expected {minimum}..={maximum}"
                )
            }
            Self::TextBytes {
                field,
                actual,
                maximum,
            } => {
                write!(
                    formatter,
                    "{field} has {actual} text bytes; maximum is {maximum}"
                )
            }
            Self::DuplicateSemanticKey { field, index } => {
                write!(formatter, "{field} repeats a semantic key at index {index}")
            }
        }
    }
}

impl Error for ObjectiveStructureError {}

impl ObjectiveSourceEnvelopeV1 {
    /// Check declared raw UTF-8 field byte limits, array count bounds and
    /// within-array semantic-key uniqueness without changing any source value.
    ///
    /// Structural ceilings are admission-safe, not merely per-field maxima:
    /// source constraints reserve ten native slots for generated resource/risk
    /// constraints and success/terminal/evidence predicates share the native
    /// 128-slot aggregate. Source actions may contain up to 128 entries because
    /// one can be an explicit intrinsic `abstain`; native compile enforces the
    /// 127-entry ceiling only when it must inject abstain itself.
    ///
    /// This is deliberately not wire validation: JSON escaping/framing and
    /// aggregate encoded-byte limits, duplicate/unknown JSON fields, ID/time
    /// syntax, NFC, canonical ordering, digest bindings, profile semantics,
    /// freshness and source authority are not established here. No unsupported
    /// operator or trust label is rewritten. Cross-array action references stay
    /// in semantic admission so their existing error taxonomy is preserved.
    pub fn validate_structure(&self) -> Result<(), ObjectiveStructureError> {
        text_bytes(&self.request_id, "requestId", /*maximum*/ 128)?;
        text_bytes(&self.locale, "locale", /*maximum*/ 32)?;
        text_bytes(&self.observed_at, "observedAt", /*maximum*/ 64)?;
        if let Some(deadline) = &self.deadline {
            text_bytes(deadline, "deadline", /*maximum*/ 64)?;
        }
        let intent = &self.structured_intent;
        for (predicates, field) in [
            (&intent.success_predicates, "successPredicates"),
            (&intent.terminal_conditions, "terminalConditions"),
        ] {
            collection(
                predicates,
                field,
                /*minimum*/ 1,
                /*maximum*/ 128,
                |value| &value.predicate_id,
            )?;
            for predicate in predicates {
                text_bytes(&predicate.predicate_id, "predicateId", /*maximum*/ 128)?;
                text_bytes(&predicate.unit, "predicate.unit", /*maximum*/ 64)?;
                text_bytes(
                    &predicate.evidence_source_id,
                    "predicate.evidenceSourceId",
                    /*maximum*/ 256,
                )?;
            }
        }
        for (actions, field, minimum, maximum) in [
            (
                &intent.legal_action_classes,
                "legalActionClasses",
                0,
                MAX_SOURCE_ACTIONS,
            ),
            (
                &intent.forbidden_action_classes,
                "forbiddenActionClasses",
                0,
                MAX_SOURCE_ACTIONS,
            ),
            (
                &intent.confirmation_action_classes,
                "confirmationActionClasses",
                0,
                MAX_SOURCE_ACTIONS,
            ),
        ] {
            collection(actions, field, minimum, maximum, String::as_str)?;
            for action in actions {
                text_bytes(action, field, /*maximum*/ 128)?;
            }
        }
        collection(
            &intent.constraints,
            "constraints",
            /*minimum*/ 1,
            /*maximum*/ MAX_SOURCE_CONSTRAINTS,
            |value| &value.constraint_id,
        )?;
        for constraint in &intent.constraints {
            text_bytes(
                &constraint.constraint_id,
                "constraintId",
                /*maximum*/ 128,
            )?;
            text_bytes(&constraint.unit, "constraint.unit", /*maximum*/ 64)?;
            text_bytes(
                &constraint.evidence_source_id,
                "constraint.evidenceSourceId",
                /*maximum*/ 256,
            )?;
        }
        collection(
            &intent.soft_dimensions,
            "softDimensions",
            /*minimum*/ 0,
            /*maximum*/ 64,
            |value| &value.dimension_id,
        )?;
        for dimension in &intent.soft_dimensions {
            text_bytes(&dimension.dimension_id, "dimensionId", /*maximum*/ 128)?;
            text_bytes(&dimension.unit, "dimension.unit", /*maximum*/ 64)?;
        }
        collection(
            &intent.evidence_requirements,
            "evidenceRequirements",
            /*minimum*/ 1,
            /*maximum*/ 128,
            |value| &value.requirement_id,
        )?;
        for requirement in &intent.evidence_requirements {
            text_bytes(
                &requirement.requirement_id,
                "requirementId",
                /*maximum*/ 128,
            )?;
            text_bytes(
                &requirement.evidence_source_id,
                "requirement.evidenceSourceId",
                /*maximum*/ 256,
            )?;
        }
        aggregate_count(
            "successPredicates+terminalConditions+evidenceRequirements",
            intent
                .success_predicates
                .len()
                .saturating_add(intent.terminal_conditions.len())
                .saturating_add(intent.evidence_requirements.len()),
            MAX_AGGREGATE_SUCCESS_PREDICATES,
        )?;
        text_bytes(
            &intent.risk.abstention_rule,
            "risk.abstentionRule",
            /*maximum*/ 512,
        )
    }
}

fn aggregate_count(
    field: &'static str,
    actual: usize,
    maximum: usize,
) -> Result<(), ObjectiveStructureError> {
    if actual > maximum {
        return Err(ObjectiveStructureError::CollectionCount {
            field,
            actual,
            minimum: 0,
            maximum,
        });
    }
    Ok(())
}

fn text_bytes(
    text: &str,
    field: &'static str,
    maximum: usize,
) -> Result<(), ObjectiveStructureError> {
    if text.len() > maximum {
        return Err(ObjectiveStructureError::TextBytes {
            field,
            actual: text.len(),
            maximum,
        });
    }
    Ok(())
}

fn collection<T>(
    values: &[T],
    field: &'static str,
    minimum: usize,
    maximum: usize,
    key: impl Fn(&T) -> &str,
) -> Result<(), ObjectiveStructureError> {
    if !(minimum..=maximum).contains(&values.len()) {
        return Err(ObjectiveStructureError::CollectionCount {
            field,
            actual: values.len(),
            minimum,
            maximum,
        });
    }
    let mut keys = BTreeSet::new();
    for (index, value) in values.iter().enumerate() {
        let key = key(value);
        // Every semantic key in this grammar has a 128-byte ceiling. Check it
        // before ordered comparisons so invalid large keys do not expand work.
        text_bytes(key, field, /*maximum*/ 128)?;
        if !keys.insert(key) {
            return Err(ObjectiveStructureError::DuplicateSemanticKey { field, index });
        }
    }
    Ok(())
}
