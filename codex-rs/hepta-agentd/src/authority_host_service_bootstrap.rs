//! Read-only Root capture from the already composed original service.
use super::*;
use crate::HostAuthorityFiveLanePathsV1;
use crate::HostAuthorityPublicBootstrapV1;
use crate::HostAuthorityPublicConsumerV1;
use crate::HostAuthorityPublicConsumersV1;
use crate::HostAuthorityPublicIssuerKeyV1;
use crate::HostAuthorityRegisteredIdentity;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::HostAuthorityOwnerLifetime;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use std::os::unix::fs::MetadataExt;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

#[path = "authority_host_bootstrap_process.rs"]
mod process;

/// Root launcher input, installed exactly once. This is deliberately neither
/// Clone nor Serde. No ordinary request selects these paths or the lifetime.
pub struct HostAuthorityBootstrapLocations {
    pub sockets: HostAuthorityFiveLanePathsV1,
    pub device_local_state_dir: PathBuf,
    pub notes_local_state_dir: PathBuf,
    /// The original OwnerChannel's non-renewing hard bound, at most 300 seconds.
    pub lifetime: Duration,
}

pub(super) struct RegisteredBootstrap {
    root: CognitiveCheckpointPeerLifetime,
    consumer: CognitiveCheckpointPeerLifetime,
    locations: HostAuthorityBootstrapLocations,
    owner: HostAuthorityOwnerLifetime,
}

impl RegisteredBootstrap {
    pub(super) fn validate_peer(&self, peer: codex_hepta_contracts::HostIssuerPeer) -> io::Result<()> {
        if peer.uid != self.consumer.uid || peer.pid != self.consumer.pid {
            return Err(io::Error::other("bootstrap fixed Host peer mismatch"));
        }
        self.check_serving()
    }

    pub(super) fn check_serving(&self) -> io::Result<()> {
        // SAFETY: geteuid reads the actual caller without borrowed pointers.
        if std::process::id() != self.root.pid || unsafe { libc::geteuid() } != 0 {
            return Err(io::Error::other("bootstrap must be served by its actual Root producer"));
        }
        self.owner.check_alive().map_err(io::Error::other)
    }

    pub(super) fn verify_processes(&self) -> io::Result<()> {
        self.check_serving()?;
        process::verify_root(&self.root)?;
        process::verify_consumer(&self.consumer)?;
        self.check_serving()
    }
}

impl HostAuthorityService {
    /// Attach one launcher's pre-held actual Host pidfd to this exact assembled
    /// service. The launcher attests namespace provenance; this method never
    /// opens a numeric PID. No lease, proof, cut, consumer or sequence is made.
    /// Root must retain this same service/PID and subsequently serve its lanes.
    pub fn with_bootstrap_registration(
        mut self,
        locations: HostAuthorityBootstrapLocations,
        preheld_host_pidfd: OwnedFd,
    ) -> io::Result<Self> {
        if self.bootstrap.is_some() || self.writer.is_none() || self.consumers.is_none() {
            return Err(io::Error::other("bootstrap requires one complete registered service"));
        }
        let consumer = self.checkpoint.as_ref()
            .ok_or_else(|| io::Error::other("registered checkpoint required"))?.peer.clone();
        let root = process::current_root()?;
        process::verify_consumer(&consumer)?;
        validate_locations(&locations)?;
        let owner = HostAuthorityOwnerLifetime::from_pidfd(preheld_host_pidfd,
            consumer.pid, locations.lifetime).map_err(io::Error::other)?;
        let registration = RegisteredBootstrap { root, consumer, locations, owner };
        registration.verify_processes()?;
        self.bootstrap = Some(registration);
        Ok(self)
    }

