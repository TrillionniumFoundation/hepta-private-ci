//! Test-only owner fixture. All verified phases traverse the real public
//! signature checks; no constructor or trust bypass is exposed by production.
use codex_hepta_contracts::{
    FinalUseAuthority, FinalUseGrant, FinalUseRevocations, SignedFinalUseGrant,
};
use codex_hepta_learning_ledger::*;
use codex_hepta_prompt_optimizer::canonical as policy;
use codex_hepta_prompt_registry::*;
use codex_hepta_types::{AuthorityPosture, Digest32, FixedQ32, Generation, Revision, StableId};
use ed25519_dalek::{Signer, SigningKey};
use policy::knowledge_graph as kg;
use std::collections::BTreeSet;
use std::path::Path;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

pub(super) fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|e| panic!("fixture id: {e}"))
}
pub(super) fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

pub(super) struct FixtureSource {
    pub(super) snapshot: Mutex<policy::PromptEvidenceSnapshotV1>,
}

impl FixtureSource {
    pub(super) fn for_candidates(candidates: &policy::EnumeratedPromptCandidatesV1) -> Arc<Self> {
        let scope = digest("scope:prompt-fixture");
        let signers = [
            (
                "generator",
                "generator-controller",
                7_u8,
                LearningEvidenceRoleV1::Generator,
            ),
            (
                "evaluator",
                "evaluator-controller",
                9_u8,
                LearningEvidenceRoleV1::Evaluator,
            ),
        ]
        .into_iter()
        .map(|(principal, controller, seed, role)| {
            let key = SigningKey::from_bytes(&[seed; 32])
                .verifying_key()
                .to_bytes();
            TrustedLearningSignerV1 {
                principal: AuthenticatedPrincipalV1 {
                    principal_id: id(principal),
                    credential_chain_digest: Digest32::of_bytes(&key),
                    signing_key_digest: Digest32::of_bytes(&key),
                    scope_digest: scope,
                    authority_epoch: 1,
                    authenticated_at: 1,
                    expires_at: 9_000,
                },
                controller_id: id(controller),
                verifying_key: key,
                roles: vec![role],
                revoked_at: None,
            }
        })
        .collect();
        let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: scope,
            objective_digest: candidates.receipt.objective_digest,
            authority_epoch: 1,
            signers,
        })
        .unwrap_or_else(|e| panic!("fixture trust: {e}"));
        let nodes = candidates
            .candidates
            .iter()
            .map(|candidate| kg::KnowledgeNodeV2 {
                node_id: candidate.factor_id.clone(),
                node_kind_id: id("kind:prompt-factor"),
                payload_digest: candidate.binding_digest,
                supports: vec![kg::KnowledgeSupportV2 {
                    source_id: candidate.factor_id.clone(),
                    source_revision: Revision::new(1).unwrap_or_else(|e| panic!("revision: {e}")),
                    source_fact_digest: candidate.binding_digest,
                    validity_digest: candidates.registry_snapshot.snapshot_digest,
                    valid_from_unix_seconds: None,
                    valid_to_unix_seconds: None,
                    tombstoned: false,
                }],
            })
            .collect();
        let graph = kg::build_complete_generation(
            Generation::new(1).unwrap_or_else(|e| panic!("generation: {e}")),
            kg::KnowledgeProjectionInputV2 {
                source_snapshot_digest: candidates.registry_snapshot.snapshot_digest,
                generation_vector_digest: candidates.generation_vector_digest,
                graph_profile_digest: digest("fixture-graph-profile"),
                complete_source_cut: true,
                nodes,
                edges: Vec::new(),
            },
        )
        .unwrap_or_else(|e| panic!("fixture graph: {e}"));
        Arc::new(Self {
            snapshot: Mutex::new(policy::PromptEvidenceSnapshotV1 {
                source_id: id("source:prompt-fixture"),
                verifier,
                graph,
                pricing_policy: policy::PromptPricingPolicyV1 {
                    policy_id: id("pricing:fixture"),
                    token_cost_per_token_q32: FixedQ32::ZERO,
                    latency_cost_per_micro_q32: FixedQ32::ZERO,
                    interference_cost_per_ppm_q32: FixedQ32::ZERO,
                    downside_weight_q32: FixedQ32::ONE,
                    minimum_support_count: 1,
                    maximum_interference_ppm: 1_000_000,
                },
                exercise_policy: policy::PromptExercisePolicyV1 {
                    policy_id: id("exercise:fixture"),
                    objective_digest: candidates.receipt.objective_digest,
                    scope_digest: scope,
                    state_digest: candidates.receipt.state_digest,
                    generation_vector_digest: candidates.generation_vector_digest,
                    model_tuple_digest: candidates.model_tuple.digest(),
                    allowed_boundaries: vec![
                        policy::PromptDecisionBoundaryV1::BeforeModelOrToolDispatch,
                    ],
                    wait_value_q32: FixedQ32::ZERO,
                    not_before_unix_ms: 1,
                    valid_until_unix_ms: 9_000,
                },
            }),
        })
    }
}

