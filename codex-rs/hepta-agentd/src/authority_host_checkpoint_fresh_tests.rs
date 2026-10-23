//! Actual original owner/client binding to the concrete root backend. The key
//! and verifier below are qualification inputs, not deployed registry authority.

use super::*;
use crate::root_writer_proof::VerifiedRootWriterProof;
use codex_hepta_memory::CognitiveCheckpointReceipt;
use codex_hepta_memory::CognitiveCheckpointTransport;
use codex_hepta_memory::CognitiveRecoveryRequirement;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::ObjectiveSenderCheckpointError;
use codex_hepta_memory::ProductionAuthorityLease;
use codex_hepta_paths::HeptaFleetRoot;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

struct ConcreteBackendTransport(Arc<HostCognitiveCheckpoint>);

impl CognitiveCheckpointTransport for ConcreteBackendTransport {
    async fn exchange(&self, bytes: &[u8]) -> Result<Vec<u8>, ObjectiveSenderCheckpointError> {
        let backend = self.0.clone();
        let bytes = bytes.to_vec();
        tokio::task::spawn_blocking(move || backend.exchange(&bytes))
            .await.map_err(|_| ObjectiveSenderCheckpointError::Unavailable)?
            .map_err(|_| ObjectiveSenderCheckpointError::Unavailable)
    }
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn root_fresh_publication_binds_original_exclusive_owner_and_checkpoint_client() {
    let root = std::env::var_os("HEPTA_CHECKPOINT_TEST_ROOT")
        .expect("explicit root-owned data-bind qualification root required");
    let temp = tempfile::tempdir_in(root).unwrap();
    std::fs::set_permissions(temp.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let fleet = temp.path().join("fleet");
    std::fs::create_dir(&fleet).unwrap();
    let (mut trust, mut proof) = crate::root_writer_proof::tests::fixture();
    let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis() as u64;
    // Retain the original strict signature-to-authority conversion and full
    // grant-bound token derivation. This synthetic key has no deployment role.
    proof.claims.authority_lease.issued_at_unix_ms = now;
    proof.claims.authority_lease.expires_at_unix_ms = now + 60_000;
    proof.claims.authority_lease_sha256 = Sha256Digest::for_bytes(
        &serde_json::to_vec(&proof.claims.authority_lease).unwrap());
    trust.authority_lease = proof.claims.authority_lease.clone();
    proof.signature_hex = SigningKey::from_bytes(&[47; 32])
        .sign(&proof.claims.signing_bytes().unwrap()).to_bytes()
        .iter().map(|byte| format!("{byte:02x}")).collect();
    let verified = VerifiedRootWriterProof::verify(proof, &trust).unwrap();
    let authority = verified.authority().clone();
    let layout = HeptaFleetRoot::parse(fleet).unwrap().layout().agent(&trust.agent_id);
    let fresh = CognitiveStore::open(&layout).await.unwrap();
    let cut = fresh.recovery_anchor().await.unwrap();
    fresh.close().await;
    let path = temp.path().join("checkpoint");
    std::fs::create_dir(&path).unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
    let backend = Arc::new(HostCognitiveCheckpoint::initialize_fresh(
        RootAuthorityDirectory::open(&path).unwrap(),
        HostCognitiveCheckpointRegistration {
            owner_agent_id: trust.agent_id.clone(), publisher_epoch: 7,
            writer_binding: CognitiveCheckpointWriterBinding {
                lease_id: trust.local_lease_id.clone(), generation: trust.local_lease_generation,
                authority_epoch: authority.authority_epoch, owner_epoch: authority.owner_epoch,
                authority_grant_digest: authority.grant_digest.clone(),
                fencing_token_digest: authority.fencing_token_digest().unwrap(),
                expires_at_unix_seconds: authority.lease_expires_at_unix_seconds,
            },
            // This direct backend adapter deliberately does not qualify a peer
            // transport. Actual peer/pidfd tests live in the handoff/service suites.
            peer_lifetime: CognitiveCheckpointPeerLifetime {
                uid: 60001, pid: 12345, boot_id: "controlled-direct-adapter".into(), process_start_ticks: 12,
            },
        }, cut.clone(), Arc::new(codex_hepta_contracts::SystemAuthorityClock),
    ).unwrap());
    let head = backend.load().unwrap();
    let expected = CognitiveCheckpointReceipt { token: token_for(&head).unwrap(), head };
    let retained = authority.clone();
    let verifier = move |observed: &ProductionAuthorityLease, owner: &AgentId| {
        if observed == &retained && owner == &retained.agent_id { Ok(()) }
        else { Err("controlled qualification authority mismatch".into()) }
    };
    let store = CognitiveStore::open_with_recovery(&layout,
        CognitiveRecoveryRequirement::ExactCurrentCut(&cut), &authority, &verifier).await.unwrap();
    let (store, _checkpoint) = store.bind_protected_checkpoint(
        Arc::new(ConcreteBackendTransport(backend.clone())), expected, Duration::from_secs(2))
        .await.expect("fresh concrete Root publication must bind the unchanged original client");
    assert_eq!(store.recovery_anchor().await.unwrap(), cut);
    store.close().await;
    let after = backend.load().unwrap();
    assert_eq!(after.phase, CognitiveCheckpointPhase::Dirty);
    assert_eq!(after.last_current, cut);
}
