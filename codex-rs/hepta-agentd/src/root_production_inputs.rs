//! Consume the original Root's sealed handoff and its five retained lanes.
//! No ordinary JSON, local cut, key, nonce owner or lease is substituted here.

use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::os::fd::OwnedFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseIssuerTrustKey;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::RootFinalUseFrontierClient;
use codex_hepta_contracts::RootPeerIdentity;

use crate::AgentdCognitiveCheckpointPeer;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdProtectedCheckpointInputs;
use crate::AgentdRootAuthorityPeer;
use crate::AgentdRootAuthoritySession;
use crate::AgentdRootWriterTrust;
use crate::AgentdUnixCognitiveCheckpointTransport;
use crate::AgentdUnixFinalUseGrantProvider;
use crate::HOST_AUTHORITY_BOOTSTRAP_BOUND;
use crate::HOST_AUTHORITY_BOOTSTRAP_V1;
use crate::HostAuthorityPublicBootstrapV1;
use crate::HostAuthorityPublicConsumerV1;
use crate::authority_host_config::HostAuthorityRegistration;

/// Retain `session` until the original runtime and recovered writer stop.
/// Device and Notes are the actual two journal owners installed in that same
/// live verifier; their clones share those owners, never a replacement ledger.
pub struct AgentdRootProductionInputs {
    pub session: AgentdRootAuthoritySession,
    pub checkpoint: AgentdProtectedCheckpointInputs<AgentdUnixCognitiveCheckpointTransport>,
    pub device: FinalUseAuthority,
    pub notes: FinalUseAuthority,
    pub grants: Arc<AgentdUnixFinalUseGrantProvider>,
    pub bootstrap: HostAuthorityPublicBootstrapV1,
}

/// Bootstrap only from the trusted launcher's original sealed descriptor and
/// pre-held Root pidfd. The fixed paths come from that sealed handoff. Each
/// connection is pinned to the same actual Root before protocol use; there is
/// no retry, PID discovery, authority initialization or alternate transport.
pub async fn receive_root_production_inputs(
    bootstrap: File,
    root_pidfd: OwnedFd,
    expected: &AgentdIdentity,
    timeout: Duration,
    lifetime: Duration,
) -> Result<AgentdRootProductionInputs, AgentdError> {
    if timeout.is_zero() || timeout > Duration::from_millis(500)
        || lifetime.is_zero() || lifetime > Duration::from_secs(300)
    {
        return Err(refused("bounded original Root bootstrap timing required"));
    }
    let end = Instant::now() + lifetime;
    let bundle = read_bootstrap(bootstrap, expected)?;
    let root = &bundle.root;
    crate::root_observation_stream::check_lifetime(&root_pidfd).map_err(protocol)?;
    // The original server accepts all fixed lanes before serving any request.
    // Connect all five first; requesting observation after only its connect
    // would deadlock against that original acceptance barrier.
    let observation = connect(&bundle.sockets.observation, timeout, end).await?;
    let issuer = connect(&bundle.sockets.issuer, timeout, end).await?;
    let checkpoint = connect(&bundle.sockets.checkpoint, timeout, end).await?;
    let device = connect(&bundle.sockets.device_frontier, timeout, end).await?;
    let notes = connect(&bundle.sockets.notes_frontier, timeout, end).await?;
    let trust = writer_trust(&bundle);
    crate::root_writer_proof::VerifiedRootWriterProof::verify(bundle.writer_proof.clone(), &trust)
        .map_err(protocol)?;
    let session = AgentdRootAuthoritySession::connect(
        observation,
        AgentdRootAuthorityPeer {
            pid: root.pid, boot_id: root.boot_id.clone(), process_start_ticks: root.process_start_ticks,
        },
        root_pidfd.try_clone()?, timeout, remaining(end)?, trust,
    ).await.map_err(protocol)?;
    if session.revocations().map_err(protocol)? != bundle.revocations
        || session.authority().grant_digest != bundle.writer_proof.sha256().map_err(protocol)?
    {
        return Err(refused("original Root head changed since sealed capture"));
    }
    let grants = Arc::new(AgentdUnixFinalUseGrantProvider::from_root_stream(
        issuer, root.pid, root_pidfd.try_clone()?, timeout, remaining(end)?,
    ).map_err(protocol)?);
    let checkpoint = AgentdUnixCognitiveCheckpointTransport::from_stream(
        checkpoint,
        AgentdCognitiveCheckpointPeer {
            pid: root.pid, boot_id: root.boot_id.clone(), process_start_ticks: root.process_start_ticks,
        },
        root_pidfd.try_clone()?, timeout, remaining(end)?,
    ).map_err(protocol)?.into_protected_inputs(bundle.checkpoint.clone()).await.map_err(protocol)?;
    let device = open_consumer(device, bundle.consumers.device.clone(), &bundle,
        root_pidfd.try_clone()?, session.clock(), timeout, remaining(end)?).await?;
    let notes = open_consumer(notes, bundle.consumers.notes.clone(), &bundle,
        root_pidfd, session.clock(), timeout, remaining(end)?).await?;
    session.activate_final_use_owners(vec![device.clone(), notes.clone()]).await.map_err(protocol)?;
    session.verifier().verify_sender_process_binding(
        &session.authority(), &expected.agent_id, &bundle.writer.local_lease_id,
        bundle.writer.local_lease_generation, expected.spawn_generation,
    ).map_err(AgentdError::GenerationFenced)?;
    remaining(end)?;
    Ok(AgentdRootProductionInputs { session, checkpoint, device, notes, grants, bootstrap: bundle })
}

