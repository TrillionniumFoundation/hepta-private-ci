use std::fs::OpenOptions;

use codex_hepta_learning_ledger::AppendDisposition;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::LedgerAnchor;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerRecovery;
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

use super::ProductionObjectiveDispositionV1;
use super::ProductionObjectiveError;
use super::ProductionRunBindingsV1;
use super::prepare_intelligence_run_v1;

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
        profile_id: id("objective.profile.production.v1"),
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
    let source_digest = digest("source-bytes");
    let mut source = ObjectiveSourceEnvelopeV1 {
        request_id: "request.production.001".to_string(),
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
    source.intent_digest =
        canonical_objective_intent_digest_v1(&source).expect("canonical intent");
    source
}

fn context(profile: &ObjectiveAdmissionProfileV1, source: &ObjectiveSourceEnvelopeV1) -> ObjectiveAdmissionContextV1 {
    ObjectiveAdmissionContextV1 {
        revision: Revision::new(7).expect("revision"),
        now_unix_micros: NOW_MICROS,
        selected_profile_digest: profile.digest().expect("profile digest"),
        source_authentication: ObjectiveSourceAuthenticationV1::Principal {
            principal_scope_digest: source.principal_scope_digest,
            source_digest: source.structured_intent.provenance.source_digest,
        },
    }
}

fn bindings(record_id: &str, run_id: &str, predecessor: Digest32) -> ProductionRunBindingsV1 {
    ProductionRunBindingsV1 {
        record_id: id(record_id),
        run_id: id(run_id),
        preference_state_digest: digest("preference-state"),
        model_tuple_digest: digest("model-tuple"),
        prompt_registry_digest: digest("prompt-registry"),
        artifact_set_digest: digest("artifact-set"),
        runtime_body_digest: digest("runtime-body"),
        authority_epoch: 11,
        generation: 3,
        fence_digest: digest("fence"),
        expected_ledger_predecessor: predecessor,
    }
}

#[test]
fn product_objective_is_one_durable_replayable_run_start() {
    let directory = tempdir().expect("tempdir");
    let path = directory.path().join("learning.ledger");
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(&path)
        .expect("create ledger");
    let binding = digest("ledger-binding");
    let mut ledger = DurableLedger::create(file, binding, 16).expect("ledger");
    let profile = profile();
    let source = source();
    let context = context(&profile, &source);

    let result = prepare_intelligence_run_v1(
        &mut ledger,
        &source,
        &profile,
        &context,
        bindings("run-start-record-1", "run-1", Digest32::ZERO),
    )
    .expect("prepare product run");
    let ProductionObjectiveDispositionV1::Published(receipt) = result else {
        panic!("expected published run")
    };
    receipt.validate().expect("valid product receipt");
    assert_eq!(ledger.records().expect("records").len(), 1);
    let chain_digest = receipt.durable_append.chain_digest;
    assert_eq!(receipt.durable_append.disposition, AppendDisposition::Appended);
    drop(ledger);

    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&path)
        .expect("reopen ledger");
    let recovered = DurableLedger::recover(
        file,
        binding,
        16,
        LedgerRecovery::Acknowledged(LedgerAnchor {
            sequence: 1,
            chain_digest,
        }),
    )
    .expect("recover ledger");
    let records = recovered.records().expect("records");
    assert_eq!(records.len(), 1);
    let LedgerEvent::RunStart(publication) = &records[0].event else {
        panic!("expected run-start publication")
    };
    assert_eq!(publication.run_start.run_id, id("run-1"));
    assert_eq!(
        publication.compile.objective.semantic_digest,
        receipt.objective.objective.semantic_digest
    );
    assert_eq!(publication.runtime_body_digest, digest("runtime-body"));
    assert_eq!(
        publication.objective_v1_digest,
        receipt.objective_v1_digest,
        "recovered canonical digest must match the product receipt"
    );
    assert_eq!(
        publication.objective_v1_json,
        receipt.objective_v1.canonical_json().expect("canonical objective"),
        "recovery must preserve exact registered ObjectiveFunctionV1 bytes"
    );
    publication
        .run_start
        .validate_for_objective(
            &publication.compile.objective,
            publication.objective_v1_digest,
        )
        .expect("recovered run-start binding");
}

#[test]
fn exact_retry_is_idempotent_and_run_id_drift_conflicts() {
    let directory = tempdir().expect("tempdir");
    let path = directory.path().join("learning.ledger");
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(&path)
        .expect("create ledger");
    let mut ledger = DurableLedger::create(file, digest("ledger-binding"), 16).expect("ledger");
    let profile = profile();
    let source = source();
    let context = context(&profile, &source);

    let first = prepare_intelligence_run_v1(
        &mut ledger,
        &source,
        &profile,
        &context,
        bindings("run-start-record-1", "run-1", Digest32::ZERO),
    )
    .expect("first");
    assert!(matches!(first, ProductionObjectiveDispositionV1::Published(_)));

    let replay = prepare_intelligence_run_v1(
        &mut ledger,
        &source,
        &profile,
        &context,
        bindings("run-start-record-1", "run-1", Digest32::ZERO),
    )
    .expect("replay");
    let ProductionObjectiveDispositionV1::Published(replay) = replay else {
        panic!("expected replayed publication")
    };
    assert_eq!(replay.durable_append.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(ledger.records().expect("records").len(), 1);

    let conflict = prepare_intelligence_run_v1(
        &mut ledger,
        &source,
        &profile,
        &context,
        bindings(
            "run-start-record-2",
            "run-1",
            replay.durable_append.chain_digest,
        ),
    )
    .expect_err("same run id with a different record must conflict");
    assert!(matches!(
        conflict,
        ProductionObjectiveError::Durable(
            codex_hepta_learning_ledger::DurableLedgerError::Semantic(
                codex_hepta_learning_ledger::LedgerError::RunAlreadyExists(_)
            )
        )
    ));
}

#[test]
fn product_objective_named_host_measurement_receipt() {
    if std::env::var_os("HEPTA_OBJECTIVE_MEASURE").is_none() {
        return;
    }
    let directory = tempdir().expect("tempdir");
    let path = directory.path().join("learning.ledger");
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(&path)
        .expect("create ledger");
    let mut ledger = DurableLedger::create(file, digest("measurement-binding"), 128).expect("ledger");
    let profile = profile();
    let source = source();
    let context = context(&profile, &source);
    let mut predecessor = Digest32::ZERO;
    let mut micros = Vec::new();
    for index in 0..32 {
        let started = std::time::Instant::now();
        let result = prepare_intelligence_run_v1(
            &mut ledger,
            &source,
            &profile,
            &context,
            bindings(
                &format!("measure-record-{index:03}"),
                &format!("measure-run-{index:03}"),
                predecessor,
            ),
        )
        .expect("measurement run");
        let ProductionObjectiveDispositionV1::Published(receipt) = result else {
            panic!("measurement must publish");
        };
        predecessor = receipt.durable_append.chain_digest;
        micros.push(started.elapsed().as_micros());
    }
    micros.sort_unstable();
    let percentile = |numerator: usize| {
        let index = ((micros.len() - 1) * numerator + 99) / 100;
        micros[index]
    };
    println!(
        "{{\"schema\":\"hepta.objective-product-measurement.v1\",\"samples\":{},\"p50Micros\":{},\"p95Micros\":{},\"p99Micros\":{},\"path\":\"authenticated-admission+compile+durable-fsync\"}}",
        micros.len(),
        percentile(50),
        percentile(95),
        percentile(99)
    );
}
