use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::ActionClass;
use crate::CompileDisposition;
use crate::ConfirmationPolicy;
use crate::Constraint;
use crate::ObjectiveCompileReceipt;
use crate::ObjectiveConflictReceipt;
use crate::ObjectiveError;
use crate::ObjectiveFunction;
use crate::ObjectiveSourceEnvelope;
use crate::SoftPreference;
use crate::SuccessPredicate;

const MAX_CONSTRAINTS: usize = 256;
const MAX_SUCCESS_PREDICATES: usize = 128;
const MAX_ACTIONS: usize = 128;
const MAX_SOFT_DIMENSIONS: usize = 64;
const OBJECTIVE_DIGEST_DOMAIN: &[u8] = b"hepta.objective.v1";
const CONFLICT_DIGEST_DOMAIN: &[u8] = b"hepta.objective.conflict.v1";
const CONSTRAINT_DIGEST_DOMAIN: &[u8] = b"hepta.objective.constraints.v1";

/// Compiles a typed source envelope into an immutable objective or an explicit
/// minimal conflict receipt.
pub fn compile(
    mut source: ObjectiveSourceEnvelope,
) -> Result<Result<ObjectiveCompileReceipt, ObjectiveConflictReceipt>, ObjectiveError> {
    validate_source(&source)?;

    source.constraints.sort_by(constraint_order);
    source.success_predicates.sort_by(predicate_order);
    source.allowed_actions.sort_by(action_order);
    source.forbidden_actions.sort();
    source.forbidden_actions.dedup();
    source.soft_preferences.sort_by(preference_order);

    if let Some(conflicting_ids) = crate::scalar_adapter::scalar_conflict(&source)? {
        return Ok(Err(conflict_receipt(&source, conflicting_ids)));
    }

    let forbidden: BTreeSet<_> = source.forbidden_actions.iter().cloned().collect();
    let mut removed_action_ids = Vec::new();
    let mut legal_actions = Vec::new();
    let mut requested_forbidden = Vec::new();
    let allowed_actions = std::mem::take(&mut source.allowed_actions);
    for action in allowed_actions {
        if forbidden.contains(&action.id) {
            removed_action_ids.push(action.id.clone());
            requested_forbidden.push(action.id);
        } else {
            legal_actions.push(action);
        }
    }
    if !requested_forbidden.is_empty() {
        return Ok(Err(conflict_receipt(&source, requested_forbidden)));
    }

    let abstain = StableId::new("abstain").map_err(|_| ObjectiveError::Arithmetic)?;
    if !forbidden.contains(&abstain) && !legal_actions.iter().any(|action| action.id == abstain) {
        legal_actions.push(ActionClass {
            id: abstain.clone(),
            confirmation: ConfirmationPolicy::NotRequired,
        });
        legal_actions.sort_by(action_order);
    }
    if legal_actions.is_empty() {
        return Ok(Err(conflict_receipt(&source, vec![abstain])));
    }
    validate_count("compiled legal actions", legal_actions.len(), MAX_ACTIONS)?;

    let disposition = if legal_actions.len() == 1 && legal_actions[0].id == abstain {
        CompileDisposition::ExplicitAbstain
    } else {
        CompileDisposition::Compiled
    };
    let hard_constraint_digest = digest_constraints(&source.constraints);
    let semantic_digest = digest_objective(&source, &legal_actions, hard_constraint_digest);
    let objective = ObjectiveFunction {
        request_id: source.request_id,
        principal_scope: source.principal_scope,
        revision: source.revision,
        source_digest: source.source_digest,
        schema_digest: source.schema_digest,
        hard_constraint_digest,
        semantic_digest,
        constraints: source.constraints,
        success_predicates: source.success_predicates,
        legal_actions,
        soft_preferences: source.soft_preferences,
    };

    Ok(Ok(ObjectiveCompileReceipt {
        objective,
        disposition,
        removed_action_ids,
    }))
}

