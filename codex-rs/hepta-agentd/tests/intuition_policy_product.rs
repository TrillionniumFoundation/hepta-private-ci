#![allow(clippy::expect_used)]
use codex_hepta_agentd::AgentdIntuitionPolicyError;
use codex_hepta_agentd::AgentdIntuitionPolicyHostV1;
use codex_hepta_agentd::AgentdIntuitionPolicyPinsV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_intelligence::IntuitionQualificationEvidenceV2;
use codex_hepta_intuition::AssignmentCommitmentV1;
use codex_hepta_intuition::AssignmentModeV1;
use codex_hepta_intuition::CalibratedActionCandidateV1;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CalibratedDispositionV1;
use codex_hepta_intuition::CalibrationArtifactV1;
use codex_hepta_intuition::CandidateSetCompletenessBindingV1;
use codex_hepta_intuition::CanonicalPolicyProfileV1;
use codex_hepta_intuition::CanonicalRiskRuleV1;
use codex_hepta_intuition::LearnedScorerContractV1;
use codex_hepta_intuition::OodArtifactV1;
use codex_hepta_intuition::RiskClass;
use codex_hepta_intuition::ScoringCommitmentV1;
use codex_hepta_intuition::canonical_candidate_order_digest_v1;
use codex_hepta_intuition::canonical_candidate_set_digest_v1;
use codex_hepta_intuition::canonical_completeness_evidence_payload_v1;
use codex_hepta_intuition::canonical_profile_qualification_payload_v1;
use codex_hepta_intuition::canonical_runtime_commitment_payload_v1;
use codex_hepta_intuition::canonical_scored_outputs_digest_v1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn sign(
    verifier: &LearningEvidenceVerifierV1,
    principal: &AuthenticatedPrincipalV1,
    key: &SigningKey,
    role: LearningEvidenceRoleV1,
    evidence_id: &str,
    objective_digest: Digest32,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(evidence_id),
        principal_id: principal.principal_id.clone(),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: principal.scope_digest,
        objective_digest,
        authority_epoch: principal.authority_epoch,
        issued_at: 100,
        expires_at: 200,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}

