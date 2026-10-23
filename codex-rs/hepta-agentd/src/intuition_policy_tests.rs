use super::final_use::preserve_known_commit;
use super::*;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use ed25519_dalek::SigningKey;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

#[allow(
    clippy::expect_used,
    reason = "Fixed test-fixture identifiers and scalar values are valid by construction."
)]
fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

#[test]
#[allow(
    clippy::expect_used,
    reason = "Test setup and success assertions intentionally fail the test on unexpected errors."
)]
fn host_identity_and_owner_pins_fail_closed_before_policy_admission() {
    let agent_id = AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dde").expect("agent id");
    let key = SigningKey::from_bytes(&[7; 32]);
    let scope = digest("scope");
    let principal = AuthenticatedPrincipalV1 {
        principal_id: id("intuition-generator"),
        credential_chain_digest: digest("credentials"),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        scope_digest: scope,
        authority_epoch: 1,
        authenticated_at: 1,
        expires_at: 100,
    };
    let verifier = Arc::new(
        LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: scope,
            objective_digest: digest("objective"),
            authority_epoch: 1,
            signers: vec![TrustedLearningSignerV1 {
                principal,
                controller_id: id("intuition-generator-controller"),
                verifying_key: key.verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Generator],
                revoked_at: None,
            }],
        })
        .expect("host trust"),
    );
    let host = AgentdIntuitionPolicyHostV1::new(
        agent_id.clone(),
        7,
        verifier,
        AgentdIntuitionPolicyPinsV1 {
            model_artifact_digest: digest("model"),
            scorer_contract_digest: digest("scorer"),
            rng_owner_digest: Some(digest("rng-owner")),
        },
    )
    .expect("host");
    assert!(host.require_identity(&agent_id, 7).is_ok());
    assert!(matches!(
        host.require_identity(&agent_id, 8),
        Err(AgentdIntuitionPolicyError::GenerationFence)
    ));
    assert!(!host.is_product_ready());
    assert_eq!(
        AgentdIntuitionPolicyError::GenerationFence.code(),
        "agentd.intuition.generation_fenced"
    );
}

#[test]
fn prepared_time_rejects_expiry_and_clock_rollback() {
    assert!(validate_prepared_time(150, 200, 150).is_ok());
    assert!(validate_prepared_time(150, 200, 199).is_ok());
    assert!(matches!(
        validate_prepared_time(150, 200, 149),
        Err(AgentdIntuitionPolicyError::PreparedClockReversed)
    ));
    for now in [200, 201, u64::MAX] {
        assert!(matches!(
            validate_prepared_time(150, 200, now),
            Err(AgentdIntuitionPolicyError::PreparedEvidenceExpired)
        ));
    }
}

#[test]
fn failed_reconciliation_preserves_the_first_durable_commit() {
    let receipt = String::from("committed:event:7:chain:verified");
    for failure in [
        "witness unavailable",
        "trust changed",
        "writer lock poisoned",
    ] {
        assert_eq!(
            preserve_known_commit(receipt.clone(), Err(failure)),
            Err(receipt.clone()),
        );
    }
}

#[test]
fn successful_reconciliation_returns_the_verified_replay_receipt() {
    let original = String::from("committed:unwitnessed");
    let reconciled = String::from("committed:witnessed");
    assert_eq!(
        preserve_known_commit::<_, ()>(original, Ok(reconciled.clone())),
        Ok(reconciled),
    );
}

#[test]
#[allow(
    clippy::expect_used,
    reason = "Test setup and success assertions intentionally fail the test on unexpected errors."
)]
fn product_host_binding_mutation_covers_every_profile_pin() {
    let agent = AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dde").expect("agent");
    let pins = AgentdIntuitionPolicyPinsV2 {
        policy_profile_digest: digest("profile"),
        policy_digest: digest("policy"),
        policy_generation: PolicyGeneration::new(4).expect("generation"),
        objective_class_digest: digest("class"),
        model_artifact_digest: digest("model"),
        scorer_contract_digest: digest("scorer"),
        calibration_artifact_digest: digest("calibration"),
        ood_artifact_digest: digest("ood"),
        risk_rule_digest: digest("risk"),
        rng_owner_digest: Some(digest("rng")),
    };
    let binding = |value: &AgentdIntuitionPolicyPinsV2| {
        product_host_binding_digest(&agent, 7, digest("trust"), value, digest("authentication"))
    };
    let original = binding(&pins);
    for field in 0..11 {
        let mut changed = pins.clone();
        match field {
            0 => changed.policy_profile_digest = digest("changed-profile"),
            1 => changed.policy_digest = digest("changed-policy"),
            2 => changed.policy_generation = PolicyGeneration::new(5).expect("generation"),
            3 => changed.objective_class_digest = digest("changed-class"),
            4 => changed.model_artifact_digest = digest("changed-model"),
            5 => changed.scorer_contract_digest = digest("changed-scorer"),
            6 => changed.calibration_artifact_digest = digest("changed-calibration"),
            7 => changed.ood_artifact_digest = digest("changed-ood"),
            8 => changed.risk_rule_digest = digest("changed-risk"),
            9 => changed.rng_owner_digest = Some(digest("changed-rng")),
            10 => changed.rng_owner_digest = None,
            _ => unreachable!(),
        }
        assert_ne!(
            binding(&changed),
            original,
            "pin field {field} was not bound"
        );
    }
}
