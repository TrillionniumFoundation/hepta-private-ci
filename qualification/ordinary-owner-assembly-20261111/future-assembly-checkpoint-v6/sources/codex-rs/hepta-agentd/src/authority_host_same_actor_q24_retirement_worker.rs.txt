//! The Root-only retirement serving scope. It retains actual returned owners;
//! a peer request or a zero count can never construct a joined scope.

use super::*;

pub(in super::super) struct OriginalRootScopedJoined {
    channels: learning::OriginalRootScopedChannelsJoined,
    _lane: learning::BoundLearning,
    _record: OriginalPhaseRecord,
    _scope: scope_cap::ScopeRuntime,
    _origin: crate::authority_host_service::generation_initial::OriginalSameActorPhaseA,
}

struct OriginalRootBusinessJoined {
    retirement: Arc<crate::OriginalRootRetirementScope>,
    lanes: listeners::OriginalRootAuthorityLanesJoined,
    scoped: OriginalRootScopedJoined,
    _initial: generation_initial::BoundInitial,
    _control: BoundPhaseControl,
    _initial_retirement: OriginalInitialRetirement,
}

/// Only constructed after joining the actual Initial, scoped and all nested
/// lane workers. The outer deployment still joins its registration, material
/// bridge and deadline worker before it may acknowledge RootWorkersJoined.
pub(in super::super) struct OriginalRootPhaseWorkersJoined {
    business: OriginalRootBusinessJoined,
    // Keep this actual issuer, clock, checkpoints and registered observers
    // until after the final Root ACK. The writer-lock File was already moved
    // to the daemon by the original three-right handoff; it is not here.
    _original: PreparedHostAuthoritySession,
}

impl OriginalRootPhaseWorkersJoined {
    pub(in super::super) fn require_original(
        &self,
        retirement: &crate::OriginalRootRetirementScope,
    ) -> io::Result<()> {
        if !std::ptr::eq(self.business.retirement.as_ref(), retirement) {
            return Err(io::Error::other("Root joined scope replaced its original retirement owner"));
        }
        self.business.lanes.require_original(retirement)?;
        self.business.scoped.channels.require_original(retirement)
    }
}

pub(in super::super) fn serve_original_phase_for_retirement(
    phase: PreparedRootSameActorQ24PhaseV1,
    root_retirement: &Arc<crate::OriginalRootRetirementScope>,
    ready: impl FnOnce() -> io::Result<()>,
) -> io::Result<OriginalRootPhaseWorkersJoined> {
    let PreparedRootSameActorQ24PhaseV1 {
        mut original,
        gate,
        record,
        descriptor,
        model,
        scope: scope_runtime,
        start,
        mut closing,
    } = phase;
    if start.is_some() {
        return Err(io::Error::other(
            "original phase start capabilities must be taken before serving",
        ));
    }
    root_retirement.require_original(&gate)?;
    let initial = generation_initial::BoundInitial::bind(
        original
            .initial_publication
            .take()
            .ok_or_else(|| io::Error::other("original phase Initial route missing"))?,
        &original.config,
    )?;
    let control =
        BoundPhaseControl::bind(&original.config, &descriptor.control_socket, initial.path())?;
    initial.activate_same_actor_phase()?;
    scope_runtime.activate()?;
    let five = listeners::bind_runtime_lanes(&original.config, || Ok(()))?;
    let retirement = OriginalInitialRetirement::new(&gate, &descriptor.phase);
    let (lanes, scoped) = std::thread::scope(|threads| {
        let mut scope_close = CloseSameActorPhaseOnDrop::new(&gate);
        let (initial_sender, initial_receiver) = mpsc::sync_channel(1);
        let initial_ref = &initial;
        let original_ref = &original;
        let gate_ref = &gate;
        let retirement_ref = &retirement;
        let first = threads.spawn(move || {
            let mut phase_close = CloseSameActorPhaseOnDrop::new(gate_ref);
            let result = initial_ref.serve_same_actor_phase_initial(
                &original_ref.service,
                &original_ref.config,
                &original_ref.registration,
                &original_ref.owner_pidfd,
                gate_ref,
                retirement_ref,
            );
            let transferred = match result {
                Ok(slot) => initial_sender
                    .try_send(slot)
                    .map_err(|_| io::Error::other("original Initial owner handoff was lost")),
                Err(error) => Err(error),
            };
            gate_ref.notify_original_waiters();
            if transferred.is_ok() {
                phase_close.disarm();
            }
            transferred
        });
        let scoped = threads.spawn(|| {
            run_original_scoped_phase_for_retirement(
                &original,
                &gate,
                record,
                &descriptor,
                &model,
                scope_runtime,
                &control,
                &retirement,
                initial_receiver,
                root_retirement,
            )
        });
        let announced = (|| {
            gate.require_open()?;
            ready()?;
            gate.require_open()?;
            Ok(())
        })();
        let served = match announced {
            Ok(()) => listeners::serve_bound_phase_lanes_for_root_retirement(
                &original.service,
                &original.config,
                &original.registration,
                &original.owner_pidfd,
                five,
                root_retirement,
            ),
            Err(error) => Err(error),
        };
        if served.is_err() {
            gate.close();
        }
        let first = first
            .join()
            .map_err(|_| io::Error::other("original Initial phase worker panicked"))
            .and_then(|result| result);
        if first.is_err() {
            gate.close();
        }
        let scoped = scoped
            .join()
            .map_err(|_| io::Error::other("original scoped phase worker panicked"))
            .and_then(|result| result);
        if scoped.is_err() {
            gate.close();
        }
        let served = served?;
        first?;
        let scoped = scoped?;
        root_retirement.require_original(&gate)?;
        scope_close.disarm();
        Ok::<_, io::Error>((served, scoped))
    })?;
    let joined = OriginalRootPhaseWorkersJoined {
        business: OriginalRootBusinessJoined {
            retirement: Arc::clone(root_retirement),
            lanes,
            scoped,
            _initial: initial,
            _control: control,
            _initial_retirement: retirement,
        },
        _original: original,
    };
    joined.require_original(root_retirement)?;
    closing.disarm();
    Ok(joined)
}

