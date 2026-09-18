use std::collections::BTreeSet;
use std::fmt::Debug;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;

use codex_hepta_cognitive_read::ReadRequest;
use codex_hepta_cognitive_read::read;
use codex_hepta_cognitive_types::Citation;
use codex_hepta_cognitive_types::CognitiveSnapshot;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::build_snapshot;
use codex_hepta_context_compiler::CompilationRequest;
use codex_hepta_context_compiler::ContextItem;
use codex_hepta_context_compiler::ContextCompilationRequestV2;
use codex_hepta_context_compiler::ContextModelProfileV2;
use codex_hepta_context_compiler::ContextRole;
use codex_hepta_ndu::AxisDirection;
use codex_hepta_ndu::AxisValue;
use codex_hepta_ndu::FeasibilityPosture;
use codex_hepta_ndu::RequiredOrganSet;
use codex_hepta_ndu::UtilityProfile;
use codex_hepta_objective::ConstraintClass;
use codex_hepta_objective::ObjectiveAbstentionRuleProfileV1;
use codex_hepta_objective::ObjectiveActionProfileV1;
use codex_hepta_objective::ObjectiveAdmissionContextV1;
use codex_hepta_objective::ObjectiveAdmissionError;
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
use codex_hepta_objective::admit_and_compile_objective_v1;
use codex_hepta_objective::canonical_objective_intent_digest_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_prompt_optimizer::registry_source::RegistryCandidateScore;
use codex_hepta_prompt_optimizer::registry_source::RegistryOptimizationRequest;
use codex_hepta_prompt_registry::AdmissionRequest;
use codex_hepta_prompt_registry::FactorSource;
use codex_hepta_prompt_registry::Lifecycle;
use codex_hepta_prompt_registry::PromptFactor;
use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRealizationBindingV2;
use codex_hepta_prompt_registry::PromptRegistry;
use codex_hepta_prompt_registry::PromptRoleV2;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::PlanDecision;
use crate::ReadOnlyUtilityContribution;
use crate::ReadOnlyVerticalError;
use crate::ReadOnlyVerticalRequest;
use crate::run_read_only_vertical;

const OBSERVED_MICROS: u64 = 1_788_861_600_000_000;
const NOW_MICROS: u64 = OBSERVED_MICROS + 1_000_000;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value.to_string()))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn revision(value: u64) -> Revision {
    must(Revision::new(value))
}

