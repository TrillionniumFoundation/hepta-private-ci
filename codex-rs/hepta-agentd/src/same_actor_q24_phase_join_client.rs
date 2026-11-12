//! The daemon side of the same-purpose two-ACK Root join.
//! Only an actual accepted task/Outcome retained capability can enter it.
//! A first ACK permits dropping Initial; only the second yields a Joined owner.

use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use crate::AgentdError;
use crate::AgentdRootAuthorityPeer;
use crate::CellQ24PreparedLearningV1;
use crate::HostAuthorityLearningProfileV1;
use crate::OriginalCellQ24RetainedLearningSourceV1;
use crate::authority_host_same_actor_q24_phase_join::PhaseJoinRequest;
use crate::authority_host_same_actor_q24_phase_join::PhaseJoinResponse;
use crate::root_observation_stream::RootObservationStream;
use crate::root_production_inputs::same_actor_phase::OriginalSameActorRootContext;
use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;
use crate::same_actor_q24_phase_gate::SameActorPhaseGate;
use crate::same_actor_q24_phase_gate::SameActorPhaseStream;

const PURPOSE: &str = "hepta.same-actor-q24-phase.join.v1";

/// Only this module's successful FIRST original ACK may mark intentional
/// retirement. It is not a grant, a Joined value, or permission to create C.
pub(crate) struct OriginalInitialPhaseLifetime {
    gate: Arc<SameActorPhaseGate>,
    phase: String,
    accepted: AtomicBool,
}

impl OriginalInitialPhaseLifetime {
    pub(crate) fn new(gate: &Arc<SameActorPhaseGate>, phase: &str) -> Arc<Self> {
        Arc::new(Self {
            gate: Arc::clone(gate),
            phase: phase.into(),
            accepted: AtomicBool::new(false),
        })
    }

    pub(crate) fn require_original_gate(
        &self,
        gate: &Arc<SameActorPhaseGate>,
    ) -> Result<(), AgentdError> {
        gate.require_open()?;
        if !Arc::ptr_eq(&self.gate, gate) {
            return Err(refused("Initial lifetime belongs to another phase gate"));
        }
        Ok(())
    }

    pub(crate) fn permits_original_drop(&self, gate: &Arc<SameActorPhaseGate>) -> bool {
        Arc::ptr_eq(&self.gate, gate) && self.accepted.load(Ordering::Acquire)
    }

    fn accept_original_retirement_ack(
        &self,
        context: &OriginalSameActorRootContext,
    ) -> Result<(), AgentdError> {
        self.require_original_gate(context.gate())?;
        OriginalSameActorRootContext::require_current(context)?;
        if self.phase != context.descriptor().phase
            || self
                .accepted
                .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
                .is_err()
        {
            return Err(refused(
                "original retirement acknowledgement was already consumed",
            ));
        }
        OriginalSameActorRootContext::require_current(context)
    }
}

pub(crate) struct OriginalDaemonPhaseRetirement {
    transport: RootObservationStream,
    context: Arc<OriginalSameActorRootContext>,
    profile: HostAuthorityLearningProfileV1,
    prepared: Arc<CellQ24PreparedLearningV1>,
    retained: OriginalCellQ24RetainedLearningSourceV1,
    _stop: SameActorPhaseStream,
    closing: CloseSameActorPhaseOnDrop,
}

/// Carries the actual private Prepared and retained capability. Serializing
/// its profile does not create this object or authorize another phase.
pub(crate) struct OriginalJoinedSameActorA {
    context: Arc<OriginalSameActorRootContext>,
    profile: HostAuthorityLearningProfileV1,
    prepared: Arc<CellQ24PreparedLearningV1>,
    retained: OriginalCellQ24RetainedLearningSourceV1,
    closing: CloseSameActorPhaseOnDrop,
}

impl OriginalDaemonPhaseRetirement {
    /// The enclosing task worker must already have closed A admission and
    /// joined its queued/active tasks. It keeps the actual owners until this
    /// ACK succeeds, then releases them before completing the second join.
    pub(crate) fn begin_original_retirement(
        context: Arc<OriginalSameActorRootContext>,
        prepared: Arc<CellQ24PreparedLearningV1>,
        retained: OriginalCellQ24RetainedLearningSourceV1,
        timeout: Duration,
    ) -> impl std::future::Future<Output = Result<Self, AgentdError>> {
        let closing = CloseSameActorPhaseOnDrop::new(context.gate());
        async move {
            if timeout.is_zero() || timeout > Duration::from_millis(500) {
                return Err(refused("bounded original phase join timeout required"));
            }
            OriginalSameActorRootContext::require_current(&context)?;
            retained
                .require_same_actor_phase_prepared(&prepared, context.identity())
                .await?;
            let profile = prepared
                .root_profile(
                    context.identity(),
                    context
                        .bootstrap()
                        .writer_proof
                        .sha256()?
                        .as_str()
                        .parse::<codex_hepta_types::Digest32>()
                        .map_err(refused)?
                        .into_array(),
                )
                .map_err(refused)?;
            let stream = tokio::time::timeout(
                timeout.min(context.gate().require_open()?),
                tokio::net::UnixStream::connect(&context.descriptor().control_socket),
            )
            .await
            .map_err(|_| refused("original phase join connection expired"))??;
            OriginalSameActorRootContext::require_current(&context)?;
            let stream = stream.into_std()?;
            let stop = context.gate().retain_original_stream(&stream)?;
            let root = &context.bootstrap().root;
            let transport = RootObservationStream::from_stream_until(
                stream,
                AgentdRootAuthorityPeer {
                    pid: root.pid,
                    boot_id: root.boot_id.clone(),
                    process_start_ticks: root.process_start_ticks,
                },
                context.root_pidfd()?,
                timeout,
                context.gate().deadline().instant(),
            )
            .map_err(refused)?;
            original_join_exchange(&transport, &context, &profile, 1).await?;
            retained
                .require_same_actor_phase_prepared(&prepared, context.identity())
                .await?;
            context
                .initial_lifetime()
                .accept_original_retirement_ack(&context)?;
            Ok(Self {
                transport,
                context,
                profile,
                prepared,
                retained,
                _stop: stop,
                closing,
            })
        }
    }

