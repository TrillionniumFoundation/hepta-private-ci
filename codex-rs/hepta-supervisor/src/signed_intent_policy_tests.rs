use super::*;
use crate::H7H89ProductionTransition;
use crate::signed_authority::ProductionAuthorityError;
use crate::signed_authority::pq_tests::AuthorityFixture;
use crate::signed_authority::pq_tests::fixture_at;
use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use codex_hepta_contracts::AgentId;
use pretty_assertions::assert_eq;

fn signed_intent(fixture: &AuthorityFixture) -> SignedSupervisorIntent {
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap();
    let grant = fixture
        .grant
        .sign(
            &agent,
            "v1",
            "v2",
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
        agent.as_str(),
        H7H89ProductionTransition::Upgrade,
        "v1",
        "v2",
        /*expected_control_revision*/ 3,
        /*expected_lifecycle_generation*/ 5,
        /*authority_epoch*/ 7,
        SignedIntentStatus::Prepared,
    )
    .unwrap()
    .bind_authority(&grant, &fixture.envelope, &fixture.verifier)
    .unwrap()
}

#[test]
fn owned_policy_verifiers_recheck_every_role_after_prior_success() {
    let fixture = fixture_at(/*issued*/ 100, /*expires*/ 500);
    let original: serde_json::Value = serde_json::from_slice(&fixture.policy).unwrap();
    for role in ["grant", "artifact", "recovery"] {
        let mut changed = original.clone();
        let first = changed[role]["public_key_id"][0].as_u64().unwrap();
        changed[role]["public_key_id"][0] = serde_json::json!(first ^ 1);
        let bytes = serde_json::to_vec(&changed).unwrap();
        assert!(
            matches!(
                H7H89ProductionGrantVerifier::from_pq_policy_bytes(&bytes),
                Err(ProductionAuthorityError::Invalid(message))
                    if message == "PQ authority key does not match its canonical pin"
            ),
            "{role}"
        );
    }
    let mut duplicate = original;
    duplicate["recovery"] = duplicate["grant"].clone();
    assert!(
        H7H89ProductionGrantVerifier::from_pq_policy_bytes(
            &serde_json::to_vec(&duplicate).unwrap()
        )
        .is_err()
    );
    let intent = signed_intent(&fixture);
    intent
        .pq_authority
        .as_ref()
        .unwrap()
        .verify_historical_for(&intent)
        .unwrap();
}

#[test]
fn owned_intent_verifier_preserves_exact_policy_and_message_bindings() {
    let fixture = fixture_at(/*issued*/ 100, /*expires*/ 500);
    let intent = signed_intent(&fixture);
    let proof = intent.pq_authority.as_ref().unwrap();
    proof.verify_at(&intent, /*now*/ 200).unwrap();
    for changed in [
        SignedSupervisorIntent {
            target_release: "v3".to_string(),
            ..intent.clone()
        },
        SignedSupervisorIntent {
            authority_epoch: 8,
            ..intent.clone()
        },
    ] {
        let shape_error = proof.validate_for(&changed).unwrap_err().to_string();
        assert!(shape_error.contains("retained PQ proof differs from its admitted intent"));
        assert_eq!(
            proof
                .verify_at(&changed, /*now*/ 200)
                .unwrap_err()
                .to_string(),
            SupervisorError::Invalid(shape_error).to_string()
        );
    }
    let mut changed = proof.clone();
    changed.policy_json.push(' ');
    assert!(changed.validate_for(&intent).is_err());
    assert!(changed.verify_at(&intent, /*now*/ 200).is_err());
    proof.verify_at(&intent, /*now*/ 200).unwrap();
}

#[test]
fn owned_intent_verifier_still_verifies_each_actual_signature() {
    let fixture = fixture_at(/*issued*/ 100, /*expires*/ 500);
    let intent = signed_intent(&fixture);
    let proof = intent.pq_authority.as_ref().unwrap();
    proof.verify_at(&intent, /*now*/ 200).unwrap();
    for artifact in [false, true] {
        let mut changed = proof.clone();
        let signature = if artifact {
            &mut changed.h7_envelope.signature_base64
        } else {
            &mut changed.grant.signature_base64
        };
        let mut bytes = STANDARD.decode(signature.as_bytes()).unwrap();
        bytes[0] ^= 1;
        *signature = STANDARD.encode(bytes);
        changed.validate_for(&intent).unwrap();
        assert!(changed.verify_at(&intent, /*now*/ 200).is_err());
    }
}

