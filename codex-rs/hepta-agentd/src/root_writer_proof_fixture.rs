//! Original synthetic-key fixture retained only for host checkpoint tests.
use super::*;
use codex_hepta_authority_types::HostSignedWriterAuthorizationV1;
use codex_hepta_authority_types::HostWriterAuthorizationClaimsV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

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