fn validate_source(source: &ObjectiveSourceEnvelope) -> Result<(), ObjectiveError> {
    validate_count("constraints", source.constraints.len(), MAX_CONSTRAINTS)?;
    validate_count(
        "success predicates",
        source.success_predicates.len(),
        MAX_SUCCESS_PREDICATES,
    )?;
    validate_count("allowed actions", source.allowed_actions.len(), MAX_ACTIONS)?;
    validate_count(
        "forbidden actions",
        source.forbidden_actions.len(),
        MAX_ACTIONS,
    )?;
    validate_count(
        "soft dimensions",
        source.soft_preferences.len(),
        MAX_SOFT_DIMENSIONS,
    )?;
    if source.principal_scope.as_str().is_empty() {
        return Err(ObjectiveError::EmptyPrincipalScope);
    }
    if source.source_digest.is_zero() {
        return Err(ObjectiveError::EmptyDigest("source"));
    }
    if source.schema_digest.is_zero() {
        return Err(ObjectiveError::EmptyDigest("schema"));
    }
    validate_source_authority(source)?;
    validate_unique_ids(source)?;
    validate_soft_preferences(source)
}

fn validate_source_authority(source: &ObjectiveSourceEnvelope) -> Result<(), ObjectiveError> {
    if source.source_trust != crate::SourceTrust::UntrustedEvidence {
        return Ok(());
    }

    let creates_authority = source
        .constraints
        .iter()
        .any(|constraint| constraint.class != crate::ConstraintClass::Task)
        || !source.allowed_actions.is_empty();
    if creates_authority {
        return Err(ObjectiveError::UntrustedAuthorityEscalation);
    }
    Ok(())
}

fn validate_count(kind: &'static str, actual: usize, maximum: usize) -> Result<(), ObjectiveError> {
    if actual > maximum {
        return Err(ObjectiveError::InvalidBound {
            kind,
            maximum,
            actual,
        });
    }
    Ok(())
}

fn validate_unique_ids(source: &ObjectiveSourceEnvelope) -> Result<(), ObjectiveError> {
    let mut ids = BTreeSet::new();
    for id in source
        .constraints
        .iter()
        .map(|value| &value.id)
        .chain(source.success_predicates.iter().map(|value| &value.id))
    {
        if !ids.insert(id.clone()) {
            return Err(ObjectiveError::DuplicateSemanticId(id.to_string()));
        }
    }

    let mut dimensions = BTreeSet::new();
    for preference in &source.soft_preferences {
        if !dimensions.insert(preference.dimension.clone()) {
            return Err(ObjectiveError::DuplicateSemanticId(
                preference.dimension.to_string(),
            ));
        }
    }

    let mut actions = BTreeSet::new();
    for action in &source.allowed_actions {
        if !actions.insert(action.id.clone()) {
            return Err(ObjectiveError::DuplicateSemanticId(action.id.to_string()));
        }
    }
    Ok(())
}

fn validate_soft_preferences(source: &ObjectiveSourceEnvelope) -> Result<(), ObjectiveError> {
    for preference in &source.soft_preferences {
        if !(FixedQ32::ZERO..=FixedQ32::ONE).contains(&preference.weight) {
            return Err(ObjectiveError::InvalidSoftWeight(
                preference.dimension.to_string(),
            ));
        }
    }
    Ok(())
}

fn conflict_receipt(
    source: &ObjectiveSourceEnvelope,
    mut conflicting_ids: Vec<StableId>,
) -> ObjectiveConflictReceipt {
    conflicting_ids.sort();
    conflicting_ids.dedup();
    let mut bytes = Vec::new();
    bytes.extend_from_slice(CONFLICT_DIGEST_DOMAIN);
    push_id(&mut bytes, &source.request_id);
    push_u64(&mut bytes, source.revision.get());
    push_digest(&mut bytes, source.source_digest);
    push_len(&mut bytes, conflicting_ids.len());
    for id in &conflicting_ids {
        push_id(&mut bytes, id);
    }
    ObjectiveConflictReceipt {
        request_id: source.request_id.clone(),
        revision: source.revision,
        source_digest: source.source_digest,
        conflicting_ids,
        conflict_digest: Digest32::of_bytes(&bytes),
    }
}