#[test]
fn owned_intent_verifier_keeps_current_time_and_historical_checks_separate() {
    let fixture = fixture_at(/*issued*/ 100, /*expires*/ 500);
    let intent = signed_intent(&fixture);
    let proof = intent.pq_authority.as_ref().unwrap();
    proof.verify_at(&intent, /*now*/ 100).unwrap();
    proof.verify_at(&intent, /*now*/ 399).unwrap();
    assert!(proof.verify_at(&intent, /*now*/ 99).is_err());
    assert_eq!(
        proof
            .verify_at(&intent, /*now*/ 400)
            .unwrap_err()
            .to_string(),
        SupervisorError::ProductionAuthority(ProductionAuthorityError::Expired.to_string())
            .to_string()
    );
    assert!(proof.verify_at(&intent, /*now*/ 500).is_err());
    proof.verify_historical_for(&intent).unwrap();
}

#[test]
fn prepared_policy_keys_still_verify_both_actual_signatures() {
    let fixture = fixture_at(/*issued*/ 100, /*expires*/ 500);
    let intent = signed_intent(&fixture);
    let proof = intent.pq_authority.as_ref().unwrap();
    proof
        .verify_at_using_keys(&intent, /*now*/ 200, &fixture.verifier)
        .unwrap();
    for artifact in [false, true] {
        let mut changed = proof.clone();
        let signature = if artifact {
            &mut changed.h7_envelope.signature_base64
        } else {
            &mut changed.grant.signature_base64
        };
        let mut bytes = STANDARD.decode(signature.as_bytes()).unwrap();
        bytes[0] ^= 1;
        *signature = STANDARD.encode(bytes);
        changed.validate_for(&intent).unwrap();
        assert_eq!(
            changed
                .verify_at_using_keys(&intent, /*now*/ 200, &fixture.verifier)
                .unwrap_err()
                .to_string(),
            changed
                .verify_at(&intent, /*now*/ 200)
                .unwrap_err()
                .to_string()
        );
    }
    proof
        .verify_at_using_keys(&intent, /*now*/ 200, &fixture.verifier)
        .unwrap();
}

#[test]
fn prepared_policy_keys_preserve_time_message_and_qualification_boundaries() {
    let fixture = fixture_at(/*issued*/ 100, /*expires*/ 500);
    let intent = signed_intent(&fixture);
    let proof = intent.pq_authority.as_ref().unwrap();
    for now in [99, 400, 500] {
        assert_eq!(
            proof
                .verify_at_using_keys(&intent, now, &fixture.verifier)
                .unwrap_err()
                .to_string(),
            proof.verify_at(&intent, now).unwrap_err().to_string()
        );
    }
    for changed in [
        SignedSupervisorIntent {
            target_release: "v3".to_string(),
            ..intent.clone()
        },
        SignedSupervisorIntent {
            authority_epoch: 8,
            ..intent.clone()
        },
        SignedSupervisorIntent {
            expected_control_revision: 4,
            ..intent.clone()
        },
    ] {
        assert_eq!(
            proof
                .verify_at_using_keys(&changed, /*now*/ 200, &fixture.verifier)
                .unwrap_err()
                .to_string(),
            proof
                .verify_at(&changed, /*now*/ 200)
                .unwrap_err()
                .to_string()
        );
    }
    for (field, value) in [
        ("qualification_only", false),
        ("production_authority", true),
        ("external_effects", true),
        ("promotion_eligible", true),
    ] {
        let mut wire = serde_json::to_value(proof).unwrap();
        wire["h7_envelope"][field] = serde_json::json!(value);
        let changed: SignedIntentPqAuthority = serde_json::from_value(wire).unwrap();
        assert_eq!(
            changed
                .verify_at_using_keys(&intent, /*now*/ 200, &fixture.verifier)
                .unwrap_err()
                .to_string(),
            changed
                .verify_at(&intent, /*now*/ 200)
                .unwrap_err()
                .to_string(),
            "{field}"
        );
    }
    proof
        .verify_historical_using_keys(&intent, &fixture.verifier)
        .unwrap();
}

