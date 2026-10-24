//! Root's open-only handoff from the existing original five-lane state.
//! No state from qualification constructors enters this factory.

use super::*;
use crate::authority_host_config::HostAuthorityRegistration;
use crate::authority_host_config::HostAuthorityServiceConfig;
use crate::authority_host_runtime::verify_pinned_process;
use crate::authority_host_runtime::validate_runtime_lanes;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use std::fs::File;
use std::os::unix::fs::MetadataExt;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

/// Capture only already registered Root state, then seal it with the existing
/// memfd producer. `owner_pidfd` must have been retained for the actual daemon;
/// it is never opened from peer JSON. `consumer_state_root` is the original
/// daemon-owned private local-journal parent, distinct from Root's frontiers.
/// The original live feed, checkpoint client and FinalUse owners still verify
/// currentness after delivery. This is neither genesis nor a live grant.
impl HostAuthorityService {
pub(crate) fn seal_registered_bootstrap(
    &self,
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
    owner_pidfd: &OwnedFd,
    consumer_state_root: &Path,
) -> io::Result<File> {
    // SAFETY: geteuid reads the actual process identity without pointers.
    if unsafe { libc::geteuid() } != 0 {
        return Err(io::Error::new(io::ErrorKind::PermissionDenied, "Root producer required"));
    }
    let end = Instant::now() + Duration::from_secs(30);
    verify_pinned_process(registration, config.peer_uid, config.peer_gid, owner_pidfd, end)?;
    validate_runtime_lanes(config)?;
    let service = self;
    let writer = service.writer.as_ref().ok_or_else(|| io::Error::other("registered writer required"))?;
    let checkpoint = service.checkpoint.as_ref().ok_or_else(|| io::Error::other("registered Current required"))?;
    let consumers = service.consumers.as_ref().ok_or_else(|| io::Error::other("both original consumers required"))?;
    let slots = config.consumers.as_ref().ok_or_else(|| io::Error::other("fixed consumer namespaces required"))?;
    let local = std::fs::symlink_metadata(consumer_state_root)?;
    if consumer_state_root.canonicalize()? != consumer_state_root
        || !local.is_dir() || local.uid() != config.peer_uid || local.gid() != config.peer_gid
        || local.mode() & 0o7777 != 0o700
    {
        return Err(io::Error::other("original consumer journal parent must be private and peer-owned"));
    }
    let sockets = crate::HostAuthorityFiveLanePathsV1 {
        observation: config.sockets.observation.clone(),
        issuer: config.sockets.issuer.clone(),
        checkpoint: config.sockets.checkpoint.clone(),
        device_frontier: config.sockets.device_frontier.clone().ok_or_else(|| io::Error::other("missing device lane"))?,
        notes_frontier: config.sockets.notes_frontier.clone().ok_or_else(|| io::Error::other("missing Notes lane"))?,
    };
    writer.registration.with_live(&writer.leases, |_| {
        let proof = service.issuer.retained_writer_authorization(&writer.registration)?;
        if proof != writer.proof {
            return Err(io::Error::other("retained writer proof changed"));
        }
        let revocations = service.issuer.revocations()?;
        let head = checkpoint.backend.current_for_handoff().map_err(io::Error::other)?;
        let device = consumers.device.frontier_for_handoff(&revocations).map_err(io::Error::other)?;
        let notes = consumers.notes.frontier_for_handoff(&revocations).map_err(io::Error::other)?;
        let stat = std::fs::read_to_string("/proc/self/stat")?;
        let start = stat.rsplit_once(") ").and_then(|(_, fields)| fields.split_whitespace().nth(19))
            .and_then(|value| value.parse::<u64>().ok()).filter(|value| *value != 0)
            .ok_or_else(|| io::Error::other("missing actual Root process start identity"))?;
        let bundle = crate::HostAuthorityPublicBootstrapV1 {
            schema_version: 1, operation: crate::HOST_AUTHORITY_BOOTSTRAP_V1.into(),
            root: CognitiveCheckpointPeerLifetime {
                uid: 0, pid: std::process::id(), boot_id: registration.boot_id.clone(), process_start_ticks: start,
            },
            consumer: CognitiveCheckpointPeerLifetime {
                uid: config.peer_uid, pid: registration.peer_pid, boot_id: registration.boot_id.clone(),
                process_start_ticks: registration.process_start_ticks,
            },
            registered_identity: registration.registered_identity.clone(),
            issuer_key: service.issuer.trust_key()?.into(), revocations: revocations.clone(),
            writer: writer.registration.clone(), writer_proof: proof, checkpoint: head.clone(),
            consumers: crate::HostAuthorityPublicConsumersV1 {
                device: crate::HostAuthorityPublicConsumerV1 {
                    local_state_dir: consumer_state_root.join("device"), owner_id: slots.device.owner_id.clone(), frontier: device,
                },
                notes: crate::HostAuthorityPublicConsumerV1 {
                    local_state_dir: consumer_state_root.join("notes"), owner_id: slots.notes.owner_id.clone(), frontier: notes,
                },
            },
            sockets,
        };
        let sealed = crate::seal_host_authority_bootstrap(&bundle)?;
        // No publication ACK or output escapes after an uncertain read or an
        // observed concurrent change. No change is repaired or retried here.
        if service.issuer.revocations()? != revocations
            || checkpoint.backend.current_for_handoff().map_err(io::Error::other)? != head
            || consumers.device.frontier_for_handoff(&revocations).map_err(io::Error::other)? != device
            || consumers.notes.frontier_for_handoff(&revocations).map_err(io::Error::other)? != notes
            || service.issuer.retained_writer_authorization(&writer.registration)? != writer.proof
        {
            return Err(io::Error::other("original authority state changed during handoff capture"));
        }
        validate_observation_lease(&writer.registration.authority_lease, &revocations,
            service.clock.now_unix_ms().map_err(io::Error::other)?)?;
        validate_runtime_lanes(config)?;
        verify_pinned_process(registration, config.peer_uid, config.peer_gid, owner_pidfd, end)?;
        Ok(sealed)
    })
}
}
