//! Trusted Root host entry for the complete same-service phase transport.
//! Commands carry original typed owners, never daemon-created authority.
//! The host waits for the daemon's actual InputsOpened notification before
//! supplying Initial enrollment, and for actual Prepared/selection before
//! the respective later commands. Every original owner revalidates them.

use super::*;
use std::os::unix::net::UnixDatagram;
use std::sync::mpsc;

/// Actual trusted-host materials for the one original Root serving scope.
/// These values do not create a new writer admission or relax its permissions.
pub struct RootSameActorHostInputsV1 {
    pub writer_handoff: UnixDatagram,
    pub phase_handoff: UnixDatagram,
    pub scoped_handoff: UnixDatagram,
    pub registered_writer: File,
    pub root_pidfd: OwnedFd,
    pub consumer_state_root: std::path::PathBuf,
    pub timeout: std::time::Duration,
    pub commands: mpsc::Receiver<RootSameActorHostCommandV1>,
    pub acknowledgements: mpsc::SyncSender<RootSameActorHostAcknowledgementV1>,
}

/// The Root host supplies original file/trust/observer owners. Public daemon
/// profile data alone cannot populate either actual enrollment structure.
pub enum RootSameActorHostCommandV1 {
    Initial(crate::RootGenerationInitialEnrollmentV1),
    Scoped(crate::HostAuthorityLearningProfileV1),
    Current(crate::RootGenerationPublicationEnrollmentV1),
}

/// Read-only delivery acknowledgements; none is a grant, receipt or execution
/// admission, and a lost acknowledgement never recreates a capability.
pub enum RootSameActorHostAcknowledgementV1 {
    InitialRegistered { binding: String },
    ScopedRightsSent,
    CurrentRegistered { binding: String },
}

