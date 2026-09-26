use std::sync::Arc;

use super::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_intuition::AssignmentCommitmentV1;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CanonicalPolicyProfileV1;
use codex_hepta_intuition::CanonicalRiskRuleV1;
use codex_hepta_intuition::LearnedScorerContractV1;
use codex_hepta_intuition::ScoringCommitmentV2;
use codex_hepta_intuition::canonical_completeness_evidence_payload_v1;
use codex_hepta_intuition::canonical_policy_profile_digest_v1;
use codex_hepta_intuition::canonical_profile_qualification_payload_v1;
use codex_hepta_intuition::canonical_runtime_commitment_payload_v2;
use codex_hepta_intuition::canonical_scored_outputs_digest_v2;
use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::LearningTrustDistributionV1;
use codex_hepta_learning_ledger::LearningTrustRootV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::SignedLearningTrustDistributionV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::activate_learning_trust;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

pub(super) const TEST_AGENT_ID: &str = "019153a4-3088-7e03-a56a-9b1964f75dde";

pub(super) struct IntuitionProductFixture {
    pub input: AgentdAuthenticatedIntuitionInputV1,
    pub host: Arc<AgentdIntuitionPolicyHostV2>,
    pub root_key_digest: Digest32,
    pub authority_epoch: u64,
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("intuition support id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn principal(
    name: &str,
    credential: &str,
    key: &SigningKey,
    scope_digest: Digest32,
    authority_epoch: u64,
    now: u64,
) -> AuthenticatedPrincipalV1 {
    AuthenticatedPrincipalV1 {
        principal_id: id(name),
        credential_chain_digest: digest(credential),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        scope_digest,
        authority_epoch,
        authenticated_at: now.saturating_sub(10_000),
        expires_at: now.saturating_add(180_000),
    }
}

fn sign(
    verifier: &LearningEvidenceVerifierV1,
    principal: &AuthenticatedPrincipalV1,
    key: &SigningKey,
    role: LearningEvidenceRoleV1,
    evidence_id: &str,
    payload: &[u8],
    now: u64,
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(evidence_id),
        principal_id: principal.principal_id.clone(),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: principal.scope_digest,
        objective_digest: verifier.objective_digest(),
        authority_epoch: verifier.authority_epoch(),
        issued_at: now.saturating_sub(1_000),
        expires_at: now.saturating_add(60_000),
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}

fn activate_trust(
    objective_digest: Digest32,
    now: u64,
) -> (
    ActivatedLearningTrustV1,
    [SigningKey; 3],
    [AuthenticatedPrincipalV1; 3],
) {
    let authority_epoch = 11;
    let scope_digest = digest("intuition-product-scope");
    let keys = [
        SigningKey::from_bytes(&[13; 32]),
        SigningKey::from_bytes(&[29; 32]),
        SigningKey::from_bytes(&[43; 32]),
    ];
    let principals = [
        principal(
            "intuition-product-generator",
            "intuition-generator-credential",
            &keys[0],
            scope_digest,
            authority_epoch,
            now,
        ),
        principal(
            "intuition-product-evaluator",
            "intuition-evaluator-credential",
            &keys[1],
            scope_digest,
            authority_epoch,
            now,
        ),
        principal(
            "intuition-product-observer",
            "intuition-observer-credential",
            &keys[2],
            scope_digest,
            authority_epoch,
            now,
        ),
    ];
    let trust = LearningEvidenceTrustV1 {
        scope_digest,
        objective_digest,
        authority_epoch,
        signers: vec![
            TrustedLearningSignerV1 {
                principal: principals[0].clone(),
                controller_id: id("intuition-generator-controller"),
                verifying_key: keys[0].verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Generator],
                revoked_at: None,
            },
            TrustedLearningSignerV1 {
                principal: principals[1].clone(),
                controller_id: id("intuition-evaluator-controller"),
                verifying_key: keys[1].verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Evaluator],
                revoked_at: None,
            },
            TrustedLearningSignerV1 {
                principal: principals[2].clone(),
                controller_id: id("intuition-observer-controller"),
                verifying_key: keys[2].verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Observer],
                revoked_at: None,
            },
        ],
    };
    let root_key = SigningKey::from_bytes(&[99; 32]);
    let root = LearningTrustRootV1 {
        root_id: id("intuition-product-root"),
        scope_digest,
        verifying_key: root_key.verifying_key().to_bytes(),
        valid_from: now.saturating_sub(20_000),
        expires_at: now.saturating_add(1_200_000),
        revoked_at: None,
    };
    let mut signed = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("intuition-product-distribution"),
            generation: 1,
            effective_at: now.saturating_sub(5_000),
            trust,
        },
        root_id: root.root_id.clone(),
        issued_at: now.saturating_sub(6_000),
        expires_at: now.saturating_add(120_000),
        signature: [0; 64],
    };
    signed.signature = root_key
        .sign(&signed.signing_bytes().expect("trust distribution bytes"))
        .to_bytes();
    let activated = activate_learning_trust(&root, signed, None, now)
        .expect("activate intuition product trust");
    (activated, keys, principals)
}

