//! Open-only checkpoint lane for the exact registered original writer/peer.

use super::*;
use crate::HostCognitiveCheckpoint;
use crate::HostCognitiveCheckpointRegistration;
use crate::root_writer_proof::VerifiedRootWriterProof;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_memory::CognitiveCheckpointWriterBinding;
use crate::authority_host_checkpoint::MaterialIntent;
use crate::authority_host_material::PreparedCheckpointMaterial;
use crate::authority_host_material::RegisteredMaterialArchive;

pub(super) struct RegisteredCheckpoint {
    pub(super) backend: HostCognitiveCheckpoint,
    pub(super) peer: CognitiveCheckpointPeerLifetime,
    pub(super) material: std::sync::OnceLock<RegisteredMaterialArchive>,
    pub(super) material_attempted: std::sync::atomic::AtomicBool,
    pub(super) recovered: Option<RecoveredCheckpointInstall>,
}

// Ephemeral receipt retained by the one trusted recovery composition. This is
// not serialized, cloned, remotely selectable or an independent authority head.
pub(super) struct RecoveredCheckpointInstall {
    pub(super) previous: codex_hepta_memory::CognitiveCheckpointReceipt,
    pub(super) attempted: std::sync::atomic::AtomicBool,
    pub(super) installed: std::sync::atomic::AtomicBool,
}

impl RegisteredCheckpoint {
    pub(super) fn open(
        directory: Arc<RootAuthorityDirectory>,
        registration: HostCognitiveCheckpointRegistration,
        clock: Arc<HostAuthorityClock>,
    ) -> io::Result<Self> {
        Ok(Self {
            recovered: None,
            material: std::sync::OnceLock::new(),
            material_attempted: std::sync::atomic::AtomicBool::new(false),
            peer: registration.peer_lifetime.clone(),
            backend: HostCognitiveCheckpoint::open(directory, registration, clock)
                .map_err(io::Error::other)?,
        })
    }

    /// Large copy/schema/integrity work precedes the registry writer fence.
    /// The original handler independently rechecks full request/predecessor
    /// and the held image immediately before its existing durable CAS.
    pub(super) fn prepare_material(&self, bytes: &[u8]) -> io::Result<Option<PreparedCheckpointMaterial>> {
        let prepared = (|| {
            let Some(intent) = self.backend.material_intent(bytes).map_err(io::Error::other)? else {
                return Ok(None);
            };
            let archive = self.material.get().ok_or_else(|| io::Error::other("registered physical material archive required"))?;
            match intent {
                MaterialIntent::Prepare(cut) => archive.prepare(bytes, &cut),
                MaterialIntent::Retained(cut) => archive.retained(bytes, &cut),
            }.map(Some)
        })();
        if prepared.is_err() {
            self.backend.close();
        }
        prepared
    }

    pub(super) fn validate_peer(&self, peer: HostIssuerPeer) -> io::Result<()> {
        if self.peer.uid != peer.uid || self.peer.pid != peer.pid {
            return Err(io::Error::other("checkpoint fixed peer mismatch"));
        }
        let boot = std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?;
        let stat = std::fs::read_to_string(format!("/proc/{}/stat", peer.pid))?;
        let start = stat
            .rsplit_once(") ")
            .and_then(|(_, fields)| fields.split_whitespace().nth(19))
            .and_then(|value| value.parse::<u64>().ok());
        if boot.trim() != self.peer.boot_id || start != Some(self.peer.process_start_ticks) {
            return Err(io::Error::other("checkpoint fixed lifetime mismatch"));
        }
        Ok(())
    }
}

impl RegisteredWriter {
    /// Derive the original whole-writer binding through its verified proof and
    /// original ProductionAuthorityLease implementation; do not invent hashes.
    pub(super) fn checkpoint_registration(
        &self,
        issuer: &DeploymentFinalUseIssuer,
        publisher_epoch: u64,
        peer_lifetime: CognitiveCheckpointPeerLifetime,
    ) -> io::Result<HostCognitiveCheckpointRegistration> {
        let registration = &self.registration;
        let key = issuer.trust_key()?;
        let verified = VerifiedRootWriterProof::verify(
            self.proof.clone(),
            &crate::AgentdRootWriterTrust {
                issuer_id: key.key_id,
                verifying_key: key.verifying_key,
                agent_id: registration.registered_agent_id.clone(),
                spawn_generation: registration.spawn_generation,
                owner_epoch: registration.owner_epoch,
                local_lease_id: registration.local_lease_id.clone(),
                local_lease_generation: registration.local_lease_generation,
                authority_lease: registration.authority_lease.clone(),
            },
        )
        .map_err(io::Error::other)?;
        let authority = verified.authority();
        Ok(HostCognitiveCheckpointRegistration {
            owner_agent_id: authority.agent_id.clone(),
            publisher_epoch,
            writer_binding: CognitiveCheckpointWriterBinding {
                lease_id: registration.local_lease_id.clone(),
                generation: registration.local_lease_generation,
                authority_epoch: authority.authority_epoch,
                owner_epoch: authority.owner_epoch,
                authority_grant_digest: authority.grant_digest.clone(),
                fencing_token_digest: authority.fencing_token_digest().map_err(io::Error::other)?,
                expires_at_unix_seconds: authority.lease_expires_at_unix_seconds,
            },
            peer_lifetime,
        })
    }
}