fn read_bootstrap(mut file: File, expected: &AgentdIdentity) -> Result<HostAuthorityPublicBootstrapV1, AgentdError> {
    let length = file.metadata()?.len();
    if length == 0 || length > HOST_AUTHORITY_BOOTSTRAP_BOUND as u64 {
        return Err(refused("sealed Root handoff exceeds its original bound"));
    }
    crate::authority_host_bootstrap_seal::validate_sealed(&file, length)?;
    file.rewind()?;
    let mut bytes = Vec::new();
    Read::by_ref(&mut file).take(HOST_AUTHORITY_BOOTSTRAP_BOUND as u64 + 1).read_to_end(&mut bytes)?;
    crate::authority_host_bootstrap_seal::validate_sealed(&file, length)?;
    if bytes.len() as u64 != length {
        return Err(refused("sealed Root handoff length changed"));
    }
    let bundle: HostAuthorityPublicBootstrapV1 = serde_json::from_slice(&bytes)?;
    // SAFETY: these calls only read this process's actual kernel credentials.
    let (uid, gid) = unsafe { (libc::geteuid(), libc::getegid()) };
    if uid == 0 || gid == 0 || bundle.schema_version != 1 || bundle.operation != HOST_AUTHORITY_BOOTSTRAP_V1
        || bundle.root.uid != 0 || bundle.root.pid == 0 || bundle.root.pid == std::process::id()
        || bundle.consumer.uid != uid || bundle.consumer.pid != std::process::id()
        || bundle.consumer != bundle.checkpoint.peer_lifetime
        || bundle.registered_identity.identity()? != *expected
        || bundle.writer.registered_agent_id != expected.agent_id
        || bundle.writer.spawn_generation != expected.spawn_generation
        || bundle.checkpoint.owner_agent_id != expected.agent_id
    {
        return Err(refused("sealed Root handoff differs from the actual original Agentd launch"));
    }
    let registration = HostAuthorityRegistration {
        schema_version: 1, peer_pid: bundle.consumer.pid,
        boot_id: bundle.consumer.boot_id.clone(), process_start_ticks: bundle.consumer.process_start_ticks,
        registered_identity: bundle.registered_identity.clone(),
        checkpoint_owner_agent_id: expected.agent_id.clone(), publisher_epoch: bundle.checkpoint.publisher_epoch,
    };
    crate::authority_host_runtime::verify_process(&registration, uid, gid)?;
    crate::authority_host_runtime::validate_lane_paths(&[
        &bundle.sockets.observation, &bundle.sockets.issuer, &bundle.sockets.checkpoint,
        &bundle.sockets.device_frontier, &bundle.sockets.notes_frontier,
    ], gid)?;
    validate_local_consumers(&bundle, uid, gid)?;
    Ok(bundle)
}

