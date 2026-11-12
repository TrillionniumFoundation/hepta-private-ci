//! Receive one explicit same-actor phase on the original five Root lanes.
//! The new mode retains the receiver's earliest two clock samples; a later
//! offer cannot rebuild either end. All authority still comes from the
//! original sealed bootstrap, live writer proof and actual consumer owners.

use super::*;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_types::Digest32;

use crate::root_production_handoff::same_actor_phase::OriginalSameActorPhaseHandoff;
use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;
use crate::same_actor_q24_phase_gate::RequiredSameActorPhaseChannel;
use crate::same_actor_q24_phase_gate::SameActorPhaseDeadline;
use crate::same_actor_q24_phase_gate::SameActorPhaseGate;
use crate::same_actor_q24_phase_protocol::OriginalPhaseBootstrap;
use crate::same_actor_q24_phase_protocol::OriginalScopedPhaseBootstrap;

/// Captured by the actual typed entry before parsing or consuming any offer.
/// The private fields cannot be populated from host JSON or a later Duration.
pub(crate) struct OriginalPhaseReceiveStart {
    instant: Instant,
    boottime_ns: u64,
}

pub(crate) struct OriginalPhaseReceiveDeadline {
    instant: Instant,
    boottime_ns: u64,
    last_boottime_ns: u64,
}

impl OriginalPhaseReceiveStart {
    pub(crate) fn capture() -> Result<Self, AgentdError> {
        let boottime_ns = crate::root_observation_cache::boottime_ns().map_err(protocol)?;
        let instant = Instant::now();
        Ok(Self {
            instant,
            boottime_ns,
        })
    }

    pub(crate) fn finish(
        self,
        lifetime: Duration,
    ) -> Result<OriginalPhaseReceiveDeadline, AgentdError> {
        if lifetime.is_zero() || lifetime > Duration::from_secs(300) {
            return Err(refused(
                "original phase receive lifetime is outside its bound",
            ));
        }
        let instant = self
            .instant
            .checked_add(lifetime)
            .ok_or_else(|| refused("original receiver Instant overflow"))?;
        let boottime_ns = self
            .boottime_ns
            .checked_add(u64::try_from(lifetime.as_nanos()).map_err(protocol)?)
            .ok_or_else(|| refused("original receiver BOOTTIME overflow"))?;
        remaining(instant)?;
        let checked = crate::root_observation_cache::boottime_ns().map_err(protocol)?;
        if checked < self.boottime_ns || checked >= boottime_ns {
            return Err(refused("original receiver BOOTTIME end elapsed"));
        }
        Ok(OriginalPhaseReceiveDeadline {
            instant,
            boottime_ns,
            last_boottime_ns: checked,
        })
    }
}

impl OriginalPhaseReceiveDeadline {
    pub(crate) fn instant(&self) -> Instant {
        self.instant
    }

    /// Keep an already parsed original launcher end as an additional local
    /// upper bound. It is never converted into a newly sampled BOOTTIME end.
    pub(crate) fn restrict_original_launcher_end(
        mut self,
        original_end: Instant,
    ) -> Result<Self, AgentdError> {
        self.instant = self.instant.min(original_end);
        self.remaining()?;
        Ok(self)
    }

    /// Bound bootstrap waits by these original samples too. This is only an
    /// admission limit, never a writer proof or a newly started session.
    pub(crate) fn remaining(&mut self) -> Result<Duration, AgentdError> {
        let now = crate::root_observation_cache::boottime_ns().map_err(protocol)?;
        if now < self.last_boottime_ns {
            return Err(refused("original receiver BOOTTIME regressed"));
        }
        self.last_boottime_ns = now;
        let boot = self
            .boottime_ns
            .checked_sub(now)
            .filter(|remaining| *remaining != 0)
            .map(Duration::from_nanos)
            .ok_or_else(|| refused("original receiver BOOTTIME end elapsed"))?;
        Ok(remaining(self.instant)?.min(boot))
    }
}

