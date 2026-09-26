use super::*;

use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRealizationBindingV2;
use codex_hepta_prompt_registry::PromptRegistrySnapshotV2;
use codex_hepta_prompt_registry::PromptRoleV2;
use codex_hepta_types::Revision;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn tuple() -> PromptModelTupleV2 {
    PromptModelTupleV2 {
        model_id: id("model:test"),
        model_version: "v1".to_owned(),
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tools"),
        context_profile_digest: digest("context"),
        locale_id: id("locale:en-US"),
    }
}

fn verified_candidates(tokens: &[u32]) -> VerifiedEnumeratedPromptCandidatesV2 {
    let tuple = tuple();
    let generation_vector_digest = digest("generation");
    let mut snapshot = PromptRegistrySnapshotV2 {
        revision: Revision::new(1).unwrap_or_else(|error| panic!("revision: {error}")),
        registry_digest: digest("registry"),
        lifecycle_frontier: 1,
        revocation_frontier: 0,
        generation_vector_digest,
        model_tuple_digest: tuple.digest(),
        snapshot_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    snapshot.snapshot_digest = snapshot.compute_snapshot_digest();
    let candidates = tokens
        .iter()
        .enumerate()
        .map(|(index, token_cost)| {
            let factor_id = id(&format!("factor:{index:03}"));
            let realization = PromptRealizationBindingV2 {
                realization_id: id(&format!("realization:{index:03}")),
                factor_id: factor_id.clone(),
                model_id: tuple.model_id.clone(),
                model_version: tuple.model_version.clone(),
                model_digest: tuple.model_digest,
                tokenizer_digest: tuple.tokenizer_digest,
                template_digest: tuple.template_digest,
                tool_schema_digest: tuple.tool_schema_digest,
                context_profile_digest: tuple.context_profile_digest,
                locale_id: tuple.locale_id.clone(),
                role: PromptRoleV2::DeveloperInstruction,
                payload_digest: digest(&format!("payload:{index:03}")),
                token_cost: *token_cost,
                expires_unix_ms: Some(10_000),
            };
            v1::PromptCandidateBindingV1 {
                factor_id,
                binding_digest: realization.digest(),
                realization,
            }
        })
        .collect::<Vec<_>>();
    let candidates_digest = digest_candidates(&candidates);
    let canonical_order_digest = digest_candidate_order(&candidates);
    let factor_ids = candidates
        .iter()
        .map(|candidate| candidate.factor_id.clone())
        .collect::<Vec<_>>();
    let mut value = v1::EnumeratedPromptCandidatesV1 {
        registry_snapshot: snapshot,
        model_tuple: tuple,
        generation_vector_digest,
        candidates_digest,
        canonical_order_digest,
        omitted_count: 0,
        candidates,
        receipt: v1::PromptCandidateSetReceiptV1 {
            set_id: id("set:test"),
            objective_digest: digest("objective"),
            state_digest: digest("state"),
            registry_digest: digest("registry"),
            candidate_factor_ids: factor_ids,
            selection_grammar_digest: digest("grammar"),
            receipt_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        },
    };
    let receipt_digest = digest_candidate_receipt(&value);
    value.receipt.receipt_digest = receipt_digest;
    VerifiedEnumeratedPromptCandidatesV2::try_from_v1(value)
        .unwrap_or_else(|error| panic!("verified candidates: {error}"))
}

fn pricing_policy() -> PromptPricingPolicyV1 {
    PromptPricingPolicyV1 {
        policy_id: id("pricing-policy:test"),
        token_cost_per_token_q32: FixedQ32::ZERO,
        latency_cost_per_micro_q32: FixedQ32::ZERO,
        interference_cost_per_ppm_q32: FixedQ32::ZERO,
        downside_weight_q32: FixedQ32::ZERO,
        minimum_support_count: 1,
        maximum_interference_ppm: 1_000_000,
    }
}

fn evidence_context(
    candidates: &VerifiedEnumeratedPromptCandidatesV2,
    policy: &PromptPricingPolicyV1,
) -> PromptEvidenceContextV2 {
    PromptEvidenceContextV2 {
        scope_digest: digest("scope"),
        objective_digest: candidates.receipt.objective_digest,
        candidate_set_digest: candidates.candidates_digest,
        registry_snapshot_digest: candidates.registry_snapshot.snapshot_digest,
        generation_vector_digest: candidates.generation_vector_digest,
        model_tuple_digest: candidates.model_tuple.digest(),
        selection_grammar_digest: candidates.receipt.selection_grammar_digest,
        generator_code_digest: digest("generator-code"),
        hard_filter_digest: digest("hard-filter"),
        truncation_digest: digest("truncation"),
        pricing_policy_digest: policy
            .digest()
            .unwrap_or_else(|error| panic!("policy digest: {error}")),
    }
}

struct TestEvidenceAuthority {
    verifier: LearningEvidenceVerifierV1,
    generator_key: SigningKey,
    evaluator_key: SigningKey,
    generator_id: StableId,
    evaluator_id: StableId,
}

fn evidence_authority(same_controller: bool, objective_digest: Digest32) -> TestEvidenceAuthority {
    let generator_key = SigningKey::from_bytes(&[11; 32]);
    let evaluator_key = SigningKey::from_bytes(&[12; 32]);
    let generator_id = id("principal:generator");
    let evaluator_id = id("principal:evaluator");
    let evaluator_controller = if same_controller {
        id("controller:shared")
    } else {
        id("controller:evaluator")
    };
    let trust = LearningEvidenceTrustV1 {
        scope_digest: digest("scope"),
        objective_digest,
        authority_epoch: 7,
        signers: vec![
            trusted_signer(
                generator_id.clone(),
                id("controller:shared"),
                &generator_key,
                LearningEvidenceRoleV1::Generator,
            ),
            trusted_signer(
                evaluator_id.clone(),
                evaluator_controller,
                &evaluator_key,
                LearningEvidenceRoleV1::Evaluator,
            ),
        ],
    };
    TestEvidenceAuthority {
        verifier: LearningEvidenceVerifierV1::new(trust)
            .unwrap_or_else(|error| panic!("evidence verifier: {error}")),
        generator_key,
        evaluator_key,
        generator_id,
        evaluator_id,
    }
}

fn trusted_signer(
    principal_id: StableId,
    controller_id: StableId,
    key: &SigningKey,
    role: LearningEvidenceRoleV1,
) -> TrustedLearningSignerV1 {
    let verifying_key = key.verifying_key().to_bytes();
    let credential_chain_digest =
        Digest32::of_bytes(format!("credential:{}", principal_id.as_str()).as_bytes());
    TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 {
            principal_id,
            credential_chain_digest,
            signing_key_digest: Digest32::of_bytes(&verifying_key),
            scope_digest: digest("scope"),
            authority_epoch: 7,
            authenticated_at: 1,
            expires_at: 10_000,
        },
        controller_id,
        verifying_key,
        roles: vec![role],
        revoked_at: None,
    }
}