#[test]
fn agentd_calls_authenticated_current_intuition_policy_with_owner_pins() {
    let agent_id = AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dde").expect("agent id");
    let policy_digest = digest("policy:agentd-product");
    let model_digest = digest("model:agentd-product");
    let scorer_contract_digest = digest("scorer:agentd-product");
    let objective_digest = digest("objective:agentd-product");
    let objective_class_digest = digest("objective-class:agentd-product");
    let candidates = vec![CalibratedActionCandidateV1 {
        candidate_id: id("candidate:product"),
        legal: true,
        hard_veto: false,
        utility: FixedQ32::from_raw(7),
        calibrated_confidence: ProbabilityQ32::ONE,
        ood_score: ProbabilityQ32::ZERO,
        assignment_probability: ProbabilityQ32::ZERO,
        support_digest: digest("support:product"),
    }];
    let candidate_set_digest =
        canonical_candidate_set_digest_v1(&candidates).expect("candidate set");
    let request = CalibratedDecisionRequestV1 {
        decision_id: id("decision:agentd-product"),
        objective_digest,
        objective_class_digest,
        state_digest: digest("state:agentd-product"),
        policy_digest,
        policy_generation: 3,
        sequence: 11,
        minimum_confidence: ProbabilityQ32::ZERO,
        maximum_ece_ppm: 50_000,
        maximum_ood_false_acceptance_ppm: 5_000,
        risk_class: RiskClass::Low,
        completeness: CandidateSetCompletenessBindingV1 {
            receipt_digest: digest("complete:agentd-product"),
            generator_digest: digest("generator:agentd-product"),
            grammar_digest: digest("grammar:agentd-product"),
            hard_filter_digest: digest("filter:agentd-product"),
            truncation_digest: digest("truncation:agentd-product"),
            candidate_set_digest,
            canonical_order_digest: canonical_candidate_order_digest_v1(&candidates)
                .expect("candidate order"),
            candidate_count: 1,
            omitted_count_bound: 0,
        },
        calibration: CalibrationArtifactV1 {
            artifact_digest: digest("calibration:agentd-product"),
            policy_digest,
            objective_class_digest,
            generation: 3,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            measured_ece_ppm: 0,
            subgroup_audit_digest: digest("subgroup:agentd-product"),
        },
        ood: OodArtifactV1 {
            artifact_digest: digest("ood:agentd-product"),
            policy_digest,
            detector_digest: digest("detector:agentd-product"),
            support_digest: digest("ood-support:agentd-product"),
            generation: 3,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            maximum_in_domain_score: ProbabilityQ32::ONE,
            measured_false_acceptance_ppm: 0,
        },
        assignment: AssignmentModeV1::Deterministic,
        candidates,
    };
    let profile = CanonicalPolicyProfileV1 {
        profile_id: id("profile:agentd-product"),
        policy_digest,
        objective_class_digest,
        generation: 3,
        valid_from_sequence: 1,
        expires_after_sequence: 100,
        minimum_confidence: ProbabilityQ32::ZERO,
        maximum_ece_ppm: 50_000,
        maximum_ood_false_acceptance_ppm: 5_000,
        maximum_in_domain_score: ProbabilityQ32::ONE,
        risk_rule: CanonicalRiskRuleV1::HighOnlySlowPath,
        scorer: LearnedScorerContractV1 {
            model_digest,
            feature_schema_digest: digest("features:agentd-product"),
            output_schema_digest: digest("outputs:agentd-product"),
            score_semantics_digest: digest("semantics:agentd-product"),
            scorer_contract_digest,
        },
        calibration_dataset_digest: digest("cal-data:agentd-product"),
        ood_dataset_digest: digest("ood-data:agentd-product"),
        calibration_artifact_digest: request.calibration.artifact_digest,
        ood_artifact_digest: request.ood.artifact_digest,
    };
    let scoring = ScoringCommitmentV1 {
        model_artifact_digest: model_digest,
        feature_snapshot_digest: digest("feature-snapshot:agentd-product"),
        feature_schema_digest: profile.scorer.feature_schema_digest,
        scorer_contract_digest,
        candidate_set_digest,
        scored_outputs_digest: canonical_scored_outputs_digest_v1(&request).expect("scores"),
        policy_digest,
        policy_generation: 3,
    };
    let assignment = AssignmentCommitmentV1::Deterministic;

    let keys = [
        SigningKey::from_bytes(&[13; 32]),
        SigningKey::from_bytes(&[29; 32]),
        SigningKey::from_bytes(&[43; 32]),
    ];
    let scope_digest = digest("scope:agentd-product");
    let principals = [
        AuthenticatedPrincipalV1 {
            principal_id: id("agentd-generator"),
            credential_chain_digest: digest("cred:generator"),
            signing_key_digest: Digest32::of_bytes(&keys[0].verifying_key().to_bytes()),
            scope_digest,
            authority_epoch: 9,
            authenticated_at: 1,
            expires_at: 1_000,
        },
        AuthenticatedPrincipalV1 {
            principal_id: id("agentd-evaluator"),
            credential_chain_digest: digest("cred:evaluator"),
            signing_key_digest: Digest32::of_bytes(&keys[1].verifying_key().to_bytes()),
            scope_digest,
            authority_epoch: 9,
            authenticated_at: 1,
            expires_at: 1_000,
        },
        AuthenticatedPrincipalV1 {
            principal_id: id("agentd-observer"),
            credential_chain_digest: digest("cred:observer"),
            signing_key_digest: Digest32::of_bytes(&keys[2].verifying_key().to_bytes()),
            scope_digest,
            authority_epoch: 9,
            authenticated_at: 1,
            expires_at: 1_000,
        },
    ];
    let verifier = std::sync::Arc::new(
        LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest,
            objective_digest,
            authority_epoch: 9,
            signers: vec![
                TrustedLearningSignerV1 {
                    principal: principals[0].clone(),
                    controller_id: id("controller:agentd-generator"),
                    verifying_key: keys[0].verifying_key().to_bytes(),
                    roles: vec![LearningEvidenceRoleV1::Generator],
                    revoked_at: None,
                },
                TrustedLearningSignerV1 {
                    principal: principals[1].clone(),
                    controller_id: id("controller:agentd-evaluator"),
                    verifying_key: keys[1].verifying_key().to_bytes(),
                    roles: vec![LearningEvidenceRoleV1::Evaluator],
                    revoked_at: None,
                },
                TrustedLearningSignerV1 {
                    principal: principals[2].clone(),
                    controller_id: id("controller:agentd-observer"),
                    verifying_key: keys[2].verifying_key().to_bytes(),
                    roles: vec![LearningEvidenceRoleV1::Observer],
                    revoked_at: None,
                },
            ],
        })
        .expect("verifier"),
    );
    let completeness_payload =
        canonical_completeness_evidence_payload_v1(&request).expect("completeness payload");
    let profile_payload =
        canonical_profile_qualification_payload_v1(&profile).expect("profile payload");
    let runtime_payload =
        canonical_runtime_commitment_payload_v1(&request, &profile, &scoring, &assignment)
            .expect("runtime payload");
    let completeness = sign(
        &verifier,
        &principals[0],
        &keys[0],
        LearningEvidenceRoleV1::Generator,
        "evidence:agentd-complete",
        objective_digest,
        &completeness_payload,
    );
    let profile_evidence = sign(
        &verifier,
        &principals[1],
        &keys[1],
        LearningEvidenceRoleV1::Evaluator,
        "evidence:agentd-profile",
        objective_digest,
        &profile_payload,
    );
    let runtime = sign(
        &verifier,
        &principals[2],
        &keys[2],
        LearningEvidenceRoleV1::Observer,
        "evidence:agentd-runtime",
        objective_digest,
        &runtime_payload,
    );

    let host = AgentdIntuitionPolicyHostV1::new(
        agent_id.clone(),
        7,
        verifier,
        AgentdIntuitionPolicyPinsV1 {
            model_artifact_digest: model_digest,
            scorer_contract_digest,
            rng_owner_digest: None,
        },
    )
    .expect("Agentd intuition host");
    let receipt = host
        .decide(
            &agent_id,
            7,
            request.clone(),
            profile.clone(),
            scoring.clone(),
            assignment.clone(),
            IntuitionQualificationEvidenceV2 {
                completeness: &completeness,
                profile_qualification: &profile_evidence,
                runtime: &runtime,
            },
            150,
        )
        .expect("authenticated Agentd intuition decision");
    assert_eq!(
        receipt.decision.decision.disposition,
        CalibratedDispositionV1::Selected(id("candidate:product"))
    );
    assert!(!receipt.host_binding_digest.is_zero());

    let mut drifted_scoring = scoring;
    drifted_scoring.model_artifact_digest = digest("model:wrong");
    assert!(matches!(
        host.decide(
            &agent_id,
            7,
            request,
            profile,
            drifted_scoring,
            assignment,
            IntuitionQualificationEvidenceV2 {
                completeness: &completeness,
                profile_qualification: &profile_evidence,
                runtime: &runtime,
            },
            150,
        ),
        Err(AgentdIntuitionPolicyError::ModelPinMismatch)
    ));
}
