//! Concrete ordinary A/C ingress for the explicit deployment coordinator.
//! Only the original signed Control API admits a task. Its acknowledgement
//! is retained as control evidence; it is never an Outcome or completion.

use std::sync::Arc;
use std::time::Duration;

use codex_hepta_fleet::AgentLifecycle;

use crate::AgentdClient;
use crate::AgentdError;
use crate::AuthBusObjectiveIngress;
use crate::ObjectiveStartOutcome;
use crate::client::ObjectiveStartReplyV1;
use crate::root_production_inputs::same_actor_phase::OriginalSameActorRootContext;
use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;

use super::deployment_refused;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum OriginalOrdinaryTaskStage {
    A,
    C,
}

impl OriginalOrdinaryTaskStage {
    fn index(self) -> usize {
        match self {
            Self::A => 0,
            Self::C => 1,
        }
    }
}

/// Only the actual coordinator constructs and owns this one sequential client.
/// Attempts and returned acknowledgements are not reset on any error. In
/// particular, no later health response permits an uncertain task to be sent
/// again, and the retained control receipt cannot authorize C installation.
pub(super) struct OriginalOrdinaryTaskIngress {
    context: Arc<OriginalSameActorRootContext>,
    client: AgentdClient,
    attempted: [bool; 2],
    run_ids: [Option<String>; 2],
    acknowledged: [Option<ObjectiveStartOutcome>; 2],
}

impl OriginalOrdinaryTaskIngress {
    pub(super) fn for_original_context(
        context: Arc<OriginalSameActorRootContext>,
    ) -> Result<Self, AgentdError> {
        let mut closing = CloseSameActorPhaseOnDrop::new(context.gate());
        OriginalSameActorRootContext::require_current(&context)?;
        let identity = context.identity();
        if context.bootstrap().consumer.pid != std::process::id() {
            return Err(deployment_refused(
                "ordinary ingress requires this actual daemon process",
            ));
        }
        let client = AgentdClient::new(
            identity.control_socket.clone(),
            identity.agent_id.clone(),
            identity.spawn_generation,
        )?;
        OriginalSameActorRootContext::require_current(&context)?;
        closing.disarm();
        Ok(Self {
            context,
            client,
            attempted: [false, false],
            run_ids: [None, None],
            acknowledged: [None, None],
        })
    }

    pub(super) async fn submit_original_once(
        &mut self,
        stage: OriginalOrdinaryTaskStage,
        request: AuthBusObjectiveIngress,
    ) -> Result<(), AgentdError> {
        let mut closing = CloseSameActorPhaseOnDrop::new(self.context.gate());
        OriginalSameActorRootContext::require_current(&self.context)?;
        let index = stage.index();
        if self.attempted[index]
            || request.body.spawn_generation != self.context.identity().spawn_generation
            || request.body.run_id.is_empty()
        {
            return Err(deployment_refused(
                "ordinary task is repeated or differs from the original spawn",
            ));
        }
        if stage == OriginalOrdinaryTaskStage::C {
            if !matches!(self.acknowledged[0].as_ref(), Some(ObjectiveStartOutcome::Admitted { .. }))
                || self.run_ids[0].as_ref() == Some(&request.body.run_id)
            {
                return Err(deployment_refused(
                    "ordinary C requires an original A admission and a distinct real run",
                ));
            }
        }
        // This terminal attempt bit precedes every await. Cancellation,
        // malformed input, rejection and ACK loss never rearm this stage.
        self.attempted[index] = true;
        self.run_ids[index] = Some(request.body.run_id.clone());
        self.wait_original_running().await?;
        OriginalSameActorRootContext::require_current(&self.context)?;
        // Keep the existing signature/body, original Control framing and its
        // existing request timeout. No Root observation or deadline is reset.
        let reply = tokio::select! {
            _ = self.context.gate().cancelled() => {
                return Err(deployment_refused(
                    "ordinary task admission became uncertain while the phase closed",
                ));
            }
            reply = self.client.objective_start_once(request) => reply,
        }?;
        match reply {
            ObjectiveStartReplyV1::Completed(outcome) => {
                // Store the actual acknowledgement before a later local
                // validation can fail. It is not replaced by synthetic
                // completion and remains in this actual coordinator owner.
                self.acknowledged[index] = Some(outcome);
            }
            ObjectiveStartReplyV1::AcknowledgementLost(error) => {
                // The original error is returned intact. The armed common
                // close guard and terminal attempt bit prohibit resubmission.
                return Err(error);
            }
        }
        match self.acknowledged[index].as_ref() {
            Some(ObjectiveStartOutcome::Admitted { receipt }) => {
                if Some(&receipt.run_id) != self.run_ids[index].as_ref() {
                    return Err(deployment_refused(
                        "ordinary admission acknowledgement names another run",
                    ));
                }
            }
            Some(ObjectiveStartOutcome::Conflict { .. }) => {
                return Err(deployment_refused(
                    "original signed objective was rejected with a durable conflict",
                ));
            }
            None => {
                return Err(deployment_refused(
                    "original ordinary admission acknowledgement is missing",
                ));
            }
        }
        OriginalSameActorRootContext::require_current(&self.context)?;
        closing.disarm();
        Ok(())
    }

    async fn wait_original_running(&self) -> Result<(), AgentdError> {
        loop {
            OriginalSameActorRootContext::require_current(&self.context)?;
            let health = tokio::select! {
                _ = self.context.gate().cancelled() => {
                    return Err(deployment_refused(
                        "original daemon closed before ordinary task admission",
                    ));
                }
                result = self.client.health() => result,
            }?;
            OriginalSameActorRootContext::require_current(&self.context)?;
            let identity = self.context.identity();
            if health.fenced
                || health.process_id != self.context.bootstrap().consumer.pid
                || health.process_id != std::process::id()
                || health.workspace != identity.workspace
                || health.home_root != identity.home_root
                || health.run_root != identity.run_root
            {
                return Err(deployment_refused(
                    "actual daemon health differs from the original live owner",
                ));
            }
            if health.ready {
                if health.lifecycle != AgentLifecycle::Running {
                    return Err(deployment_refused(
                        "ordinary admission requires the actual promoted Running state",
                    ));
                }
                return Ok(());
            }
            // A successful not-yet-Running observation is only a read-only
            // startup wait. Any RPC or authority error above returns once.
            let remaining = self.context.gate().require_open()?;
            tokio::select! {
                _ = self.context.gate().cancelled() => {
                    return Err(deployment_refused(
                        "original daemon closed during its readiness wait",
                    ));
                }
                _ = tokio::time::sleep(remaining.min(Duration::from_millis(10))) => {}
            }
        }
    }
}
