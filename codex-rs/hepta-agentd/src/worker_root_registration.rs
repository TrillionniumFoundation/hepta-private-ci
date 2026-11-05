//! Worker-specific Root custody, before any provider or FinalUse activation.
//! A received registration is an observation, never an effect capability.

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use serde::Deserialize;
use serde::Serialize;
use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixDatagram;
use std::time::Duration;

#[path = "worker_root_process.rs"]
pub(crate) mod process;

#[path = "worker_root_registration_wire.rs"]
pub(crate) mod wire;

#[path = "worker_root_lanes_wire.rs"]
pub(crate) mod lanes_wire;
pub use lanes_wire::WorkerRootLaneBootstrapV1;
pub use lanes_wire::WorkerRootLanePathsV1;
pub use lanes_wire::WorkerRootObservationV1;

#[path = "worker_root_lanes_client.rs"]
mod lanes_client;
pub use lanes_client::WorkerRootLaneReceipt;

pub const WORKER_ROOT_REGISTRATION_V1: &str = "runtime.infer_worker.root_registration.v1";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct WorkerProcessIdentityV1 {
    pub uid: u32,
    pub gid: u32,
    pub pid: u32,
    pub boot_id: String,
    pub process_start_ticks: u64,
}

/// Public Root observations. Deserializing or copying these bytes conveys no
/// authority; only the inherited, sealed descriptor receiver retains custody.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct WorkerRootRegistrationV1 {
    pub schema_version: u32,
    pub purpose: String,
    pub registered_agent_id: AgentId,
    pub spawn_generation: u64,
    pub lifecycle_generation: u64,
    pub root: WorkerProcessIdentityV1,
    pub agentd: WorkerProcessIdentityV1,
    pub worker: WorkerProcessIdentityV1,
    pub registration_nonce: [u8; 32],
    pub consumer_namespace: String,
    pub issuer_lease: AuthorityLease,
    pub writer: crate::HostAuthorityWriterRegistration,
    pub writer_proof_sha256: Sha256Digest,
    pub observed_unix_ms: u64,
    pub expires_at_unix_ms: u64,
}

impl WorkerRootRegistrationV1 {
    pub(crate) fn validate(&self) -> io::Result<()> {
        self.writer.validate()?;
        if self.schema_version != 1
            || self.purpose != WORKER_ROOT_REGISTRATION_V1
            || self.spawn_generation == 0
            || self.lifecycle_generation < self.spawn_generation
            || self.registered_agent_id != self.writer.registered_agent_id
            || self.spawn_generation != self.writer.spawn_generation
            || self.root.uid != 0
            || matches!(self.worker.uid, 0 | u32::MAX)
            || matches!(self.worker.gid, 0 | u32::MAX)
            || self.agentd.uid == 0
            || self.worker.uid == self.agentd.uid
            || self.worker.gid == self.agentd.gid
            || self.root.pid == self.worker.pid
            || self.agentd.pid == self.worker.pid
            || self.root.pid == self.agentd.pid
            || self.root.boot_id != self.worker.boot_id
            || self.root.boot_id != self.agentd.boot_id
            || self.registration_nonce == [0; 32]
            || self.consumer_namespace != consumer_namespace(self)?
            || self.issuer_lease.schema_version != 1
            || self.issuer_lease.revision == 0
            || self.issuer_lease.authority_epoch != self.writer.authority_lease.authority_epoch
            || self.issuer_lease.binding.principal_id != self.registered_agent_id.as_str()
            || self.issuer_lease.binding.operation_class != "runtime.agentd.production_operation"
            || self.expires_at_unix_ms
                != self
                    .issuer_lease
                    .expires_at_unix_ms
                    .min(self.writer.authority_lease.expires_at_unix_ms)
            || self.observed_unix_ms < self.issuer_lease.issued_at_unix_ms
            || self.observed_unix_ms < self.writer.authority_lease.issued_at_unix_ms
            || self.observed_unix_ms >= self.expires_at_unix_ms
        {
            return Err(refused("Worker registration purpose, identity or authority pins differ"));
        }
        for peer in [&self.root, &self.agentd, &self.worker] {
            if peer.pid == 0
                || peer.pid > i32::MAX as u32
                || peer.process_start_ticks == 0
                || peer.boot_id.is_empty()
                || peer.boot_id.len() > 64
            {
                return Err(refused("complete process lifetime required"));
            }
        }
        Ok(())
    }
}

