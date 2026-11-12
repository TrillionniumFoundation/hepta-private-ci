//! Actual Root orchestration. No namespace is entered before both original
//! handshake messages, the held Initial owner's physical cut and the durable
//! once-claim. No error or lost acknowledgement can restart this scope.

use super::*;
use std::os::unix::net::UnixListener;
use std::sync::mpsc;

use crate::authority_host_same_actor_q24_phase_join::OriginalInitialRetirement;
use crate::authority_host_same_actor_q24_phase_join::accept_original_phase_join;
use crate::authority_host_same_actor_q24_phase_publication::OriginalPhasePublicationContext;

struct BoundPhaseControl {
    listener: UnixListener,
    path: std::path::PathBuf,
    device: u64,
    inode: u64,
}

impl BoundPhaseControl {
    fn bind(config: &HostAuthorityServiceConfig, path: &Path, initial: &Path) -> io::Result<Self> {
        let mut paths: Vec<_> = validate_runtime_lanes(config)?.into_iter().map(|(_, path)| path).collect();
        let initial_path = initial.to_path_buf();
        let control_path = path.to_path_buf();
        paths.push(&initial_path);
        paths.push(&control_path);
        validate_lane_paths(&paths, config.peer_gid)?;
        let listener = UnixListener::bind(path)?;
        let metadata = std::fs::symlink_metadata(path)?;
        let bound = Self { listener, path: path.into(), device: metadata.dev(), inode: metadata.ino() };
        if metadata.uid() != 0 || metadata.gid() != config.peer_gid {
            return Err(io::Error::other("original phase control listener custody differs"));
        }
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o660))?;
        bound.listener.set_nonblocking(true)?;
        Ok(bound)
    }

    fn accept_original(
        &self,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        gate: &Arc<SameActorPhaseGate>,
    ) -> io::Result<std::os::unix::net::UnixStream> {
        let end = gate.deadline().instant();
        loop {
            let epoch = gate.original_wait_epoch()?;
            owner_alive(owner, end)?;
            match self.listener.accept() {
                Ok((stream, _)) => {
                    verify_pinned_process(registration, config.peer_uid, config.peer_gid, owner, end)?;
                    gate.require_open()?;
                    return Ok(stream);
                }
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                    gate.wait_original_change(epoch)?;
                }
                Err(error) => return Err(error),
            }
        }
    }
}

impl Drop for BoundPhaseControl {
    fn drop(&mut self) {
        if std::fs::symlink_metadata(&self.path)
            .is_ok_and(|value| value.dev() == self.device && value.ino() == self.inode)
        {
            let _ = std::fs::remove_file(&self.path);
        }
    }
}

pub(super) fn serve_original_phase(
    phase: PreparedRootSameActorQ24PhaseV1,
    ready: impl FnOnce() -> io::Result<()>,
) -> io::Result<()> {
    let PreparedRootSameActorQ24PhaseV1 {
        mut original, gate, record, descriptor, model, scope: scope_runtime, start, closing,
    } = phase;
    if start.is_some() {
        return Err(io::Error::other("original phase start capabilities must be taken before serving"));
    }
    gate.require_open()?;
    let initial = generation_initial::BoundInitial::bind(
        original.initial_publication.take()
            .ok_or_else(|| io::Error::other("original phase Initial route missing"))?,
        &original.config,
    )?;
    let control = BoundPhaseControl::bind(&original.config, &descriptor.control_socket, initial.path())?;
    initial.activate_same_actor_phase()?;
    scope_runtime.activate()?;
    // Binding publishes no external ready notification. Required workers and
    // their shared close guards must exist before trusted handoff delivery.
    let five = listeners::bind_runtime_lanes(&original.config, || Ok(()))?;
    let retirement = OriginalInitialRetirement::new(&gate, &descriptor.phase);
    std::thread::scope(|threads| {
        // This guard is inside the scope closure, so unwind/early return closes
        // sockets before the standard scope performs automatic joins.
        let scope_close = CloseSameActorPhaseOnDrop::new(&gate);
        let watcher = threads.spawn(|| gate.watch_original_deadline());
        let (initial_sender, initial_receiver) = mpsc::sync_channel(1);
        let initial_ref = &initial;
        let original_ref = &original;
        let gate_ref = &gate;
        let retirement_ref = &retirement;
        let first = threads.spawn(move || {
            let mut phase_close = CloseSameActorPhaseOnDrop::new(gate_ref);
            let result = initial_ref.serve_same_actor_phase_initial(
                &original_ref.service, &original_ref.config, &original_ref.registration,
                &original_ref.owner_pidfd, gate_ref, retirement_ref,
            );
            let transferred = match result {
                Ok(slot) => initial_sender.try_send(slot)
                    .map_err(|_| io::Error::other("original Initial owner handoff was lost")),
                Err(error) => Err(error),
            };
            gate_ref.notify_original_waiters();
            if transferred.is_ok() {
                phase_close.disarm();
            }
            transferred
        });
        let scoped = threads.spawn(|| run_original_scoped_phase(
            &original, &gate, record, &descriptor, &model,
            scope_runtime, &control, &retirement, initial_receiver,
        ));
        let announced = (|| {
            gate.require_open()?;
            ready()?;
            gate.require_open()?;
            Ok(())
        })();
        let served = match announced {
            Ok(()) => listeners::serve_bound_phase_lanes_until(
                &original.service, &original.config, &original.registration,
                &original.owner_pidfd, five, &gate,
            ),
            Err(error) => Err(error),
        };
        drop(scope_close);
        drop(closing);
        let first = first.join().map_err(|_| io::Error::other("original Initial phase worker panicked"))?;
        let scoped = scoped.join().map_err(|_| io::Error::other("original scoped phase worker panicked"))?;
        watcher.join().map_err(|_| io::Error::other("original phase deadline worker panicked"))?;
        served.and(first).and(scoped)
    })
}

