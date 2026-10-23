//! Synthetic-key fixtures qualify conversion and binding, not a deployment.
use super::*;
use crate::HostAuthorityWriterObservationV2;
use crate::HostWriterAuthorizationClaimsV1;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::HostAuthorityClockProjection;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

pub(crate) fn fixture() -> (AgentdRootWriterTrust, HostSignedWriterAuthorizationV1) {
    let key = SigningKey::from_bytes(&[47; 32]);
    let agent_id = AgentId::parse("00000000-0000-4000-8000-000000000001").unwrap();
    let lease = AuthorityLease {
        schema_version: 1,
        lease_id: "root-writer".into(),
        authority_epoch: 2,
        revision: 7,
        binding: AuthorityLeaseBinding {
            principal_id: agent_id.to_string(),
            operation_class: "runtime.agentd.production_writer".into(),
            destination_id: "notes".into(),
            scope_sha256: [1; 32],
            payload_sha256: [2; 32],
        },
        issued_at_unix_ms: 1_000,
        expires_at_unix_ms: 30_999,
    };
    let trust = AgentdRootWriterTrust {
        issuer_id: "root-issuer".into(),
        verifying_key: key.verifying_key().to_bytes(),
        agent_id: agent_id.clone(),
        spawn_generation: 3,
        owner_epoch: 4,
        local_lease_id: "local-writer".into(),
        local_lease_generation: 5,
        authority_lease: lease.clone(),
    };
    let claims = HostWriterAuthorizationClaimsV1 {
        schema_version: 1,
        issuer_id: trust.issuer_id.clone(),
        sequence: 13,
        registered_agent_id: agent_id,
        spawn_generation: trust.spawn_generation,
        owner_epoch: trust.owner_epoch,
        local_lease_id: trust.local_lease_id.clone(),
        local_lease_generation: trust.local_lease_generation,
        authority_lease_sha256: Sha256Digest::for_bytes(&serde_json::to_vec(&lease).unwrap()),
        authority_lease: lease,
    };
    let signature = key.sign(&claims.signing_bytes().unwrap());
    let signature_hex = signature
        .to_bytes()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    (
        trust,
        HostSignedWriterAuthorizationV1 {
            claims,
            signature_hex,
        },
    )
}

pub(crate) fn observation(
    proof: &HostSignedWriterAuthorizationV1,
) -> HostAuthorityObservationResponseV2 {
    let claims = &proof.claims;
    HostAuthorityObservationResponseV2 {
        schema_version: 2,
        operation: HOST_AUTHORITY_OBSERVATION_V2.into(),
        authority_epoch: claims.authority_lease.authority_epoch,
        revocations: FinalUseRevocations {
            authority_epoch: claims.authority_lease.authority_epoch,
            revision: 1,
            revoked_grant_ids: Default::default(),
        },
        clock: HostAuthorityClockProjection {
            schema_version: 1,
            boot_id: "fixture-boot".into(),
            anchor_boottime_ns: 1,
            anchor_unix_ms: 2_000,
            ceiling_unix_ms: 3_000,
        },
        observed_unix_ms: 2_000,
        registered_agent_id: claims.registered_agent_id.clone(),
        spawn_generation: claims.spawn_generation,
        writer: HostAuthorityWriterObservationV2 {
            authority_lease: claims.authority_lease.clone(),
            store_revision: 7,
            authority_lease_sha256: claims.authority_lease_sha256.clone(),
            owner_epoch: claims.owner_epoch,
            local_lease_id: claims.local_lease_id.clone(),
            local_lease_generation: claims.local_lease_generation,
            writer_authorization_sha256: proof.sha256().unwrap(),
        },
    }
}

#[test]
fn verified_complete_proof_and_ascii_signature_create_exact_original_lease() {
    let (trust, proof) = fixture();
    let verified = VerifiedRootWriterProof::verify(proof.clone(), &trust).unwrap();
    let expected = ProductionAuthorityLease::from_verified_parts(
        trust.agent_id.clone(),
        Sha256Digest::for_bytes(&serde_json::to_vec(&proof).unwrap()),
        2,
        4,
        30,
        ProductionAuthorityToken::from_verified_bytes(proof.signature_hex.as_bytes().to_vec())
            .unwrap(),
    )
    .unwrap();
    assert_eq!(verified.authority(), &expected);
    let unsigned = Sha256Digest::for_bytes(&proof.claims.signing_bytes().unwrap());
    assert_ne!(verified.authority().grant_digest, unsigned);
    assert_eq!(
        verified.authority().fencing_token_digest().unwrap(),
        expected.fencing_token_digest().unwrap()
    );
}

