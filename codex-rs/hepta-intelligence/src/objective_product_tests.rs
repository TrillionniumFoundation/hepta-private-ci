use std::fs::OpenOptions;
use std::io::Write;

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
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use tempfile::NamedTempFile;

use super::ObjectiveProductCallerV1;
use super::ObjectiveProductErrorV1;
use super::ObjectiveProductRequestV1;
use super::ObjectivePublicationDispositionV1;
use super::ObjectivePublicationRecoveryV1;
use super::ObjectivePublicationStoreErrorV1;
use super::RunStartBindingsV1;

const OBSERVED_MICROS: u64 = 1_788_861_600_000_000;
const NOW_MICROS: u64 = OBSERVED_MICROS + 1_000_000;

fn id(value: &str) -> StableId {
    StableId::new(value.to_string()).expect("stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn resource_axis(
    name: &str,
    class: codex_hepta_objective::ConstraintClass,
) -> ObjectiveResourceAxisProfileV1 {
    ObjectiveResourceAxisProfileV1 {
        constraint_id: id(&format!("resource.{name}.ceiling")),
        axis: id(&format!("resource.{name}")),
        class,
        q32_per_source_unit: FixedQ32::from_raw(1),
        evidence_source: id("objective.resource.profile"),
    }
}

fn profile() -> ObjectiveAdmissionProfileV1 {
    use codex_hepta_objective::ConstraintClass;

    ObjectiveAdmissionProfileV1 {
        profile_id: id("objective.profile.product.v1"),
        profile_revision: Revision::new(1).expect("revision"),
        expected_input_schema_digest: digest("schema-v1"),
        expected_normalization_profile_digest: digest("normalization-v1"),
        principal_scope_digest: digest("principal-scope"),
        principal_scope: id("principal.alpha"),
        allowed_locales: vec!["en-US".to_string()],
        maximum_source_age_micros: 60_000_000,
        maximum_future_skew_micros: 1_000_000,
        deadline_required: true,
        allowed_trusted_source_identities: vec![id("adapter.console")],
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
                source_action_class: "inspect".to_string(),
                action_id: id("action.inspect"),
            },
            ObjectiveActionProfileV1 {
                source_action_class: "network".to_string(),
                action_id: id("action.network"),
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
    let source_digest = digest("source-bytes");
    let mut envelope = ObjectiveSourceEnvelopeV1 {
        request_id: "request.001".to_string(),
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
            legal_action_classes: vec!["read".to_string(), "inspect".to_string()],
            forbidden_action_classes: vec!["network".to_string()],
            confirmation_action_classes: vec!["inspect".to_string()],
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
                source_digest,
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
        canonical_objective_intent_digest_v1(&envelope).expect("canonical intent");
    envelope
}

fn request(run_id: &str) -> ObjectiveProductRequestV1 {
    let profile = profile();
    let envelope = envelope();
    let context = ObjectiveAdmissionContextV1 {
        revision: Revision::new(7).expect("revision"),
        now_unix_micros: NOW_MICROS,
        selected_profile_digest: profile.digest().expect("profile digest"),
        source_authentication: ObjectiveSourceAuthenticationV1::Principal {
            principal_scope_digest: envelope.principal_scope_digest,
            source_digest: envelope.structured_intent.provenance.source_digest,
        },
    };
    ObjectiveProductRequestV1 {
        envelope,
        profile,
        context,
        run: RunStartBindingsV1 {
            run_id: id(run_id),
            preference_state_digest: digest("preference-state"),
            model_tuple_digest: digest("model-tuple"),
            prompt_registry_digest: digest("prompt-registry"),
            artifact_set_digest: digest("artifact-set"),
            authority_epoch: 11,
            generation: 13,
            fence_digest: digest("authority-fence"),
        },
    }
}

#[test]
fn product_caller_atomically_publishes_and_recovers_objective_and_run_snapshot() {
    let host = NamedTempFile::new().expect("host file");
    let binding = digest("objective-publication-store");
    let mut caller =
        ObjectiveProductCallerV1::create(host.reopen().expect("writer"), binding, 64)
            .expect("create");

    let receipt = caller
        .admit_compile_publish(request("run.001"))
        .expect("publish");
    assert_eq!(
        receipt.disposition,
        ObjectivePublicationDispositionV1::Appended
    );
    assert!(!receipt.authority.grants_any());
    assert_eq!(
        receipt.publication.run_start.objective_digest,
        receipt.publication.objective.objective.semantic_digest
    );
    assert_eq!(
        receipt.publication.run_start.hard_constraint_digest,
        receipt.publication.objective.objective.hard_constraint_digest
    );
    assert!(!receipt.publication.run_start.digest().is_zero());

    let expected = receipt.publication.clone();
    let anchor = caller.anchor().expect("anchor");
    drop(caller);

    let recovered = ObjectiveProductCallerV1::recover(
        host.reopen().expect("reader"),
        binding,
        64,
        ObjectivePublicationRecoveryV1::Acknowledged(anchor),
    )
    .expect("recover");
    assert_eq!(recovered.records().expect("records"), &[expected.clone()]);
    assert_eq!(
        recovered
            .publication_for_run(&id("run.001"))
            .expect("lookup"),
        Some(&expected)
    );
}

#[test]
fn exact_retry_is_idempotent_and_does_not_append_a_second_frame() {
    let host = NamedTempFile::new().expect("host file");
    let binding = digest("objective-idempotent-store");
    let mut caller =
        ObjectiveProductCallerV1::create(host.reopen().expect("writer"), binding, 64)
            .expect("create");
    let request = request("run.retry");

    let first = caller
        .admit_compile_publish(request.clone())
        .expect("first publish");
    let second = caller
        .admit_compile_publish(request)
        .expect("replay publish");
    assert_eq!(first.publication, second.publication);
    assert_eq!(
        second.disposition,
        ObjectivePublicationDispositionV1::IdempotentReplay
    );
    assert_eq!(caller.records().expect("records").len(), 1);
}

#[test]
fn same_objective_revision_with_new_run_is_allowed_when_semantics_match() {
    let host = NamedTempFile::new().expect("host file");
    let binding = digest("objective-multi-run-store");
    let mut caller =
        ObjectiveProductCallerV1::create(host.reopen().expect("writer"), binding, 64)
            .expect("create");

    let first = caller
        .admit_compile_publish(request("run.one"))
        .expect("first");
    let second = caller
        .admit_compile_publish(request("run.two"))
        .expect("second");
    assert_eq!(
        first.publication.objective.objective.semantic_digest,
        second.publication.objective.objective.semantic_digest
    );
    assert_eq!(caller.records().expect("records").len(), 2);
}

#[test]
fn reused_request_revision_with_different_semantics_is_a_durable_conflict() {
    let host = NamedTempFile::new().expect("host file");
    let binding = digest("objective-conflict-store");
    let mut caller =
        ObjectiveProductCallerV1::create(host.reopen().expect("writer"), binding, 64)
            .expect("create");

    caller
        .admit_compile_publish(request("run.first"))
        .expect("first");
    let mut changed = request("run.second");
    changed.envelope.structured_intent.success_predicates[0].bound_q32 += 1;
    changed.envelope.intent_digest =
        canonical_objective_intent_digest_v1(&changed.envelope).expect("intent");

    assert!(matches!(
        caller.admit_compile_publish(changed),
        Err(ObjectiveProductErrorV1::Store(
            ObjectivePublicationStoreErrorV1::Conflict
        ))
    ));
    assert_eq!(caller.records().expect("records").len(), 1);
}

#[test]
fn invalid_run_binding_rejects_before_durable_publication() {
    let host = NamedTempFile::new().expect("host file");
    let binding = digest("objective-invalid-run-store");
    let mut caller =
        ObjectiveProductCallerV1::create(host.reopen().expect("writer"), binding, 64)
            .expect("create");
    let mut invalid = request("run.invalid");
    invalid.run.model_tuple_digest = Digest32::ZERO;

    assert!(matches!(
        caller.admit_compile_publish(invalid),
        Err(ObjectiveProductErrorV1::InvalidRunBinding("model tuple"))
    ));
    assert!(caller.records().expect("records").is_empty());
}

#[test]
fn acknowledged_recovery_trims_only_an_incomplete_unacknowledged_tail() {
    let host = NamedTempFile::new().expect("host file");
    let binding = digest("objective-recovery-store");
    let mut caller =
        ObjectiveProductCallerV1::create(host.reopen().expect("writer"), binding, 64)
            .expect("create");
    let expected = caller
        .admit_compile_publish(request("run.recover"))
        .expect("publish")
        .publication;
    let anchor = caller.anchor().expect("anchor");
    drop(caller);

    {
        let mut file = OpenOptions::new()
            .append(true)
            .open(host.path())
            .expect("append tail");
        file.write_all(&[0, 0, 0]).expect("tail");
        file.sync_all().expect("sync tail");
    }

    let recovered = ObjectiveProductCallerV1::recover(
        host.reopen().expect("reader"),
        binding,
        64,
        ObjectivePublicationRecoveryV1::Acknowledged(anchor),
    )
    .expect("recover");
    assert_eq!(recovered.records().expect("records"), &[expected]);
}
