//! Consume the one post-A Root purpose after the real two-ACK join.
//! Public profile bytes never create a second Initial connection or an owner.

use super::*;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::os::unix::net::UnixDatagram;

use crate::AgentdRootQ24ModelFactoryV1;
use crate::CellQ24PreparedLearningV1;
use crate::OriginalCellQ24RetainedLearningSourceV1;
use crate::RootGenerationPublicationHandoffV1;
use crate::RootQ24ModelFactoryHandoffV1;
use crate::authority_host_service::q24_model::Q24ModelFactoryBootstrap;
use crate::root_observation_stream::RootObservationStream;
use crate::root_production_handoff::same_actor_phase::receive_original_scoped_phase;
use crate::root_production_inputs::OriginalQ24SuccessorSession;
use crate::root_production_inputs::same_actor_phase::OriginalSameActorRootContext;
use crate::root_production_inputs::same_actor_phase::read_original_phase_descriptor;
use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;
use crate::same_actor_q24_phase_join_client::OriginalJoinedSameActorA;
use crate::same_actor_q24_phase_protocol::OriginalScopedPhaseBootstrap;

/// No constructor accepts a caller-created connection, bare verifier, slot or
/// provider. The only constructor is the actual scoped receiver below.
pub(crate) struct OriginalScopedPublicationTicket {
    handoff: RootGenerationPublicationHandoffV1,
    context: Arc<OriginalSameActorRootContext>,
    scoped: OriginalScopedPhaseBootstrap,
    consumed: AtomicBool,
    closing: CloseSameActorPhaseOnDrop,
}

pub(crate) struct OriginalSameActorScopedOwners {
    context: Arc<OriginalSameActorRootContext>,
    learning: AgentdRootLearningInputsV1,
    model: AgentdRootQ24ModelFactoryV1,
    publication: OriginalScopedPublicationTicket,
    prepared: Arc<CellQ24PreparedLearningV1>,
    retained: OriginalCellQ24RetainedLearningSourceV1,
    closing: CloseSameActorPhaseOnDrop,
}

impl OriginalScopedPublicationTicket {
    /// Called only by the same captured Session to mint this distinct purpose
    /// connection. The existing Initial slot is never taken again.
    pub(crate) fn claim_original_session(
        &self,
        session: &OriginalQ24SuccessorSession,
    ) -> Result<(), AgentdError> {
        let mut closing = CloseSameActorPhaseOnDrop::new(self.context.gate());
        OriginalSameActorRootContext::require_current(&self.context)?;
        if !std::ptr::eq(self.context.successor_session().as_ref(), session)
            || self.scoped.original != *self.context.descriptor()
            || self.consumed.compare_exchange(
                false, true, Ordering::AcqRel, Ordering::Acquire,
            ).is_err()
        {
            return Err(refused("scoped CURRENT ticket differs or was already consumed"));
        }
        session.require_original_same_actor_phase(self.context.gate())?;
        closing.disarm();
        Ok(())
    }

    pub(crate) fn gate(&self) -> &Arc<crate::same_actor_q24_phase_gate::SameActorPhaseGate> {
        self.context.gate()
    }

    pub(crate) fn connect_original_current(
        mut self,
        timeout: Duration,
    ) -> impl std::future::Future<Output = Result<Arc<crate::NeuronGenerationCurrentOwnerV1>, AgentdError>> {
        // The ticket already owns its close guard before this future is polled.
        async move {
            OriginalSameActorRootContext::require_current(&self.context)?;
            let connection = self.context.successor_session()
                .take_original_scoped_publication_connection(&self)?;
            let current = self.handoff.connect_original_same_actor_publication(
                connection, Arc::clone(&self.context), self.scoped, timeout,
            ).await?;
            OriginalSameActorRootContext::require_current(&self.context)?;
            self.closing.disarm();
            Ok(current)
        }
    }
}

impl OriginalSameActorScopedOwners {
    pub(crate) fn context(&self) -> &Arc<OriginalSameActorRootContext> { &self.context }

    /// The required task worker already owns its common close guard. Every
    /// returned lane also retains its original same-Gate close responsibility.
    pub(crate) fn into_original_parts(
        mut self,
    ) -> Result<(
        Arc<OriginalSameActorRootContext>,
        AgentdRootLearningInputsV1,
        AgentdRootQ24ModelFactoryV1,
        OriginalScopedPublicationTicket,
        Arc<CellQ24PreparedLearningV1>,
        OriginalCellQ24RetainedLearningSourceV1,
    ), AgentdError> {
        OriginalSameActorRootContext::require_current(&self.context)?;
        self.learning.require_prepared_q24(&self.prepared)?;
        self.closing.disarm();
        Ok((self.context, self.learning, self.model, self.publication, self.prepared, self.retained))
    }
}