pub(super) fn build(
    request: CalibratedDecisionRequestV1,
    model_digest: Digest32,
    agent_id: &str,
    spawn_generation: u64,
    now: u64,
) -> IntuitionProductFixture {
    let scorer_contract_digest = digest("intuition-product-scorer-contract");
    let profile = CanonicalPolicyProfileV1 {
        profile_id: id("intuition-product-profile"),
        policy_digest: request.policy_digest,
        objective_class_digest: request.objective_class_digest,
        generation: request.policy_generation,
        valid_from_sequence: request.calibration.valid_from_sequence,
        expires_after_sequence: request.calibration.expires_after_sequence,
        minimum_confidence: request.minimum_confidence,
        maximum_ece_ppm: request.maximum_ece_ppm,
        maximum_ood_false_acceptance_ppm: request.maximum_ood_false_acceptance_ppm,
        maximum_in_domain_score: request.ood.maximum_in_domain_score,
        risk_rule: CanonicalRiskRuleV1::HighOnlySlowPath,
        scorer: LearnedScorerContractV1 {
            model_digest,
            feature_schema_digest: digest("intuition-product-feature-schema"),
            output_schema_digest: digest("intuition-product-output-schema"),
            score_semantics_digest: digest("intuition-product-score-semantics"),
            scorer_contract_digest,
        },
        calibration_dataset_digest: digest("intuition-product-calibration-data"),
        ood_dataset_digest: digest("intuition-product-ood-data"),
        calibration_artifact_digest: request.calibration.artifact_digest,
        ood_artifact_digest: request.ood.artifact_digest,
    };
    let scoring = ScoringCommitmentV2 {
        model_artifact_digest: model_digest,
        feature_snapshot_digest: digest("intuition-product-feature-snapshot"),
        feature_schema_digest: profile.scorer.feature_schema_digest,
        scorer_contract_digest,
        scored_outputs_digest: canonical_scored_outputs_digest_v2(&request)
            .expect("intuition scored outputs"),
        policy_digest: request.policy_digest,
        policy_generation: request.policy_generation,
    };
    let assignment = AssignmentCommitmentV1::Deterministic;
    let (trust, keys, principals) = activate_trust(request.objective_digest, now);
    let completeness_payload = canonical_completeness_evidence_payload_v1(&request)
        .expect("intuition completeness payload");
    let profile_payload =
        canonical_profile_qualification_payload_v1(&profile).expect("intuition profile payload");
    let runtime_payload =
        canonical_runtime_commitment_payload_v2(&request, &profile, &scoring, &assignment)
            .expect("intuition runtime payload");
    let completeness = sign(
        trust.verifier(),
        &principals[0],
        &keys[0],
        LearningEvidenceRoleV1::Generator,
        "intuition-product-completeness",
        &completeness_payload,
        now,
    );
    let profile_qualification = sign(
        trust.verifier(),
        &principals[1],
        &keys[1],
        LearningEvidenceRoleV1::Evaluator,
        "intuition-product-profile-qualification",
        &profile_payload,
        now,
    );
    let runtime = sign(
        trust.verifier(),
        &principals[2],
        &keys[2],
        LearningEvidenceRoleV1::Observer,
        "intuition-product-runtime",
        &runtime_payload,
        now,
    );
    let profile_digest =
        canonical_policy_profile_digest_v1(&profile).expect("intuition profile digest");
    let root_key_digest = trust.root_key_digest();
    let authority_epoch = trust.verifier().authority_epoch();
    let pins = AgentdIntuitionPolicyPinsV2 {
        selected_profile_digest: profile_digest,
        owner_implementation_digest: digest("intuition.policy:impl"),
        policy_generation: profile.generation,
        model_artifact_digest: model_digest,
        scorer_contract_digest,
        rng_owner_digest: None,
        trust_distribution_digest: trust.distribution_digest(),
        revocation_frontier_digest: digest("revocation-frontier"),
    };
    let host = Arc::new(
        AgentdIntuitionPolicyHostV2::new(
            AgentId::parse(agent_id).expect("intuition product agent id"),
            spawn_generation,
            Arc::new(trust),
            pins,
        )
        .expect("intuition product host"),
    );
    IntuitionProductFixture {
        input: AgentdAuthenticatedIntuitionInputV1 {
            request,
            profile,
            scoring,
            assignment,
            completeness,
            profile_qualification,
            runtime,
        },
        host,
        root_key_digest,
        authority_epoch,
    }
}