/// Read-only handles to the SAME live Root/consumer owners. The actual Session
/// and recovered writer remain retained by the original production attachment.
/// Dropping that Session closes this gate and invalidates these verifier arcs.
pub(crate) struct OriginalSameActorRootContext {
    bootstrap: HostAuthorityPublicBootstrapV1,
    identity: AgentdIdentity,
    descriptor: OriginalPhaseBootstrap,
    session: Arc<OriginalQ24SuccessorSession>,
    gate: Arc<SameActorPhaseGate>,
    root_pidfd: OwnedFd,
    clock: Arc<dyn AuthorityClock>,
    device: FinalUseAuthority,
    notes: FinalUseAuthority,
    grants: Arc<AgentdUnixFinalUseGrantProvider>,
    scoped_consumed: AtomicBool,
    initial_lifetime: Arc<crate::same_actor_q24_phase_join_client::OriginalInitialPhaseLifetime>,
    _closing: CloseSameActorPhaseOnDrop,
    _deadline_watch: crate::same_actor_q24_phase_gate::OriginalSameActorPhaseWatch,
}

pub(crate) struct OriginalSameActorProductionInputs {
    pub(crate) root: AgentdRootProductionInputs,
    pub(crate) context: Arc<OriginalSameActorRootContext>,
    pub(crate) initial: crate::RootGenerationInitialHandoffV1,
}

impl OriginalSameActorRootContext {
    pub(crate) fn require_current(&self) -> Result<(), AgentdError> {
        let mut closing = CloseSameActorPhaseOnDrop::new(&self.gate);
        self.session.require_original_same_actor_phase(&self.gate)?;
        self.gate.require_open()?;
        closing.disarm();
        Ok(())
    }

    pub(crate) fn bootstrap(&self) -> &HostAuthorityPublicBootstrapV1 {
        &self.bootstrap
    }
    pub(crate) fn identity(&self) -> &AgentdIdentity {
        &self.identity
    }
    pub(crate) fn descriptor(&self) -> &OriginalPhaseBootstrap {
        &self.descriptor
    }
    pub(crate) fn gate(&self) -> &Arc<SameActorPhaseGate> {
        &self.gate
    }
    pub(crate) fn initial_lifetime(
        &self,
    ) -> &Arc<crate::same_actor_q24_phase_join_client::OriginalInitialPhaseLifetime> {
        &self.initial_lifetime
    }
    pub(crate) fn successor_session(&self) -> Arc<OriginalQ24SuccessorSession> {
        Arc::clone(&self.session)
    }
    pub(crate) fn root_pidfd(&self) -> Result<OwnedFd, AgentdError> {
        OriginalSameActorRootContext::require_current(self)?;
        Ok(self.root_pidfd.try_clone()?)
    }
    pub(crate) fn clock(&self) -> Arc<dyn AuthorityClock> {
        Arc::clone(&self.clock)
    }
    pub(crate) fn device(&self) -> FinalUseAuthority {
        self.device.clone()
    }
    pub(crate) fn notes(&self) -> FinalUseAuthority {
        self.notes.clone()
    }
    pub(crate) fn grants(&self) -> Arc<AgentdUnixFinalUseGrantProvider> {
        Arc::clone(&self.grants)
    }

    /// Claim only the new, Root-sealed post-A purpose. This is not a second
    /// take of the Initial connection. Any refusal consumes and closes it.
    pub(crate) fn accept_original_scoped_descriptor(
        &self,
        scoped: &OriginalScopedPhaseBootstrap,
        prepared: &crate::CellQ24PreparedLearningV1,
    ) -> Result<(), AgentdError> {
        let mut closing = CloseSameActorPhaseOnDrop::new(&self.gate);
        OriginalSameActorRootContext::require_current(self)?;
        if self
            .scoped_consumed
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .is_err()
        {
            return Err(refused(
                "original scoped phase purpose was already consumed",
            ));
        }
        if scoped.purpose != crate::same_actor_q24_phase_protocol::SCOPED_PURPOSE
            || scoped.phase != self.descriptor.phase
            || scoped.original != self.descriptor
            || scoped.claim.source_binding != self.descriptor.original.initial.target
            || scoped.claim.learning_profile != serde_json::to_string(&scoped.learning)?
            || scoped.claim.initial_learning_head != prepared.initial().head_digest.to_string()
            || scoped.claim.scope != prepared.scope().binding().to_string()
            || !scoped
                .factory
                .parse::<Digest32>()
                .is_ok_and(|value| !value.is_zero() && value.to_string() == scoped.factory)
        {
            return Err(refused(
                "original scoped phase differs from its actual A and Prepared",
            ));
        }
        prepared
            .require_profile(
                &scoped.learning,
                &self.identity,
                self.bootstrap
                    .writer_proof
                    .sha256()?
                    .as_str()
                    .parse::<Digest32>()
                    .map_err(protocol)?
                    .into_array(),
            )
            .map_err(protocol)?;
        OriginalSameActorRootContext::require_current(self)?;
        closing.disarm();
        Ok(())
    }
}

