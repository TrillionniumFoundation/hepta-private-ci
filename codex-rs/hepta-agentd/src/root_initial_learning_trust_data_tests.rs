//! Crypto/data component tests only. No fixture constructs the opaque Root
//! handoff capsule, an actual Root registration or independent B execution.

use super::*;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

type TestResult = Result<(), Box<dyn std::error::Error>>;

fn payload() -> LearningTrustPayloadV1 {
    let root = SigningKey::from_bytes(&[71; 32]);
    let scope = Digest32::of_bytes(b"component-ledger-scope").into_array();
    let signers = [
        ("generator", 72, LearningTrustRoleV1::Generator),
        ("observer", 73, LearningTrustRoleV1::Observer),
    ]
    .into_iter()
    .map(|(name, seed, role)| {
        let key = SigningKey::from_bytes(&[seed; 32])
            .verifying_key()
            .to_bytes();
        LearningTrustSignerDataV1 {
            principal_id: name.into(),
            credential_chain_digest: Digest32::of_bytes(name.as_bytes()).into_array(),
            signing_key_digest: Digest32::of_bytes(&key).into_array(),
            scope_digest: scope,
            authority_epoch: 1,
            authenticated_at_seconds: 10,
            expires_at_seconds: 100,
            controller_id: format!("{name}-controller"),
            verifying_key: key,
            roles: vec![role],
            revoked_at_seconds: None,
        }
    })
    .collect();
    LearningTrustPayloadV1 {
        root: LearningTrustRootDataV1 {
            schema: 1,
            root_id: "root".into(),
            scope_digest: scope,
            verifying_key: root.verifying_key().to_bytes(),
            valid_from_seconds: 1,
            expires_at_seconds: 200,
            revoked_at_seconds: None,
        },
        distribution: LearningTrustDistributionDataV1 {
            schema: 1,
            root_id: "root".into(),
            distribution_id: "first".into(),
            generation: 1,
            effective_at_seconds: 20,
            scope_digest: scope,
            objective_digest: Digest32::of_bytes(b"component-objective").into_array(),
            authority_epoch: 1,
            signers,
            issued_at_seconds: 15,
            expires_at_seconds: 90,
            signature: vec![0; 64],
        },
        generator: LearningTrustRoleSelectionV1 {
            principal_id: "generator".into(),
            controller_id: "generator-controller".into(),
        },
        observer: LearningTrustRoleSelectionV1 {
            principal_id: "observer".into(),
            controller_id: "observer-controller".into(),
        },
    }
}

fn sign(payload: &mut LearningTrustPayloadV1) -> Result<(), Box<dyn std::error::Error>> {
    let data = &payload.distribution;
    let signed = SignedLearningTrustDistributionV1 {
        root_id: StableId::new(&data.root_id)?,
        distribution: LearningTrustDistributionV1 {
            distribution_id: StableId::new(&data.distribution_id)?,
            generation: data.generation,
            effective_at: data.effective_at_seconds,
            trust: LearningEvidenceTrustV1 {
                scope_digest: Digest32::from_array(data.scope_digest),
                objective_digest: Digest32::from_array(data.objective_digest),
                authority_epoch: data.authority_epoch,
                signers: data
                    .signers
                    .iter()
                    .map(LearningTrustSignerDataV1::original_signer)
                    .collect::<io::Result<_>>()?,
            },
        },
        issued_at: data.issued_at_seconds,
        expires_at: data.expires_at_seconds,
        signature: [0; 64],
    };
    payload.distribution.signature = SigningKey::from_bytes(&[71; 32])
        .sign(&signed.signing_bytes()?)
        .to_bytes()
        .to_vec();
    Ok(())
}

