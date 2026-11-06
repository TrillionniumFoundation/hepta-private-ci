use super::*;
use crate::H7H89ProductionTransition;
use crate::signed_authority::ProductionAuthorityError;
use crate::signed_authority::ProductionAuthorityPolicyV1;
use crate::signed_authority::pq_tests::AuthorityFixture;
use crate::signed_authority::pq_tests::fixture_at;
use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use pretty_assertions::assert_eq;

fn assert_same_rejection(bytes: &[u8]) {
    let shape = H7H89ProductionGrantVerifier::validate_pq_policy_shape(bytes).unwrap_err();
    let prepared = H7H89ProductionGrantVerifier::from_pq_policy_bytes(bytes)
        .err()
        .expect("the actual constructor must reject the same policy");
    assert_eq!(shape, prepared);
}

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
fn shape_policy_preserves_role_metadata_and_base64_rejections() {
    let fixture = fixture_at(/*issued*/ 100, /*expires*/ 500);
    let original: serde_json::Value = serde_json::from_slice(&fixture.policy).unwrap();
    for role in ["grant", "artifact", "recovery"] {
        for (field, value) in [
            ("signer_id", serde_json::json!("")),
            ("signer_id", serde_json::json!("x".repeat(257))),
            ("signer_id", serde_json::json!("nul\0id")),
            ("signer_id", serde_json::json!("invalid identity")),
            ("signer_epoch", serde_json::json!(0)),
        ] {
            let mut changed = original.clone();
            changed[role][field] = value;
            assert_same_rejection(&serde_json::to_vec(&changed).unwrap());
        }
        let encoded = original[role]["public_spki_base64"].as_str().unwrap();
        for malformed in [
            encoded[1..].to_string(),
            format!("!{}", &encoded[1..]),
            format!("{}=", &encoded[1..]),
        ] {
            let mut changed = original.clone();
            changed[role]["public_spki_base64"] = serde_json::json!(malformed);
            assert_same_rejection(&serde_json::to_vec(&changed).unwrap());
        }
    }
}

#[test]
fn shape_policy_preserves_canonical_spki_pins_and_distinct_roles() {
    let fixture = fixture_at(/*issued*/ 100, /*expires*/ 500);
    let original: serde_json::Value = serde_json::from_slice(&fixture.policy).unwrap();
    for role in ["grant", "artifact", "recovery"] {
        let spki = STANDARD
            .decode(original[role]["public_spki_base64"].as_str().unwrap())
            .unwrap();
        let mut wrong_prefix = spki.clone();
        wrong_prefix[0] ^= 1;
        let mut wrong_algorithm = spki.clone();
        wrong_algorithm[18] ^= 1;
        for bytes in [
            wrong_prefix,
            wrong_algorithm,
            spki[..spki.len() - 1].to_vec(),
        ] {
            let mut changed = original.clone();
            changed[role]["public_spki_base64"] = serde_json::json!(STANDARD.encode(bytes));
            assert_same_rejection(&serde_json::to_vec(&changed).unwrap());
        }
        for pin in [
            serde_json::to_value([0_u8; 32]).unwrap(),
            serde_json::to_value([17_u8; 32]).unwrap(),
        ] {
            let mut changed = original.clone();
            changed[role]["public_key_id"] = pin;
            assert_same_rejection(&serde_json::to_vec(&changed).unwrap());
        }
    }
    for (left, right) in [
        ("grant", "artifact"),
        ("grant", "recovery"),
        ("artifact", "recovery"),
    ] {
        let mut changed = original.clone();
        changed[right] = changed[left].clone();
        assert_same_rejection(&serde_json::to_vec(&changed).unwrap());
    }
}

#[test]
fn shape_policy_preserves_header_bounds_and_rejection_order() {
    let fixture = fixture_at(/*issued*/ 100, /*expires*/ 500);
    let original: serde_json::Value = serde_json::from_slice(&fixture.policy).unwrap();
    for (field, value) in [
        ("schema_version", serde_json::json!(2)),
        ("algorithm", serde_json::json!("ed25519_v1")),
        ("unknown", serde_json::json!(true)),
        ("artifact", serde_json::Value::Null),
    ] {
        let mut changed = original.clone();
        changed[field] = value;
        changed["grant"]["signer_id"] = serde_json::json!("");
        assert_same_rejection(&serde_json::to_vec(&changed).unwrap());
    }
    let mut absent = original.clone();
    absent.as_object_mut().unwrap().remove("recovery");
    assert_same_rejection(&serde_json::to_vec(&absent).unwrap());
    for bytes in [Vec::new(), b"{".to_vec(), vec![b' '; 16_385]] {
        assert_same_rejection(&bytes);
    }
    let mut changed = original;
    changed["artifact"]["signer_id"] = serde_json::json!("");
    changed["recovery"]["signer_epoch"] = serde_json::json!(0);
    let bytes = serde_json::to_vec(&changed).unwrap();
    assert_same_rejection(&bytes);
    assert_eq!(
        H7H89ProductionGrantVerifier::validate_pq_policy_shape(&bytes),
        Err(ProductionAuthorityError::Invalid(
            "PQ authority signer id contains an invalid identifier".to_string()
        ))
    );
}

