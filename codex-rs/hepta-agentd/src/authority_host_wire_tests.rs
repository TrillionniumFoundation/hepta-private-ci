use super::*;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use ed25519_dalek::Signer;
use ed25519_dalek::Verifier;
use std::io::Read;

fn claims() -> HostWriterAuthorizationClaimsV1 {
    let lease = AuthorityLease {
        schema_version: 1,
        lease_id: "root-writer-lease".into(),
        authority_epoch: 1,
        revision: 3,
        binding: AuthorityLeaseBinding {
            principal_id: "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12".into(),
            operation_class: "runtime.agentd.production_writer".into(),
            destination_id: "original-owner".into(),
            scope_sha256: [2; 32],
            payload_sha256: [3; 32],
        },
        issued_at_unix_ms: 10_000,
        expires_at_unix_ms: 20_000,
    };
    HostWriterAuthorizationClaimsV1 {
        schema_version: 1,
        issuer_id: "canonical-root-issuer".into(),
        sequence: 11,
        registered_agent_id: AgentId::parse(lease.binding.principal_id.clone()).unwrap(),
        spawn_generation: 7,
        owner_epoch: 4,
        local_lease_id: "original-local-lease".into(),
        local_lease_generation: 5,
        authority_lease_sha256: Sha256Digest::for_bytes(&serde_json::to_vec(&lease).unwrap()),
        authority_lease: lease,
    }
}

#[test]
fn shared_typed_proof_signature_binds_original_identity_epochs_lease_and_sequence() {
    let mut secret = [0; 32];
    std::fs::File::open("/dev/urandom")
        .unwrap()
        .read_exact(&mut secret)
        .unwrap();
    let key = ed25519_dalek::SigningKey::from_bytes(&secret);
    let original = claims();
    let bytes = original.signing_bytes().unwrap();
    let signature = key.sign(&bytes);
    key.verifying_key().verify(&bytes, &signature).unwrap();
    let mut variants = Vec::new();
    let mut changed = original.clone();
    changed.owner_epoch += 1;
    variants.push(changed);
    let mut changed = original.clone();
    changed.spawn_generation += 1;
    variants.push(changed);
    let mut changed = original.clone();
    changed.local_lease_generation += 1;
    variants.push(changed);
    let mut changed = original.clone();
    changed.authority_lease.revision += 1;
    variants.push(changed);
    let mut changed = original.clone();
    changed.authority_lease.expires_at_unix_ms += 1;
    variants.push(changed);
    let mut changed = original.clone();
    changed.authority_lease.binding.payload_sha256[0] ^= 1;
    variants.push(changed);
    let mut changed = original.clone();
    changed.sequence += 1;
    variants.push(changed);
    for changed in variants {
        assert!(
            key.verifying_key()
                .verify(&changed.signing_bytes().unwrap(), &signature)
                .is_err()
        );
    }
    assert!(
        key.verifying_key()
            .verify(&serde_json::to_vec(&original).unwrap(), &signature)
            .is_err(),
        "plain JSON is a different signing domain"
    );
}

#[test]
fn shared_proof_digest_covers_signature_and_closed_nested_original_lease() {
    let mut proof = HostSignedWriterAuthorizationV1 {
        claims: claims(),
        signature_hex: "ab".repeat(64),
    };
    let bytes = serde_json::to_vec(&proof).unwrap();
    assert_eq!(
        serde_json::from_slice::<HostSignedWriterAuthorizationV1>(&bytes).unwrap(),
        proof
    );
    let first = proof.sha256().unwrap();
    proof.signature_hex = "ac".repeat(64);
    assert_ne!(proof.sha256().unwrap(), first);
    for bad in ["AB".repeat(64), "ab".repeat(63), "ag".repeat(64)] {
        let mut value = serde_json::to_value(&proof).unwrap();
        value["signature_hex"] = serde_json::json!(bad);
        assert!(serde_json::from_value::<HostSignedWriterAuthorizationV1>(value).is_err());
    }
    let mut value = serde_json::to_value(&proof).unwrap();
    value["claims"]["authority_lease"]["untrusted_reset"] = serde_json::json!(true);
    assert!(serde_json::from_value::<HostSignedWriterAuthorizationV1>(value).is_err());
}

#[test]
fn shared_frontier_wire_has_no_owner_or_initializer_and_rejects_duplicates() {
    let request = HostConsumerFrontierRequestV1::CompareAndSet {
        schema_version: 1,
        request_id: 9,
        expected: FinalUseFrontier {
            authority_epoch: 1,
            revocation_revision: 1,
            state_sha256: [2; 32],
        },
        next: FinalUseFrontier {
            authority_epoch: 1,
            revocation_revision: 1,
            state_sha256: [3; 32],
        },
    };
    let bytes = serde_json::to_vec(&request).unwrap();
    assert_eq!(
        serde_json::from_slice::<HostConsumerFrontierRequestV1>(&bytes).unwrap(),
        request
    );
    let mut value = serde_json::to_value(&request).unwrap();
    value["owner_id"] = serde_json::json!("peer-selected");
    assert!(serde_json::from_value::<HostConsumerFrontierRequestV1>(value).is_err());
    let duplicate = std::str::from_utf8(&bytes)
        .unwrap()
        .replace("\"request_id\":9", "\"request_id\":9,\"request_id\":10");
    assert!(serde_json::from_str::<HostConsumerFrontierRequestV1>(&duplicate).is_err());
    assert!(
        serde_json::from_str::<HostConsumerFrontierRequestV1>(
            r#"{"operation":"initialize","schema_version":1,"request_id":1}"#
        )
        .is_err()
    );
}