fn run_original_scoped_phase(
    original: &PreparedHostAuthoritySession,
    gate: &Arc<SameActorPhaseGate>,
    mut record: OriginalPhaseRecord,
    descriptor: &OriginalPhaseBootstrap,
    model: &crate::HostAuthorityQ24ModelFactoryReservationV1,
    scope: scope_cap::ScopeRuntime,
    control: &BoundPhaseControl,
    retirement: &OriginalInitialRetirement,
    initial_receiver: mpsc::Receiver<crate::authority_host_service::generation_initial::RegisteredGenerationInitial>,
) -> io::Result<()> {
    let _closing = CloseSameActorPhaseOnDrop::new(gate);
    let submission = loop {
        let epoch = gate.original_wait_epoch()?;
        owner_alive(&original.owner_pidfd, gate.deadline().instant())?;
        match scope.receiver.try_recv() {
            Ok(value) => break value,
            Err(mpsc::TryRecvError::Empty) => gate.wait_original_change(epoch)?,
            Err(mpsc::TryRecvError::Disconnected) => {
                return Err(io::Error::other("original Root scope capability was dropped"));
            }
        }
    };
    let stream = control.accept_original(
        &original.config, &original.registration, &original.owner_pidfd, gate,
    )?;
    let joined = accept_original_phase_join(
        &original.service, &original.config, &original.registration,
        &original.owner_pidfd, stream,
        HostAuthorityPeerPolicy {
            peer: HostIssuerPeer { uid: original.config.peer_uid, pid: original.registration.peer_pid },
            timeout: std::time::Duration::from_millis(original.config.timeout_ms),
            lifetime: std::time::Duration::from_millis(original.config.lifetime_ms),
            request_bound: 16 * 1024,
            response_bound: 16 * 1024,
        },
        &descriptor.phase, &submission.profile, retirement, gate,
    )?;
    // A transport EOF can only transfer this actual held owner. It cannot
    // replace the independently completed original join above.
    let initial = loop {
        let epoch = gate.original_wait_epoch()?;
        match initial_receiver.try_recv() {
            Ok(slot) => break slot,
            Err(mpsc::TryRecvError::Empty) => gate.wait_original_change(epoch)?,
            Err(mpsc::TryRecvError::Disconnected) => {
                return Err(io::Error::other("original Initial owner was not transferred"));
            }
        }
    };
    joined.require_original_profile(&descriptor.phase, &submission.profile, retirement, gate)?;
    let claim = original.service.claim_same_actor_phase_after_original_a(
        &original.config, &original.registration, &original.owner_pidfd,
        &initial, &submission.profile, &mut record, gate,
    )?;
    // Any failure above leaves a claimed/partial record closed. No fallthrough
    // can open a Learning/Model namespace or convert this attempt into recovery.
    joined.require_original_profile(&descriptor.phase, &submission.profile, retirement, gate)?;
    let origin = initial.retire_original_phase_slot(claim)?;
    gate.require_open()?;
    origin.require_retained_predecessor()?;
    record.require_claimed()?;
    let namespace = crate::authority_host_same_actor_q24_phase_namespace::OriginalPhaseNamespaceContext {
        gate, record: &record,
    };
    original.service.reserve_original_learning_profile_in_phase(
        &original.config, &original.registration, &original.owner_pidfd, &submission.profile,
        Some(&namespace),
    )?;
    gate.require_open()?;
    record.require_claimed()?;
    let mut learning = original.service.open_original_learning_profile_in_phase(
        &original.config, &original.registration, &original.owner_pidfd, submission.profile.clone(),
        Some(&namespace),
    )?;
    gate.require_open()?;
    record.require_claimed()?;
    let factory_profile = HostAuthorityService::reserve_original_phase_q24_model_factory(
        &original.service, &original.config, &original.registration, &original.owner_pidfd,
        &learning.profile, model, Some(&namespace),
    )?;
    gate.require_open()?;
    record.require_claimed()?;
    let factory = original.service.open_original_phase_q24_model_reservation(
        &original.config, &original.registration, &original.owner_pidfd,
        &learning.profile, model.clone(), Some(&namespace),
    )?;
    if factory.profile != factory_profile {
        return Err(io::Error::other("original reserved Model factory changed on open"));
    }
    learning.q24_model = Some(factory);
    let learning_bootstrap = original.service.seal_learning_checkpoint(
        &original.config, &original.registration, &original.owner_pidfd, &learning,
    )?;
    gate.require_open()?;
    let (publication, capability, publication_offer) = generation_publication::original_publication_route(
        &original.service, &original.config, &original.registration, &original.owner_pidfd, &learning,
    )?;
    gate.require_open()?;
    record.require_claimed()?;
    gate.require_open()?;
    record.mark_scoped_before_rights(factory_profile.binding().to_string())?;
    gate.require_open()?;
    let factory_offer = original.service.seal_q24_model_factory_offer(
        &original.config, &original.registration, &original.owner_pidfd,
        learning.q24_model.as_mut()
            .ok_or_else(|| io::Error::other("original scoped Model owner missing"))?,
    )?;
    let scoped_descriptor = crate::same_actor_q24_phase_protocol::OriginalScopedPhaseBootstrap {
        purpose: crate::same_actor_q24_phase_protocol::SCOPED_PURPOSE.into(),
        phase: descriptor.phase.clone(),
        original: descriptor.clone(),
        learning: submission.profile,
        claim: record.claimed()?.clone(),
        factory: factory_profile.binding().to_string(),
    };
    let scoped_seal = crate::authority_host_bootstrap_seal::seal_bytes(
        &serde_json::to_vec(&scoped_descriptor).map_err(io::Error::other)?,
    )?;
    let lane = learning::BoundLearning::bind(learning, &original.config, Some(publication))?;
    record.require_scoped()?;
    gate.require_open()?;
    let enrolled = RootSameActorScopedEnrollmentV1 {
        offer: crate::root_production_handoff::same_actor_phase::RootSameActorScopedOfferV1 {
            bootstrap: scoped_seal, learning: learning_bootstrap,
            model: factory_offer, publication: publication_offer,
        },
        publication: generation_publication::RootGenerationPublicationEnrollmentCapabilityV1::into_same_actor_phase(
            capability, gate,
        ),
        gate: Arc::clone(gate),
        closing: CloseSameActorPhaseOnDrop::new(gate),
    };
    let context = OriginalPhasePublicationContext { gate, record: &record, original: &origin };
    lane.serve_same_actor_phase_learning(
        &original.service, &original.config, &original.registration, &original.owner_pidfd,
        &context,
        || {
            record.require_scoped()?;
            gate.require_open()?;
            submission.acknowledgement.try_send(Ok(enrolled))
                .map_err(|_| io::Error::other("original scoped owner offer acknowledgement lost"))?;
            gate.notify_original_waiters();
            gate.require_open()?;
            Ok(())
        },
    )
}
