use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use super::*;
use crate::ActionClass;
use crate::CompileDisposition;
use crate::ConfirmationPolicy;
use crate::Constraint;
use crate::ConstraintClass;
use crate::ConstraintRelation;
use crate::ObjectiveFunction;
use crate::SoftDirection;
use crate::SoftPreference;
use crate::SuccessPredicate;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn admission() -> ObjectiveAdmissionReceiptV1 {
    ObjectiveAdmissionReceiptV1 {
        profile_id: id("profile.v1"),
        profile_revision: Revision::new(1).expect("revision"),
        profile_digest: digest("profile"),
        supplied_source_digest: digest("source"),
        intent_digest: digest("intent"),
        admitted_source_digest: digest("admitted"),
        observed_at_unix_micros: 10,
        deadline_unix_micros: Some(20),
        authority: AuthorityPosture::DENY_ALL,
    }
}

fn compiled() -> ObjectiveCompileReceipt {
    let constraint = Constraint {
        id: id("hard"),
        class: ConstraintClass::Principal,
        axis: id("risk"),
        relation: ConstraintRelation::AtMost,
        bound: FixedQ32::ZERO,
        evidence_source: id("owner"),
    };
    let predicate = SuccessPredicate {
        id: id("success"),
        axis: id("quality"),
        relation: ConstraintRelation::AtLeast,
        bound: FixedQ32::ONE,
        evidence_source: id("observer"),
        terminality: PredicateTerminality::Terminal,
    };
    ObjectiveCompileReceipt {
        objective: ObjectiveFunction {
            request_id: id("request.1"),
            principal_scope: id("principal.1"),
            revision: Revision::new(1).expect("revision"),
            source_digest: digest("admitted"),
            schema_digest: digest("schema"),
            hard_constraint_digest: digest("hard-digest"),
            semantic_digest: digest("objective"),
            constraints: vec![constraint],
            success_predicates: vec![predicate],
            legal_actions: vec![ActionClass {
                id: id("abstain"),
                confirmation: ConfirmationPolicy::NotRequired,
            }],
            soft_preferences: vec![SoftPreference {
                dimension: id("quality"),
                direction: SoftDirection::Maximize,
                weight: FixedQ32::ONE,
            }],
        },
        disposition: CompileDisposition::Compiled,
        removed_action_ids: Vec::new(),
    }
}

fn bindings() -> RunStartBindingsV1 {
    RunStartBindingsV1 {
        run_id: id("run.1"),
        preference_state_digest: digest("preference"),
        model_tuple_digest: digest("model"),
        prompt_registry_digest: digest("prompt"),
        artifact_set_digest: digest("artifacts"),
        authority_epoch: 7,
        generation: 9,
        fence_digest: digest("fence"),
    }
}

#[test]
fn publication_binds_compiled_objective_and_run_snapshot() {
    let publication = ObjectiveRunPublicationV1::new(admission(), compiled(), bindings())
        .expect("publication");
    assert_eq!(
        publication.run_start.objective_digest,
        publication.compile.objective.semantic_digest
    );
    assert_eq!(
        publication.run_start.hard_constraint_digest,
        publication.compile.objective.hard_constraint_digest
    );
    let json = String::from_utf8(publication.canonical_json().expect("json")).expect("utf8");
    assert!(json.contains("\"runStart\""));
    assert!(json.contains("\"authorityDenyAll\":true"));
    assert!(!publication.publication_digest().expect("digest").is_zero());
}

#[test]
fn publication_rejects_authority_or_unbound_run_identity() {
    let mut receipt = admission();
    receipt.authority.runtime = true;
    assert_eq!(
        ObjectiveRunPublicationV1::new(receipt, compiled(), bindings()),
        Err(ObjectiveRunPublicationError::AuthorityEscalation)
    );
    let mut missing = bindings();
    missing.fence_digest = Digest32::ZERO;
    assert_eq!(
        ObjectiveRunPublicationV1::new(admission(), compiled(), missing),
        Err(ObjectiveRunPublicationError::EmptyDigest("fence"))
    );
}

#[test]
fn run_snapshot_digest_changes_with_generation() {
    let first = ObjectiveRunPublicationV1::new(admission(), compiled(), bindings())
        .expect("first");
    let mut second_bindings = bindings();
    second_bindings.generation += 1;
    let second = ObjectiveRunPublicationV1::new(admission(), compiled(), second_bindings)
        .expect("second");
    assert_ne!(
        first.run_start.semantic_digest().expect("first digest"),
        second.run_start.semantic_digest().expect("second digest")
    );
}