fn signed_evidence(
    verifier: &LearningEvidenceVerifierV1,
    key: &SigningKey,
    principal_id: StableId,
    role: LearningEvidenceRoleV1,
    evidence_id: &str,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(evidence_id),
        principal_id,
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: verifier.scope_digest(),
        objective_digest: verifier.objective_digest(),
        authority_epoch: verifier.authority_epoch(),
        issued_at: 10,
        expires_at: 1_000,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}

fn signed_inputs(
    candidates: &VerifiedEnumeratedPromptCandidatesV2,
    authority: &TestEvidenceAuthority,
    policy: &PromptPricingPolicyV1,
) -> (PromptCompletenessEvidenceV2, Vec<PromptPricingEvidenceV2>) {
    let context = evidence_context(candidates, policy);
    let receipt = CandidateSetCompletenessReceiptV1 {
        set_id: candidates.receipt.set_id.clone(),
        state_digest: candidates.receipt.state_digest,
        generator_id: id("prompt.optimizer"),
        generator_code_digest: context.generator_code_digest,
        grammar_digest: candidates.receipt.selection_grammar_digest,
        hard_filter_digest: context.hard_filter_digest,
        truncation_digest: context.truncation_digest,
        candidates_digest: candidates.candidates_digest,
        candidate_count: u32::try_from(candidates.candidates.len()).unwrap_or(u32::MAX),
        omitted_count_bound: candidates.omitted_count,
        canonical_order_digest: candidates.canonical_order_digest,
        complete_for_generator: true,
    };
    let mut completeness = PromptCompletenessEvidenceV2 {
        receipt,
        context: context.clone(),
        evidence: placeholder_evidence(),
    };
    let completeness_payload = completeness_evidence_signing_payload_v2(&completeness);
    completeness.evidence = signed_evidence(
        &authority.verifier,
        &authority.generator_key,
        authority.generator_id.clone(),
        LearningEvidenceRoleV1::Generator,
        "evidence:completeness",
        &completeness_payload,
    );

    let pricing = candidates
        .candidates
        .iter()
        .enumerate()
        .map(|(index, candidate)| {
            let utility = i64::try_from(index)
                .unwrap_or(i64::MAX)
                .saturating_add(100);
            let mut evidence = PromptPricingEvidenceV2 {
                factor_id: candidate.factor_id.clone(),
                realization_id: candidate.realization.realization_id.clone(),
                realization_binding_digest: candidate.binding_digest,
                context: context.clone(),
                state_digest: candidates.receipt.state_digest,
                expected_incremental_utility_q32: FixedQ32::from_raw(utility),
                downside_q32: FixedQ32::ZERO,
                confidence_lower_q32: FixedQ32::from_raw(utility.saturating_sub(1)),
                confidence_upper_q32: FixedQ32::from_raw(utility.saturating_add(1)),
                support_count: 10,
                latency_cost_micros: 0,
                interference_ppm: 0,
                context_crowding_cost_q32: FixedQ32::ZERO,
                privacy_cost_q32: FixedQ32::ZERO,
                instability_cost_q32: FixedQ32::ZERO,
                future_context_option_cost_q32: FixedQ32::ZERO,
                support_audit_digest: digest(&format!("support:{index}")),
                evidence: placeholder_evidence(),
            };
            let payload = pricing_evidence_signing_payload_v2(&evidence);
            evidence.evidence = signed_evidence(
                &authority.verifier,
                &authority.evaluator_key,
                authority.evaluator_id.clone(),
                LearningEvidenceRoleV1::Evaluator,
                &format!("evidence:pricing:{index}"),
                &payload,
            );
            evidence
        })
        .collect();
    (completeness, pricing)
}

fn placeholder_evidence() -> SignedLearningEvidenceV1 {
    SignedLearningEvidenceV1 {
        evidence_id: id("evidence:placeholder"),
        principal_id: id("principal:placeholder"),
        role: LearningEvidenceRoleV1::Evaluator,
        trust_digest: digest("placeholder-trust"),
        scope_digest: digest("placeholder-scope"),
        objective_digest: digest("placeholder-objective"),
        authority_epoch: 1,
        issued_at: 1,
        expires_at: 2,
        payload_digest: digest("placeholder-payload"),
        signature: [0; 64],
    }
}
