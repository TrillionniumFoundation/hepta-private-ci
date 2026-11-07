use super::*;
use crate::signed_authority::H7H89ProductionTransition;
use crate::signed_authority::pq_tests::fixture_at;
use base64::Engine;
use base64::engine::general_purpose::STANDARD;
use codex_hepta_contracts::AgentId;
use pretty_assertions::assert_eq;

fn retained_intent() -> SignedSupervisorIntent {
    let fixture = fixture_at(/*issued*/ 100, /*expires*/ 500);
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap();
    let grant = fixture
        .grant
        .sign(
            &agent,
            "source-v1",
            "target-v2",
            H7H89ProductionTransition::Upgrade,
            &fixture.envelope,
            /*expected_control_revision*/ 3,
            /*expected_lifecycle_generation*/ 5,
            /*authority_epoch*/ 7,
            /*issued_at_unix_seconds*/ 100,
            /*expires_at_unix_seconds*/ 400,
        )
        .unwrap();
    SignedSupervisorIntent::new(
        grant.grant_sha256.clone(),
        agent.to_string(),
        grant.transition,
        &grant.source_release,
        &grant.target_release,
        grant.expected_control_revision,
        grant.expected_lifecycle_generation,
        grant.authority_epoch,
        SignedIntentStatus::Prepared,
    )
    .unwrap()
    .bind_authority(&grant, &fixture.envelope, &fixture.verifier)
    .unwrap()
}

#[test]
fn retained_proof_rechecks_both_actual_signatures_after_successful_verification() {
    let intent = retained_intent();
    let proof = intent.pq_authority.as_ref().unwrap();
    let original = serde_json::to_vec(&intent).unwrap();
    let prepared =
        H7H89ProductionGrantVerifier::from_pq_policy_bytes(proof.policy_json.as_bytes()).unwrap();
    proof.verify_at(&intent, /*now*/ 200).unwrap();
    proof
        .verify_at_with_prepared(&intent, /*now*/ 200, Some(&prepared))
        .unwrap();
    #[derive(Debug)]
    enum SignatureRole {
        Grant,
        Artifact,
    }
    for field in [SignatureRole::Grant, SignatureRole::Artifact] {
        let mut changed = proof.clone();
        let signature = match field {
            SignatureRole::Grant => &mut changed.grant.signature_base64,
            SignatureRole::Artifact => &mut changed.h7_envelope.signature_base64,
        };
        let mut bytes = STANDARD.decode(&*signature).unwrap();
        bytes[0] ^= 1;
        *signature = STANDARD.encode(bytes);
        // The detached signature mutation still passes the complete shape and
        // binding checks, so the refusal must come from actual verification.
        changed.validate_for(&intent).unwrap();
        assert!(
            changed.verify_at(&intent, /*now*/ 200).is_err(),
            "{field:?}"
        );
        assert!(
            changed
                .verify_at_with_prepared(&intent, /*now*/ 200, Some(&prepared))
                .is_err(),
            "prepared {field:?}"
        );
    }
    proof.verify_at(&intent, /*now*/ 200).unwrap();
    proof
        .verify_at_with_prepared(&intent, /*now*/ 200, Some(&prepared))
        .unwrap();
    assert_eq!(serde_json::to_vec(&intent).unwrap(), original);
}

#[test]
fn retained_proof_rechecks_exact_policy_bytes_and_the_supplied_time() {
    let intent = retained_intent();
    let proof = intent.pq_authority.as_ref().unwrap();
    let prepared =
        H7H89ProductionGrantVerifier::from_pq_policy_bytes(proof.policy_json.as_bytes()).unwrap();
    proof.verify_at(&intent, /*now*/ 200).unwrap();
    proof
        .verify_at_with_prepared(&intent, /*now*/ 200, Some(&prepared))
        .unwrap();
    for now in [99, 400] {
        assert!(
            proof
                .verify_at_with_prepared(&intent, now, Some(&prepared))
                .is_err()
        );
    }
    assert!(proof.verify_at(&intent, /*now*/ 99).is_err());
    assert!(proof.verify_at(&intent, /*now*/ 400).is_err());
    let mut changed = proof.clone();
    changed.policy_json.push(' ');
    assert!(changed.verify_at(&intent, /*now*/ 200).is_err());
    assert!(
        changed
            .verify_at_with_prepared(&intent, /*now*/ 200, Some(&prepared))
            .is_err()
    );
    // Historical verification uses its original signed window only; it does
    // not confer live authority or replace the separate current owner checks.
    proof.verify_historical_for(&intent).unwrap();
}

#[test]
fn retained_proof_prepared_keys_preserve_different_policy_history() {
    let intent = retained_intent();
    let proof = intent.pq_authority.as_ref().unwrap();
    let mut whitespace_bytes = proof.policy_json.as_bytes().to_vec();
    whitespace_bytes.push(b' ');
    let whitespace_prepared =
        H7H89ProductionGrantVerifier::from_pq_policy_bytes(&whitespace_bytes).unwrap();
    assert_ne!(
        whitespace_prepared.policy_bytes(),
        Some(proof.policy_json.as_bytes())
    );
    // Equal parsed roles do not make different raw policy bytes reusable.
    proof
        .verify_historical_for_with_prepared(&intent, &whitespace_prepared)
        .unwrap();
    let mut different: crate::signed_authority::ProductionAuthorityPolicyV1 =
        serde_json::from_str(&proof.policy_json).unwrap();
    std::mem::swap(&mut different.grant, &mut different.recovery);
    let bytes = serde_json::to_vec(&different).unwrap();
    let prepared = H7H89ProductionGrantVerifier::from_pq_policy_bytes(&bytes).unwrap();
    assert_ne!(prepared.policy_bytes(), Some(proof.policy_json.as_bytes()));
    // Current recovery roles may differ from retained grant roles. A mismatch
    // must use the historical keys, not substitute or reject the current ones.
    proof
        .verify_historical_for_with_prepared(&intent, &prepared)
        .unwrap();
    let classical = H7H89ProductionGrantVerifier::new(
        "classical-qualification-only",
        /*signer_epoch*/ 1,
        ed25519_dalek::SigningKey::from_bytes(&[93; 32]).verifying_key(),
    )
    .unwrap();
    assert!(classical.policy_bytes().is_none());
    proof
        .verify_historical_for_with_prepared(&intent, &classical)
        .unwrap();
}
