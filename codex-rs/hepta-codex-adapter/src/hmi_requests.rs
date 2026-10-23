use super::*;

impl HmiRequestsV1 {
    pub(super) fn id(&self) -> RequestId {
        RequestId::Integer(self.shared.request_id.fetch_add(1, Ordering::Relaxed))
    }

    pub(super) async fn call<T: serde::de::DeserializeOwned>(
        &self,
        request: ClientRequest,
    ) -> Result<T, HmiError> {
        tokio::time::timeout(self.shared.timeout, self.handle.request_typed(request))
            .await
            .map_err(|_| HmiError::Deadline)?
            .map_err(|error| HmiError::Transport(error.to_string()))
    }

    /// Stable across connection/Agentd restarts; process generation is deliberately
    /// excluded so recovering one utterance cannot mint a second Core admission.
    pub fn client_message_id(&self, request_id: &str) -> Result<String, HmiError> {
        if request_id.is_empty() || request_id.len() > 256 {
            return Err(HmiError::Invalid("request id"));
        }
        let encoded = serde_json::to_vec(&(
            "hepta.hmi.message.v1",
            &self.shared.binding.principal_id,
            &self.shared.binding.device_id,
            &self.shared.binding.logical_session_id,
            request_id,
        ))
        .map_err(|error| HmiError::Protocol(error.to_string()))?;
        Ok(format!("hepta.hmi:{}", Digest32::of_bytes(&encoded)))
    }

