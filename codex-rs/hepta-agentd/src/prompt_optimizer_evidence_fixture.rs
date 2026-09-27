//! Test-only owner fixture. All verified phases traverse the real public
//! signature checks; no constructor or trust bypass is exposed by production.
use codex_hepta_learning_ledger::*;
use codex_hepta_prompt_optimizer::canonical as policy;
use codex_hepta_types::{Digest32, FixedQ32, Generation, Revision, StableId};
use ed25519_dalek::{Signer, SigningKey};
use policy::knowledge_graph as kg;
use std::sync::Arc;
use std::sync::Mutex;

pub(super) fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|e| panic!("fixture id: {e}"))
}
pub(super) fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

pub(super) struct FixtureSource {
    pub(super) snapshot: Mutex<policy::PromptEvidenceSnapshotV1>,
    issued_at: u64,
    expires_at: u64,
}

impl FixtureSource {
    pub(super) fn for_candidates_at(
        candidates: &policy::EnumeratedPromptCandidatesV1,
        issued_at: u64,
        expires_at: u64,
    ) -> Arc<Self> {
        assert!(issued_at < expires_at, "fixture evidence window");
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
                    authenticated_at: issued_at,
                    expires_at,
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
                    not_before_unix_ms: issued_at,
                    valid_until_unix_ms: expires_at,
                },
            }),
            issued_at,
            expires_at,
        })
    }
}

fn signed(
    current: &policy::PromptEvidenceSnapshotV1,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
    issued_at: u64,
    expires_at: u64,
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
        issued_at,
        expires_at,
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
            self.issued_at,
            self.expires_at,
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
                    evidence: signed(
                        &current,
                        LearningEvidenceRoleV1::Evaluator,
                        b"pending",
                        self.issued_at,
                        self.expires_at,
                    ),
                };
                estimate.evidence = signed(
                    &current,
                    LearningEvidenceRoleV1::Evaluator,
                    &policy::pricing_evidence_signing_payload_v1(&estimate),
                    self.issued_at,
                    self.expires_at,
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
            binding_evidence: signed(
                &current,
                LearningEvidenceRoleV1::Evaluator,
                &payload,
                self.issued_at,
                self.expires_at,
            ),
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
            binding_evidence: signed(
                &current,
                LearningEvidenceRoleV1::Evaluator,
                &payload,
                self.issued_at,
                self.expires_at,
            ),
        })
    }
}