/// Receipt of a bounded registration exchange. This is deliberately not a
/// FinalUse owner, signer, live clock, consumer floor or production input.
/// There is no deserializer, Clone, raw-FD constructor or activation method.
/// A later independent Root Worker owner must revalidate currentness before
/// it can open its own floor. Abandoned receipts cannot authorize an effect.
pub struct WorkerRootRegistrationReceipt {
    registration: WorkerRootRegistrationV1,
    _sealed: File,
    _root_pidfd: OwnedFd,
    channel: UnixDatagram,
}

impl WorkerRootRegistrationReceipt {
    pub fn observation(&self) -> &WorkerRootRegistrationV1 {
        &self.registration
    }
}

impl Drop for WorkerRootRegistrationReceipt {
    fn drop(&mut self) {
        let _ = self.channel.shutdown(std::net::Shutdown::Both);
    }
}

/// Consume one inherited Root-created pair. The exact typed Worker purpose
/// rejects an Agentd/Notes bootstrap even if its descriptor custody is valid.
/// The ACK names the complete sealed bytes; Root checks its kernel sender.
/// A missing final confirmation returns no receipt and never retries.
pub fn receive_worker_root_registration(
    channel: UnixDatagram,
    expected_agent: &AgentId,
    expected_spawn: u64,
    timeout: Duration,
) -> io::Result<WorkerRootRegistrationReceipt> {
    let end = wire::deadline(timeout)?;
    let peer = crate::root_production_handoff::root_pair(&channel, timeout)
        .map_err(io::Error::other)?;
    let (mut sealed, root_pidfd) = crate::receive_root_production_handoff(
        channel.try_clone()?,
        wire::remaining(end)?,
    )
    .map_err(io::Error::other)?;
    let size = sealed.metadata()?.len();
    sealed.rewind()?;
    let mut bytes = Vec::new();
    Read::by_ref(&mut sealed)
        .take(crate::HOST_AUTHORITY_BOOTSTRAP_BOUND as u64 + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 != size || bytes.len() > crate::HOST_AUTHORITY_BOOTSTRAP_BOUND {
        return Err(refused("complete sealed Worker registration required"));
    }
    crate::authority_host_bootstrap_seal::validate_sealed(&sealed, size)?;
    let registration: WorkerRootRegistrationV1 =
        serde_json::from_slice(&bytes).map_err(io::Error::other)?;
    registration.validate()?;
    if registration.registered_agent_id != *expected_agent
        || registration.spawn_generation != expected_spawn
        || registration.root.pid != peer.pid as u32
        || registration.root.uid != peer.uid
        || registration.root.gid != peer.gid
        || registration.worker != process::observe(std::process::id())?
    {
        return Err(refused("actual receiver or expected original Agent differs"));
    }
    crate::authority_host_runtime::verify_process_credentials(
        registration.worker.pid,
        registration.worker.uid,
        registration.worker.gid,
    )?;
    process::verify(&registration.root, &root_pidfd, end)?;
    let digest = Sha256Digest::for_bytes(&bytes);
    wire::enable_credentials(&channel)?;
    wire::send(&channel, wire::Phase::Acknowledged, &digest, end)?;
    wire::receive(
        &channel,
        wire::Phase::Confirmed,
        &digest,
        &registration.root,
        end,
    )?;
    process::verify(&registration.root, &root_pidfd, end)?;
    if registration.worker != process::observe(std::process::id())? {
        return Err(refused("Worker identity changed across confirmation"));
    }
    Ok(WorkerRootRegistrationReceipt {
        registration,
        _sealed: sealed,
        _root_pidfd: root_pidfd,
        channel,
    })
}

pub(crate) fn consumer_namespace(value: &WorkerRootRegistrationV1) -> io::Result<String> {
    let bytes = serde_json::to_vec(&(
        WORKER_ROOT_REGISTRATION_V1,
        &value.registered_agent_id,
        value.spawn_generation,
        &value.worker,
        value.registration_nonce,
    ))
    .map_err(io::Error::other)?;
    let hash = Sha256Digest::for_bytes(&bytes);
    Ok(format!("worker-final-use-v1:{}", hash.as_str()))
}

pub(crate) fn refused(message: &str) -> io::Error {
    io::Error::new(
        io::ErrorKind::PermissionDenied,
        format!("Root Worker registration: {message}"),
    )
}
