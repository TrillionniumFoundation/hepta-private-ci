use super::*;

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_learning_ledger::DurableRunStartJournal;
use codex_hepta_learning_ledger::RunStartAppendDisposition;
use codex_hepta_learning_ledger::RunStartAnchor;
use codex_hepta_learning_ledger::RunStartRecovery;
use codex_hepta_objective::ConstraintClass;
use codex_hepta_objective::ObjectiveAbstentionRuleProfileV1;
use codex_hepta_objective::ObjectiveActionProfileV1;
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
use codex_hepta_objective::ObjectiveSourcePredicateV1;
use codex_hepta_objective::ObjectiveSourceTrustV1;
use codex_hepta_objective::ObjectiveStructuredIntentV1;
use codex_hepta_objective::canonical_objective_intent_digest_v1;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Revision;

static NEXT: AtomicU64 = AtomicU64::new(0);
const OBSERVED_MICROS: u64 = 1_788_861_600_000_000;
const NOW_MICROS: u64 = OBSERVED_MICROS + 1_000_000;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid stable id")
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
        actions: vec![ObjectiveActionProfileV1 {
            source_action_class: "read".to_string(),
            action_id: id("action.read"),
        }],
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
    refresh(&mut envelope);
    envelope
}

fn refresh(envelope: &mut ObjectiveSourceEnvelopeV1) {
    envelope.intent_digest =
        canonical_objective_intent_digest_v1(envelope).expect("canonical intent");
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

fn bindings(run: &str, expected: Digest32) -> ObjectiveRunBindingsV1 {
    ObjectiveRunBindingsV1 {
        run_id: id(run),
        preference_state_digest: digest("preference-state"),
        model_tuple_digest: digest("model-tuple"),
        prompt_registry_digest: digest("prompt-registry"),
        artifact_set_digest: digest("artifact-set"),
        authority_epoch: 11,
        generation: 17,
        fence_digest: digest("run-fence"),
        expected_run_start_head: expected,
    }
}

struct Fixture {
    root: PathBuf,
}
impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-objective-product-run-{}-{serial}",
            std::process::id()
        ));
        fs::create_dir(&root).expect("create dir");
        OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(root.join("run-start"))
            .expect("create file");
        Self { root }
    }
    fn file(&self) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(self.root.join("run-start"))
            .expect("open")
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

#[test]
fn authenticated_objective_is_durable_before_product_receipt_returns() {
    let fixture = Fixture::new();
    let mut journal = DurableRunStartJournal::create(
        fixture.file(),
        digest("principal-run-start-scope"),
        16,
    )
    .expect("journal");
    let profile = profile();
    let envelope = envelope();
    let context = context(&profile, &envelope);
    let receipt = compile_and_publish_objective_run_v1(
        &envelope,
        &profile,
        &context,
        bindings("run-1", Digest32::ZERO),
        &mut journal,
    )
    .expect("publish");

    assert_eq!(AuthorityPosture::DENY_ALL, receipt.authority);
    assert_eq!(
        receipt.objective.objective.semantic_digest,
        receipt.run_start.objective_digest
    );
    assert_eq!(
        receipt.objective.objective.hard_constraint_digest,
        receipt.run_start.hard_constraint_digest
    );
    assert_eq!(
        RunStartAppendDisposition::Appended,
        receipt.publication.disposition
    );
    let anchor = RunStartAnchor {
        sequence: receipt.publication.sequence,
        chain_digest: receipt.publication.chain_digest,
    };
    drop(journal);

    let reopened = DurableRunStartJournal::recover(
        fixture.file(),
        digest("principal-run-start-scope"),
        16,
        RunStartRecovery::Acknowledged(anchor),
    )
    .expect("recover");
    let durable = reopened
        .get(&id("run-1"))
        .expect("read")
        .expect("record");
    assert_eq!(durable.snapshot, receipt.run_start);
    assert_eq!(
        Digest32::of_bytes(&durable.objective_semantic_bytes),
        receipt.objective.objective.semantic_digest
    );
}

#[test]
fn exact_product_retry_is_idempotent_and_semantic_drift_conflicts() {
    let fixture = Fixture::new();
    let mut journal = DurableRunStartJournal::create(
        fixture.file(),
        digest("principal-run-start-scope"),
        16,
    )
    .expect("journal");
    let profile = profile();
    let envelope = envelope();
    let context = context(&profile, &envelope);
    let first = compile_and_publish_objective_run_v1(
        &envelope,
        &profile,
        &context,
        bindings("run-1", Digest32::ZERO),
        &mut journal,
    )
    .expect("first");
    let retry = compile_and_publish_objective_run_v1(
        &envelope,
        &profile,
        &context,
        bindings("run-1", Digest32::ZERO),
        &mut journal,
    )
    .expect("retry");
    assert_eq!(
        RunStartAppendDisposition::IdempotentReplay,
        retry.publication.disposition
    );
    assert_eq!(first.publication.chain_digest, retry.publication.chain_digest);

    let mut changed = envelope.clone();
    changed.structured_intent.success_predicates[0].bound_q32 += 1;
    refresh(&mut changed);
    let changed_context = context(&profile, &changed);
    assert!(matches!(
        compile_and_publish_objective_run_v1(
            &changed,
            &profile,
            &changed_context,
            bindings("run-1", Digest32::ZERO),
            &mut journal,
        ),
        Err(ObjectiveRunError::RunStart(RunStartStoreError::Conflict))
    ));
}

#[test]
fn compiler_conflict_never_publishes_run_start() {
    let fixture = Fixture::new();
    let mut journal = DurableRunStartJournal::create(
        fixture.file(),
        digest("principal-run-start-scope"),
        16,
    )
    .expect("journal");
    let profile = profile();
    let mut envelope = envelope();
    envelope.structured_intent.forbidden_action_classes = vec!["read".to_string()];
    refresh(&mut envelope);
    let context = context(&profile, &envelope);
    assert!(matches!(
        compile_and_publish_objective_run_v1(
            &envelope,
            &profile,
            &context,
            bindings("run-conflict", Digest32::ZERO),
            &mut journal,
        ),
        Err(ObjectiveRunError::Conflict(_))
    ));
    assert!(journal.records().expect("records").is_empty());
}
