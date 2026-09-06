use std::fmt::Debug;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::compile;
use crate::ActionClass;
use crate::CompileDisposition;
use crate::ConfirmationPolicy;
use crate::Constraint;
use crate::ConstraintClass;
use crate::ConstraintRelation;
use crate::ObjectiveError;
use crate::ObjectiveSourceEnvelope;
use crate::PredicateTerminality;
use crate::SoftDirection;
use crate::SoftPreference;
use crate::SourceTrust;
use crate::SuccessPredicate;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn must_err<T: Debug, E>(result: Result<T, E>) -> E {
    match result {
        Err(error) => error,
        Ok(value) => panic!("expected error, received value: {value:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn envelope() -> ObjectiveSourceEnvelope {
    ObjectiveSourceEnvelope {
        request_id: id("request-1"),
        principal_scope: id("principal:alpha"),
        revision: must(Revision::new(1)),
        source_trust: SourceTrust::PrincipalStructured,
        source_digest: Digest32::of_bytes(b"source"),
        schema_digest: Digest32::of_bytes(b"schema"),
        constraints: vec![
            Constraint {
                id: id("privacy-ceiling"),
                class: ConstraintClass::Constitutional,
                axis: id("privacy-risk"),
                relation: ConstraintRelation::AtMost,
                bound: FixedQ32::ZERO,
                evidence_source: id("constitution-v1"),
            },
            Constraint {
                id: id("latency-ceiling"),
                class: ConstraintClass::Task,
                axis: id("latency-ms"),
                relation: ConstraintRelation::AtMost,
                bound: FixedQ32::from_raw(100_i64 << 32),
                evidence_source: id("request-1"),
            },
        ],
        success_predicates: vec![SuccessPredicate {
            id: id("answer-produced"),
            axis: id("answer-count"),
            relation: ConstraintRelation::AtLeast,
            bound: FixedQ32::ONE,
            evidence_source: id("terminal-observer"),
            terminality: PredicateTerminality::Terminal,
        }],
        allowed_actions: vec![ActionClass {
            id: id("read-local"),
            confirmation: ConfirmationPolicy::NotRequired,
        }],
        forbidden_actions: Vec::new(),
        soft_preferences: vec![SoftPreference {
            dimension: id("evidence-quality"),
            direction: SoftDirection::Maximize,
            weight: FixedQ32::ONE,
        }],
    }
}

#[test]
fn compilation_is_permutation_invariant() {
    let first = must(must(compile(envelope())));
    let mut reordered = envelope();
    reordered.constraints.reverse();
    reordered.allowed_actions.reverse();
    let second = must(must(compile(reordered)));

    assert_eq!(
        first.objective.semantic_digest,
        second.objective.semantic_digest
    );
    assert_eq!(first.objective, second.objective);
}

#[test]
fn forbidden_requested_action_returns_conflict() {
    let mut source = envelope();
    source.allowed_actions.push(ActionClass {
        id: id("network-connect"),
        confirmation: ConfirmationPolicy::Required,
    });
    source.forbidden_actions.push(id("network-connect"));

    let conflict = must_err(must(compile(source)));

    assert_eq!(conflict.conflicting_ids, vec![id("network-connect")]);
}

#[test]
fn contradictory_hard_bounds_return_minimal_pair() {
    let mut source = envelope();
    source.constraints.extend([
        Constraint {
            id: id("minimum-memory"),
            class: ConstraintClass::Task,
            axis: id("memory-bytes"),
            relation: ConstraintRelation::AtLeast,
            bound: FixedQ32::from_raw(10_i64 << 32),
            evidence_source: id("request-1"),
        },
        Constraint {
            id: id("maximum-memory"),
            class: ConstraintClass::Environment,
            axis: id("memory-bytes"),
            relation: ConstraintRelation::AtMost,
            bound: FixedQ32::from_raw(5_i64 << 32),
            evidence_source: id("host-policy"),
        },
    ]);

    let conflict = must_err(must(compile(source)));

    assert_eq!(
        conflict.conflicting_ids,
        vec![id("maximum-memory"), id("minimum-memory")]
    );
}

#[test]
fn changing_soft_weight_preserves_hard_digest() {
    let first = must(must(compile(envelope())));
    let mut changed = envelope();
    changed.soft_preferences[0].weight = FixedQ32::from_raw(1_i64 << 31);
    let second = must(must(compile(changed)));

    assert_eq!(
        first.objective.hard_constraint_digest,
        second.objective.hard_constraint_digest
    );
    assert_ne!(
        first.objective.semantic_digest,
        second.objective.semantic_digest
    );
}

#[test]
fn only_abstain_is_explicitly_reported() {
    let mut source = envelope();
    source.allowed_actions.clear();
    let receipt = must(must(compile(source)));

    assert_eq!(receipt.disposition, CompileDisposition::ExplicitAbstain);
    assert_eq!(receipt.objective.legal_actions[0].id, id("abstain"));
}

#[test]
fn duplicate_semantic_ids_fail_before_digest_publication() {
    let mut source = envelope();
    source.constraints.push(source.constraints[0].clone());
    let error = must_err(compile(source));

    assert_eq!(error.code(), "OBJ-E001");
    assert!(matches!(error, ObjectiveError::DuplicateSemanticId(_)));
}

#[test]
fn untrusted_evidence_cannot_create_privileged_authority() {
    let mut source = envelope();
    source.source_trust = SourceTrust::UntrustedEvidence;

    let error = must_err(compile(source));

    assert_eq!(error, ObjectiveError::UntrustedAuthorityEscalation);
    assert_eq!(error.code(), "OBJ-E009");
}

#[test]
fn forbidden_abstain_is_not_implicitly_legalized_or_misreported() {
    let mut source = envelope();
    source.forbidden_actions.push(id("abstain"));
    let receipt = must(must(compile(source.clone())));
    assert_eq!(receipt.objective.legal_actions, source.allowed_actions);
    assert_eq!(receipt.disposition, CompileDisposition::Compiled);
    source.allowed_actions.clear();
    assert_eq!(
        must_err(must(compile(source))).conflicting_ids,
        vec![id("abstain")]
    );
}

#[test]
fn implicit_abstain_cannot_exceed_the_legal_action_bound() {
    let mut source = envelope();
    source.allowed_actions = (0..128)
        .map(|i| ActionClass {
            id: id(&format!("action-{i:03}")),
            confirmation: ConfirmationPolicy::Required,
        })
        .collect();
    assert_eq!(
        must_err(compile(source)),
        ObjectiveError::InvalidBound {
            kind: "compiled legal actions",
            maximum: 128,
            actual: 129
        }
    );
}