#[test]
fn original_signature_domain_key_spelling_and_static_registration_are_all_required() {
    let (trust, proof) = fixture();
    for index in 0..11 {
        let mut wrong = proof.clone();
        let mut expected = trust.clone();
        match index {
            0 => wrong.signature_hex.make_ascii_uppercase(),
            1 => {
                let replacement = if wrong.signature_hex.starts_with('0') {
                    "1"
                } else {
                    "0"
                };
                wrong.signature_hex.replace_range(0..1, replacement);
            }
            2 => {
                expected.verifying_key =
                    SigningKey::from_bytes(&[48; 32]).verifying_key().to_bytes()
            }
            3 => expected.verifying_key = [0; 32],
            4 => wrong.claims.sequence += 1,
            5 => expected.owner_epoch += 1,
            6 => expected.spawn_generation += 1,
            7 => expected.local_lease_generation += 1,
            8 => expected.authority_lease.binding.destination_id = "other".into(),
            9 => expected.authority_lease.revision += 1,
            10 => {
                let wrong_domain = serde_json::to_vec(&wrong.claims).unwrap();
                wrong.signature_hex = SigningKey::from_bytes(&[47; 32])
                    .sign(&wrong_domain)
                    .to_bytes()
                    .iter()
                    .map(|byte| format!("{byte:02x}"))
                    .collect();
            }
            _ => unreachable!(),
        }
        assert!(
            VerifiedRootWriterProof::verify(wrong, &expected).is_err(),
            "case {index}"
        );
    }
    let mut mutated = serde_json::to_value(&proof).unwrap();
    mutated["claims"]["unexpected"] = serde_json::json!(true);
    assert!(serde_json::from_value::<HostSignedWriterAuthorizationV1>(mutated).is_err());
    let mut duplicate = serde_json::to_string(&proof).unwrap();
    duplicate = duplicate.replacen("\"sequence\":13", "\"sequence\":13,\"sequence\":13", 1);
    assert!(serde_json::from_str::<HostSignedWriterAuthorizationV1>(&duplicate).is_err());
}

#[test]
fn observation_requires_full_fixed_identity_but_allows_unrelated_store_advancement() {
    let (trust, proof) = fixture();
    let verified = VerifiedRootWriterProof::verify(proof.clone(), &trust).unwrap();
    let original = observation(&proof);
    assert_eq!(verified.matches_observation(&original), Ok(()));
    let mut next = original.clone();
    next.writer.store_revision += 100;
    assert_eq!(verified.matches_observation(&next), Ok(()));
    for index in 0..11 {
        let mut wrong = original.clone();
        match index {
            0 => wrong.writer.authority_lease.revision += 1,
            1 => wrong.writer.authority_lease.binding.payload_sha256 = [9; 32],
            2 => wrong.writer.authority_lease_sha256 = Sha256Digest::for_bytes(b"wrong"),
            3 => wrong.writer.writer_authorization_sha256 = Sha256Digest::for_bytes(b"wrong"),
            4 => wrong.writer.owner_epoch += 1,
            5 => wrong.writer.local_lease_id = "other".into(),
            6 => wrong.writer.local_lease_generation += 1,
            7 => wrong.spawn_generation += 1,
            8 => wrong.authority_epoch += 1,
            9 => wrong.writer.store_revision = 6,
            10 => wrong.observed_unix_ms = 30_000, // conservative floor, not 30_999
            _ => unreachable!(),
        }
        assert!(
            verified.matches_observation(&wrong).is_err(),
            "case {index}"
        );
    }
}

#[test]
fn correctly_signed_single_effect_lease_cannot_become_the_long_lived_writer() {
    let (mut trust, mut proof) = fixture();
    trust.authority_lease.binding.operation_class = "runtime.agentd.production_operation".into();
    proof.claims.authority_lease = trust.authority_lease.clone();
    proof.claims.authority_lease_sha256 =
        Sha256Digest::for_bytes(&serde_json::to_vec(&trust.authority_lease).unwrap());
    proof.signature_hex = SigningKey::from_bytes(&[47; 32])
        .sign(&proof.claims.signing_bytes().unwrap())
        .to_bytes()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    assert!(VerifiedRootWriterProof::verify(proof, &trust).is_err());
}
