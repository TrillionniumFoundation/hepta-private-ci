//! Resume the existing turn's incomplete host preparation under the same Core
//! reservation and original queue admission acknowledgement.

use std::sync::Arc;

use codex_history::TurnRecoveryRequestBinding;
use codex_protocol::turn_input::{NotSubmittedReason, StartIfIdleSubmission, TurnInputSubmission};
use codex_protocol::user_input::{UserInput, user_input_payload_sha256};

use crate::CodexThread;
use crate::hosted_turn::{HostedPreparationRequest, HostedQueueBinding, HostedQueueCommitWaiter, HostedTurnDispatch, HostedTurnExecutor, HostedTurnMode, HostedTurnProvenance, invalid};
use crate::user_message_admission::{UserMessageAdmission, UserMessageAdmissionError};

impl CodexThread {
    /// The original queue must hold its dispatch process lock and claim while
    /// calling this method, and complete that same claim after the reply. This
    /// never submits a new UserInput, creates a new turn ID, or grants an effect.
    pub async fn resume_hosted_preparation_if_idle_and_wait_for_persisted_admission(
        &self,
        input: Vec<UserInput>,
        queue: HostedQueueBinding,
        recovery: TurnRecoveryRequestBinding,
        executor: Arc<dyn HostedTurnExecutor>,
        completion: HostedQueueCommitWaiter,
    ) -> Result<StartIfIdleSubmission, UserMessageAdmissionError> {
        let invalid_admission = |message: &str| UserMessageAdmissionError::Admission(invalid(message));
        let provenance = HostedTurnProvenance::from_recovery(&recovery)
            .map_err(UserMessageAdmissionError::Admission)?
            .ok_or_else(|| invalid_admission("original hosted provenance is absent"))?;
        if !self.session.services.session_extension_data.get::<HostedTurnMode>()
            .is_some_and(|mode| Arc::ptr_eq(&mode.executor, &executor))
            || provenance.executor_id != executor.executor_id() || provenance.queue != queue
            || input.is_empty()
            || user_input_payload_sha256(&input).map_err(|error| invalid_admission(&error.to_string()))? != queue.payload_sha256
        {
            return Err(invalid_admission("original hosted preparation input or owner changed"));
        }
        let history = crate::hosted_turn_history::load(&self.session, &recovery.turn_id)
            .await.map_err(UserMessageAdmissionError::Admission)?;
        if history.original != recovery {
            return Err(invalid_admission("hosted preparation does not match the original history"));
        }
        if history.preparation_interrupted {
            return Err(invalid_admission("original hosted turn was interrupted; only existing effects may be observed"));
        }
        self.session.services.agent_control.ensure_execution_capacity_for_turn_start(self)
            .await.map_err(UserMessageAdmissionError::Admission)?;
        let Some(epoch) = self.hosted_recovery_epoch_if_idle(&recovery.turn_id).await else {
            return Ok(StartIfIdleSubmission::NotSubmitted { reason: NotSubmittedReason::NotIdle });
        };
        let turn_id = recovery.turn_id.clone();
        let (_pending, admission) = self.session.pending_user_message_admissions.register_hosted_recovery(
            turn_id.clone(), HostedTurnDispatch {
                executor, queue, completion,
                recovery: Some(HostedPreparationRequest { input, original: recovery }),
            },
        ).map_err(UserMessageAdmissionError::Admission)?;
        let submission = self.io.submit_recover_turn(epoch, Default::default(), /*trace*/ None, turn_id.clone())
            .await.map_err(UserMessageAdmissionError::Admission)?;
        match submission {
            TurnInputSubmission::NotSubmitted { reason } => return Ok(StartIfIdleSubmission::NotSubmitted { reason }),
            TurnInputSubmission::Started { turn_id: observed } if observed == turn_id => {}
            _ => return Err(invalid_admission("Core changed the retained hosted turn")),
        }
        let admitted = tokio::select! {
            biased;
            result = admission => result.unwrap_or(Err(UserMessageAdmissionError::TaskEndedBeforePersistence))?,
            () = self.io.session_loop_termination.clone() => return Err(UserMessageAdmissionError::TaskEndedBeforePersistence),
        };
        match admitted.into_admission() {
            UserMessageAdmission::Started { turn_id: observed } if observed == turn_id => Ok(StartIfIdleSubmission::Started { turn_id }),
            _ => Err(invalid_admission("hosted recovery admission changed the original turn")),
        }
    }
}
