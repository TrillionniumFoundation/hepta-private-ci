use std::fs::OpenOptions;

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
use codex_hepta_objective::ObjectiveRunStartBindingsV1;
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

use super::append_objective_run_start_v1;
use super::decode_objective_run_start_record_v1;
use crate::AppendDisposition;
use crate::DurableLedger;
use crate::LedgerAnchor;
use crate::LedgerEvent;
use crate::LedgerRecovery;

const OBSERVED_MICROS: u64 = 1_788_861_600_000_000;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn resource_axis(name: &str) -> ObjectiveResourceAxisProfileV1 {
    ObjectiveResourceAxisProfileV1 {
        constraint_id: id(&format!("resource.{name}.ceiling")),
        axis: id(&format!("resource.{name}")),
        class: codex_hepta_objective::ConstraintClass::Task,
        q32_per_source_unit: FixedQ32::from_raw(1),
        evidence_source: id("resource.profile"),
    }
}

fn profile() -> ObjectiveAdmissionProfileV1 {
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
        allowed_trusted_source_identities: vec![id("adapter.product")],
        constraints: vec![ObjectiveConstraintProfileV1 {
            source_constraint_id: "latency.ceiling".to_string(),
            expected_unit: "micros".to_string(),
            class: codex_hepta_objective::ConstraintClass::Constitutional,
            axis: id("latency.micros"),
        }],
        predicates: vec![
            ObjectivePredicateProfileV1 {
                source_predicate_id: "task.success".to_string(),
                expected_unit: "ratio".to_string(),
                axis: id("task.success"),
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
            axis: id("evidence.quality"),
        }],
        resources: ObjectiveResourceProfileV1 {
            time_micros: resource_axis("time"),
            token_count: resource_axis("tokens"),
            compute_micros: resource_axis("compute"),
            memory_bytes: resource_axis("memory"),
            network_bytes: resource_axis("network"),
            external_effect_count: resource_axis("effects"),
        },
        risk: ObjectiveRiskProfileV1 {
            evidence_source: id("risk.profile"),
            class: codex_hepta_objective::ConstraintClass::Principal,
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
        request_id: "request.product.1".to_string(),
        principal_scope_digest: digest("principal-scope"),
        intent_digest: Digest32::ZERO,
        structured_intent: ObjectiveStructuredIntentV1 {
            success_predicates: vec![ObjectiveSourcePredicateV1 {
                predicate_id: "task.success".to_string(),
                unit: "ratio".to_string(),
                comparator: ObjectivePredicateComparatorV1::GreaterThanOrEqual,
                bound_q32: FixedQ32::ONE.raw(),
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
        now_unix_micros: OBSERVED_MICROS + 1_000_000,
        selected_profile_digest: profile.digest().expect("profile digest"),
        source_authentication: ObjectiveSourceAuthenticationV1::Principal {
            principal_scope_digest: envelope.principal_scope_digest,
            source_digest: envelope.structured_intent.provenance.source_digest,
        },
    }
}

fn bindings() -> ObjectiveRunStartBindingsV1 {
    ObjectiveRunStartBindingsV1 {
        run_id: id("run.product.1"),
        preference_state_digest: digest("preference"),
        model_tuple_digest: digest("model"),
        prompt_registry_digest: digest("prompt"),
        artifact_set_digest: digest("artifact"),
        authority_epoch: 3,
        generation: 5,
        fence_digest: digest("fence"),
    }
}

#[test]
fn objective_and_run_start_commit_atomically_replay_after_reopen() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("learning.ledger");
    let binding = digest("learning-ledger-binding");
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(&path)
        .expect("create ledger");
    let mut ledger = DurableLedger::create(file, binding, 32).expect("create durable ledger");

    let profile = profile();
    let envelope = envelope();
    let context = context(&profile, &envelope);
    let first = append_objective_run_start_v1(
        &mut ledger,
        Digest32::ZERO,
        &envelope,
        &profile,
        &context,
        bindings(),
    )
    .expect("append run start");
    assert_eq!(first.append.disposition, AppendDisposition::Appended);
    assert_eq!(first.append.sequence.get(), 1);

    let replay = append_objective_run_start_v1(
        &mut ledger,
        Digest32::ZERO,
        &envelope,
        &profile,
        &context,
        bindings(),
    )
    .expect("idempotent replay");
    assert_eq!(
        replay.append.disposition,
        AppendDisposition::IdempotentReplay
    );
    assert_eq!(replay.publication, first.publication);

    let anchor = LedgerAnchor {
        sequence: first.append.sequence.get(),
        chain_digest: first.append.chain_digest,
    };
    drop(ledger);

    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&path)
        .expect("reopen ledger");
    let recovered = DurableLedger::recover(file, binding, 32, LedgerRecovery::Acknowledged(anchor))
        .expect("recover");
    let records = recovered.records().expect("records");
    let LedgerEvent::RunStart(record) = &records[0].event else {
        panic!("expected run-start record");
    };
    let decoded = decode_objective_run_start_record_v1(record).expect("decode run start");
    assert_eq!(decoded, first.publication);
}
