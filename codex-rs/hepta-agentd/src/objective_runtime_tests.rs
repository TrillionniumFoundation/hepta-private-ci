use std::sync::Arc;
use std::sync::Barrier;

use codex_hepta_objective::ConstraintClass;
use codex_hepta_objective::ObjectiveAbstentionRuleProfileV1;
use codex_hepta_objective::ObjectiveActionProfileV1;
use codex_hepta_objective::ObjectiveAdmissionContextV1;
use codex_hepta_objective::ObjectiveAdmissionProfileV1;
use codex_hepta_objective::ObjectiveConstraintComparatorV1;
use codex_hepta_objective::ObjectiveConstraintProfileV1;
use codex_hepta_objective::ObjectiveEvidenceProfileV1;
use codex_hepta_objective::ObjectiveEvidenceRequirementV1;
use codex_hepta_objective::ObjectivePredicateComparatorV1;
use codex_hepta_objective::ObjectivePredicateProfileV1;
use codex_hepta_objective::ObjectiveProvenanceV1;
use codex_hepta_objective::ObjectiveResourceAxisProfileV1;
use codex_hepta_objective::ObjectiveResourceProfileV1;
use codex_hepta_objective::ObjectiveResourcesV1;
use codex_hepta_objective::ObjectiveRiskClassV1;
use codex_hepta_objective::ObjectiveRiskProfileV1;
use codex_hepta_objective::ObjectiveRiskV1;
use codex_hepta_objective::ObjectiveRollbackClassV1;
use codex_hepta_objective::ObjectiveSoftDimensionProfileV1;
use codex_hepta_objective::ObjectiveSoftDimensionV1;
use codex_hepta_objective::ObjectiveSoftDirectionV1;
use codex_hepta_objective::ObjectiveSourceAuthenticationV1;
use codex_hepta_objective::ObjectiveSourceConstraintV1;
use codex_hepta_objective::ObjectiveSourceEnvelopeV1;
use codex_hepta_objective::ObjectiveSourcePredicateV1;
use codex_hepta_objective::ObjectiveSourceTrustV1;
use codex_hepta_objective::ObjectiveStructuredIntentV1;
use codex_hepta_objective::canonical_objective_intent_digest_v1;
use codex_hepta_objective::admit_and_compile_objective_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use super::ObjectiveProductRunDispositionV1;
use super::ObjectiveProductRunError;
use super::ObjectivePublicationError;
use super::ObjectiveRunBindingsV1;
use super::ObjectiveRunFileStore;
use super::admit_publish_and_start_objective_run_v1;
use crate::AgentRunCoordinator;
use crate::RunPhase;
use crate::RuntimeComposition;

const OBSERVED_MICROS: u64 = 1_788_861_600_000_000;
const NOW_MICROS: u64 = OBSERVED_MICROS + 1_000_000;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn resource_axis(name: &str, class: ConstraintClass) -> ObjectiveResourceAxisProfileV1 {
    ObjectiveResourceAxisProfileV1 {
        constraint_id: id(&format!("resource.{name}.ceiling")),
        axis: id(&format!("resource.{name}")),
        class,
        q32_per_source_unit: FixedQ32::from_raw(1),
        evidence_source: id("objective.resource.profile"),
    }
}

