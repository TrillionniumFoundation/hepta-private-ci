//! The actual registered Child consumes a second sealed Root handoff.
//! Three pinned lanes expose observations and the independent durable floor;
//! they do not create a local FinalUse journal or activate any effect owner.

use super::WorkerRootRegistrationReceipt;
use super::lanes_wire;
use super::process;
use super::refused;
use super::wire;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_contracts::RootFinalUseFrontierClient;
use codex_hepta_contracts::RootPeerIdentity;
use codex_hepta_contracts::Sha256Digest;
use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::net::Shutdown;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

#[path = "worker_root_journal_client.rs"]
pub(super) mod journal;

enum WorkerLaneSelection {
    ObservationOnly,
    Journal,
}

/// Non-cloneable, non-deserializable custody of the original Root lanes.
/// No raw-FD, trait/config or public-observation constructor exists. Keeping
/// this receipt alive alone grants no provider, tool, writer or Cell ability.
pub struct WorkerRootLaneReceipt {
    registration: WorkerRootRegistrationReceipt,
    bootstrap: lanes_wire::WorkerRootLaneBootstrapV1,
    _sealed: File,
    root_pidfd: OwnedFd,
    observation: HostAuthorityPeerChannel,
    writer: HostAuthorityPeerChannel,
    frontier: RootFinalUseFrontierClient,
    streams: Vec<UnixStream>,
    end: Instant,
    closed: bool,
}

impl Drop for WorkerRootLaneReceipt {
    fn drop(&mut self) { self.close(); }
}

impl WorkerRootRegistrationReceipt {
    /// Receive only from the original retained Root pair, then connect all
    /// fixed lanes before reading any response. Missing confirmation returns
    /// no receipt. There is no retry or local-disk fallback on any error.
    pub async fn receive_worker_lanes(self, timeout: Duration) -> io::Result<WorkerRootLaneReceipt> {
        let (lanes, journal) = self.receive_selected_worker_lanes(timeout, WorkerLaneSelection::ObservationOnly).await?;
        if journal.is_some() { return Err(refused("observation-only lane receiver cannot activate a journal")); }
        Ok(lanes)
    }

    /// Consume the original Root registration and the distinct journal offer.
    /// No caller path, key, clock, floor or initialization flag is accepted.
    pub async fn receive_worker_journal(self, timeout: Duration) -> io::Result<journal::WorkerRootJournal> {
        let (lanes, directory) = self.receive_selected_worker_lanes(timeout, WorkerLaneSelection::Journal).await?;
        journal::WorkerRootJournal::from_confirmed_lanes(lanes, directory.ok_or_else(|| refused("actual Root journal offer required"))?)
    }