/// This consumes the actual Joined owner, not its serialized profile. Failure
/// or cancellation closes all phase lanes and never reopens the scoped claim.
pub(crate) fn receive_original_same_actor_scoped_owners(
    socket: UnixDatagram,
    joined: OriginalJoinedSameActorA,
    timeout: Duration,
) -> impl std::future::Future<Output = Result<OriginalSameActorScopedOwners, AgentdError>> {
    let mut closing = CloseSameActorPhaseOnDrop::new(joined.context().gate());
    async move {
        joined.require_original().await?;
        let context = Arc::clone(joined.context());
        let receive_context = Arc::clone(&context);
        let handoff = tokio::task::spawn_blocking(move || {
            OriginalSameActorRootContext::require_current(&receive_context)?;
            let handoff = receive_original_scoped_phase(socket, timeout, receive_context.gate())?;
            OriginalSameActorRootContext::require_current(&receive_context)?;
            Ok::<_, AgentdError>(handoff)
        }).await.map_err(|_| refused("original scoped rights receiver was lost"))??;
        joined.require_original().await?;
        let scoped: OriginalScopedPhaseBootstrap = read_original_phase_descriptor(handoff.bootstrap)?;
        if handoff.root_pid != context.bootstrap().root.pid {
            return Err(refused("scoped rights came from another original Root"));
        }
        context.accept_original_scoped_descriptor(&scoped, OriginalJoinedSameActorA::prepared(&joined))?;
        if serde_json::to_vec(&scoped.learning)? != serde_json::to_vec(joined.profile())? {
            return Err(refused("scoped Root profile differs from the actual joined A"));
        }
        let learning = handoff.learning.connect_original_same_actor_learning(
            Arc::clone(&context), scoped.clone(), Arc::clone(OriginalJoinedSameActorA::prepared(&joined)), timeout,
        ).await?;
        OriginalSameActorRootContext::require_current(&context)?;
        let model = connect_original_same_actor_model(
            handoff.model, &context, &learning, &scoped, timeout,
        ).await?;
        joined.require_original().await?;
        OriginalSameActorRootContext::require_current(&context)?;
        let publication = OriginalScopedPublicationTicket {
            handoff: handoff.publication,
            context: Arc::clone(&context),
            scoped,
            consumed: AtomicBool::new(false),
            closing: CloseSameActorPhaseOnDrop::new(context.gate()),
        };
        let (context, prepared, retained) = joined.into_original_learning_parts()?;
        let result = OriginalSameActorScopedOwners {
            closing: CloseSameActorPhaseOnDrop::new(context.gate()),
            context, learning, model, publication, prepared, retained,
        };
        closing.disarm();
        Ok(result)
    }
}

impl RootLearningHandoffV1 {
    pub(crate) fn connect_original_same_actor_learning(
        self,
        context: Arc<OriginalSameActorRootContext>,
        scoped: OriginalScopedPhaseBootstrap,
        prepared: Arc<CellQ24PreparedLearningV1>,
        timeout: Duration,
    ) -> impl std::future::Future<Output = Result<AgentdRootLearningInputsV1, AgentdError>> {
        let mut closing = CloseSameActorPhaseOnDrop::new(context.gate());
        async move {
            if timeout.is_zero() || timeout > Duration::from_millis(500) {
                return Err(refused("bounded original phase Learning timeout required"));
            }
            OriginalSameActorRootContext::require_current(&context)?;
            let bundle: HostAuthorityLearningBootstrapV1 = read_original_phase_descriptor(self.bootstrap)?;
            let initial = validate_binding(
                &bundle, context.bootstrap(), context.identity(), self.root_pid,
            )?;
            let scope = bundle.frozen_scope(&initial)?
                .ok_or_else(|| refused("original phase requires its scoped Learning purpose"))?;
            let expected_initial = scoped.learning.require_binding(
                context.identity(), context.bootstrap().writer_proof.sha256()?.as_str(),
            )?;
            let expected_scope = scoped.learning.require_cell_scope(&expected_initial)?;
            if initial != expected_initial || scope != expected_scope
                || scoped.original != *context.descriptor()
                || scoped.phase != context.descriptor().phase
                || scoped.purpose != crate::same_actor_q24_phase_protocol::SCOPED_PURPOSE
            {
                return Err(refused("Learning handoff differs from the actual scoped purpose"));
            }
            prepared.require_initial(&initial, &scope)
                .map_err(|error| refused(error.to_string()))?;
            let paths = &context.bootstrap().sockets;
            // SAFETY: only observes the actual current credential.
            crate::authority_host_runtime::validate_lane_paths(
                &[&paths.observation, &paths.issuer, &paths.checkpoint,
                  &paths.device_frontier, &paths.notes_frontier, &bundle.socket_path],
                unsafe { libc::getegid() },
            )?;
            OriginalSameActorRootContext::require_current(&context)?;
            let stream = tokio::time::timeout(
                timeout.min(context.gate().require_open()?),
                tokio::net::UnixStream::connect(&bundle.socket_path),
            ).await.map_err(|_| refused("original phase Learning connection expired"))??;
            OriginalSameActorRootContext::require_current(&context)?;
            let client = AgentdLearningCheckpointClientV1::from_original_same_actor_stream_until(
                stream.into_std()?,
                AgentdRootAuthorityPeer {
                    pid: bundle.root.pid, boot_id: bundle.root.boot_id,
                    process_start_ticks: bundle.root.process_start_ticks,
                },
                self.root_pidfd, initial.clone(), timeout, scope.clone(), context.gate(),
            ).map_err(|error| refused(format!("original phase Learning transport: {error}")))?;
            client.restore(&initial.request).await
                .map_err(|error| refused(format!("original phase Learning CURRENT: {error}")))?;
            OriginalSameActorRootContext::require_current(&context)?;
            closing.disarm();
            Ok(AgentdRootLearningInputsV1 {
                client, initial, identity: context.identity().clone(), scope: Some(scope),
            })
        }
    }
}