/// The private entry takes only descriptors already received by the original
/// SCM_RIGHTS purpose and a private earliest-receive deadline.
pub(crate) async fn receive_original_same_actor_inputs(
    bootstrap: File,
    root_pidfd: OwnedFd,
    handoff: OriginalSameActorPhaseHandoff,
    expected: &AgentdIdentity,
    timeout: Duration,
    mut receiver: OriginalPhaseReceiveDeadline,
) -> Result<OriginalSameActorProductionInputs, AgentdError> {
    if timeout.is_zero() || timeout > Duration::from_millis(500) {
        return Err(refused("bounded original phase five-lane timeout required"));
    }
    let bundle = read_bootstrap(bootstrap, expected)?;
    let OriginalSameActorPhaseHandoff {
        bootstrap: phase_bootstrap,
        root_pidfd: phase_pidfd,
        root_pid,
        initial,
    } = handoff;
    let descriptor: OriginalPhaseBootstrap = read_original_phase_descriptor(phase_bootstrap)?;
    validate_original_phase_binding(&descriptor, &bundle, expected, root_pid)?;
    crate::root_observation_stream::check_lifetime(&phase_pidfd).map_err(protocol)?;
    crate::root_observation_stream::check_lifetime(&root_pidfd).map_err(protocol)?;
    let gate =
        SameActorPhaseGate::from_original_deadline(SameActorPhaseDeadline::from_original_receive(
            receiver.instant,
            receiver.boottime_ns,
            descriptor.original.root_end_boottime_ns,
        )?)?;
    let mut closing = CloseSameActorPhaseOnDrop::new(&gate);
    receiver.remaining()?;
    let deadline_watch =
        crate::same_actor_q24_phase_gate::OriginalSameActorPhaseWatch::start(&gate)?;
    let end = gate.deadline().instant();
    // Keep the original all-five acceptance barrier. No request is sent while
    // Root is still waiting to accept another mandatory original lane.
    let observation = connect(&bundle.sockets.observation, timeout, end).await?;
    let issuer = connect(&bundle.sockets.issuer, timeout, end).await?;
    let checkpoint = connect(&bundle.sockets.checkpoint, timeout, end).await?;
    let device = connect(&bundle.sockets.device_frontier, timeout, end).await?;
    let notes = connect(&bundle.sockets.notes_frontier, timeout, end).await?;
    gate.require_open()?;
    let trust = writer_trust(&bundle);
    crate::root_writer_proof::VerifiedRootWriterProof::verify(bundle.writer_proof.clone(), &trust)
        .map_err(protocol)?;
    let session = AgentdRootAuthoritySession::connect_same_actor_phase_until(
        observation,
        AgentdRootAuthorityPeer {
            pid: bundle.root.pid,
            boot_id: bundle.root.boot_id.clone(),
            process_start_ticks: bundle.root.process_start_ticks,
        },
        root_pidfd.try_clone()?,
        timeout,
        receiver.boottime_ns,
        trust,
        Arc::clone(&gate),
    )
    .await
    .map_err(protocol)?;
    if session.original_session_end_boottime_ns() != receiver.boottime_ns
        || session.revocations().map_err(protocol)? != bundle.revocations
        || session.authority().grant_digest != bundle.writer_proof.sha256().map_err(protocol)?
    {
        return Err(refused("original Root capture or receiver end changed"));
    }
    let grants = Arc::new(
        AgentdUnixFinalUseGrantProvider::into_same_actor_phase(
            AgentdUnixFinalUseGrantProvider::from_root_stream_until(
                issuer,
                bundle.root.pid,
                root_pidfd.try_clone()?,
                timeout,
                end,
            )
            .map_err(protocol)?,
            &gate,
        )
        .map_err(protocol)?,
    );
    let checkpoint = AgentdUnixCognitiveCheckpointTransport::from_original_phase_stream_until(
        checkpoint,
        AgentdCognitiveCheckpointPeer {
            pid: bundle.root.pid,
            boot_id: bundle.root.boot_id.clone(),
            process_start_ticks: bundle.root.process_start_ticks,
        },
        root_pidfd.try_clone()?,
        timeout,
        &gate,
    )
    .map_err(protocol)?
    .into_protected_inputs(bundle.checkpoint.clone())
    .await
    .map_err(protocol)?;
    gate.require_open()?;
    let device = open_original_phase_consumer(
        device,
        bundle.consumers.device.clone(),
        &bundle,
        root_pidfd.try_clone()?,
        session.clock(),
        timeout,
        &gate,
    )
    .await?;
    let notes = open_original_phase_consumer(
        notes,
        bundle.consumers.notes.clone(),
        &bundle,
        root_pidfd.try_clone()?,
        session.clock(),
        timeout,
        &gate,
    )
    .await?;
    session
        .activate_original_phase_final_use_owners(vec![device.clone(), notes.clone()])
        .await
        .map_err(protocol)?;
    session
        .verifier()
        .verify_sender_process_binding(
            &session.authority(),
            &expected.agent_id,
            &bundle.writer.local_lease_id,
            bundle.writer.local_lease_generation,
            expected.spawn_generation,
        )
        .map_err(AgentdError::GenerationFenced)?;
    gate.require_open()?;
    let publication_connection =
        RootGenerationPublicationSlot::capture_after_original_receive(&session, &bundle, expected)?;
    let original_session = Arc::new(
        OriginalQ24SuccessorSession::capture_original_same_actor_successor_session(
            &session, &bundle, expected, &gate,
        )?,
    );
    let initial_lifetime =
        crate::same_actor_q24_phase_join_client::OriginalInitialPhaseLifetime::new(
            &gate,
            &descriptor.phase,
        );
    let context = Arc::new(OriginalSameActorRootContext {
        bootstrap: bundle.clone(),
        identity: expected.clone(),
        descriptor,
        session: original_session,
        gate: Arc::clone(&gate),
        root_pidfd: phase_pidfd,
        clock: session.clock(),
        device: device.clone(),
        notes: notes.clone(),
        grants: Arc::clone(&grants),
        scoped_consumed: AtomicBool::new(false),
        initial_lifetime,
        _closing: CloseSameActorPhaseOnDrop::new(&gate),
        _deadline_watch: deadline_watch,
    });
    let root = AgentdRootProductionInputs {
        session,
        checkpoint,
        device,
        notes,
        grants,
        bootstrap: bundle,
        publication_connection,
    };
    OriginalSameActorRootContext::require_current(&context)?;
    closing.disarm();
    Ok(OriginalSameActorProductionInputs {
        root,
        context,
        initial,
    })
}