    /// Capture the existing original Current/full consumer frontiers under the
    /// original writer registry dispatch fence. This is not a wire operation,
    /// genesis, authority mint, sequence spend, recovery hash or reset. Unknown
    /// backends remain closed; the generic protected store is never reopened.
    pub fn capture_public_bootstrap(&self) -> io::Result<HostAuthorityPublicBootstrapV1> {
        let bootstrap = self.bootstrap.as_ref()
            .ok_or_else(|| io::Error::other("Root bootstrap registration required"))?;
        let writer = self.writer.as_ref().ok_or_else(|| io::Error::other("writer required"))?;
        let checkpoint = self.checkpoint.as_ref().ok_or_else(|| io::Error::other("checkpoint required"))?;
        let consumers = self.consumers.as_ref().ok_or_else(|| io::Error::other("consumers required"))?;
        writer.registration.with_live(&writer.leases, |_| {
            // This callback must never re-enter the original registry.
            bootstrap.verify_processes()?;
            validate_locations(&bootstrap.locations)?;
            let proof = self.issuer.retained_writer_authorization(&writer.registration)?;
            if proof != writer.proof {
                return Err(io::Error::other("retained canonical writer proof changed"));
            }
            let key: HostAuthorityPublicIssuerKeyV1 = self.issuer.trust_key()?.into();
            let revocations = self.issuer.revocations()?;
            let head = checkpoint.backend.retained_current_for_root().map_err(io::Error::other)?;
            let expected = writer.checkpoint_registration(&self.issuer,
                head.publisher_epoch, bootstrap.consumer.clone())?;
            if head.owner_agent_id != expected.owner_agent_id
                || head.publisher_epoch != expected.publisher_epoch
                || head.writer_binding != expected.writer_binding
                || head.peer_lifetime != expected.peer_lifetime
            {
                return Err(io::Error::other("complete original writer/checkpoint binding mismatch"));
            }
            let public_consumer = |backend: &crate::HostConsumerFrontier, local: &PathBuf| {
                Ok::<_, io::Error>(HostAuthorityPublicConsumerV1 {
                    local_state_dir: local.clone(),
                    owner_id: key.key_id.clone(),
                    frontier: backend.retained_frontier_for_root(&key.key_id, &revocations)
                        .map_err(io::Error::other)?,
                })
            };
            let identity = &self.identity;
            let bundle = HostAuthorityPublicBootstrapV1 {
                schema_version: 1,
                operation: crate::HOST_AUTHORITY_BOOTSTRAP_V1.into(),
                root: bootstrap.root.clone(),
                consumer: bootstrap.consumer.clone(),
                registered_identity: HostAuthorityRegisteredIdentity {
                    agent_id: identity.agent_id.clone(), spawn_generation: identity.spawn_generation,
                    fleet_root: identity.fleet_root.clone(), workspace: identity.workspace.clone(),
                    resources: identity.resources.clone(),
                },
                consumers: HostAuthorityPublicConsumersV1 {
                    device: public_consumer(&consumers.device, &bootstrap.locations.device_local_state_dir)?,
                    notes: public_consumer(&consumers.notes, &bootstrap.locations.notes_local_state_dir)?,
                },
                issuer_key: key.clone(), revocations: revocations.clone(),
                writer: writer.registration.clone(), writer_proof: proof.clone(), checkpoint: head,
                sockets: bootstrap.locations.sockets.clone(),
            };
            crate::authority_host_bootstrap_seal::encode_public_bootstrap(&bundle)?;
            bootstrap.verify_processes()?;
            validate_locations(&bootstrap.locations)?;
            if self.issuer.revocations()? != revocations
                || HostAuthorityPublicIssuerKeyV1::from(self.issuer.trust_key()?) != key
                || self.issuer.retained_writer_authorization(&writer.registration)? != proof
            {
                return Err(io::Error::other("canonical owner changed during read-only capture"));
            }
            validate_observation_lease(&writer.registration.authority_lease, &revocations,
                self.clock.now_unix_ms().map_err(io::Error::other)?)?;
            bootstrap.check_serving()?;
            Ok(bundle)
        })
    }
}

fn clean_absolute(path: &Path) -> bool {
    path.is_absolute() && !path.components().any(|part| matches!(part, Component::CurDir | Component::ParentDir))
}

fn validate_locations(locations: &HostAuthorityBootstrapLocations) -> io::Result<()> {
    let s = &locations.sockets;
    let sockets = [&s.observation, &s.issuer, &s.checkpoint, &s.device_frontier, &s.notes_frontier];
    let parent = s.observation.parent().ok_or_else(|| io::Error::other("socket parent"))?;
    if sockets.iter().collect::<std::collections::BTreeSet<_>>().len() != 5
        || sockets.iter().any(|path| !clean_absolute(path) || path.parent() != Some(parent))
    {
        return Err(io::Error::other("five distinct fixed absolute socket paths required"));
    }
    let runtime = std::fs::symlink_metadata(parent)?;
    if !runtime.is_dir() || runtime.uid() != 0 || runtime.gid() != process::CONSUMER_UID
        || runtime.mode() & 0o7777 != 0o2710
    {
        return Err(io::Error::other("fixed runtime must be Root:Host mode02710"));
    }
    for ancestor in parent.ancestors() {
        let entry = std::fs::symlink_metadata(ancestor)?;
        if !entry.is_dir() || entry.uid() != 0 || entry.mode() & 0o022 != 0 {
            return Err(io::Error::other("unsafe fixed runtime ancestor"));
        }
    }
    let device = &locations.device_local_state_dir;
    let notes = &locations.notes_local_state_dir;
    if !clean_absolute(device) || !clean_absolute(notes) || device == notes
        || device.parent() != notes.parent() || device.parent().and_then(Path::parent) != Some(parent)
    {
        return Err(io::Error::other("distinct fixed local journal paths required"));
    }
    let journals = std::fs::symlink_metadata(device.parent().ok_or_else(|| io::Error::other("journal parent"))?)?;
    if !journals.is_dir() || journals.uid() != process::CONSUMER_UID
        || journals.gid() != process::CONSUMER_UID || journals.mode() & 0o7777 != 0o700
    {
        return Err(io::Error::other("fixed journal parent must be Host0700"));
    }
    Ok(())
}