fn profile() -> ObjectiveAdmissionProfileV1 {
    ObjectiveAdmissionProfileV1 {
        profile_id: id("objective.profile.agentd.v1"),
        profile_revision: Revision::new(1).expect("revision"),
        expected_input_schema_digest: digest("schema-v1"),
        expected_normalization_profile_digest: digest("normalization-v1"),
        principal_scope_digest: digest("principal-scope"),
        principal_scope: id("principal.alpha"),
        allowed_locales: vec!["en-US".to_string()],
        maximum_source_age_micros: 60_000_000,
        maximum_future_skew_micros: 1_000_000,
        deadline_required: true,
        allowed_trusted_source_identities: vec![id("adapter.agentd")],
        constraints: vec![ObjectiveConstraintProfileV1 {
            source_constraint_id: "latency.ceiling".to_string(),
            expected_unit: "micros".to_string(),
            class: ConstraintClass::Task,
            axis: id("latency.micros"),
        }],
        predicates: vec![
            ObjectivePredicateProfileV1 {
                source_predicate_id: "task.success".to_string(),
                expected_unit: "ratio".to_string(),
                axis: id("task.success.ratio"),
            },
            ObjectivePredicateProfileV1 {
                source_predicate_id: "task.terminal".to_string(),
                expected_unit: "boolean".to_string(),
                axis: id("task.terminal"),
            },
        ],
        actions: vec![
            ObjectiveActionProfileV1 {
                source_action_class: "read".to_string(),
                action_id: id("action.read"),
            },
            ObjectiveActionProfileV1 {
                source_action_class: "abstain".to_string(),
                action_id: id("abstain"),
            },
        ],
        soft_dimensions: vec![ObjectiveSoftDimensionProfileV1 {
            source_dimension_id: "quality".to_string(),
            expected_unit: "ratio".to_string(),
            expected_direction: ObjectiveSoftDirectionV1::Maximize,
            dimension: id("quality.ratio"),
            baseline_weight: FixedQ32::from_raw(1_i64 << 31),
        }],
        evidence_requirements: vec![ObjectiveEvidenceProfileV1 {
            source_requirement_id: "evidence.quality".to_string(),
            axis: id("evidence.confidence"),
        }],
        resources: ObjectiveResourceProfileV1 {
            time_micros: resource_axis("time", ConstraintClass::Task),
            token_count: resource_axis("tokens", ConstraintClass::Task),
            compute_micros: resource_axis("compute", ConstraintClass::Environment),
            memory_bytes: resource_axis("memory", ConstraintClass::Environment),
            network_bytes: resource_axis("network", ConstraintClass::Principal),
            external_effect_count: resource_axis("effects", ConstraintClass::Principal),
        },
        risk: ObjectiveRiskProfileV1 {
            evidence_source: id("objective.risk.profile"),
            class: ConstraintClass::Principal,
            risk_constraint_id: id("risk.class"),
            risk_axis: id("risk.class.value"),
            low_value: FixedQ32::from_raw(0),
            medium_value: FixedQ32::from_raw(1),
            high_value: FixedQ32::from_raw(2),
            critical_value: FixedQ32::from_raw(3),
            rollback_constraint_id: id("risk.rollback"),
            rollback_axis: id("risk.rollback.value"),
            rollback_none_value: FixedQ32::from_raw(0),
            rollback_reversible_value: FixedQ32::from_raw(1),
            rollback_compensatable_value: FixedQ32::from_raw(2),
            rollback_irreversible_value: FixedQ32::from_raw(3),
            compensation_constraint_id: id("risk.compensation"),
            compensation_axis: id("risk.compensation.value"),
            compensation_false_value: FixedQ32::from_raw(0),
            compensation_true_value: FixedQ32::from_raw(1),
            abstention_constraint_id: id("risk.abstention"),
            abstention_axis: id("risk.abstention.value"),
            abstention_rules: vec![ObjectiveAbstentionRuleProfileV1 {
                source_rule: "ask".to_string(),
                value: FixedQ32::from_raw(1),
            }],
        },
    }
}

fn envelope() -> ObjectiveSourceEnvelopeV1 {
    let mut envelope = ObjectiveSourceEnvelopeV1 {
        request_id: "request.agentd.001".to_string(),
        principal_scope_digest: digest("principal-scope"),
        intent_digest: Digest32::ZERO,
        structured_intent: ObjectiveStructuredIntentV1 {
            success_predicates: vec![ObjectiveSourcePredicateV1 {
                predicate_id: "task.success".to_string(),
                unit: "ratio".to_string(),
                comparator: ObjectivePredicateComparatorV1::GreaterThanOrEqual,
                bound_q32: 1_i64 << 31,
                evidence_source_id: "observer.task".to_string(),
                terminal: false,
            }],
            terminal_conditions: vec![ObjectiveSourcePredicateV1 {
                predicate_id: "task.terminal".to_string(),
                unit: "boolean".to_string(),
                comparator: ObjectivePredicateComparatorV1::Equal,
                bound_q32: FixedQ32::ONE.raw(),
                evidence_source_id: "observer.task".to_string(),
                terminal: true,
            }],
            legal_action_classes: vec!["read".to_string()],
            forbidden_action_classes: Vec::new(),
            confirmation_action_classes: Vec::new(),
            constraints: vec![ObjectiveSourceConstraintV1 {
                constraint_id: "latency.ceiling".to_string(),
                unit: "micros".to_string(),
                comparator: ObjectiveConstraintComparatorV1::LessThanOrEqual,
                bound_q32: 5_000,
                evidence_source_id: "observer.clock".to_string(),
                terminal: false,
            }],
            soft_dimensions: vec![ObjectiveSoftDimensionV1 {
                dimension_id: "quality".to_string(),
                unit: "ratio".to_string(),
                direction: ObjectiveSoftDirectionV1::Maximize,
                minimum_weight_q32: 0,
                maximum_weight_q32: FixedQ32::ONE.raw(),
            }],
            evidence_requirements: vec![ObjectiveEvidenceRequirementV1 {
                requirement_id: "evidence.quality".to_string(),
                evidence_source_id: "observer.evidence".to_string(),
                minimum_confidence_ppm: 900_000,
                terminal: true,
            }],
            resources: ObjectiveResourcesV1 {
                time_micros: 10_000,
                token_count: 1_000,
                compute_micros: 50_000,
                memory_bytes: 1_048_576,
                network_bytes: 0,
                external_effect_count: 0,
            },
            risk: ObjectiveRiskV1 {
                risk_class: ObjectiveRiskClassV1::Low,
                abstention_rule: "ask".to_string(),
                rollback_class: ObjectiveRollbackClassV1::Reversible,
                compensation_required: false,
            },
            provenance: ObjectiveProvenanceV1 {
                source_digest: digest("source-bytes"),
                normalization_profile_digest: digest("normalization-v1"),
            },
        },
        source_trust_class: ObjectiveSourceTrustV1::Principal,
        locale: "en-US".to_string(),
        observed_at: "2026-09-08T10:00:00Z".to_string(),
        deadline: Some("2026-09-08T10:05:00Z".to_string()),
        input_schema_digest: digest("schema-v1"),
    };
    envelope.intent_digest =
        canonical_objective_intent_digest_v1(&envelope).expect("intent digest");
    envelope
}