#[test]
fn prepared_policy_keys_do_not_mask_changed_or_invalid_policy_bytes() {
    let fixture = fixture_at(/*issued*/ 100, /*expires*/ 500);
    let intent = signed_intent(&fixture);
    let proof = intent.pq_authority.as_ref().unwrap();
    let original: serde_json::Value = serde_json::from_slice(&fixture.policy).unwrap();
    let mut policies = vec![
        String::new(),
        "{".to_string(),
        " ".repeat(16_385),
        format!("{} ", proof.policy_json),
    ];
    for role in ["grant", "artifact", "recovery"] {
        let mut changed = original.clone();
        let first = changed[role]["public_key_id"][0].as_u64().unwrap();
        changed[role]["public_key_id"][0] = serde_json::json!(first ^ 1);
        policies.push(serde_json::to_string(&changed).unwrap());
    }
    let mut duplicate = original;
    duplicate["recovery"] = duplicate["grant"].clone();
    policies.push(serde_json::to_string(&duplicate).unwrap());
    for policy_json in policies {
        let changed = SignedIntentPqAuthority {
            policy_json,
            ..proof.clone()
        };
        assert_eq!(
            changed
                .verify_at_using_keys(&intent, /*now*/ 200, &fixture.verifier)
                .unwrap_err()
                .to_string(),
            changed
                .verify_at(&intent, /*now*/ 200)
                .unwrap_err()
                .to_string()
        );
    }
    proof
        .verify_at_using_keys(&intent, /*now*/ 200, &fixture.verifier)
        .unwrap();
}

#[test]
fn prepared_policy_keys_decode_a_distinct_valid_policy_for_each_signature() {
    use crate::signed_authority::H7PqProductionGrantSigner;
    use crate::signed_authority::H7PqProductionRecoverySigner;
    use crate::signed_authority::ProductionAuthorityPolicyV1;
    use crate::signed_authority::pq_tests::key;

    let original = fixture_at(/*issued*/ 100, /*expires*/ 500);
    let old_intent = signed_intent(&original);
    let old_proof = old_intent.pq_authority.as_ref().unwrap();
    let mut alternate = fixture_at(/*issued*/ 100, /*expires*/ 500);
    let new_key = key(/*seed*/ 104);
    let mut policy: ProductionAuthorityPolicyV1 =
        serde_json::from_slice(&alternate.policy).unwrap();
    policy.grant.public_key_id = new_key.public_key_id();
    policy.grant.public_spki_base64 = STANDARD.encode(new_key.public_spki());
    alternate.policy = serde_json::to_vec(&policy).unwrap();
    alternate.verifier =
        H7H89ProductionGrantVerifier::from_pq_policy_bytes(&alternate.policy).unwrap();
    alternate.grant = H7PqProductionGrantSigner::new(&alternate.policy, new_key).unwrap();
    alternate.recovery =
        H7PqProductionRecoverySigner::new(&alternate.policy, key(/*seed*/ 103)).unwrap();
    let intent = signed_intent(&alternate);
    let proof = intent.pq_authority.as_ref().unwrap();
    assert_ne!(
        original.verifier.policy_sha256(),
        alternate.verifier.policy_sha256()
    );
    // Mismatched prepared bytes cannot authorize this proof; its own complete
    // policy must be constructed, and its actual different key must verify it.
    proof
        .verify_at_using_keys(&intent, /*now*/ 200, &original.verifier)
        .unwrap();
    old_proof
        .verify_historical_using_keys(&old_intent, &alternate.verifier)
        .unwrap();
    let mut changed = proof.clone();
    changed.grant.signature_base64 = old_proof.grant.signature_base64.clone();
    changed.validate_for(&intent).unwrap();
    assert_eq!(
        changed
            .verify_at_using_keys(&intent, /*now*/ 200, &original.verifier)
            .unwrap_err()
            .to_string(),
        changed
            .verify_at(&intent, /*now*/ 200)
            .unwrap_err()
            .to_string()
    );
}