fn signed(
    current: &policy::PromptEvidenceSnapshotV1,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let (principal, seed) = match role {
        LearningEvidenceRoleV1::Generator => ("generator", 7_u8),
        LearningEvidenceRoleV1::Evaluator => ("evaluator", 9_u8),
        _ => panic!("fixture only signs generator/evaluator roles"),
    };
    let payload_digest = Digest32::of_bytes(payload);
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("evidence:{payload_digest}")),
        principal_id: id(principal),
        role,
        trust_digest: current.verifier.trust_digest(),
        scope_digest: current.verifier.scope_digest(),
        objective_digest: current.verifier.objective_digest(),
        authority_epoch: current.verifier.authority_epoch(),
        issued_at: 1,
        expires_at: 9_000,
        payload_digest,
        signature: [0; 64],
    };
    evidence.signature = SigningKey::from_bytes(&[seed; 32])
        .sign(&evidence.signing_bytes())
        .to_bytes();
    evidence
}

impl policy::PromptEvidenceSourceV1 for FixtureSource {
    fn current(&self) -> Result<policy::PromptEvidenceSnapshotV1, policy::CanonicalPromptError> {
        self.snapshot
            .lock()
            .map(|snapshot| snapshot.clone())
            .map_err(|_| policy::CanonicalPromptError::Quarantined)
    }
    fn pricing(
        &self,
        candidates: &policy::EnumeratedPromptCandidatesV1,
        _now: u64,
    ) -> Result<policy::PromptPricingAdmissionV1, policy::CanonicalPromptError> {
        let current = self.current()?;
        let completeness = CandidateSetCompletenessReceiptV1 {
            set_id: candidates.receipt.set_id.clone(),
            state_digest: candidates.receipt.state_digest,
            generator_id: id("prompt.optimizer"),
            generator_code_digest: digest("fixture-generator-code"),
            grammar_digest: candidates.receipt.selection_grammar_digest,
            hard_filter_digest: digest("fixture-filters"),
            truncation_digest: digest("fixture-truncation"),
            candidates_digest: candidates.candidates_digest,
            candidate_count: candidates.candidates.len() as u32,
            omitted_count_bound: candidates.omitted_count,
            canonical_order_digest: candidates.canonical_order_digest,
            complete_for_generator: true,
        };
        let completeness_evidence = signed(
            &current,
            LearningEvidenceRoleV1::Generator,
            &policy::candidate_completeness_signing_payload_v1(&completeness)?,
        );
        let estimates = candidates
            .candidates
            .iter()
            .map(|candidate| {
                let mut estimate = policy::PromptPricingEvidenceV1 {
                    factor_id: candidate.factor_id.clone(),
                    state_digest: candidates.receipt.state_digest,
                    model_tuple_digest: candidates.model_tuple.digest(),
                    expected_incremental_utility_q32: FixedQ32::ONE,
                    downside_q32: FixedQ32::ZERO,
                    confidence_lower_q32: FixedQ32::ONE,
                    confidence_upper_q32: FixedQ32::ONE,
                    support_count: 10,
                    latency_cost_micros: 0,
                    interference_ppm: 0,
                    context_crowding_cost_q32: FixedQ32::ZERO,
                    privacy_cost_q32: FixedQ32::ZERO,
                    instability_cost_q32: FixedQ32::ZERO,
                    future_context_option_cost_q32: FixedQ32::ZERO,
                    support_audit_digest: candidate.binding_digest,
                    evidence: signed(&current, LearningEvidenceRoleV1::Evaluator, b"pending"),
                };
                estimate.evidence = signed(
                    &current,
                    LearningEvidenceRoleV1::Evaluator,
                    &policy::pricing_evidence_signing_payload_v1(&estimate),
                );
                estimate
            })
            .collect::<Vec<_>>();
        let payload = policy::pricing_admission_signing_payload_v1(
            candidates,
            &estimates,
            &current.pricing_policy,
            current.verifier.scope_digest(),
        )?;
        Ok(policy::PromptPricingAdmissionV1 {
            completeness,
            completeness_evidence,
            estimates,
            binding_evidence: signed(&current, LearningEvidenceRoleV1::Evaluator, &payload),
        })
    }
    fn interactions(
        &self,
        priced: &policy::PricedPromptCandidatesV1,
        _now: u64,
    ) -> Result<policy::PromptInteractionAdmissionV1, policy::CanonicalPromptError> {
        let current = self.current()?;
        let missing_pairs = policy::PromptMissingPairPolicyV1::AssumeZeroWithWitness;
        let pairs = Vec::new();
        let payload = policy::interaction_admission_signing_payload_v1(
            priced,
            &pairs,
            &current.graph,
            missing_pairs,
        )?;
        Ok(policy::PromptInteractionAdmissionV1 {
            pairs,
            missing_pairs,
            binding_evidence: signed(&current, LearningEvidenceRoleV1::Evaluator, &payload),
        })
    }
}