fn context(
    profile: &ObjectiveAdmissionProfileV1,
    envelope: &ObjectiveSourceEnvelopeV1,
) -> ObjectiveAdmissionContextV1 {
    ObjectiveAdmissionContextV1 {
        revision: Revision::new(7).expect("revision"),
        now_unix_micros: NOW_MICROS,
        selected_profile_digest: profile.digest().expect("profile digest"),
        source_authentication: ObjectiveSourceAuthenticationV1::Principal {
            principal_scope_digest: envelope.principal_scope_digest,
            source_digest: envelope.structured_intent.provenance.source_digest,
        },
    }
}

fn bindings(run_id: &str) -> ObjectiveRunBindingsV1 {
    ObjectiveRunBindingsV1 {
        run_id: id(run_id),
        body_digest: digest("body"),
        preference_state_digest: digest("preference"),
        model_tuple_digest: digest("model"),
        prompt_registry_digest: digest("prompt-registry"),
        artifact_set_digest: digest("artifacts"),
        authority_epoch: 4,
        generation: 9,
        fence_digest: digest("fence"),
    }
}

fn stored_publication_fixture(
    run_id: &str,
    model_label: &str,
) -> super::StoredObjectiveRunPublicationV1 {
    let profile = profile();
    let envelope = envelope();
    let context = context(&profile, &envelope);
    let outcome = admit_and_compile_objective_v1(&envelope, &profile, &context)
        .expect("admission fixture");
    let objective = outcome.compile_result.expect("compiled fixture");
    let mut bindings = bindings(run_id);
    bindings.model_tuple_digest = digest(model_label);
    super::stored_publication(&outcome.receipt, &objective, &bindings)
}

fn coordinator() -> AgentRunCoordinator {
    AgentRunCoordinator::compose_runtime(RuntimeComposition {
        agent_id: "agent.alpha".to_string(),
        supervisor_generation: 3,
        agentd_generation: 4,
        configuration_digest: digest("configuration").to_string(),
        ports_digest: digest("ports").to_string(),
    })
    .expect("coordinator")
}

#[test]
fn authenticated_objective_is_durably_published_before_run_admission() {
    let directory = tempfile::tempdir().expect("tempdir");
    let store = ObjectiveRunFileStore::open(directory.path()).expect("store");
    let mut coordinator = coordinator();
    let profile = profile();
    let envelope = envelope();
    let context = context(&profile, &envelope);
    let bindings = bindings("run.objective.001");

    let first = admit_publish_and_start_objective_run_v1(
        &mut coordinator,
        &store,
        NOW_MICROS / 1_000,
        &envelope,
        &profile,
        &context,
        &bindings,
    )
    .expect("product objective run");
    assert_eq!(first.disposition, ObjectiveProductRunDispositionV1::Started);
    assert!(!first.publication.idempotent);
    let run = first.run.as_ref().expect("run receipt");
    assert_eq!(run.phase, RunPhase::Admitted);
    assert!(!run.idempotent);

    let (stored, digest) = store
        .load(&bindings.run_id)
        .expect("load")
        .expect("publication exists");
    assert_eq!(stored.run_id, bindings.run_id.to_string());
    assert_eq!(
        stored.semantic_digest,
        first.objective.objective.semantic_digest.to_string()
    );
    assert_eq!(digest, first.publication.publication_digest);
    assert_eq!(stored.runtime_body_digest, bindings.body_digest.to_string());
    assert!(stored.admission.authority_denied);

    let second = admit_publish_and_start_objective_run_v1(
        &mut coordinator,
        &store,
        NOW_MICROS / 1_000,
        &envelope,
        &profile,
        &context,
        &bindings,
    )
    .expect("idempotent replay");
    assert!(second.publication.idempotent);
    assert!(second.run.expect("run").idempotent);
}