    /// This consumes the first-ACK owner. The caller must have actually dropped
    /// the old Initial/Cell/CURRENT resources; Root independently waits for
    /// their authorized EOF and checks the held physical drained journal cut.
    pub(crate) async fn join_after_original_a_drop(
        mut self,
    ) -> Result<OriginalJoinedSameActorA, AgentdError> {
        OriginalSameActorRootContext::require_current(&self.context)?;
        self.retained
            .require_same_actor_phase_prepared(&self.prepared, self.context.identity())
            .await?;
        original_join_exchange(&self.transport, &self.context, &self.profile, 2).await?;
        self.retained
            .require_same_actor_phase_prepared(&self.prepared, self.context.identity())
            .await?;
        OriginalSameActorRootContext::require_current(&self.context)?;
        let closing = CloseSameActorPhaseOnDrop::new(self.context.gate());
        self.closing.disarm();
        Ok(OriginalJoinedSameActorA {
            context: self.context,
            profile: self.profile,
            prepared: self.prepared,
            retained: self.retained,
            closing,
        })
    }
}

impl OriginalJoinedSameActorA {
    pub(crate) fn context(&self) -> &Arc<OriginalSameActorRootContext> {
        &self.context
    }
    pub(crate) fn prepared(&self) -> &Arc<CellQ24PreparedLearningV1> {
        &self.prepared
    }
    pub(crate) fn profile(&self) -> &HostAuthorityLearningProfileV1 {
        &self.profile
    }

    pub(crate) async fn require_original(&self) -> Result<(), AgentdError> {
        OriginalSameActorRootContext::require_current(&self.context)?;
        self.retained
            .require_same_actor_phase_prepared(&self.prepared, self.context.identity())
            .await?;
        self.prepared
            .require_profile(
                &self.profile,
                self.context.identity(),
                self.context
                    .bootstrap()
                    .writer_proof
                    .sha256()?
                    .as_str()
                    .parse::<codex_hepta_types::Digest32>()
                    .map_err(refused)?
                    .into_array(),
            )
            .map_err(refused)?;
        OriginalSameActorRootContext::require_current(&self.context)
    }

    pub(crate) fn into_original_learning_parts(
        mut self,
    ) -> Result<
        (
            Arc<OriginalSameActorRootContext>,
            Arc<CellQ24PreparedLearningV1>,
            OriginalCellQ24RetainedLearningSourceV1,
        ),
        AgentdError,
    > {
        OriginalSameActorRootContext::require_current(&self.context)?;
        self.closing.disarm();
        Ok((self.context, self.prepared, self.retained))
    }
}

async fn original_join_exchange(
    transport: &RootObservationStream,
    context: &OriginalSameActorRootContext,
    profile: &HostAuthorityLearningProfileV1,
    sequence: u8,
) -> Result<(), AgentdError> {
    let mut closing = CloseSameActorPhaseOnDrop::new(context.gate());
    OriginalSameActorRootContext::require_current(context)?;
    let profile = serde_json::to_string(profile)?;
    let request = PhaseJoinRequest {
        schema: 1,
        purpose: PURPOSE.into(),
        sequence,
        phase: context.descriptor().phase.clone(),
        profile: profile.clone(),
    };
    if serde_json::to_vec(&request)?.len() > 16 * 1024 {
        return Err(refused("original phase request bound"));
    }
    let response: PhaseJoinResponse = transport.read(&request).await.map_err(refused)?;
    // This follows actual framing and semantic ACK validation, including
    // BOOTTIME after suspend; a watcher alone is not the acceptance condition.
    if response.schema != 1
        || response.purpose != PURPOSE
        || response.sequence != sequence
        || response.phase != request.phase
        || response.profile != profile
    {
        return Err(refused("original phase acknowledgement differs"));
    }
    OriginalSameActorRootContext::require_current(context)?;
    closing.disarm();
    Ok(())
}

fn refused(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::GenerationFenced(format!("original same-actor phase join: {error}"))
}