    async fn receive_selected_worker_lanes(self, timeout: Duration, selection: WorkerLaneSelection) -> io::Result<(WorkerRootLaneReceipt, Option<super::journal_path::WorkerJournalDirectory>)> {
        let handoff_end = wire::deadline(timeout)?;
        process::verify(&self.registration.root, &self._root_pidfd, handoff_end)?;
        let (mut sealed, root_pidfd) = crate::receive_root_production_handoff(self.channel.try_clone()?, wire::remaining(handoff_end)?)
            .map_err(io::Error::other)?;
        let size = sealed.metadata()?.len();
        sealed.rewind()?;
        let mut bytes = Vec::new();
        Read::by_ref(&mut sealed).take(crate::HOST_AUTHORITY_BOOTSTRAP_BOUND as u64 + 1).read_to_end(&mut bytes)?;
        if bytes.len() as u64 != size || bytes.len() > crate::HOST_AUTHORITY_BOOTSTRAP_BOUND {
            return Err(refused("complete sealed Worker lane bootstrap required"));
        }
        crate::authority_host_bootstrap_seal::validate_sealed(&sealed, size)?;
        let (bootstrap, journal) = match selection {
            WorkerLaneSelection::Journal => {
                let bundle: super::journal_wire::WorkerRootJournalBootstrapV1 = serde_json::from_slice(&bytes).map_err(io::Error::other)?;
                bundle.validate()?;
                let directory = super::journal_path::WorkerJournalDirectory::open_from_root_pin(&bundle.journal)?;
                (bundle.lanes, Some(directory))
            }
            WorkerLaneSelection::ObservationOnly => {
                let bootstrap: lanes_wire::WorkerRootLaneBootstrapV1 = serde_json::from_slice(&bytes).map_err(io::Error::other)?;
                (bootstrap, None)
            }
        };
        bootstrap.validate()?;
        if bootstrap.registration != self.registration
            || self.registration.worker != process::observe(std::process::id())?
            || timeout > Duration::from_millis(bootstrap.timeout_ms)
        {
            return Err(refused("Worker lane handoff does not belong to the original actual receiver"));
        }
        process::verify(&bootstrap.registration.root, &root_pidfd, handoff_end)?;
        crate::authority_host_runtime::verify_process_credentials(
            self.registration.worker.pid, self.registration.worker.uid, self.registration.worker.gid,
        )?;
        crate::authority_host_runtime::validate_lane_paths(
            &[&bootstrap.sockets.observation, &bootstrap.sockets.issuer, &bootstrap.sockets.consumer_frontier], self.registration.worker.gid,
        )?;
        verify_writer(&bootstrap, &bootstrap.writer_proof)?;
        let digest = Sha256Digest::for_bytes(&bytes);
        wire::send(&self.channel, wire::Phase::Acknowledged, &digest, handoff_end)?;
        wire::receive(&self.channel, wire::Phase::Confirmed, &digest, &self.registration.root, handoff_end)?;
        process::verify(&self.registration.root, &root_pidfd, handoff_end)?;
        let end = Instant::now().checked_add(Duration::from_millis(bootstrap.lifetime_ms))
            .ok_or_else(|| refused("Worker lane lifetime overflow"))?;
        // The Root's earlier absolute deadline still wins at every response.
        // This local deadline cannot cause Root to renew a lease or owner.
        let observation = connect(&bootstrap.sockets.observation, handoff_end).await?;
        let writer = connect(&bootstrap.sockets.issuer, handoff_end).await?;
        let frontier = connect(&bootstrap.sockets.consumer_frontier, handoff_end).await?;
        let streams = vec![observation.try_clone()?, writer.try_clone()?, frontier.try_clone()?];
        let policy = HostAuthorityPeerPolicy {
            peer: HostIssuerPeer { uid: 0, pid: self.registration.root.pid },
            timeout,
            lifetime: wire::remaining(end)?,
            request_bound: 16 * 1024,
            response_bound: 64 * 1024,
        };
        let observation = HostAuthorityPeerChannel::from_stream(observation, policy, root_pidfd.try_clone()?)
            .map_err(io::Error::other)?;
        let writer = HostAuthorityPeerChannel::from_stream(writer, policy, root_pidfd.try_clone()?)
            .map_err(io::Error::other)?;
        let frontier = RootFinalUseFrontierClient::from_stream(
            frontier, bootstrap.owner_id.clone(), RootPeerIdentity {
                pid: self.registration.root.pid, boot_id: self.registration.root.boot_id.clone(), process_start_ticks: self.registration.root.process_start_ticks,
            }, root_pidfd.try_clone()?, timeout, wire::remaining(end)?,
        ).map_err(io::Error::other)?;
        let mut received = WorkerRootLaneReceipt { registration: self, bootstrap, _sealed: sealed, root_pidfd, observation, writer, frontier, streams, end, closed: false };
        // These are actual exchanges with the same Root. Failure drops and
        // closes all three streams, retaining the consumed slot on Root disk.
        let initial = received.read_observation()?;
        if initial.revocations != received.bootstrap.revocations
            || received.read_original_writer_proof()? != received.bootstrap.writer_proof
            || received.load_frontier().map_err(io::Error::other)? != received.bootstrap.frontier
        {
            return Err(refused("Worker original head, proof or floor changed during handoff"));
        }
        received.check()?;
        if let Some(directory) = journal.as_ref() { directory.check()?; }
        Ok((received, journal))
    }
}

impl WorkerRootLaneReceipt {
    pub fn bootstrap_observation(&self) -> &lanes_wire::WorkerRootLaneBootstrapV1 { &self.bootstrap }

    fn check(&self) -> io::Result<()> {
        if self.closed { return Err(refused("Worker lane owner was permanently fenced")); }
        process::verify(&self.registration.registration.root, &self.root_pidfd, self.end)?;
        process::verify(&self.registration.registration.root, &self.registration._root_pidfd, self.end)?;
        if self.registration.registration.worker != process::observe(std::process::id())? {
            return Err(refused("Worker process incarnation or credentials changed"));
        }
        crate::authority_host_runtime::verify_process_credentials(
            self.registration.registration.worker.pid, self.registration.registration.worker.uid, self.registration.registration.worker.gid,
        )
    }

    fn close(&mut self) {
        self.closed = true;
        for stream in &self.streams { let _ = stream.shutdown(Shutdown::Both); }
    }

