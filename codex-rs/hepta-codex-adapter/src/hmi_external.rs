//! Presentation attachment to an already authorized external queue owner.
use super::*;
/// Owner-minted admission floor, retained across asynchronous ingress lookup.
/// A local interrupt invalidates it before any fresh output can be armed.
pub struct HmiOwnerAdmissionFenceV1 {
    connection_id: u64,
    epoch: u64,
}

impl HmiRequestsV1 {
    pub fn owner_admission_fence(&self) -> Result<HmiOwnerAdmissionFenceV1, HmiError> {
        let state = self.shared.state.lock().map_err(|_| HmiError::Fenced)?;
        if state.fenced {
            return Err(HmiError::Fenced);
        }
        Ok(HmiOwnerAdmissionFenceV1 {
            connection_id: self.shared.connection_id,
            epoch: state.epoch,
        })
    }
    /// Current context may report an interrupted/failed terminal even though its
    /// output admission is closed. It cannot publish text from a fenced handle.
    pub fn permits_owner_context(&self, scope: &HmiOutputScopeV1) -> Result<bool, HmiError> {
        let state = self.shared.state.lock().map_err(|_| HmiError::Fenced)?;
        Ok(!state.fenced
            && (output_scope(&self.shared, &state) == *scope
                || state
                    .terminal
                    .as_ref()
                    .is_some_and(|event| event.scope == *scope)))
    }
    /// Arm observation before the existing owner dispatches its exact Core client
    /// ID. This performs no admission, authentication, persistence or replay.
    /// The caller must authenticate first and use its original durable ingress.
    /// A duplicate never reopens output, including after interruption.
    pub fn observe_owner_submission(
        &self,
        fence: HmiOwnerAdmissionFenceV1,
        generation: u64,
        sequence: u64,
        client_id: &str,
        text: &str,
    ) -> Result<(), HmiError> {
        let (_, digest) = owner_input(client_id, text)?;
        let mut state = self.shared.state.lock().map_err(|_| HmiError::Fenced)?;
        if state.fenced
            || generation != self.shared.binding.organ_generation
            || fence.connection_id != self.shared.connection_id
            || fence.epoch != state.epoch
        {
            return Err(HmiError::Fenced);
        }
        if state.pending.as_ref() == Some(&(client_id.into(), digest.clone())) {
            return Ok(());
        }
        if sequence == 0 || sequence <= state.sequence {
            return Err(HmiError::Invalid("utterance sequence"));
        }
        if state.pending.is_some() && !terminal_is_known(&state) {
            return Err(HmiError::Busy);
        }
        state.epoch = state.epoch.checked_add(1).ok_or(HmiError::Fenced)?;
        state.sequence = sequence;
        state.pending = Some((client_id.into(), digest));
        state.output_enabled = true;
        state.cancel_requested = false;
        state.queued_id = None;
        state.active_turn = None;
        state.items.clear();
        state.terminal = None;
        state.speech_taken = false;
        Ok(())
    }

    /// Read-only recovery of that external owner's exact ID and canonical text.
    /// Never creates a queue row or opens an output gate on a new connection.
    pub async fn reconcile_owner_submission(
        &self,
        generation: u64,
        client_id: &str,
        text: &str,
    ) -> Result<ThreadQueueReconcileResponse, HmiError> {
        let (input, digest) = owner_input(client_id, text)?;
        {
            let state = self.shared.state.lock().map_err(|_| HmiError::Fenced)?;
            if state.fenced || generation != self.shared.binding.organ_generation {
                return Err(HmiError::Fenced);
            }
        }
        let response: ThreadQueueReconcileResponse = self
            .call(ClientRequest::ThreadQueueReconcile {
                request_id: self.id(),
                params: ThreadQueueReconcileParams {
                    thread_id: self.shared.binding.thread_id.clone(),
                    input: input.clone(),
                    client_user_message_id: client_id.into(),
                    expected_payload_sha256: digest.clone(),
                    mode: ThreadQueueReconcileMode::ReconcileOnly,
                },
            })
            .await?;
        let valid = response.client_user_message_id == client_id
            && response.payload_sha256 == digest
            && match &response.outcome {
                ThreadQueueReconcileOutcome::Queued {
                    queued_submission,
                    created,
                } => {
                    !created
                        && !queued_submission.id.is_empty()
                        && queued_submission.client_user_message_id == client_id
                        && queued_submission.input == input
                }
                ThreadQueueReconcileOutcome::Persisted { turn_id } => !turn_id.is_empty(),
                ThreadQueueReconcileOutcome::Missing | ThreadQueueReconcileOutcome::Cancelled => {
                    true
                }
            };
        if !valid {
            self.revoke()?;
            return Err(HmiError::Identity);
        }
        Ok(response)
    }

    /// Cancel an exact durable owner input after process/connection loss. Close
    /// local presentation before lookup, never arm output or create admission.
    /// The response is reconciliation plus a request acknowledgement; callers
    /// must not describe it as tool rollback or an observed model terminal.
    pub async fn cancel_owner_submission(
        &self,
        generation: u64,
        client_id: &str,
        text: &str,
    ) -> Result<ThreadQueueReconcileResponse, HmiError> {
        self.retire_output_epoch(generation, 0)?;
        // Queue deletion may race the original dispatcher. Reconcile once more
        // with the same ID; an absent/cancelled input is never recreated.
        for _ in 0..2 {
            let response=self.reconcile_owner_submission(generation,client_id,text).await?;
            {
                let state=self.shared.state.lock().map_err(|_|HmiError::Fenced)?;
                if state.fenced || generation!=self.shared.binding.organ_generation {return Err(HmiError::Fenced);}
            }
            match &response.outcome {
                ThreadQueueReconcileOutcome::Persisted {turn_id}=>{
                    self.interrupt_turn(turn_id.clone()).await?;
                    return Ok(response);
                }
                ThreadQueueReconcileOutcome::Queued {queued_submission,..}=>{
                    let _:ThreadQueueDeleteResponse=self.call(ClientRequest::ThreadQueueDelete {
                        request_id:self.id(),params:ThreadQueueDeleteParams {
                            thread_id:self.shared.binding.thread_id.clone(),queued_submission_id:queued_submission.id.clone(),
                        },
                    }).await?;
                }
                ThreadQueueReconcileOutcome::Missing | ThreadQueueReconcileOutcome::Cancelled=>return Ok(response),
            }
        }
        Err(HmiError::Busy)
    }
}
fn owner_input(client_id: &str, text: &str) -> Result<(Vec<UserInput>, String), HmiError> {
    if client_id.is_empty()
        || client_id.len() > 256
        || client_id.chars().any(char::is_control)
        || text.trim().is_empty()
        || text.len() > MAX_TEXT_BYTES
    {
        return Err(HmiError::Invalid("owner input"));
    }
    let input = vec![UserInput::Text {
        text: text.into(),
        text_elements: Vec::new(),
    }];
    let digest = user_input_payload_sha256(
        &input
            .iter()
            .cloned()
            .map(UserInput::into_core)
            .collect::<Vec<_>>(),
    )
    .map_err(|e| HmiError::Protocol(e.to_string()))?;
    Ok((input, digest))
}

#[cfg(test)]
#[path = "hmi_external_tests.rs"]
mod tests;
