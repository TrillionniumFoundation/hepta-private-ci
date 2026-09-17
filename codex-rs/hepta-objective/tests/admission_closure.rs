use codex_hepta_objective::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

const OBSERVED_MICROS: u64 = 1_788_861_600_000_000;
const NOW_MICROS: u64 = OBSERVED_MICROS + 1_000_000;

fn id(value: &str) -> StableId {
    StableId::new(value.to_string()).expect("valid stable ID")
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
        profile_id: id("objective.profile.readonly.v1"),
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
    refresh_intent_digest(&mut envelope);
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

fn refresh_intent_digest(envelope: &mut ObjectiveSourceEnvelopeV1) {
    envelope.intent_digest =
        canonical_objective_intent_digest_v1(envelope).expect("canonical intent digest");
}

#[test]
fn zero_caller_actions_reaches_explicit_abstain_through_bounded_admission() {
    let profile = profile();
    let mut envelope = envelope();
    envelope.structured_intent.legal_action_classes.clear();
    envelope
        .structured_intent
        .confirmation_action_classes
        .clear();
    refresh_intent_digest(&mut envelope);
    let context = context(&profile, &envelope);

    let outcome = admit_and_compile_objective_v1(&envelope, &profile, &context)
        .expect("zero-action source should admit");
    let compile = outcome.compile_result.expect("explicit abstain is non-error");
    assert_eq!(CompileDisposition::ExplicitAbstain, compile.disposition);
    assert_eq!(1, compile.objective.legal_actions.len());
    assert_eq!("abstain", compile.objective.legal_actions[0].id.as_str());
    assert!(!outcome.receipt.authority.grants_any());
}

#[test]
fn source_constraint_bound_reserves_ten_generated_constraint_slots() {
    let mut envelope = envelope();
    envelope.structured_intent.constraints = (0..=MAX_OBJECTIVE_SOURCE_CONSTRAINTS)
        .map(|index| ObjectiveSourceConstraintV1 {
            constraint_id: format!("constraint.{index:03}"),
            unit: "micros".to_string(),
            comparator: ObjectiveConstraintComparatorV1::LessThanOrEqual,
            bound_q32: 1,
            evidence_source_id: "observer.clock".to_string(),
            terminal: false,
        })
        .collect();

    let error = envelope
        .validate_structure()
        .expect_err("247 source constraints must fail before admission adds 10 more");
    assert_eq!(
        ObjectiveStructureError::CollectionCount {
            field: "constraints",
            actual: MAX_OBJECTIVE_SOURCE_CONSTRAINTS + 1,
            minimum: 1,
            maximum: MAX_OBJECTIVE_SOURCE_CONSTRAINTS,
        },
        error
    );
}

#[test]
fn predicate_arrays_share_the_native_aggregate_ceiling() {
    let mut envelope = envelope();
    envelope.structured_intent.success_predicates = (0..64)
        .map(|index| ObjectiveSourcePredicateV1 {
            predicate_id: format!("success.{index:03}"),
            unit: "ratio".to_string(),
            comparator: ObjectivePredicateComparatorV1::Equal,
            bound_q32: 0,
            evidence_source_id: "observer.task".to_string(),
            terminal: false,
        })
        .collect();
    envelope.structured_intent.terminal_conditions = (0..64)
        .map(|index| ObjectiveSourcePredicateV1 {
            predicate_id: format!("terminal.{index:03}"),
            unit: "boolean".to_string(),
            comparator: ObjectivePredicateComparatorV1::Equal,
            bound_q32: 0,
            evidence_source_id: "observer.task".to_string(),
            terminal: true,
        })
        .collect();
    // The fixture already carries one evidence requirement: 64 + 64 + 1 = 129.
    let error = envelope
        .validate_structure()
        .expect_err("individually valid arrays must still obey aggregate native bound");
    assert_eq!(
        ObjectiveStructureError::CollectionCount {
            field: "successPredicates+terminalConditions+evidenceRequirements",
            actual: MAX_OBJECTIVE_AGGREGATE_PREDICATES + 1,
            minimum: 0,
            maximum: MAX_OBJECTIVE_AGGREGATE_PREDICATES,
        },
        error
    );
}

#[test]
fn caller_action_bound_reserves_intrinsic_abstain_slot() {
    let mut envelope = envelope();
    envelope.structured_intent.legal_action_classes = (0..=MAX_OBJECTIVE_CALLER_ACTIONS)
        .map(|index| format!("action.{index:03}"))
        .collect();
    envelope
        .structured_intent
        .confirmation_action_classes
        .clear();

    let error = envelope
        .validate_structure()
        .expect_err("128 caller actions would consume the abstain slot");
    assert_eq!(
        ObjectiveStructureError::CollectionCount {
            field: "legalActionClasses",
            actual: MAX_OBJECTIVE_CALLER_ACTIONS + 1,
            minimum: 0,
            maximum: MAX_OBJECTIVE_CALLER_ACTIONS,
        },
        error
    );
}

#[test]
fn public_admission_returns_inclusion_minimal_profile_bound_conflict() {
    let mut profile = profile();
    profile.constraints.push(ObjectiveConstraintProfileV1 {
        source_constraint_id: "latency.floor".to_string(),
        expected_unit: "micros".to_string(),
        class: ConstraintClass::Task,
        axis: id("latency.micros"),
    });
    let mut envelope = envelope();
    envelope
        .structured_intent
        .constraints
        .push(ObjectiveSourceConstraintV1 {
            constraint_id: "latency.floor".to_string(),
            unit: "micros".to_string(),
            comparator: ObjectiveConstraintComparatorV1::GreaterThanOrEqual,
            bound_q32: 6_000,
            evidence_source_id: "observer.clock".to_string(),
            terminal: false,
        });
    refresh_intent_digest(&mut envelope);
    let context = context(&profile, &envelope);

    let outcome = admit_and_compile_objective_v1(&envelope, &profile, &context)
        .expect("semantic conflict is a typed non-error outcome");
    let conflict = outcome.compile_result.expect_err("bounds are contradictory");
    assert_eq!(
        vec![id("latency.ceiling"), id("latency.floor")],
        conflict.conflicting_ids
    );
    assert_eq!(outcome.receipt.admitted_source_digest, conflict.source_digest);
}