#[test]
fn shape_policy_matches_constructor_for_canonical_key_encodings() {
    let fixture = fixture_at(/*issued*/ 100, /*expires*/ 500);
    let mut policy: ProductionAuthorityPolicyV1 = serde_json::from_slice(&fixture.policy).unwrap();
    for (role, byte) in [
        (&mut policy.grant, 0),
        (&mut policy.artifact, 255),
        (&mut policy.recovery, 85),
    ] {
        let mut spki = STANDARD.decode(&role.public_spki_base64).unwrap();
        spki[22..].fill(byte);
        role.public_key_id = ml_dsa_65_key_id_from_spki(&spki).unwrap();
        role.public_spki_base64 = STANDARD.encode(spki);
    }
    // These canonical encodings do not constitute a signature or permission.
    // Keep the shape acceptance set tied to the actual locked key decoder.
    let bytes = serde_json::to_vec(&policy).unwrap();
    let shape = H7H89ProductionGrantVerifier::validate_pq_policy_shape(&bytes).unwrap();
    let prepared = H7H89ProductionGrantVerifier::from_pq_policy_bytes(&bytes).unwrap();
    assert_eq!(prepared.policy_sha256(), Some(&shape));
}

#[test]
fn shape_retained_intent_preserves_all_message_and_window_checks() {
    let fixture = fixture_at(/*issued*/ 100, /*expires*/ 500);
    let intent = signed_intent(&fixture);
    let proof = intent.pq_authority.as_ref().unwrap();
    let original = serde_json::to_value(&intent).unwrap();
    for (field, value) in [
        (
            "grant_sha256",
            serde_json::json!(Sha256Digest::for_bytes(b"another grant")),
        ),
        ("agent_id", serde_json::json!("another-agent")),
        ("transition", serde_json::json!("rollback")),
        ("source_release", serde_json::json!("v0")),
        ("target_release", serde_json::json!("v3")),
        ("expected_control_revision", serde_json::json!(4)),
        ("expected_lifecycle_generation", serde_json::json!(6)),
        ("authority_epoch", serde_json::json!(8)),
    ] {
        let mut changed = original.clone();
        changed[field] = value;
        let changed: SignedSupervisorIntent = serde_json::from_value(changed).unwrap();
        assert_eq!(
            proof.validate_for(&changed).unwrap_err().to_string(),
            proof
                .validated_verifier(&changed)
                .err()
                .unwrap()
                .to_string(),
            "{field}"
        );
    }
    for (issued, expires) in [(0, 400), (100, 100), (101, 400), (100, 399), (100, 86_501)] {
        let mut changed = proof.clone();
        changed.issued_at_unix_seconds = issued;
        changed.expires_at_unix_seconds = expires;
        assert_eq!(
            changed.validate_for(&intent).unwrap_err().to_string(),
            changed
                .validated_verifier(&intent)
                .err()
                .unwrap()
                .to_string()
        );
    }
    let mut whitespace = proof.clone();
    whitespace.policy_json.push(' ');
    let mut wrong_binding = proof.clone();
    wrong_binding.binding.signer_public_key_id[0] ^= 1;
    for changed in [whitespace, wrong_binding] {
        assert_eq!(
            changed.validate_for(&intent).unwrap_err().to_string(),
            changed
                .validated_verifier(&intent)
                .err()
                .unwrap()
                .to_string()
        );
    }
    proof.validate_for(&intent).unwrap();
    proof.verify_at(&intent, /*now*/ 200).unwrap();
}

#[test]
fn shape_durable_intent_is_not_signature_or_current_authority() {
    let fixture = fixture_at(/*issued*/ 100, /*expires*/ 500);
    let original = signed_intent(&fixture);
    for artifact in [false, true] {
        let mut changed = original.clone();
        let proof = changed.pq_authority.as_mut().unwrap();
        let signature = if artifact {
            &mut proof.h7_envelope.signature_base64
        } else {
            &mut proof.grant.signature_base64
        };
        let mut bytes = STANDARD.decode(signature.as_bytes()).unwrap();
        bytes[0] ^= 1;
        *signature = STANDARD.encode(bytes);
        changed.intent_sha256 = changed.compute_digest().unwrap();
        let run_root = tempfile::tempdir().unwrap();
        crate::signed_intent::write_intent(run_root.path(), &changed).unwrap();
        let retained = crate::signed_intent::read_intent(run_root.path())
            .unwrap()
            .unwrap();
        assert_eq!(retained, changed);
        let proof = retained.pq_authority.as_ref().unwrap();
        proof.validate_for(&retained).unwrap();
        assert!(proof.verify_historical_for(&retained).is_err());
        assert!(proof.verify_at(&retained, /*now*/ 200).is_err());
    }
    let proof = original.pq_authority.as_ref().unwrap();
    proof.verify_historical_for(&original).unwrap();
    assert_eq!(
        proof
            .verify_at(&original, /*now*/ 400)
            .unwrap_err()
            .to_string(),
        SupervisorError::ProductionAuthority(ProductionAuthorityError::Expired.to_string())
            .to_string()
    );
}
