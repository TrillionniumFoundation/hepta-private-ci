//! One actual Root owner for the three dedicated Worker lanes.
//! The issuer lane only reads the original writer proof. No Sign operation,
//! FinalUse activation, ordinary Worker entry point or provider is exposed.

use super::HeldWorkerRootRegistration;
use super::floor::ReservedWorkerFloor;
use super::journal::RootWorkerJournal;
use crate::worker_root_registration::lanes_wire;
use crate::worker_root_registration::process;
use crate::worker_root_registration::refused;
use crate::worker_root_registration::wire;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_contracts::Sha256Digest;
use rustix::event::PollFd;
use rustix::event::PollFlags;
use rustix::event::Timespec;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::net::Shutdown;
use std::os::unix::net::UnixListener;
use std::os::unix::net::UnixStream;
use std::time::Duration;
use std::time::Instant;

#[path = "authority_host_worker_listeners.rs"]
mod listeners;
use listeners::BoundWorkerLanes;
use listeners::WorkerLane;

struct ConnectedLane {
    lane: WorkerLane,
    channel: HostAuthorityPeerChannel,
    stream: UnixStream,
}

impl Drop for ConnectedLane {
    fn drop(&mut self) {
        let _ = self.stream.shutdown(Shutdown::Both);
    }
}

struct RetainedFloor<'a>(&'a ReservedWorkerFloor);

impl Drop for RetainedFloor<'_> {
    fn drop(&mut self) {
        // This closes only the live owner. The durable consumed slot stays
        // consumed even after an unknown send, ACK, CAS, timeout or clean EOF.
        self.0.fence_unknown();
    }
}

