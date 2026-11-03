use std::sync::Arc;

use codex_history::TurnRecoveryRequestBinding;
use codex_protocol::error::Result as CodexResult;
use codex_protocol::turn_input::{StartIfIdleSubmission, TurnInput, TurnInputMode, TurnInputRequest, TurnInputSubmission};
use codex_protocol::user_input::user_input_payload_sha256;

use crate::CodexThread;
use crate::hosted_turn::{HostedQueueBinding, HostedQueueCommitWaiter, HostedTurnDispatch, HostedTurnExecutor, HostedTurnMode, HostedTurnObservation, HostedTurnProvenance, invalid};
use crate::user_message_admission::{PendingUserMessageAdmissionState, UserMessageAdmission, UserMessageAdmissionError};

impl CodexThread {
    pub(crate) async fn hosted_recovery_epoch_if_idle(&self, turn_id: &str) -> Option<u64> {
        let epoch = {
            let active = self.session.active_turn.lock().await;
            if active.is_some() || self.session.shutdown_started() || self.session.has_pending_admission_fence() { return None; }
            self.session.turn_epoch.load(std::sync::atomic::Ordering::Acquire)
        };
        crate::hosted_turn_history::load(&self.session, turn_id).await.ok()?;
        let active = self.session.active_turn.lock().await;
        (active.is_none() && !self.session.shutdown_started() && !self.session.has_pending_admission_fence()
            && self.session.turn_epoch.load(std::sync::atomic::Ordering::Acquire) == epoch).then_some(epoch)
    }

    /// Starts the host-selected executor under Core's original idle reservation.
    /// The returned Started reply proves host checkpoint/history admission only;
    /// the executor waits for the caller's original queue completion before effects.
    pub async fn start_hosted_turn_if_idle_and_wait_for_persisted_admission(
        &self,
        request: TurnInputRequest,
        queue: HostedQueueBinding,
        executor: Arc<dyn HostedTurnExecutor>,
        completion: HostedQueueCommitWaiter,
    ) -> Result<StartIfIdleSubmission, UserMessageAdmissionError> {
        Self::validate_persisted_user_input(&request)?;
        if !self.session.services.session_extension_data.get::<HostedTurnMode>()
            .is_some_and(|mode| Arc::ptr_eq(&mode.executor, &executor)) || !request.additional_context.is_empty() {
            return Err(UserMessageAdmissionError::Admission(invalid("hosted queue mode is not installed or input has unbound extra context")));
        }
        let TurnInput::UserInput { content, client_id } = &request.input else {
            return Err(UserMessageAdmissionError::Admission(invalid("hosted queue requires user input")));
        };
        if client_id.as_deref() != Some(queue.client_id.as_str())
            || user_input_payload_sha256(content).map_err(|error| UserMessageAdmissionError::Admission(invalid(&error.to_string())))? != queue.payload_sha256 {
            return Err(UserMessageAdmissionError::Admission(invalid("hosted queue payload changed")));
        }
        let (submission, admitted) = self.submit_turn_input_with_mode_and_wait_for_exact_admission(
            request,
            PendingUserMessageAdmissionState::WaitingForAdmission,
            TurnInputMode::StartIfIdle,
            Some(HostedTurnDispatch { executor, queue, completion, recovery: None }),
        ).await?;
        match (submission, admitted) {
            (TurnInputSubmission::Started { turn_id }, Some(admitted)) => {
                match admitted.into_admission() {
                    UserMessageAdmission::Started { turn_id: admitted_id } if admitted_id == turn_id => Ok(StartIfIdleSubmission::Started { turn_id }),
                    _ => Err(UserMessageAdmissionError::Admission(invalid("hosted admission returned another original turn"))),
                }
            }
            (TurnInputSubmission::NotSubmitted { reason }, None) => Ok(StartIfIdleSubmission::NotSubmitted { reason }),
            _ => Err(UserMessageAdmissionError::Admission(invalid("hosted admission did not preserve its idle-start outcome"))),
        }
    }

    /// Observes a previously recorded host checkpoint through the original live
    /// handle. This cannot prepare, dispatch, or recover a sampling task.
    pub async fn observe_hosted_turn_admission(
        &self,
        executor: Arc<dyn HostedTurnExecutor>,
        recovery: TurnRecoveryRequestBinding,
    ) -> CodexResult<Option<String>> {
        let provenance = HostedTurnProvenance::from_recovery(&recovery)?
            .ok_or_else(|| invalid("original hosted provenance is absent"))?;
        if provenance.executor_id != executor.executor_id() {
            return Err(invalid("original hosted executor is unavailable"));
        }
        let expected_turn_id = recovery.turn_id.clone();
        let observed = executor.observe_admission(HostedTurnObservation {
            live_thread: self.session.live_thread_for_persistence("observe hosted admission")
                .map_err(|error| invalid(&error.to_string()))?.clone(),
            thread_id: self.session.thread_id,
            turn_id: expected_turn_id.clone(), queue: provenance.queue, recovery,
        }).await?;
        if observed.as_ref().is_some_and(|turn_id| turn_id != &expected_turn_id) {
            return Err(invalid("hosted observation changed the original turn"));
        }
        Ok(observed)
    }
}