pub(super) fn select(
    candidates: policy::EnumeratedPromptCandidatesV1,
    now: u64,
) -> (
    policy::SelectedPromptPortfolioV1,
    policy::PromptExerciseRequestV1,
    Arc<FixtureSource>,
) {
    use policy::PromptEvidenceSourceV1;
    let source = FixtureSource::for_candidates(&candidates);
    let current = source.current().unwrap_or_else(|e| panic!("current: {e}"));
    let exercise = policy::PromptExerciseRequestV1 {
        decision_boundary: policy::PromptDecisionBoundaryV1::BeforeModelOrToolDispatch,
        current_state_digest: candidates.receipt.state_digest,
        generation_vector_digest: candidates.generation_vector_digest,
        model_tuple: candidates.model_tuple.clone(),
        now_unix_ms: now,
        wait_value_q32: FixedQ32::ZERO,
        policy_digest: current
            .exercise_policy
            .digest()
            .unwrap_or_else(|e| panic!("policy: {e}")),
    };
    let material = source
        .pricing(&candidates, now)
        .unwrap_or_else(|e| panic!("pricing fixture: {e}"));
    let priced = policy::price_factors_v1(candidates, material, source.clone(), now)
        .unwrap_or_else(|e| panic!("admit pricing: {e}"));
    let interactions = source
        .interactions(&priced, now)
        .unwrap_or_else(|e| panic!("interactions fixture: {e}"));
    let selected = policy::select_portfolio_v1(
        &priced,
        interactions,
        policy::PromptPortfolioRequestV1 {
            portfolio_id: id("portfolio:fixture"),
            graph_query_id: id("query:fixture"),
            token_budget: 128,
            maximum_selected_factors: 16,
            requested_valid_until_unix_ms: 9_000,
        },
        now,
    )
    .unwrap_or_else(|e| panic!("select fixture: {e}"));
    (selected, exercise, source)
}