fn digest_constraints(constraints: &[Constraint]) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(CONSTRAINT_DIGEST_DOMAIN);
    push_len(&mut bytes, constraints.len());
    for constraint in constraints {
        push_id(&mut bytes, &constraint.id);
        bytes.push(constraint.class.tag());
        push_id(&mut bytes, &constraint.axis);
        bytes.push(constraint.relation.tag());
        push_i64(&mut bytes, constraint.bound.raw());
        push_id(&mut bytes, &constraint.evidence_source);
    }
    Digest32::of_bytes(&bytes)
}

fn digest_objective(
    source: &ObjectiveSourceEnvelope,
    legal_actions: &[ActionClass],
    hard_constraint_digest: Digest32,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(OBJECTIVE_DIGEST_DOMAIN);
    push_id(&mut bytes, &source.request_id);
    push_id(&mut bytes, &source.principal_scope);
    push_u64(&mut bytes, source.revision.get());
    bytes.push(source.source_trust.tag());
    push_digest(&mut bytes, source.source_digest);
    push_digest(&mut bytes, source.schema_digest);
    push_digest(&mut bytes, hard_constraint_digest);
    push_len(&mut bytes, source.success_predicates.len());
    for predicate in &source.success_predicates {
        push_predicate(&mut bytes, predicate);
    }
    push_len(&mut bytes, legal_actions.len());
    for action in legal_actions {
        push_action(&mut bytes, action);
    }
    push_len(&mut bytes, source.soft_preferences.len());
    for preference in &source.soft_preferences {
        push_preference(&mut bytes, preference);
    }
    Digest32::of_bytes(&bytes)
}

fn push_predicate(bytes: &mut Vec<u8>, predicate: &SuccessPredicate) {
    push_id(bytes, &predicate.id);
    push_id(bytes, &predicate.axis);
    bytes.push(predicate.relation.tag());
    push_i64(bytes, predicate.bound.raw());
    push_id(bytes, &predicate.evidence_source);
    bytes.push(predicate.terminality.tag());
}

fn push_action(bytes: &mut Vec<u8>, action: &ActionClass) {
    push_id(bytes, &action.id);
    bytes.push(action.confirmation.tag());
}

fn push_preference(bytes: &mut Vec<u8>, preference: &SoftPreference) {
    push_id(bytes, &preference.dimension);
    bytes.push(preference.direction.tag());
    push_i64(bytes, preference.weight.raw());
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    let value = id.as_str().as_bytes();
    push_len(bytes, value.len());
    bytes.extend_from_slice(value);
}

fn push_digest(bytes: &mut Vec<u8>, digest: Digest32) {
    bytes.extend_from_slice(digest.as_array());
}

fn push_i64(bytes: &mut Vec<u8>, value: i64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    let converted = u32::try_from(value).unwrap_or(u32::MAX);
    bytes.extend_from_slice(&converted.to_be_bytes());
}

fn constraint_order(left: &Constraint, right: &Constraint) -> std::cmp::Ordering {
    (left.class, &left.axis, &left.id).cmp(&(right.class, &right.axis, &right.id))
}

fn predicate_order(left: &SuccessPredicate, right: &SuccessPredicate) -> std::cmp::Ordering {
    (&left.axis, &left.id).cmp(&(&right.axis, &right.id))
}

fn action_order(left: &ActionClass, right: &ActionClass) -> std::cmp::Ordering {
    left.id.cmp(&right.id)
}

fn preference_order(left: &SoftPreference, right: &SoftPreference) -> std::cmp::Ordering {
    left.dimension.cmp(&right.dimension)
}

#[cfg(test)]
#[path = "compiler_tests.rs"]
mod tests;
