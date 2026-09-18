use std::fs::OpenOptions;

use codex_hepta_learning_ledger::AppendDisposition;
use codex_hepta_intelligence::ProductionRunBindingsV1;
use codex_hepta_learning_ledger::DurableLedger;
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
use tempfile::tempdir;

use super::ObjectiveProductRunDispositionV1;
use super::ObjectiveProductRunError;
use super::ObjectiveProductRunRequestV1;
use super::prepare_and_start_intelligence_run_v1;
use crate::AgentRunCoordinator;
use crate::AgentRunError;
use crate::ObjectiveHostError;
use crate::RunPhase;
use crate::RuntimeComposition;

const OBSERVED_MICROS: u64 = 1_788_861_600_000_000;
const NOW_MICROS: u64 = OBSERVED_MICROS + 1_000_000;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
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
        allowed_trusted_source_identities: Vec::new(),
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
        actions: vec![ObjectiveActionProfileV1 {
            source_action_class: "read".to_string(),
            action_id: id("action.read"),
        }],
        soft_dimensions: Vec::new(),
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

fn source() -> ObjectiveSourceEnvelopeV1 {
    let mut value = ObjectiveSourceEnvelopeV1 {
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
            soft_dimensions: Vec::new(),
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
                source_digest: digest("agentd-source"),
                normalization_profile_digest: digest("normalization-v1"),
            },
        },
        source_trust_class: ObjectiveSourceTrustV1::Principal,
        locale: "en-US".to_string(),
        observed_at: "2026-09-08T10:00:00Z".to_string(),
        deadline: Some("2026-09-08T10:05:00Z".to_string()),
        input_schema_digest: digest("schema-v1"),
    };
    value.intent_digest =
        canonical_objective_intent_digest_v1(&value).expect("canonical objective intent");
    value
}

#[test]
fn durable_publication_is_required_before_agentd_run_admission() {
    let directory = tempdir().expect("tempdir");
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(directory.path().join("objective.ledger"))
        .expect("ledger file");
    let mut ledger = DurableLedger::create(file, digest("ledger-binding"), 16).expect("ledger");

    let profile = profile();
    let source = source();
    let context = ObjectiveAdmissionContextV1 {
        revision: Revision::new(7).expect("revision"),
        now_unix_micros: NOW_MICROS,
        selected_profile_digest: profile.digest().expect("profile digest"),
        source_authentication: ObjectiveSourceAuthenticationV1::Principal {
            principal_scope_digest: source.principal_scope_digest,
            source_digest: source.structured_intent.provenance.source_digest,
        },
    };
    let bindings = || ProductionRunBindingsV1 {
        record_id: id("run-start-record-agentd"),
        run_id: id("run-agentd"),
        preference_state_digest: digest("preference"),
        model_tuple_digest: digest("model"),
        prompt_registry_digest: digest("prompt"),
        artifact_set_digest: digest("artifacts"),
        authority_epoch: 11,
        generation: 3,
        fence_digest: digest("runtime-fence"),
        expected_ledger_predecessor: Digest32::ZERO,
    };

    let mut coordinator = AgentRunCoordinator::compose_runtime(RuntimeComposition {
        agent_id: "agent.1".to_string(),
        supervisor_generation: 2,
        agentd_generation: 3,
        authority_epoch: 11,
        configuration_digest: digest("configuration").to_string(),
        ports_digest: digest("ports").to_string(),
        fence_digest: digest("runtime-fence").to_string(),
    })
    .expect("runtime composition");
    let first = prepare_and_start_intelligence_run_v1(
        &mut coordinator,
        ObjectiveProductRunRequestV1 {
            now_ms: NOW_MICROS / 1_000,
            body_digest: digest("body"),
            journal: &mut ledger,
            source: &source,
            profile: &profile,
            context: &context,
            bindings: bindings(),
        },
    )
    .expect("prepare and start published run");
    let ObjectiveProductRunDispositionV1::Started {
        publication,
        runtime,
    } = first
    else {
        panic!("expected started product run");
    };
    assert_eq!(runtime.phase, RunPhase::Admitted);
    assert!(!runtime.idempotent);
    assert_eq!(publication.durable_append().disposition, AppendDisposition::Appended);
    assert_eq!(ledger.records().expect("records").len(), 1);

    let replay = prepare_and_start_intelligence_run_v1(
        &mut coordinator,
        ObjectiveProductRunRequestV1 {
            now_ms: NOW_MICROS / 1_000,
            body_digest: digest("body"),
            journal: &mut ledger,
            source: &source,
            profile: &profile,
            context: &context,
            bindings: bindings(),
        },
    )
    .expect("idempotent product replay");
    let ObjectiveProductRunDispositionV1::Started {
        publication: replay_publication,
        runtime: replay_runtime,
    } = replay
    else {
        panic!("expected replayed product run");
    };
    assert!(replay_runtime.idempotent);
    assert_eq!(
        replay_publication.durable_append().disposition,
        AppendDisposition::IdempotentReplay
    );
    assert_eq!(ledger.records().expect("records").len(), 1);

    let mut stale = AgentRunCoordinator::compose_runtime(RuntimeComposition {
        agent_id: "agent.2".to_string(),
        supervisor_generation: 2,
        agentd_generation: 4,
        authority_epoch: 11,
        configuration_digest: digest("configuration").to_string(),
        ports_digest: digest("ports").to_string(),
        fence_digest: digest("runtime-fence").to_string(),
    })
    .expect("stale runtime composition");
    let error = prepare_and_start_intelligence_run_v1(
        &mut stale,
        ObjectiveProductRunRequestV1 {
            now_ms: NOW_MICROS / 1_000,
            body_digest: digest("body"),
            journal: &mut ledger,
            source: &source,
            profile: &profile,
            context: &context,
            bindings: bindings(),
        },
    )
    .expect_err("stale runtime must reject after idempotent durable publication");
    assert!(matches!(
        error,
        ObjectiveProductRunError::Runtime {
            error: ObjectiveHostError::Runtime(AgentRunError::RuntimeBindingMismatch),
            ..
        }
    ));
    let retained = error
        .durable_publication()
        .expect("runtime failure retains durable publication");
    assert_eq!(
        retained.durable_append().disposition,
        AppendDisposition::IdempotentReplay
    );
    assert_eq!(ledger.records().expect("records").len(), 1);
}