async fn connect_original_same_actor_model(
    handoff: RootQ24ModelFactoryHandoffV1,
    context: &Arc<OriginalSameActorRootContext>,
    learning: &AgentdRootLearningInputsV1,
    scoped: &OriginalScopedPhaseBootstrap,
    timeout: Duration,
) -> Result<AgentdRootQ24ModelFactoryV1, AgentdError> {
    let mut closing = CloseSameActorPhaseOnDrop::new(context.gate());
    if timeout.is_zero() || timeout > Duration::from_millis(500) {
        return Err(refused("bounded original phase Model timeout required"));
    }
    OriginalSameActorRootContext::require_current(&context)?;
    let bundle: Q24ModelFactoryBootstrap = read_original_phase_descriptor(handoff.bootstrap)?;
    let original = context.bootstrap();
    let identity = context.identity();
    let socket = original.sockets.observation.parent()
        .ok_or_else(|| refused("original Root socket parent missing"))?
        .join("q24-model-proposal-factory-v1.sock");
    if bundle.root != original.root || bundle.consumer != original.consumer
        || bundle.root.pid != handoff.root_pid || bundle.root.uid != 0
        || bundle.identity.identity()? != *identity
        || original.registered_identity.identity()? != *identity
        || bundle.socket_path != socket
        || bundle.profile.binding().to_string() != scoped.factory
    {
        return Err(refused("Model handoff differs from the original scoped Root purpose"));
    }
    let (initial, scope) = learning.q24_model_scope(identity)?;
    bundle.profile.require_context(
        identity, original.writer_proof.sha256()?.as_str(), &initial, &scope,
    )?;
    bundle.profile.require_files(&handoff.journal, &handoff.witness)?;
    let paths = &original.sockets;
    // SAFETY: only observes the actual current credential.
    crate::authority_host_runtime::validate_lane_paths(
        &[&paths.observation, &paths.issuer, &paths.checkpoint,
          &paths.device_frontier, &paths.notes_frontier, &socket],
        unsafe { libc::getegid() },
    )?;
    OriginalSameActorRootContext::require_current(&context)?;
    let stream = tokio::time::timeout(
        timeout.min(context.gate().require_open()?), tokio::net::UnixStream::connect(&socket),
    ).await.map_err(|_| refused("original phase Model connection expired"))??;
    OriginalSameActorRootContext::require_current(&context)?;
    let stream = stream.into_std()?;
    // Both owners are derived here from THIS original stream and THIS gate.
    // The factory is never passed an externally chosen transport/guard pair.
    let required = context.gate().retain_required_original_stream(&stream)?;
    let transport = RootObservationStream::from_stream_until(
        stream,
        AgentdRootAuthorityPeer {
            pid: bundle.root.pid, boot_id: bundle.root.boot_id,
            process_start_ticks: bundle.root.process_start_ticks,
        },
        handoff.root_pidfd, timeout, context.gate().deadline().instant(),
    ).map_err(|error| refused(format!("original phase Model peer: {error}")))?;
    let model = AgentdRootQ24ModelFactoryV1::from_original_same_actor_handoff(
        transport, bundle.profile, initial, scope, identity.spawn_generation,
        (handoff.journal, handoff.witness), required,
    ).await?;
    OriginalSameActorRootContext::require_current(&context)?;
    closing.disarm();
    Ok(model)
}