#[test]
fn same_run_identity_with_changed_runtime_semantics_conflicts_before_new_start() {
    let directory = tempfile::tempdir().expect("tempdir");
    let store = ObjectiveRunFileStore::open(directory.path()).expect("store");
    let mut coordinator = coordinator();
    let profile = profile();
    let envelope = envelope();
    let context = context(&profile, &envelope);
    let bindings = bindings("run.objective.002");
    admit_publish_and_start_objective_run_v1(
        &mut coordinator,
        &store,
        NOW_MICROS / 1_000,
        &envelope,
        &profile,
        &context,
        &bindings,
    )
    .expect("first run");

    let mut changed = bindings.clone();
    changed.model_tuple_digest = digest("model.changed");
    let error = admit_publish_and_start_objective_run_v1(
        &mut coordinator,
        &store,
        NOW_MICROS / 1_000,
        &envelope,
        &profile,
        &context,
        &changed,
    )
    .expect_err("publication identity conflict");
    assert!(matches!(
        error,
        ObjectiveProductRunError::Publication(ObjectivePublicationError::Conflict)
    ));
}

#[test]
fn explicit_abstain_is_published_without_runtime_dispatch_state() {
    let directory = tempfile::tempdir().expect("tempdir");
    let store = ObjectiveRunFileStore::open(directory.path()).expect("store");
    let mut coordinator = coordinator();
    let profile = profile();
    let mut envelope = envelope();
    envelope.structured_intent.legal_action_classes = vec!["abstain".to_string()];
    envelope.intent_digest =
        canonical_objective_intent_digest_v1(&envelope).expect("intent digest");
    let context = context(&profile, &envelope);
    let bindings = bindings("run.objective.abstain");

    let receipt = admit_publish_and_start_objective_run_v1(
        &mut coordinator,
        &store,
        NOW_MICROS / 1_000,
        &envelope,
        &profile,
        &context,
        &bindings,
    )
    .expect("abstain publication");
    assert_eq!(
        receipt.disposition,
        ObjectiveProductRunDispositionV1::PublishedAbstain
    );
    assert!(receipt.run.is_none());
    assert!(coordinator.run(bindings.run_id.as_str()).is_none());
    assert!(
        store
            .load(&bindings.run_id)
            .expect("load")
            .expect("publication")
            .0
            .admission
            .authority_denied
    );
}

#[test]
fn concurrent_semantic_drift_cannot_replace_an_existing_run_publication() {
    let directory = tempfile::tempdir().expect("tempdir");
    let store = ObjectiveRunFileStore::open(directory.path()).expect("store");
    let first = stored_publication_fixture("run.objective.race", "model.first");
    let second = stored_publication_fixture("run.objective.race", "model.second");
    let barrier = Arc::new(Barrier::new(3));

    let first_store = store.clone();
    let first_barrier = Arc::clone(&barrier);
    let first_publication = first.clone();
    let left = std::thread::spawn(move || {
        first_barrier.wait();
        first_store.publish(&first_publication)
    });

    let second_store = store.clone();
    let second_barrier = Arc::clone(&barrier);
    let second_publication = second.clone();
    let right = std::thread::spawn(move || {
        second_barrier.wait();
        second_store.publish(&second_publication)
    });

    barrier.wait();
    let left = left.join().expect("left publisher");
    let right = right.join().expect("right publisher");

    let successes = usize::from(left.is_ok()) + usize::from(right.is_ok());
    let conflicts = usize::from(matches!(left, Err(ObjectivePublicationError::Conflict)))
        + usize::from(matches!(right, Err(ObjectivePublicationError::Conflict)));
    assert_eq!(successes, 1);
    assert_eq!(conflicts, 1);

    let (stored, _) = store
        .load(&id("run.objective.race"))
        .expect("load")
        .expect("winner");
    assert!(stored == first || stored == second);
}