impl HeldWorkerRootRegistration<'_> {
    pub(super) fn verify_original_custody(&self, end: Instant) -> io::Result<()> {
        let identity = self._session.registration.registered_identity.identity()?;
        crate::authority_host_runtime::verify_pinned_process(
            &self._session.registration,
            self._session.config.peer_uid,
            self._session.config.peer_gid,
            &self._session.owner_pidfd,
            end,
        )?;
        self._control.verify(self._registry, &identity)?;
        process::verify(&self.registration.root, &self._root_pidfd, end)?;
        self._worker.verify(end)
    }

    /// Consume the actual retained Root/Child registration and serve exactly
    /// one stable, previously provisioned Worker slot. No automatic fresh
    /// fallback, restart claim, reconnect, successor reset or refund exists.
    /// This blocks until the peer closes a lane or an original owner fails.
    pub fn serve_worker_lanes(self, timeout: Duration, lifetime: Duration) -> io::Result<()> {
        self.serve_worker_lanes_selected(timeout, lifetime, None)
    }

    /// Root alone selects a safe journal parent. The actual retained Child,
    /// original issuer/writer and reserved slot determine every other pin.
    /// This publishes only an empty directory and a second sealed offer; the
    /// Worker, after confirmation, creates its own journal as its actual UID.
    pub fn serve_worker_journal_lanes(self, journal_parent: &std::path::Path, timeout: Duration, lifetime: Duration) -> io::Result<()> {
        self.serve_worker_lanes_selected(timeout, lifetime, Some(journal_parent))
    }

    fn serve_worker_lanes_selected(self, timeout: Duration, lifetime: Duration, journal_parent: Option<&std::path::Path>) -> io::Result<()> {
        if timeout.is_zero() || timeout > Duration::from_millis(self._session.config.timeout_ms.min(5_000))
            || lifetime.is_zero() || lifetime > Duration::from_millis(self._session.config.lifetime_ms.min(300_000))
        {
            return Err(refused("Worker lane limits must remain within the original Root service"));
        }
        let end = Instant::now().checked_add(lifetime).ok_or_else(|| refused("Worker lifetime overflow"))?;
        let handoff_end = end.min(wire::deadline(timeout)?);
        self.verify_original_custody(handoff_end)?;
        let mut floor = ReservedWorkerFloor::reserve(self._session, &self.registration)?;
        // No error below can restore the prior Provisioned record.
        let result = (|| {
            self.verify_original_custody(handoff_end)?;
            let mut journal = match journal_parent {
                Some(parent) => Some(self._session.service.with_worker_floor_fence(Some(&self.registration), |view| {
                    self.verify_original_custody(handoff_end)?;
                    let journal = RootWorkerJournal::create_fresh(&floor, &self.registration, &view.owner_id, floor.frontier_for_handoff(&view.head)?, parent)?;
                    self.verify_original_custody(handoff_end)?;
                    Ok(journal)
                })?),
                None => None,
            };
            let bound = BoundWorkerLanes::bind(&self.registration, floor.slot_sequence())?;
            self._session.service.with_worker_floor_fence(Some(&self.registration), |view| {
                self.verify_original_custody(handoff_end)?;
                let observation = lanes_wire::WorkerRootLaneBootstrapV1 {
                    schema_version: 1,
                    purpose: lanes_wire::WORKER_ROOT_LANES_V1.into(),
                    registration: self.registration.clone(),
                    owner_id: view.owner_id.clone(),
                    consumer_namespace: floor.namespace().into(),
                    slot_sequence: floor.slot_sequence(),
                    issuer_key: view.issuer_key.clone(),
                    writer_proof: view.writer_proof.clone(),
                    revocations: view.head.clone(),
                    frontier: floor.frontier_for_handoff(&view.head)?,
                    sockets: bound.paths.clone(),
                    timeout_ms: timeout.as_millis().try_into().map_err(io::Error::other)?,
                    lifetime_ms: lifetime.as_millis().try_into().map_err(io::Error::other)?,
                    observed_unix_ms: view.observed_unix_ms,
                    expires_at_unix_ms: view.expires_at_unix_ms,
                    effect_authorization_available: false,
                };
                let mut sealed = match journal.as_ref() {
                    Some(journal) => {
                        journal.check()?;
                        crate::authority_host_bootstrap_seal::seal_worker_journal(&crate::worker_root_registration::WorkerRootJournalBootstrapV1 {
                            schema_version: 1,
                            purpose: crate::worker_root_registration::journal_wire::WORKER_ROOT_JOURNAL_V1.into(),
                            lanes: observation, journal: journal.observation().clone(), effect_authorization_available: false,
                        })?
                    }
                    None => crate::authority_host_bootstrap_seal::seal_worker_lanes(&observation)?,
                };
                let mut bytes = Vec::new();
                sealed.read_to_end(&mut bytes)?;
                sealed.rewind()?;
                let digest = Sha256Digest::for_bytes(&bytes);
                crate::send_root_production_handoff(self.channel.try_clone()?, &sealed, &self._root_pidfd, wire::remaining(handoff_end)?)
                    .map_err(io::Error::other)?;
                wire::receive(&self.channel, wire::Phase::Acknowledged, &digest, &self.registration.worker, handoff_end)?;
                self.verify_original_custody(handoff_end)?;
                floor.confirm_after_child_ack()?;
                if let Some(journal) = journal.as_mut() { journal.confirm_after_original_child_ack()?; }
                wire::send(&self.channel, wire::Phase::Confirmed, &digest, handoff_end)?;
                self.verify_original_custody(handoff_end)?;
                Ok(())
            })?;
            let retained = RetainedFloor(&floor);
            let mut connected = Vec::with_capacity(3);
            // The Worker connects all three lanes before its first request.
            // Consequently a lost confirmation/partial receiver cannot leave
            // a one-lane floor endpoint that is already being served.
            for (lane, listener) in &bound.listeners {
                let stream = self.accept_worker(listener, &floor, handoff_end)?;
                let policy = HostAuthorityPeerPolicy {
                    peer: HostIssuerPeer { uid: self.registration.worker.uid, pid: self.registration.worker.pid },
                    timeout,
                    lifetime: wire::remaining(end)?,
                    request_bound: 16 * 1024,
                    response_bound: 64 * 1024,
                };
                let shutdown = stream.try_clone()?;
                let channel = HostAuthorityPeerChannel::from_stream(stream, policy, self._worker.pidfd.try_clone()?)
                    .map_err(io::Error::other)?;
                connected.push(ConnectedLane { lane: *lane, channel, stream: shutdown });
            }
            self.verify_original_custody(handoff_end)?;
            floor.check_current()?;
            if let Some(journal) = journal.as_ref() { journal.check()?; }
            loop {
                let index = self.wait_lane(&connected, &floor, end)?;
                let lane = connected[index].lane;
                let live = connected[index].channel.exchange(|bytes| {
                    self.verify_original_custody(end).map_err(|_| HostIssuerTransportError::PeerDenied)?;
                    let response = self._session.service.with_worker_floor_fence(Some(&self.registration), |view| {
                        self.verify_original_custody(end)?;
                        floor.check_current()?;
                        if let Some(journal) = journal.as_ref() { journal.check()?; }
                        let response = match lane {
                            WorkerLane::ConsumerFrontier => floor.exchange(bytes, &view.head)?,
                            WorkerLane::Observation | WorkerLane::OriginalWriterProof => {
                                let request: lanes_wire::WorkerLaneReadRequest = serde_json::from_slice(bytes).map_err(io::Error::other)?;
                                let operation = match lane {
                                    WorkerLane::Observation => lanes_wire::WORKER_OBSERVATION_V1,
                                    WorkerLane::OriginalWriterProof => lanes_wire::WORKER_WRITER_READ_V1,
                                    WorkerLane::ConsumerFrontier => unreachable!(),
                                };
                                if request.schema_version != 1 || request.operation != operation || request.slot_sequence != floor.slot_sequence() {
                                    return Err(refused("Worker read lane cannot sign, select another slot or authorize effects"));
                                }
                                let registration_sha256 = Sha256Digest::for_bytes(&serde_json::to_vec(&self.registration).map_err(io::Error::other)?);
                                match lane {
                                    WorkerLane::Observation => serde_json::to_vec(&lanes_wire::WorkerRootObservationV1 {
                                        schema_version: 1, operation: operation.into(), registration_sha256,
                                        owner_id: view.owner_id.clone(), consumer_namespace: floor.namespace().into(), slot_sequence: floor.slot_sequence(),
                                        revocations: view.head.clone(), clock: view.clock_projection.clone(), observed_unix_ms: view.observed_unix_ms,
                                        expires_at_unix_ms: view.expires_at_unix_ms, effect_authorization_available: false,
                                    }).map_err(io::Error::other)?,
                                    WorkerLane::OriginalWriterProof => serde_json::to_vec(&lanes_wire::WorkerWriterReadResponse {
                                        schema_version: 1, operation: operation.into(), registration_sha256, slot_sequence: floor.slot_sequence(),
                                        proof: view.writer_proof.clone(), effect_authorization_available: false,
                                    }).map_err(io::Error::other)?,
                                    WorkerLane::ConsumerFrontier => unreachable!(),
                                }
                            }
                        };
                        self.verify_original_custody(end)?;
                        floor.check_current()?;
                        if let Some(journal) = journal.as_ref() { journal.check()?; }
                        Ok(response)
                    }).map_err(|_| HostIssuerTransportError::Unavailable)?;
                    self.verify_original_custody(end).map_err(|_| HostIssuerTransportError::PeerDenied)?;
                    Ok(response)
                }).map_err(io::Error::other)?;
                if !live {
                    break;
                }
                self.verify_original_custody(end)?;
                floor.check_current()?;
            }
            drop(retained);
            Ok(())
        })();
        floor.fence_unknown();
        result
    }

    fn accept_worker(&self, listener: &UnixListener, floor: &ReservedWorkerFloor, end: Instant) -> io::Result<UnixStream> {
        loop {
            self.verify_original_custody(end)?;
            floor.check_current()?;
            match listener.accept() {
                Ok((stream, _)) => return Ok(stream),
                Err(error) if error.kind() == io::ErrorKind::WouldBlock || error.kind() == io::ErrorKind::Interrupted => {},
                Err(error) => return Err(error),
            }
            let timeout = Timespec::try_from(wire::remaining(end)?.min(Duration::from_millis(100))).map_err(io::Error::other)?;
            let mut descriptors = [PollFd::new(listener, PollFlags::IN), PollFd::new(&self._worker.pidfd, PollFlags::IN)];
            match rustix::event::poll(&mut descriptors, Some(&timeout)) {
                Ok(_) if !descriptors[1].revents().is_empty() => return Err(refused("original Worker exited before all lanes connected")),
                Ok(_) => {},
                Err(rustix::io::Errno::INTR) => {},
                Err(error) => return Err(io::Error::from(error)),
            }
        }
    }

    fn wait_lane(&self, lanes: &[ConnectedLane], floor: &ReservedWorkerFloor, end: Instant) -> io::Result<usize> {
        loop {
            self.verify_original_custody(end)?;
            floor.check_current()?;
            let timeout = Timespec::try_from(wire::remaining(end)?.min(Duration::from_millis(100))).map_err(io::Error::other)?;
            let mut descriptors: Vec<_> = lanes.iter().map(|lane| PollFd::new(&lane.stream, PollFlags::IN)).collect();
            descriptors.push(PollFd::new(&self._worker.pidfd, PollFlags::IN));
            descriptors.push(PollFd::new(&self._session.owner_pidfd, PollFlags::IN));
            match rustix::event::poll(&mut descriptors, Some(&timeout)) {
                Ok(_) => {
                    if descriptors[lanes.len()..].iter().any(|value| !value.revents().is_empty()) {
                        return Err(refused("an original Worker or Agentd process exited"));
                    }
                    if let Some(index) = descriptors[..lanes.len()].iter().position(|value| !value.revents().is_empty()) {
                        return Ok(index);
                    }
                }
                Err(rustix::io::Errno::INTR) => {},
                Err(error) => return Err(io::Error::from(error)),
            }
        }
    }
}
