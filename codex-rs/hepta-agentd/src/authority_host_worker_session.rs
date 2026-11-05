//! First Worker registration from the retained original Root session.
//! This layer holds custody only; it neither creates a floor nor serves grants.

use super::PreparedHostAuthoritySession;
use crate::worker_root_registration::WORKER_ROOT_REGISTRATION_V1;
use crate::worker_root_registration::WorkerRootRegistrationV1;
use crate::worker_root_registration::consumer_namespace;
use crate::worker_root_registration::process;
use crate::worker_root_registration::refused;
use crate::worker_root_registration::wire;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::FleetRegistry;
use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixDatagram;
use std::process::Child;
use std::time::Duration;

#[path = "worker_root_control.rs"]
mod control;

/// Actual Root retains the original session, exact Child borrow, pidfds,
/// sealed record and one private channel. Dropping it closes this handoff.
/// Its public surface exposes observations only, never an activation or grant.
pub struct HeldWorkerRootRegistration<'a> {
    registration: WorkerRootRegistrationV1,
    _session: &'a PreparedHostAuthoritySession,
    _registry: &'a FleetRegistry,
    _child: &'a mut Child,
    _worker: process::PinnedWorkerChild,
    _root_pidfd: OwnedFd,
    _sealed: File,
    _control: control::WorkerControlCustody,
    channel: UnixDatagram,
}

#[cfg(test)]
#[path = "worker_root_registration_root_tests.rs"]
mod tests;

impl HeldWorkerRootRegistration<'_> {
    pub fn observation(&self) -> &WorkerRootRegistrationV1 {
        &self.registration
    }
}

impl Drop for HeldWorkerRootRegistration<'_> {
    fn drop(&mut self) {
        // Do not kill or reap a caller's Child. Only this owned, one-shot
        // channel is closed; later activation must find a live Root owner.
        let _ = self.channel.shutdown(std::net::Shutdown::Both);
    }
}

impl PreparedHostAuthoritySession {
    /// Register one already-spawned dedicated Worker. The original concrete
    /// registry supplies current generation; no path-config constructor, peer
    /// PID, injected clock, new writer or consumer authority is accepted.
    /// The private pair must be created by this Root before spawning `child`.
    ///
    /// ACK and confirmation stay under the original issuer+writer lock. An
    /// error may follow descriptor delivery, so it is not permission to retry.
    /// The child receives no effect capability, and no activation exists in
    /// this layer even when both registration observations were delivered.
    pub fn register_worker_child<'a>(
        &'a self,
        registry: &'a FleetRegistry,
        child: &'a mut Child,
        channel: UnixDatagram,
        timeout: Duration,
    ) -> io::Result<HeldWorkerRootRegistration<'a>> {
        // SAFETY: these calls read only this Root process's actual credentials.
        if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 {
            return Err(refused("actual Root producer required"));
        }
        let end = wire::deadline(timeout)?;
        if timeout > Duration::from_millis(self.config.timeout_ms) {
            return Err(refused("Worker handoff exceeds the original service timeout"));
        }
        let identity = self.registration.registered_identity.identity()?;
        let control = control::WorkerControlCustody::capture(registry, &identity)?;
        let root_pidfd = process::pin(std::process::id())?;
        let root = process::observe(std::process::id())?;
        let worker = process::PinnedWorkerChild::capture(child, end)?;
        let agentd = process::observe(self.registration.peer_pid)?;
        if worker.identity.pid == agentd.pid {
            return Err(refused("Worker cannot impersonate the registered Agentd"));
        }
        if worker.identity.uid == agentd.uid || worker.identity.gid == agentd.gid {
            return Err(refused("Worker requires an independent non-Root UID/GID"));
        }
        let verify_original = || {
            crate::authority_host_runtime::verify_pinned_process(
                &self.registration,
                self.config.peer_uid,
                self.config.peer_gid,
                &self.owner_pidfd,
                end,
            )?;
            control.verify(registry, &identity)?;
            process::verify(&root, &root_pidfd, end)?;
            worker.verify(end)
        };
        verify_original()?;
        let mut nonce = [0_u8; 32];
        let mut offset = 0;
        while offset < nonce.len() {
            // SAFETY: getrandom writes only the unfilled suffix of our live
            // fixed-size nonce. No caller-selected file or RNG is consulted.
            let count = unsafe {
                libc::getrandom(nonce[offset..].as_mut_ptr().cast(), nonce.len() - offset, 0)
            };
            if count <= 0 {
                return Err(io::Error::last_os_error());
            }
            offset += count as usize;
            wire::remaining(end)?;
        }
        wire::enable_credentials(&channel)?;
        let (registration, sealed) = self.service.with_worker_registration_fence(|issuer, writer, proof, now| {
            verify_original()?;
            let mut registration = WorkerRootRegistrationV1 {
                schema_version: 1,
                purpose: WORKER_ROOT_REGISTRATION_V1.into(),
                registered_agent_id: identity.agent_id.clone(),
                spawn_generation: identity.spawn_generation,
                lifecycle_generation: control.generation(),
                root: root.clone(),
                agentd: agentd.clone(),
                worker: worker.identity.clone(),
                registration_nonce: nonce,
                consumer_namespace: String::new(),
                issuer_lease: issuer.clone(),
                writer: writer.clone(),
                writer_proof_sha256: proof,
                observed_unix_ms: now,
                expires_at_unix_ms: issuer.expires_at_unix_ms.min(writer.authority_lease.expires_at_unix_ms),
            };
            registration.consumer_namespace = consumer_namespace(&registration)?;
            let mut sealed = crate::authority_host_bootstrap_seal::seal_worker_registration(&registration)?;
            let mut bytes = Vec::new();
            sealed.read_to_end(&mut bytes)?;
            sealed.rewind()?;
            let digest = Sha256Digest::for_bytes(&bytes);
            crate::send_root_production_handoff(
                channel.try_clone()?,
                &sealed,
                &root_pidfd,
                wire::remaining(end)?,
            )
            .map_err(io::Error::other)?;
            wire::receive(&channel, wire::Phase::Acknowledged, &digest, &worker.identity, end)?;
            verify_original()?;
            wire::send(&channel, wire::Phase::Confirmed, &digest, end)?;
            verify_original()?;
            Ok((registration, sealed))
        })?;
        verify_original()?;
        Ok(HeldWorkerRootRegistration {
            registration,
            _session: self,
            _registry: registry,
            _child: child,
            _worker: worker,
            _root_pidfd: root_pidfd,
            _sealed: sealed,
            _control: control,
            channel,
        })
    }
}