pub(crate) fn read_original_phase_descriptor<T: serde::de::DeserializeOwned>(
    mut file: File,
) -> Result<T, AgentdError> {
    let size = file.metadata()?.len();
    if size == 0 || size > HOST_AUTHORITY_BOOTSTRAP_BOUND as u64 {
        return Err(refused("original phase descriptor bound"));
    }
    crate::authority_host_bootstrap_seal::validate_sealed(&file, size)?;
    file.rewind()?;
    let mut raw = Vec::with_capacity(size as usize);
    Read::by_ref(&mut file)
        .take(size + 1)
        .read_to_end(&mut raw)?;
    crate::authority_host_bootstrap_seal::validate_sealed(&file, size)?;
    if raw.len() as u64 != size {
        return Err(refused("original phase descriptor changed"));
    }
    Ok(serde_json::from_slice(&raw)?)
}

fn validate_original_phase_binding(
    phase: &OriginalPhaseBootstrap,
    original: &HostAuthorityPublicBootstrapV1,
    identity: &AgentdIdentity,
    root_pid: u32,
) -> Result<(), AgentdError> {
    let original_root = &original.root;
    let binding = Digest32::of_parts(&[
        b"hepta.same-actor-q24-phase.original-session.v1\0",
        &serde_json::to_vec(&phase.original)?,
    ])
    .to_string();
    let control = original
        .sockets
        .observation
        .parent()
        .ok_or_else(|| refused("original Root parent missing"))?
        .join(crate::same_actor_q24_phase_protocol::CONTROL_SOCKET);
    if phase.purpose != crate::same_actor_q24_phase_protocol::START_PURPOSE
        || phase.phase != binding
        || phase.original.root.uid != original_root.uid
        || phase.original.root.pid != original_root.pid
        || phase.original.root.boot_id != original_root.boot_id
        || phase.original.root.process_start_ticks != original_root.process_start_ticks
        || root_pid != original_root.pid
        || phase.original.consumer != original.consumer
        || phase.original.identity
            != crate::neuron_generation_process_identity_digest_v1(identity)?.to_string()
        || phase.original.writer != original.writer_proof.sha256()?.as_str()
        || phase.control_socket != control
        || phase.original.initial.target.scope().agent_id != identity.agent_id.as_str()
    {
        return Err(refused(
            "phase handoff differs from its original Root session",
        ));
    }
    // SAFETY: only reads this process's current primary group.
    crate::authority_host_runtime::validate_lane_paths(
        &[&original.sockets.observation, &control],
        unsafe { libc::getegid() },
    )?;
    Ok(())
}