impl PreparedRootSameActorQ24PhaseV1 {
    /// Serve the actual original session and send the original three-right
    /// writer purpose. This entry consumes the prepared service; it does not
    /// open another issuer, registry, CURRENT owner or phase gate.
    ///
    /// Root and daemon commands originate in their respective trusted hosts.
    /// This does not add default CLI materials, an independent C contract or
    /// acceptance for an operating-system restart.
    pub fn serve_original_same_actor_host(
        mut self,
        inputs: RootSameActorHostInputsV1,
    ) -> io::Result<()> {
        self.gate.require_open()?;
        if inputs.timeout.is_zero() || inputs.timeout > std::time::Duration::from_millis(500) {
            return Err(io::Error::other(
                "bounded original phase handoff timeout required",
            ));
        }
        crate::authority_host_service::generation_initial::original_root()?;
        let bootstrap = self.seal_bootstrap(&inputs.consumer_state_root)?;
        let start = self.take_start()?;
        let gate = Arc::clone(&self.gate);
        let RootSameActorHostInputsV1 {
            writer_handoff,
            phase_handoff,
            scoped_handoff,
            registered_writer,
            root_pidfd,
            consumer_state_root: _,
            timeout,
            commands,
            acknowledgements,
        } = inputs;
        let RootSameActorPhaseStartV1 {
            initial_capability,
            initial_offer,
            phase_offer,
            scope_capability,
        } = start;
        // Retain aliases before a wait or thread can begin. Closing this one
        // gate interrupts the actual descriptor handoffs, including ACK loss.
        let _writer_stop = gate.retain_original_datagram(&writer_handoff)?;
        let _phase_stop = gate.retain_original_datagram(&phase_handoff)?;
        let _scoped_stop = gate.retain_original_datagram(&scoped_handoff)?;
        let scoped_root = root_pidfd.try_clone()?;
        let (ready, received_ready) = mpsc::sync_channel(1);
        std::thread::scope(|threads| {
            // This guard drops before the scope joins on error or unwind.
            let _scope_close = CloseSameActorPhaseOnDrop::new(&gate);
            let worker_gate = Arc::clone(&gate);
            let registration = threads.spawn(move || -> io::Result<()> {
                let mut closing = CloseSameActorPhaseOnDrop::new(&worker_gate);
                receive_host_value(&received_ready, &worker_gate)?;
                let RootSameActorHostCommandV1::Initial(initial) =
                    receive_host_value(&commands, &worker_gate)?
                else {
                    return Err(io::Error::other(
                        "original Initial host command required first",
                    ));
                };
                let original = crate::RootSameActorInitialEnrollmentCapabilityV1::register(
                    initial_capability,
                    initial,
                )?;
                worker_gate.require_open()?;
                acknowledgements
                    .try_send(RootSameActorHostAcknowledgementV1::InitialRegistered {
                        binding: original.binding().to_string(),
                    })
                    .map_err(|_| io::Error::other("original Initial host acknowledgement lost"))?;
                let RootSameActorHostCommandV1::Scoped(profile) =
                    receive_host_value(&commands, &worker_gate)?
                else {
                    return Err(io::Error::other(
                        "actual original Prepared profile required next",
                    ));
                };
                let scoped =
                    RootSameActorScopeEnrollmentCapabilityV1::register(scope_capability, profile)?;
                worker_gate.require_open()?;
                let publication = crate::send_root_same_actor_scoped_handoff(
                    scoped_handoff,
                    scoped,
                    &scoped_root,
                    timeout.min(worker_gate.require_open()?),
                )
                .map_err(io::Error::other)?;
                worker_gate.require_open()?;
                acknowledgements
                    .try_send(RootSameActorHostAcknowledgementV1::ScopedRightsSent)
                    .map_err(|_| io::Error::other("original scoped host acknowledgement lost"))?;
                let RootSameActorHostCommandV1::Current(current) =
                    receive_host_value(&commands, &worker_gate)?
                else {
                    return Err(io::Error::other(
                        "actual original CURRENT host enrollment required last",
                    ));
                };
                let original = crate::RootSameActorPublicationEnrollmentCapabilityV1::register(
                    publication,
                    current,
                )?;
                worker_gate.require_open()?;
                acknowledgements
                    .try_send(RootSameActorHostAcknowledgementV1::CurrentRegistered {
                        binding: original.binding().to_string(),
                    })
                    .map_err(|_| io::Error::other("original CURRENT host acknowledgement lost"))?;
                worker_gate.require_open()?;
                closing.disarm();
                Ok(())
            });
            let ready_gate = Arc::clone(&gate);
            let served = self.serve_with_ready(move || {
                // All required Root workers already exist at this callback.
                // Sending rights does not wait for an enrollment ACK or for
                // the daemon's five-lane requests, so serving can now proceed.
                ready_gate.require_open()?;
                crate::send_root_production_writer_handoff(
                    writer_handoff,
                    &bootstrap,
                    &root_pidfd,
                    registered_writer,
                    timeout.min(ready_gate.require_open()?),
                )
                .map_err(io::Error::other)?;
                ready_gate.require_open()?;
                crate::send_root_same_actor_phase_handoff(
                    phase_handoff,
                    phase_offer,
                    initial_offer,
                    &root_pidfd,
                    timeout.min(ready_gate.require_open()?),
                )
                .map_err(io::Error::other)?;
                ready_gate.require_open()?;
                ready
                    .try_send(())
                    .map_err(|_| io::Error::other("original Root host startup receiver lost"))?;
                ready_gate.notify_original_waiters();
                ready_gate.require_open()?;
                Ok(())
            });
            gate.close();
            let registered = registration
                .join()
                .map_err(|_| io::Error::other("original Root host registration worker lost"))?;
            // An original service/owner error is never hidden by host output.
            served.and(registered)
        })
    }
}

fn receive_host_value<T>(
    receiver: &mpsc::Receiver<T>,
    gate: &Arc<SameActorPhaseGate>,
) -> io::Result<T> {
    loop {
        let epoch = gate.original_wait_epoch()?;
        match receiver.try_recv() {
            Ok(value) => {
                gate.require_open()?;
                return Ok(value);
            }
            Err(mpsc::TryRecvError::Empty) => gate.wait_original_change(epoch)?,
            Err(mpsc::TryRecvError::Disconnected) => {
                return Err(io::Error::other("original Root host command stream closed"));
            }
        }
    }
}