#[test]
fn initial_learning_trust_activates_real_signature_and_fixed_independent_roles() -> TestResult {
    let mut original = payload();
    sign(&mut original)?;
    let (trust, generator, observer) = original.activate_pinned_genesis(/*now_seconds*/ 50)?;
    assert_eq!(trust.generation(), 1);
    assert_eq!(
        (
            generator.principal.principal_id.as_str(),
            observer.principal.principal_id.as_str()
        ),
        ("generator", "observer")
    );
    assert_ne!(generator.controller_id, observer.controller_id);
    assert!(serde_json::to_vec(&original)?.len() < 12 * 1024);
    Ok(())
}

#[test]
fn initial_learning_trust_rejects_substitution_expiry_and_missing_rotation_history() -> TestResult {
    let mut original = payload();
    sign(&mut original)?;
    let mut bad = original.clone();
    bad.distribution.signature[0] ^= 1;
    assert!(bad.activate_pinned_genesis(/*now_seconds*/ 50).is_err());
    let mut bad = original.clone();
    bad.root.verifying_key = SigningKey::from_bytes(&[74; 32]).verifying_key().to_bytes();
    assert!(bad.activate_pinned_genesis(/*now_seconds*/ 50).is_err());
    assert!(
        original
            .activate_pinned_genesis(/*now_seconds*/ 91)
            .is_err()
    );
    let mut rotation = original;
    rotation.distribution.generation = 2;
    sign(&mut rotation)?;
    assert!(
        rotation
            .activate_pinned_genesis(/*now_seconds*/ 50)
            .is_err()
    );
    Ok(())
}

#[test]
fn initial_learning_trust_rejects_same_controller_even_with_a_valid_root_signature() -> TestResult {
    let mut original = payload();
    original.distribution.signers[1].controller_id = original.generator.controller_id.clone();
    original.observer.controller_id = original.generator.controller_id.clone();
    sign(&mut original)?;
    let error = original
        .activate_pinned_genesis(/*now_seconds*/ 50)
        .err()
        .ok_or("shared controller was accepted")?;
    assert_eq!(
        error.to_string(),
        "independent Observer controller required"
    );
    Ok(())
}

#[test]
fn initial_learning_trust_pins_roles_and_rejects_unknown_wire_authority_fields() -> TestResult {
    let mut original = payload();
    sign(&mut original)?;
    let (trust, _, _) = original.activate_pinned_genesis(/*now_seconds*/ 50)?;
    let mut pin = LearningTrustPinV1 {
        mapping: Digest32::of_bytes(b"mapping").to_string(),
        target: Digest32::of_bytes(b"target").to_string(),
        task: Digest32::of_bytes(b"task").to_string(),
        source_metadata: Digest32::of_bytes(b"source").to_string(),
        root: trust.root_digest().to_string(),
        distribution: trust.distribution_digest().to_string(),
        trust: trust.verifier().trust_digest().to_string(),
        learning_scope: trust.verifier().scope_digest().to_string(),
        objective: trust.verifier().objective_digest().to_string(),
        roles: original.role_digest()?.to_string(),
    };
    original.require_activation_pin(&trust, &pin)?;
    pin.roles = Digest32::of_bytes(b"different-role-selection").to_string();
    assert!(original.require_activation_pin(&trust, &pin).is_err());
    let mut encoded = serde_json::to_value(&original)?;
    encoded["completed"] = serde_json::json!(true);
    assert!(serde_json::from_value::<LearningTrustPayloadV1>(encoded).is_err());
    Ok(())
}

#[test]
fn initial_learning_trust_request_cannot_supply_authority_or_completion() -> TestResult {
    use crate::authority_host_service::generation_initial::Command;

    let command: Command = serde_json::from_str(r#"{"kind":"read_learning_trust"}"#)?;
    assert!(matches!(command, Command::ReadLearningTrust {}));
    for field in ["root", "distribution", "generator", "observer", "completed"] {
        let mut value = serde_json::json!({"kind": "read_learning_trust"});
        value[field] = serde_json::json!(true);
        assert!(serde_json::from_value::<Command>(value).is_err());
    }
    Ok(())
}