pub(super) fn admitted_registry(
    root: &Path,
    payload: &[u8],
) -> (
    DurablePromptRegistry,
    PromptModelTupleV2,
    FinalUseAuthority,
    SigningKey,
    u64,
) {
    let mut registry =
        DurablePromptRegistry::open_state_dir(root, 64).unwrap_or_else(|e| panic!("registry: {e}"));
    let factor = PromptFactor {
        factor_id: id("factor:verify"),
        proposer_id: id("proposer:fixture"),
        semantic_version: id("v1"),
        semantic_purpose: "inspect evidence before mutation".to_owned(),
        authority_class: "registered_prompt_factor".to_owned(),
        eligible_objective_dimensions: vec![id("dimension:truth")],
        content_digest: digest("factor:verify"),
        source: FactorSource::GovernedInternal,
        lifecycle: Lifecycle::Draft,
    };
    registry
        .register_factor(factor.clone())
        .unwrap_or_else(|e| panic!("factor: {e}"));
    let key = SigningKey::from_bytes(&[23; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        &root.join("fixture-authority"),
        "authority:fixture".to_owned(),
        key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .unwrap_or_else(|e| panic!("authority: {e}"));
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_else(|e| panic!("clock: {e}"))
        .as_millis() as u64;
    let reviewer = id("reviewer:fixture");
    let scope = digest("scope:registry-fixture");
    let evidence = digest("admission:fixture");
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "authority:fixture".to_owned(),
        authority_epoch: 1,
        grant_id: "grant:factor".to_owned(),
        nonce: [23; 32],
        binding: final_use_admission_binding(&factor, &reviewer, scope, evidence)
            .unwrap_or_else(|e| panic!("binding: {e}")),
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    let signed = SignedFinalUseGrant {
        signature: key
            .sign(
                &grant
                    .signing_bytes()
                    .unwrap_or_else(|e| panic!("bytes: {e}")),
            )
            .to_bytes()
            .to_vec(),
        grant,
    };
    registry
        .admit_factor_final_use(&authority, &signed, &factor.factor_id, scope, evidence)
        .unwrap_or_else(|e| panic!("admit: {e}"));
    let factor = registry
        .registry()
        .unwrap_or_else(|e| panic!("registry: {e}"))
        .factor(&factor.factor_id)
        .cloned()
        .unwrap_or_else(|| panic!("admitted factor missing"));
    let tuple = PromptModelTupleV2 {
        model_id: id("model:hepta-test"),
        model_version: "2026-09-18".to_owned(),
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
        context_profile_digest: digest("context-profile"),
        locale_id: id("locale:en-US"),
    };
    let realization = PromptRealizationBindingV2 {
        realization_id: id("realization:verify"),
        factor_id: factor.factor_id.clone(),
        model_id: tuple.model_id.clone(),
        model_version: tuple.model_version.clone(),
        model_digest: tuple.model_digest,
        tokenizer_digest: tuple.tokenizer_digest,
        template_digest: tuple.template_digest,
        tool_schema_digest: tuple.tool_schema_digest,
        context_profile_digest: tuple.context_profile_digest,
        locale_id: tuple.locale_id.clone(),
        role: PromptRoleV2::DeveloperInstruction,
        payload_digest: Digest32::of_bytes(payload),
        token_cost: 4,
        expires_unix_ms: None,
    };
    let actor = id("publisher:fixture");
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "authority:fixture".to_owned(),
        authority_epoch: 1,
        grant_id: "grant:realization".to_owned(),
        nonce: [24; 32],
        binding: final_use_realization_binding(&factor, &actor, scope, &realization, None)
            .unwrap_or_else(|e| panic!("binding: {e}")),
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    let signed = SignedFinalUseGrant {
        signature: key
            .sign(
                &grant
                    .signing_bytes()
                    .unwrap_or_else(|e| panic!("bytes: {e}")),
            )
            .to_bytes()
            .to_vec(),
        grant,
    };
    registry
        .register_realization_payload_final_use_v2(
            &authority,
            &signed,
            &actor,
            scope,
            realization,
            payload.to_vec(),
            None,
        )
        .unwrap_or_else(|e| panic!("realization: {e}"));
    let _ = AuthorityPosture::DENY_ALL;
    (registry, tuple, authority, key, now)
}