struct OriginalPhaseFinalUseFrontier {
    original: RootFinalUseFrontierClient,
    phase: RequiredSameActorPhaseChannel,
}

impl AuthorityFrontierStore<FinalUseFrontier> for OriginalPhaseFinalUseFrontier {
    fn load(&self, owner_id: &str) -> Result<FinalUseFrontier, AuthorityTrustError> {
        let mut closing = self.phase.failure_scope();
        self.phase
            .require_open()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        let value = self.original.load(owner_id)?;
        self.phase
            .require_open()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        closing.disarm();
        Ok(value)
    }

    fn compare_and_set(
        &self,
        owner_id: &str,
        expected: &FinalUseFrontier,
        next: &FinalUseFrontier,
    ) -> Result<(), AuthorityTrustError> {
        let mut closing = self.phase.failure_scope();
        self.phase
            .require_open()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        self.original.compare_and_set(owner_id, expected, next)?;
        // A failed postcondition means uncertain acknowledgement, never that
        // the original CAS did not happen. The common gate remains closed.
        self.phase
            .require_open()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        closing.disarm();
        Ok(())
    }
}

#[allow(clippy::too_many_arguments)]
async fn open_original_phase_consumer(
    stream: UnixStream,
    consumer: HostAuthorityPublicConsumerV1,
    bundle: &HostAuthorityPublicBootstrapV1,
    root_pidfd: OwnedFd,
    clock: Arc<dyn AuthorityClock>,
    timeout: Duration,
    gate: &Arc<SameActorPhaseGate>,
) -> Result<FinalUseAuthority, AgentdError> {
    let phase = gate.retain_required_original_stream(&stream)?;
    let root = RootPeerIdentity {
        pid: bundle.root.pid,
        boot_id: bundle.root.boot_id.clone(),
        process_start_ticks: bundle.root.process_start_ticks,
    };
    let key = FinalUseIssuerTrustKey::from(bundle.issuer_key.clone());
    let revocations = bundle.revocations.clone();
    let gate = Arc::clone(gate);
    let mut closing = CloseSameActorPhaseOnDrop::new(&gate);
    let worker_gate = Arc::clone(&gate);
    let owner = tokio::task::spawn_blocking(move || {
        let mut closing = CloseSameActorPhaseOnDrop::new(&worker_gate);
        worker_gate.require_open()?;
        let frontier = Arc::new(OriginalPhaseFinalUseFrontier {
            original: RootFinalUseFrontierClient::from_stream_until(
                stream,
                consumer.owner_id.clone(),
                root,
                root_pidfd,
                timeout,
                worker_gate.deadline().instant(),
            )
            .map_err(protocol)?,
            phase,
        });
        if frontier.load(&consumer.owner_id).map_err(protocol)? != consumer.frontier {
            return Err(refused(
                "original consumer frontier changed since sealed capture",
            ));
        }
        let owner = FinalUseAuthority::open_state_dir_with_issuer_keys(
            &consumer.local_state_dir,
            consumer.owner_id,
            vec![key],
            revocations,
            clock,
            frontier,
        )
        .map_err(protocol)?;
        worker_gate.require_open()?;
        closing.disarm();
        Ok(owner)
    })
    .await
    .map_err(protocol)??;
    gate.require_open()?;
    closing.disarm();
    Ok(owner)
}