fn generation(value: u64) -> Generation {
    must(Generation::new(value))
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

fn objective_profile() -> ObjectiveAdmissionProfileV1 {
    ObjectiveAdmissionProfileV1 {
        profile_id: id("objective.profile.readonly.v1"),
        profile_revision: revision(1),
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

fn objective_envelope() -> ObjectiveSourceEnvelopeV1 {
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
    envelope.intent_digest = must(canonical_objective_intent_digest_v1(&envelope));
    envelope
}

fn objective_context(
    profile: &ObjectiveAdmissionProfileV1,
    envelope: &ObjectiveSourceEnvelopeV1,
) -> ObjectiveAdmissionContextV1 {
    ObjectiveAdmissionContextV1 {
        revision: revision(7),
        now_unix_micros: NOW_MICROS,
        selected_profile_digest: must(profile.digest()),
        source_authentication: ObjectiveSourceAuthenticationV1::Principal {
            principal_scope_digest: envelope.principal_scope_digest,
            source_digest: envelope.structured_intent.provenance.source_digest,
        },
    }
}

fn cognitive_snapshot() -> CognitiveSnapshot {
    must(build_snapshot(
        generation(1),
        vec![MemoryRecord {
            record_id: id("memory.fact.001"),
            revision: revision(1),
            kind: MemoryKind::Fact,
            content_digest: digest("remembered-fact"),
            predecessor_digest: None,
            citations: vec![Citation {
                source_id: id("source.observer.001"),
                source_digest: digest("source-observation"),
            }],
            state: RecordState::Live,
        }],
    ))
}

fn utility_contribution(candidate: &str, value: FixedQ32) -> ReadOnlyUtilityContribution {
    ReadOnlyUtilityContribution {
        candidate_id: id(candidate),
        organ_id: id("planner"),
        feasibility: FeasibilityPosture::Feasible,
        utility: vec![AxisValue {
            axis: id("quality.ratio"),
            value,
        }],
        risk: Vec::new(),
        resource: Vec::new(),
        uncertainty: vec![AxisValue {
            axis: id("quality.ratio"),
            value: FixedQ32::ZERO,
        }],
    }
}

fn vertical_request() -> ReadOnlyVerticalRequest {
    let profile = objective_profile();
    let envelope = objective_envelope();
    let objective_context = objective_context(&profile, &envelope);
    let objective_outcome = must(admit_and_compile_objective_v1(
        &envelope,
        &profile,
        &objective_context,
    ));
    let objective_digest = match objective_outcome.compile_result {
        Ok(receipt) => receipt.objective.semantic_digest,
        Err(conflict) => panic!("unexpected objective conflict: {conflict:?}"),
    };
    let snapshot = cognitive_snapshot();
    let read_request = ReadRequest {
        snapshot_digest: snapshot.snapshot_digest,
        allowed_kinds: vec![MemoryKind::Fact],
        maximum_results: 8,
        include_tombstones: false,
    };
    let read_receipt = must(read(&snapshot, read_request.clone()));
    let required_read_evidence_item_id = id("context.memory.read");
    let context = CompilationRequest {
        compilation_id: id("context.compile.001"),
        run_snapshot_digest: snapshot.snapshot_digest,
        objective_digest,
        token_budget: 16,
        items: vec![
            ContextItem {
                item_id: id("context.instruction.readonly"),
                role: ContextRole::TrustedInstruction,
                content_digest: digest("readonly-instruction"),
                source_digest: digest("registered-instruction-source"),
                token_count: 2,
                contains_secret: false,
            },
            ContextItem {
                item_id: required_read_evidence_item_id.clone(),
                role: ContextRole::UntrustedEvidence,
                content_digest: read_receipt.receipt_digest,
                source_digest: snapshot.snapshot_digest,
                token_count: 2,
                contains_secret: false,
            },
        ],
    };

    ReadOnlyVerticalRequest {
        plan_id: id("plan.readonly.001"),
        objective_envelope: envelope,
        objective_profile: profile,
        objective_context,
        cognitive_snapshot: snapshot,
        cognitive_read: read_request,
        context,
        required_read_evidence_item_id,
        ndu_profile: UtilityProfile {
            profile_id: id("utility.readonly.v1"),
            dimensions: vec![(id("quality.ratio"), AxisDirection::Maximize)],
            risk_ceilings: Vec::new(),
            resource_ceilings: Vec::new(),
            required_organs: RequiredOrganSet {
                organ_ids: vec![id("planner")],
            },
        },
        ndu_scalarization_profile_id: id("scalarization.objective-derived.v1"),
        ndu_contributions: vec![
            utility_contribution("abstain", FixedQ32::ZERO),
            utility_contribution("action.read", FixedQ32::ONE),
        ],
    }
}

#[test]
fn vertical_facade_selects_only_a_legal_objective_action_without_authority() {
    let receipt = must(run_read_only_vertical(vertical_request()));

    assert_eq!(
        receipt.plan.decision,
        PlanDecision::Selected(id("action.read"))
    );
    assert!(!receipt.objective_admission.authority.grants_any());
    assert!(!receipt.cognitive_read.authority.grants_any());
    assert!(!receipt.context.authority.grants_any());
    assert!(!receipt.plan.authority.grants_any());
    assert!(!receipt.authority.grants_any());
    assert!(!receipt.plan.effect_authority);
    assert_ne!(receipt.vertical_digest, Digest32::ZERO);
    assert_eq!(
        receipt.objective.objective.semantic_digest,
        receipt.ndu.base.objective_digest
    );
    assert_ne!(receipt.ndu.evaluation_policy_digest, Digest32::ZERO);
    assert_ne!(receipt.ndu.evaluation_digest_v2, Digest32::ZERO);
    assert!(
        receipt
            .context
            .untrusted_evidence_ids
            .contains(&id("context.memory.read"))
    );
}

#[test]
fn vertical_receipt_is_stable_under_canonical_input_reordering() {
    let first = vertical_request();
    let mut second = first.clone();
    second.ndu_contributions.reverse();
    second.context.items.reverse();

    let first = must(run_read_only_vertical(first));
    let second = must(run_read_only_vertical(second));
    assert_eq!(first.vertical_digest, second.vertical_digest);
    assert_eq!(first.plan, second.plan);
}

#[test]
fn candidate_outside_compiled_legal_actions_fails_closed() {
    let mut request = vertical_request();
    request.ndu_contributions[1].candidate_id = id("action.network");

    let error = run_read_only_vertical(request).expect_err("forbidden candidate must reject");
    assert!(matches!(
        error,
        ReadOnlyVerticalError::IllegalCandidate(candidate) if candidate == "action.network"
    ));
}

#[test]
fn tampered_read_evidence_binding_fails_before_context_compilation() {
    let mut request = vertical_request();
    let evidence = request
        .context
        .items
        .iter_mut()
        .find(|item| item.item_id == request.required_read_evidence_item_id)
        .expect("read evidence item");
    evidence.content_digest = digest("tampered-read-receipt");

    let error = run_read_only_vertical(request).expect_err("tampered evidence must reject");
    assert!(matches!(
        error,
        ReadOnlyVerticalError::InvalidReadEvidenceItem(item)
            if item == "context.memory.read"
    ));
}

#[test]
fn objective_soft_dimensions_must_bind_the_ndu_profile() {
    let mut request = vertical_request();
    request.ndu_profile.dimensions[0].0 = id("quality.other");

    let error = run_read_only_vertical(request).expect_err("dimension drift must reject");
    assert!(matches!(
        error,
        ReadOnlyVerticalError::SoftDimensionMismatch
    ));
}

#[test]
fn selected_objective_profile_digest_cannot_be_replaced() {
    let mut request = vertical_request();
    request.objective_context.selected_profile_digest = digest("different-profile");

    let error = run_read_only_vertical(request).expect_err("profile mismatch must reject");
    assert!(matches!(
        error,
        ReadOnlyVerticalError::ObjectiveAdmission(ObjectiveAdmissionError::ProfileDigestMismatch)
    ));
}

#[test]
fn omitted_cognitive_read_evidence_fails_closed() {
    let mut request = vertical_request();
    request.context.token_budget = 2;

    let error = run_read_only_vertical(request).expect_err("omitted read evidence must reject");
    assert!(matches!(
        error,
        ReadOnlyVerticalError::ReadEvidenceOmitted(item)
            if item == "context.memory.read"
    ));
}


fn admit_registry_factor(registry: &mut PromptRegistry, factor_id: &str) {
    let directory = tempfile::tempdir().expect("authority directory");
    let now = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_millis(),
    )
    .expect("time fits");
    let signing_seed = Digest32::of_bytes(&now.to_be_bytes()).into_array();
    let signing = SigningKey::from_bytes(&signing_seed);
    let authority = FinalUseAuthority::open_state_dir(
        directory.path(),
        "intelligence-prompt-review-owner".to_string(),
        signing.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority");
    let request = AdmissionRequest {
        factor_id: id(factor_id),
        reviewer_id: id("reviewer:intelligence"),
        evidence_digest: digest("prompt-review-evidence"),
        reviewed_scope_digest: digest("prompt-review-scope"),
    };
    let binding = registry.admission_binding(&request).expect("admission binding");
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "intelligence-prompt-review-owner".to_string(),
        authority_epoch: 1,
        grant_id: "intelligence-prompt-admission".to_string(),
        nonce: Digest32::of_bytes(&now.saturating_add(1).to_be_bytes()).into_array(),
        binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now.saturating_add(30_000),
    };
    let signature = signing
        .sign(&grant.signing_bytes().expect("signing bytes"))
        .to_bytes()
        .to_vec();
    let signed = SignedFinalUseGrant { grant, signature };
    let token = authority
        .claim(&signed, &signed.grant.binding)
        .expect("claim admission");
    registry
        .admit_factor_authorized(&authority, token, request)
        .expect("admit factor");
}

#[test]
fn intelligence_control_composes_registry_optimizer_and_context_v2() {
    let request = vertical_request();
    let objective_digest = request.context.objective_digest;
    let mut registry = PromptRegistry::new(64).expect("prompt registry");
    registry
        .register_factor(PromptFactor {
            factor_id: id("factor:verify"),
            proposer_id: id("proposer:verify"),
            semantic_version: id("v1"),
            content_digest: digest("factor:verify"),
            source: FactorSource::GovernedInternal,
            lifecycle: Lifecycle::Draft,
        })
        .expect("register factor");
    admit_registry_factor(&mut registry, "factor:verify");

    let payload = b"Verify evidence before the final answer.".to_vec();
    let binding = PromptRealizationBindingV2 {
        realization_id: id("realization:verify"),
        factor_id: id("factor:verify"),
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
        context_profile_digest: digest("context-profile"),
        locale_id: id("locale:en-US"),
        role: PromptRoleV2::DeveloperInstruction,
        payload_digest: Digest32::of_bytes(&payload),
        token_cost: 8,
        expires_unix_ms: None,
        predecessor_realization_id: None,
    };
    registry
        .register_realization_v2(binding.clone(), payload.clone())
        .expect("register realization");
    let model_tuple = PromptModelTupleV2 {
        model_digest: binding.model_digest,
        tokenizer_digest: binding.tokenizer_digest,
        template_digest: binding.template_digest,
        tool_schema_digest: binding.tool_schema_digest,
        context_profile_digest: binding.context_profile_digest,
        locale_id: binding.locale_id.clone(),
    };
    let generation_vector_digest = digest("prompt-generation");
    let snapshot = registry
        .snapshot_v2(generation_vector_digest, &model_tuple)
        .expect("registry snapshot");

    let (portfolio, compiled, resolutions) = request
        .compose_prompt_registry_v2(
            &registry,
            &snapshot,
            RegistryOptimizationRequest {
                decision_id: id("prompt-decision"),
                objective_digest,
                generation_vector_digest,
                model_tuple: model_tuple.clone(),
                now_unix_ms: 1,
                budget: 64,
                maximum_selected: 1,
                scores: vec![RegistryCandidateScore {
                    factor_id: binding.factor_id.clone(),
                    expected_gain: FixedQ32::from_raw(1_i64 << 31),
                    legal: true,
                    support_digest: digest("prompt-support"),
                }],
            },
            ContextCompilationRequestV2 {
                compilation_id: id("prompt-context"),
                objective_digest,
                prompt_portfolio_digest: Digest32::ZERO,
                generation_vector_digest,
                model_profile: ContextModelProfileV2 {
                    model_digest: model_tuple.model_digest,
                    tokenizer_digest: model_tuple.tokenizer_digest,
                    template_digest: model_tuple.template_digest,
                    tool_schema_digest: model_tuple.tool_schema_digest,
                    maximum_context_tokens: 4_096,
                },
                token_budget: 64,
                truncation_policy_digest: digest("prompt-truncation"),
                candidates: Vec::new(),
                mandatory_groups: Vec::new(),
            },
        )
        .expect("compose prompt registry");

    assert_eq!(portfolio.selected, vec![binding.realization_id.clone()]);
    assert_eq!(
        compiled.receipt.prompt_portfolio_digest,
        portfolio.receipt_digest
    );
    assert_eq!(
        compiled.receipt.selected_item_ids,
        vec![binding.realization_id.clone()]
    );
    assert_eq!(resolutions.len(), 1);
    assert_eq!(resolutions[0].payload, payload);
    assert!(!portfolio.authority.grants_any());
    assert!(!compiled.receipt.authority.grants_any());
}