    /// Core queue/rollout is the sole persistent dedupe authority. ReconcileOnly
    /// never opens a presentation gate or creates a replacement request.
    pub async fn submit_text(
        &self,
        current_generation: u64,
        sequence: u64,
        request_id: &str,
        text: &str,
        mode: ThreadQueueReconcileMode,
    ) -> Result<ThreadQueueReconcileResponse, HmiError> {
        if text.trim().is_empty() || text.len() > MAX_TEXT_BYTES {
            return Err(HmiError::Invalid("text"));
        }
        let client_id = self.client_message_id(request_id)?;
        let input = vec![UserInput::Text {
            text: text.to_string(),
            text_elements: Vec::new(),
        }];
        let core_input = input
            .iter()
            .cloned()
            .map(UserInput::into_core)
            .collect::<Vec<_>>();
        let digest = user_input_payload_sha256(&core_input)
            .map_err(|error| HmiError::Protocol(error.to_string()))?;
        {
            let mut state = self.shared.state.lock().map_err(|_| HmiError::Fenced)?;
            if state.fenced || current_generation != self.shared.binding.organ_generation {
                return Err(HmiError::Fenced);
            }
            if mode == ThreadQueueReconcileMode::AllowIfAbsent {
                let identical =
                    state.pending.as_ref() == Some(&(client_id.clone(), digest.clone()));
                if sequence == 0
                    || sequence < state.sequence
                    || (sequence == state.sequence && !identical)
                {
                    return Err(HmiError::Invalid("utterance sequence"));
                }
                let terminal_known = terminal_is_known(&state);
                if !identical && state.pending.is_some() && !terminal_known {
                    return Err(HmiError::Busy);
                }
                if !identical {
                    state.epoch = state.epoch.checked_add(1).ok_or(HmiError::Fenced)?;
                    state.output_enabled = true;
                    state.cancel_requested = false;
                    state.queued_id = None;
                    state.sequence = sequence;
                    state.pending = Some((client_id.clone(), digest.clone()));
                    state.active_turn = None;
                    state.items.clear();
                    state.terminal = None;
                }
            }
        }
        let response: Result<ThreadQueueReconcileResponse, HmiError> = self
            .call(ClientRequest::ThreadQueueReconcile {
                request_id: self.id(),
                params: ThreadQueueReconcileParams {
                    thread_id: self.shared.binding.thread_id.clone(),
                    input: input.clone(),
                    client_user_message_id: client_id.clone(),
                    expected_payload_sha256: digest.clone(),
                    mode,
                },
            })
            .await;
        let response = match response {
            Ok(response) => response,
            Err(error) => {
                let mut state = self.shared.state.lock().map_err(|_| HmiError::Fenced)?;
                if state.sequence != sequence
                    || state.pending.as_ref() != Some(&(client_id.clone(), digest.clone()))
                    || terminal_is_known(&state)
                {
                    return Err(error);
                }
                state.output_enabled = false;
                let scope = output_scope(&self.shared, &state);
                terminal(
                    &mut state,
                    scope,
                    HmiTerminalStatusV1::Unknown,
                    Some(error.to_string()),
                );
                return Err(error);
            }
        };
        let valid = response.client_user_message_id == client_id
            && response.payload_sha256 == digest
            && match &response.outcome {
                ThreadQueueReconcileOutcome::Queued {
                    queued_submission, ..
                } => {
                    !queued_submission.id.is_empty()
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
        let cancel = {
            let mut state = self.shared.state.lock().map_err(|_| HmiError::Fenced)?;
            if state.sequence != sequence
                || state.pending.as_ref() != Some(&(client_id.clone(), digest.clone()))
            {
                return Ok(response);
            }
            if state.fenced {
                return Err(HmiError::Fenced);
            }
            if let ThreadQueueReconcileOutcome::Queued {
                queued_submission, ..
            } = &response.outcome
            {
                state.queued_id = Some(queued_submission.id.clone());
            }
            state.cancel_requested
        };
        if cancel {
            self.cancel_admission(&response.outcome).await?;
        }
        Ok(response)
    }

    /// Synchronous media fence. Call before awaiting turn/interrupt; it does not
    /// claim that any already-dispatched tool effect has been undone.
    pub fn stop_output(&self, current_generation: u64) -> Result<Option<String>, HmiError> {
        let mut state = self.shared.state.lock().map_err(|_| HmiError::Fenced)?;
        if state.fenced || current_generation != self.shared.binding.organ_generation {
            return Err(HmiError::Fenced);
        }
        state.epoch = state.epoch.checked_add(1).ok_or(HmiError::Fenced)?;
        let turn = state.active_turn.clone();
        state.cancel_requested = true;
        state.output_enabled = false;
        Ok(turn)
    }

    pub async fn interrupt(&self, current_generation: u64) -> Result<(), HmiError> {
        let turn = self.stop_output(current_generation)?;
        if let Some(turn_id) = turn {
            return self.interrupt_turn(turn_id).await;
        }
        let queued = self
            .shared
            .state
            .lock()
            .map_err(|_| HmiError::Fenced)?
            .queued_id
            .clone();
        if let Some(queued_submission_id) = queued {
            self.cancel_queued(queued_submission_id).await?;
        }
        // If admission has no answer yet, its completion or a matching late
        // ItemStarted performs the interrupt. This is not a terminal receipt.
        Ok(())
    }

    async fn cancel_admission(
        &self,
        outcome: &ThreadQueueReconcileOutcome,
    ) -> Result<(), HmiError> {
        match outcome {
            ThreadQueueReconcileOutcome::Queued {
                queued_submission, ..
            } => self.cancel_queued(queued_submission.id.clone()).await,
            ThreadQueueReconcileOutcome::Persisted { turn_id } => {
                self.interrupt_turn(turn_id.clone()).await
            }
            ThreadQueueReconcileOutcome::Missing | ThreadQueueReconcileOutcome::Cancelled => Ok(()),
        }
    }

    async fn cancel_queued(&self, queued_submission_id: String) -> Result<(), HmiError> {
        let (sequence, pending) = {
            let state = self.shared.state.lock().map_err(|_| HmiError::Fenced)?;
            if state.queued_id.as_ref() != Some(&queued_submission_id) {
                return Ok(());
            }
            (state.sequence, state.pending.clone())
        };
        let expected_queue = queued_submission_id.clone();
        let response: ThreadQueueDeleteResponse = self
            .call(ClientRequest::ThreadQueueDelete {
                request_id: self.id(),
                params: ThreadQueueDeleteParams {
                    thread_id: self.shared.binding.thread_id.clone(),
                    queued_submission_id,
                },
            })
            .await?;
        if response.deleted {
            let mut state = self.shared.state.lock().map_err(|_| HmiError::Fenced)?;
            if state.sequence != sequence
                || state.pending != pending
                || state.queued_id.as_ref() != Some(&expected_queue)
            {
                return Ok(());
            }
            let scope = output_scope(&self.shared, &state);
            terminal(&mut state, scope, HmiTerminalStatusV1::Interrupted, None);
        }
        Ok(())
    }

    pub(super) async fn interrupt_turn(&self, turn_id: String) -> Result<(), HmiError> {
        let response = tokio::time::timeout(
            self.shared.timeout,
            self.handle
                .request_typed::<TurnInterruptResponse>(ClientRequest::TurnInterrupt {
                    request_id: self.id(),
                    params: TurnInterruptParams {
                        thread_id: self.shared.binding.thread_id.clone(),
                        turn_id,
                    },
                }),
        )
        .await
        .map_err(|_| HmiError::Deadline)?;
        match response {
            Ok(_) => Ok(()),
            Err(TypedRequestError::Server { method, source })
                if method == "turn/interrupt"
                    && source.code == -32_600
                    && source.data.is_none()
                    && source.message == "no active turn to interrupt" =>
            {
                Ok(())
            }
            Err(error) => Err(HmiError::Transport(error.to_string())),
        }
    }

    pub fn revoke(&self) -> Result<(), HmiError> {
        let mut state = self.shared.state.lock().map_err(|_| HmiError::Fenced)?;
        state.fenced = true;
        state.epoch = state.epoch.checked_add(1).ok_or(HmiError::Fenced)?;
        Ok(())
    }

    pub fn binding(&self) -> &HmiBindingV1 {
        &self.shared.binding
    }

    /// Check again at the actual output boundary; queued frames from old
    /// connections, generations, turns or output epochs must be discarded.
    pub fn permits_output(&self, scope: &HmiOutputScopeV1) -> Result<bool, HmiError> {
        let state = self.shared.state.lock().map_err(|_| HmiError::Fenced)?;
        Ok(!state.fenced
            && state.output_enabled
            && state.active_turn.is_some()
            && scope.principal_id == self.shared.binding.principal_id
            && scope.device_id == self.shared.binding.device_id
            && scope.device_generation == self.shared.binding.device_generation
            && scope.organ_id == self.shared.binding.organ_id
            && scope.logical_session_id == self.shared.binding.logical_session_id
            && scope.utterance_sequence == state.sequence
            && scope.utterance_id.as_ref()
                == state.pending.as_ref().map(|(client_id, _)| client_id)
            && scope.organ_generation == self.shared.binding.organ_generation
            && scope.connection_id == self.shared.connection_id
            && scope.output_epoch == state.epoch
            && scope.turn_id == state.active_turn)
    }

    pub fn terminal_snapshot(&self) -> Result<Option<HmiEventV1>, HmiError> {
        Ok(self
            .shared
            .state
            .lock()
            .map_err(|_| HmiError::Fenced)?
            .terminal
            .clone())
    }
}