fn run_original_scoped_phase_for_retirement(
    original: &PreparedHostAuthoritySession,
    gate: &Arc<SameActorPhaseGate>,
    mut record: OriginalPhaseRecord,
    descriptor: &OriginalPhaseBootstrap,
    model: &crate::HostAuthorityQ24ModelFactoryReservationV1,
    scope: scope_cap::ScopeRuntime,
    control: &BoundPhaseControl,
    retirement: &OriginalInitialRetirement,
    initial_receiver: mpsc::Receiver<
        crate::authority_host_service::generation_initial::RegisteredGenerationInitial,
    >,
    root_retirement: &Arc<crate::OriginalRootRetirementScope>,
) -> io::Result<OriginalRootScopedJoined> {
    let mut closing = CloseSameActorPhaseOnDrop::new(gate);
    root_retirement.require_original(gate)?;
    let submission = loop {
        let epoch = gate.original_wait_epoch()?;
        owner_alive(&original.owner_pidfd, gate.deadline().instant())?;
        match scope.receiver.try_recv() {
            Ok(value) => break value,
            Err(mpsc::TryRecvError::Empty) => gate.wait_original_change(epoch)?,
            Err(mpsc::TryRecvError::Disconnected) => {
                return Err(io::Error::other(
                    "original Root scope capability was dropped",
                ));
            }
        }
    };
    let stream = control.accept_original(
        &original.config,
        &original.registration,
        &original.owner_pidfd,
        gate,
    )?;
    let joined = accept_original_phase_join(
        &original.service,
        &original.config,
        &original.registration,
        &original.owner_pidfd,
        stream,
        HostAuthorityPeerPolicy {
            peer: HostIssuerPeer {
                uid: original.config.peer_uid,
                pid: original.registration.peer_pid,
            },
            timeout: std::time::Duration::from_millis(original.config.timeout_ms),
            lifetime: std::time::Duration::from_millis(original.config.lifetime_ms),
            request_bound: 16 * 1024,
            response_bound: 16 * 1024,
        },
        &descriptor.phase,
        &submission.profile,
        retirement,
        gate,
    )?;
    // A transport EOF can only transfer this actual held owner. It cannot
    // replace the independently completed original join above.
    let initial = loop {
        let epoch = gate.original_wait_epoch()?;
        match initial_receiver.try_recv() {
            Ok(slot) => break slot,
            Err(mpsc::TryRecvError::Empty) => gate.wait_original_change(epoch)?,
            Err(mpsc::TryRecvError::Disconnected) => {
                return Err(io::Error::other(
                    "original Initial owner was not transferred",
                ));
            }
        }
    };
    joined.require_original_profile(&descriptor.phase, &submission.profile, retirement, gate)?;
    let claim = original.service.claim_same_actor_phase_after_original_a(
        &original.config,
        &original.registration,
        &original.owner_pidfd,
        &initial,
        &submission.profile,
        &mut record,
        gate,
    )?;
    // Any failure above leaves a claimed/partial record closed. No fallthrough
    // can open a Learning/Model namespace or convert this attempt into recovery.
    joined.require_original_profile(&descriptor.phase, &submission.profile, retirement, gate)?;
    let origin = initial.retire_original_phase_slot(claim)?;
    gate.require_open()?;
    origin.require_retained_predecessor()?;
    record.require_claimed()?;
    let namespace =
        crate::authority_host_same_actor_q24_phase_namespace::OriginalPhaseNamespaceContext {
            gate,
            record: &record,
        };
    original
        .service
        .reserve_original_learning_profile_in_phase(
            &original.config,
            &original.registration,
            &original.owner_pidfd,
            &submission.profile,
            Some(&namespace),
        )?;
    gate.require_open()?;
    record.require_claimed()?;
    let mut learning = original.service.open_original_learning_profile_in_phase(
        &original.config,
        &original.registration,
        &original.owner_pidfd,
        submission.profile.clone(),
        Some(&namespace),
    )?;
    gate.require_open()?;
    record.require_claimed()?;
    let factory_profile = HostAuthorityService::reserve_original_phase_q24_model_factory(
        &original.service,
        &original.config,
        &original.registration,
        &original.owner_pidfd,
        &learning.profile,
        model,
        Some(&namespace),
    )?;
    gate.require_open()?;
    record.require_claimed()?;
    let factory = original.service.open_original_phase_q24_model_reservation(
        &original.config,
        &original.registration,
        &original.owner_pidfd,
        &learning.profile,
        model.clone(),
        Some(&namespace),
    )?;
    if factory.profile != factory_profile {
        return Err(io::Error::other(
            "original reserved Model factory changed on open",
        ));
    }
    learning.q24_model = Some(factory);
    let learning_bootstrap = original.service.seal_learning_checkpoint(
        &original.config,
        &original.registration,
        &original.owner_pidfd,
        &learning,
    )?;
    gate.require_open()?;
    let (publication, capability, publication_offer) =
        generation_publication::original_publication_route(
            &original.service,
            &original.config,
            &original.registration,
            &original.owner_pidfd,
            &learning,
        )?;
    gate.require_open()?;
    record.require_claimed()?;
    gate.require_open()?;
    record.mark_scoped_before_rights(factory_profile.binding().to_string())?;
    gate.require_open()?;
    let factory_offer = original.service.seal_q24_model_factory_offer(
        &original.config,
        &original.registration,
        &original.owner_pidfd,
        learning
            .q24_model
            .as_mut()
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
    let context = OriginalPhasePublicationContext {
        gate,
        record: &record,
        original: &origin,
    };
    let channels = lane.serve_same_actor_phase_learning_for_retirement(
        &original.service,
        &original.config,
        &original.registration,
        &original.owner_pidfd,
        (&context, root_retirement),
        || {
            record.require_scoped()?;
            gate.require_open()?;
            submission
                .acknowledgement
                .try_send(Ok(enrolled))
                .map_err(|_| {
                    io::Error::other("original scoped owner offer acknowledgement lost")
                })?;
            gate.notify_original_waiters();
            gate.require_open()?;
            Ok(())
        },
    )?;
    channels.require_original(root_retirement)?;
    record.require_scoped()?;
    gate.require_open()?;
    closing.disarm();
    Ok(OriginalRootScopedJoined {
        channels,
        _lane: lane,
        _record: record,
        _scope: scope,
        _origin: origin,
    })
}