fn validate_local_consumers(bundle: &HostAuthorityPublicBootstrapV1, uid: u32, gid: u32) -> Result<(), AgentdError> {
    let device = &bundle.consumers.device;
    let notes = &bundle.consumers.notes;
    let parent = device.local_state_dir.parent().ok_or_else(|| refused("consumer parent required"))?;
    let metadata = std::fs::symlink_metadata(parent)?;
    if !device.local_state_dir.is_absolute() || device.local_state_dir != parent.join("device")
        || notes.local_state_dir != parent.join("notes") || parent.canonicalize()? != parent
        || !metadata.is_dir() || metadata.uid() != uid || metadata.gid() != gid
        || metadata.mode() & 0o7777 != 0o700 || device.owner_id != bundle.issuer_key.key_id
        || notes.owner_id != bundle.issuer_key.key_id
    {
        return Err(refused("fixed private original consumer paths and canonical issuer required"));
    }
    Ok(())
}

fn writer_trust(bundle: &HostAuthorityPublicBootstrapV1) -> AgentdRootWriterTrust {
    AgentdRootWriterTrust {
        issuer_id: bundle.issuer_key.key_id.clone(), verifying_key: bundle.issuer_key.verifying_key,
        agent_id: bundle.writer.registered_agent_id.clone(), spawn_generation: bundle.writer.spawn_generation,
        owner_epoch: bundle.writer.owner_epoch, local_lease_id: bundle.writer.local_lease_id.clone(),
        local_lease_generation: bundle.writer.local_lease_generation, authority_lease: bundle.writer.authority_lease.clone(),
    }
}

async fn connect(path: &Path, timeout: Duration, end: Instant) -> Result<UnixStream, AgentdError> {
    let stream = tokio::time::timeout(timeout.min(remaining(end)?), tokio::net::UnixStream::connect(path))
        .await.map_err(|_| protocol("original Root connect deadline elapsed"))??;
    Ok(stream.into_std()?)
}

#[allow(clippy::too_many_arguments)]
async fn open_consumer(
    stream: UnixStream,
    consumer: HostAuthorityPublicConsumerV1,
    bundle: &HostAuthorityPublicBootstrapV1,
    root_pidfd: OwnedFd,
    clock: Arc<dyn AuthorityClock>,
    timeout: Duration,
    lifetime: Duration,
) -> Result<FinalUseAuthority, AgentdError> {
    let root = RootPeerIdentity {
        pid: bundle.root.pid, boot_id: bundle.root.boot_id.clone(), process_start_ticks: bundle.root.process_start_ticks,
    };
    let key = FinalUseIssuerTrustKey::from(bundle.issuer_key.clone());
    let revocations: FinalUseRevocations = bundle.revocations.clone();
    tokio::task::spawn_blocking(move || {
        let frontier = Arc::new(RootFinalUseFrontierClient::from_stream(
            stream, consumer.owner_id.clone(), root, root_pidfd, timeout, lifetime,
        ).map_err(protocol)?);
        if frontier.load(&consumer.owner_id).map_err(protocol)? != consumer.frontier {
            return Err(refused("original consumer frontier changed since sealed capture"));
        }
        // Only the original store may create its fresh journal. Its exact-head
        // and existing-lock rules reject missing/reset state on recovery.
        FinalUseAuthority::open_state_dir_with_issuer_keys(
            &consumer.local_state_dir, consumer.owner_id, vec![key], revocations, clock, frontier,
        ).map_err(protocol)
    }).await.map_err(protocol)?
}

fn remaining(end: Instant) -> Result<Duration, AgentdError> {
    end.checked_duration_since(Instant::now()).filter(|left| !left.is_zero())
        .ok_or_else(|| protocol("original Root bootstrap lifetime elapsed"))
}

fn refused(message: &str) -> AgentdError {
    AgentdError::GenerationFenced(message.into())
}

fn protocol(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Protocol(format!("original Root production inputs: {error}"))
}

#[cfg(test)]
#[path = "root_production_inputs_tests.rs"]
mod tests;