    pub fn read_observation(&mut self) -> io::Result<lanes_wire::WorkerRootObservationV1> {
        let result = (|| {
            self.check()?;
            let request = lanes_wire::WorkerLaneReadRequest { schema_version: 1, operation: lanes_wire::WORKER_OBSERVATION_V1.into(), slot_sequence: self.bootstrap.slot_sequence };
            let bytes = self.observation.request(&serde_json::to_vec(&request).map_err(io::Error::other)?).map_err(io::Error::other)?;
            let value: lanes_wire::WorkerRootObservationV1 = serde_json::from_slice(&bytes).map_err(io::Error::other)?;
            if value.schema_version != 1 || value.operation != lanes_wire::WORKER_OBSERVATION_V1
                || value.registration_sha256 != self.bootstrap.registration_sha256()?
                || value.owner_id != self.bootstrap.owner_id || value.consumer_namespace != self.bootstrap.consumer_namespace
                || value.slot_sequence != self.bootstrap.slot_sequence || value.effect_authorization_available
                || value.expires_at_unix_ms != self.bootstrap.expires_at_unix_ms
                || value.observed_unix_ms < self.bootstrap.observed_unix_ms || value.observed_unix_ms >= value.expires_at_unix_ms
                || value.revocations.authority_epoch != self.bootstrap.revocations.authority_epoch
                || value.revocations.revision < self.bootstrap.revocations.revision
            {
                return Err(refused("Worker Root observation identity, head or deadline differs"));
            }
            self.check()?;
            Ok(value)
        })();
        if result.is_err() { self.close(); }
        result
    }

    pub fn read_original_writer_proof(&mut self) -> io::Result<crate::HostSignedWriterAuthorizationV1> {
        let result = (|| {
            self.check()?;
            let request = lanes_wire::WorkerLaneReadRequest { schema_version: 1, operation: lanes_wire::WORKER_WRITER_READ_V1.into(), slot_sequence: self.bootstrap.slot_sequence };
            let bytes = self.writer.request(&serde_json::to_vec(&request).map_err(io::Error::other)?).map_err(io::Error::other)?;
            let value: lanes_wire::WorkerWriterReadResponse = serde_json::from_slice(&bytes).map_err(io::Error::other)?;
            if value.schema_version != 1 || value.operation != lanes_wire::WORKER_WRITER_READ_V1
                || value.registration_sha256 != self.bootstrap.registration_sha256()? || value.slot_sequence != self.bootstrap.slot_sequence
                || value.effect_authorization_available || value.proof != self.bootstrap.writer_proof
            {
                return Err(refused("Worker issuer lane returned a different original proof or new authority"));
            }
            verify_writer(&self.bootstrap, &value.proof)?;
            self.check()?;
            Ok(value.proof)
        })();
        if result.is_err() { self.close(); }
        result
    }

    pub fn load_frontier(&mut self) -> Result<FinalUseFrontier, AuthorityTrustError> {
        let result = (|| {
            self.check().map_err(|_| AuthorityTrustError::Unavailable)?;
            let value = self.frontier.load(&self.bootstrap.owner_id)?;
            self.check().map_err(|_| AuthorityTrustError::Unavailable)?;
            Ok(value)
        })();
        if result.is_err() { self.close(); }
        result
    }

    /// The real Root CAS acknowledges durable state only. A Conflict proves
    /// a different expected record; any other error may follow persistence,
    /// closes every lane, and is never retried, refunded or reset here.
    pub fn compare_and_set_frontier(&mut self, expected: &FinalUseFrontier, next: &FinalUseFrontier) -> Result<(), AuthorityTrustError> {
        let result = (|| {
            self.check().map_err(|_| AuthorityTrustError::Unavailable)?;
            let outcome = self.frontier.compare_and_set(&self.bootstrap.owner_id, expected, next);
            self.check().map_err(|_| AuthorityTrustError::Unavailable)?;
            outcome
        })();
        if result.is_err() && result != Err(AuthorityTrustError::Conflict) { self.close(); }
        result
    }
}

fn verify_writer(bundle: &lanes_wire::WorkerRootLaneBootstrapV1, proof: &crate::HostSignedWriterAuthorizationV1) -> io::Result<()> {
    let writer = &bundle.registration.writer;
    let trust = crate::AgentdRootWriterTrust {
        issuer_id: bundle.issuer_key.key_id.clone(), verifying_key: bundle.issuer_key.verifying_key,
        agent_id: writer.registered_agent_id.clone(), spawn_generation: writer.spawn_generation, owner_epoch: writer.owner_epoch,
        local_lease_id: writer.local_lease_id.clone(), local_lease_generation: writer.local_lease_generation, authority_lease: writer.authority_lease.clone(),
    };
    crate::root_writer_proof::VerifiedRootWriterProof::verify(proof.clone(), &trust).map_err(io::Error::other)?;
    Ok(())
}

async fn connect(path: &Path, end: Instant) -> io::Result<UnixStream> {
    tokio::time::timeout(wire::remaining(end)?, tokio::net::UnixStream::connect(path))
        .await.map_err(|_| io::Error::new(io::ErrorKind::TimedOut, "Worker Root connect deadline elapsed"))??.into_std()
}
