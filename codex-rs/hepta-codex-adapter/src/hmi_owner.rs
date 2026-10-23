//! Bidirectional wiring hosted by the existing authenticated channel owner.
//! Ports have no default implementation: config strings are never authentication
//! and no second conversation, observation database or grant issuer is created.
use super::*;

#[derive(Default)]
struct InputState {
    last: Option<(u64, u64, String, u64)>,
}
enum Retirement {
    OutputOnly,
    RevokeCapture,
}
enum OutputMode {
    Speech,
    Text,
}

/// Install inside the current owner. Drain Hepta/media events concurrently with
/// admission futures (as with HmiRequestsV1); this object starts no detached work.
/// One input permit rejects pressure immediately. The existing owner's
/// task set must retain each future/outcome and reconcile ambiguous receipts.
pub struct HmiOwnerBridgeV1<A, M, O> {
    requests: HmiRequestsV1,
    authority: A,
    media: M,
    observations: O,
    input: Mutex<InputState>,
    input_slot: tokio::sync::Semaphore,
    output_mode: OutputMode,
}
impl<A: HmiOwnerAuthorityV1, M: HmiOwnerMediaV1, O: HmiOwnerObservationsV1>
    HmiOwnerBridgeV1<A, M, O>
{
    pub fn attach(
        requests: HmiRequestsV1,
        authority: A,
        media: M,
        observations: O,
    ) -> Result<Self, HmiError> {
        Self::attach_mode(requests, authority, media, observations, OutputMode::Speech)
    }
    /// A text channel has no capture or speech authority. Its existing owner
    /// still supplies live authorization and deterministic local retirement.
    pub fn attach_text(
        requests: HmiRequestsV1,
        authority: A,
        media: M,
        observations: O,
    ) -> Result<Self, HmiError> {
        Self::attach_mode(requests, authority, media, observations, OutputMode::Text)
    }
    fn attach_mode(
        requests: HmiRequestsV1,
        authority: A,
        media: M,
        observations: O,
        output_mode: OutputMode,
    ) -> Result<Self, HmiError> {
        authority.check_current(requests.binding())?;
        if media.connection_id() != requests.connection_id()
            || (matches!(output_mode, OutputMode::Speech) && media.capture_generation() == 0)
        {
            return Err(HmiError::Identity);
        }
        Ok(Self {
            requests,
            authority,
            media,
            observations,
            input: Mutex::new(InputState::default()),
            input_slot: tokio::sync::Semaphore::new(1),
            output_mode,
        })
    }
    fn current(&self) -> Result<(), HmiError> {
        if self.media.connection_id() != self.requests.connection_id() {
            return Err(HmiError::Fenced);
        }
        if self
            .requests
            .shared
            .state
            .lock()
            .map_err(|_| HmiError::Fenced)?
            .fenced
        {
            return Err(HmiError::Fenced);
        }
        self.authority.check_current(self.requests.binding())
    }
    /// Route the current owned JSONL reader back through the same authority,
    /// sourced-observation and Core admission boundaries. Display-only text
    /// never becomes a final observation. Preserve native terminal diagnostics.
    pub async fn route_media_event(&self, event: HmiOwnedMediaEventV1) -> HmiOwnerMediaOutcomeV1 {
        let mut outcome = HmiOwnerMediaOutcomeV1 {
            event,
            input: None,
            interruption: None,
            error: None,
        };
        let result = match &outcome.event {
            HmiOwnedMediaEventV1::FinalTranscript { input } => {
                let routed = self
                    .route_transcript(input.clone(), ThreadQueueReconcileMode::AllowIfAbsent)
                    .await;
                outcome.error = routed.error.clone();
                outcome.input = Some(routed);
                Ok(())
            }
            HmiOwnedMediaEventV1::Interrupt {
                connection_id,
                stream,
                output_epoch,
                local_error,
            } => {
                outcome.error = local_error.clone();
                match self
                    .route_media_interrupt(*connection_id, stream, *output_epoch)
                    .await
                {
                    Ok(interrupt) => {
                        outcome.interruption = Some(interrupt);
                        Ok(())
                    }
                    Err(error) => Err(error),
                }
            }
            HmiOwnedMediaEventV1::Presentation { observation } => {
                match self
                    .current()
                    .and_then(|()| self.requests.permits_output(&observation.scope))
                {
                    Ok(true) => {
                        outcome.error = observation.error.clone();
                        if observation.state == HmiMediaPresentationV1::Unknown
                            || observation.error.is_some()
                        {
                            outcome.error.get_or_insert_with(|| {
                                "media presentation completion unknown".into()
                            });
                            outcome.interruption = Some(self.interrupt().await);
                        }
                        Ok(())
                    }
                    Ok(false) => Err(HmiError::Fenced),
                    Err(error) => Err(error),
                }
            }
            HmiOwnedMediaEventV1::DisplayTranscript { .. } => Ok(()),
            HmiOwnedMediaEventV1::Terminal { connection_id, .. } => {
                if *connection_id != self.requests.connection_id() {
                    Err(HmiError::Fenced)
                } else {
                    outcome.interruption = Some(self.revoke().await);
                    Ok(())
                }
            }
        };
        if let Err(error) = result {
            outcome.error = Some(error.to_string());
            if self.current().is_err() {
                outcome.interruption = Some(self.revoke().await);
            }
        }
        outcome
    }
    /// Local retirement is awaited before the Hepta interrupt RPC. Local failure
    /// never suppresses the remote request; neither outcome rolls back tools.
    pub async fn interrupt(&self) -> HmiOwnerInterruptV1 {
        self.retire(Retirement::OutputOnly, 0).await
    }
    /// Wired to the existing owner's permission-revocation/emergency boundary.
    /// Capture privacy and stop controls are deterministic and never learned.
    pub async fn revoke(&self) -> HmiOwnerInterruptV1 {
        self.retire(Retirement::RevokeCapture, 0).await
    }
    /// For an event from the current owned media reader. A late reader from an
    /// earlier connection cannot stop or submit work on the new incarnation.
    pub async fn route_media_interrupt(
        &self,
        connection_id: u64,
        stream: &HmiCaptureStreamV1,
        output_epoch: u64,
    ) -> Result<HmiOwnerInterruptV1, HmiError> {
        let binding = self.requests.binding();
        if connection_id != self.requests.connection_id()
            || stream.principal_id != binding.principal_id
            || stream.device_id != binding.device_id
            || stream.device_generation != binding.device_generation
            || stream.organ_id != binding.organ_id
            || stream.organ_generation != binding.organ_generation
            || stream.logical_session_id != binding.logical_session_id
            || output_epoch == 0
        {
            return Err(HmiError::Identity);
        }
        {
            let state = self
                .requests
                .shared
                .state
                .lock()
                .map_err(|_| HmiError::Fenced)?;
            if output_epoch < state.epoch || (output_epoch == state.epoch && state.output_enabled) {
                return Err(HmiError::Fenced);
            }
        }
        Ok(self.retire(Retirement::OutputOnly, output_epoch).await)
    }
    async fn retire(&self, policy: Retirement, minimum_epoch: u64) -> HmiOwnerInterruptV1 {
        let fenced = self
            .requests
            .retire_output_epoch(self.requests.binding().organ_generation, minimum_epoch);
        let scope = match &fenced {
            Ok(scope) => scope.clone(),
            Err(_) => output_scope(
                &self.requests.shared,
                &self
                    .requests
                    .shared
                    .state
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner),
            ),
        };
        let epoch = scope.output_epoch;
        let local_stop_error = self
            .media
            .retire_output(epoch)
            .await
            .err()
            .map(|e| e.to_string());
        let capture_stop_error = match policy {
            Retirement::OutputOnly => None,
            Retirement::RevokeCapture => self
                .media
                .revoke_capture()
                .await
                .err()
                .map(|e| e.to_string()),
        };
        let remote_interrupt_error = match fenced {
            Ok(_) => self
                .requests
                .interrupt_retired(epoch)
                .await
                .err()
                .map(|e| e.to_string()),
            Err(error) => Some(error.to_string()),
        };
        HmiOwnerInterruptV1 {
            scope,
            local_stop_error,
            remote_interrupt_error,
            capture_stop_error,
            terminal_observed: false,
        }
    }

    /// Forward only current owner-issued turns and one completed utterance.
    /// Deltas remain UI observations. All errors retain the original event and
    /// both local/remote interruption diagnostics rather than an empty summary.
    pub async fn route_output(&self, event: HmiEventV1) -> HmiOwnerOutputOutcomeV1 {
        let is_current_scope = self
            .requests
            .shared
            .state
            .lock()
            .is_ok_and(|state| event.scope == output_scope(&self.requests.shared, &state));
        if !is_current_scope {
            return HmiOwnerOutputOutcomeV1 {
                event,
                presentation: None,
                error: Some(HmiError::Fenced.to_string()),
                interruption: None,
            };
        }
        if let Err(error) = self.current() {
            return HmiOwnerOutputOutcomeV1 {
                event,
                presentation: None,
                error: Some(error.to_string()),
                interruption: Some(self.revoke().await),
            };
        }
        let result = async {
            match &event.kind {
                HmiEventKindV1::TurnStarted => {
                    if !self.requests.permits_output(&event.scope)? {
                        return Err(HmiError::Fenced);
                    }
                    self.media.attach_turn(&event.scope).await?;
                    Ok(None)
                }
                HmiEventKindV1::TextDelta { .. } | HmiEventKindV1::TextFinal { .. } => Ok(None),
                HmiEventKindV1::Terminal { outcome } => {
                    if self.requests.terminal_snapshot()?.as_ref() != Some(&event) {
                        return Err(HmiError::Identity);
                    }
                    if outcome.status != HmiTerminalStatusV1::Completed {
                        return Err(HmiError::Fenced);
                    }
                    if matches!(self.output_mode, OutputMode::Text) {
                        return Ok(None);
                    }
                    let Some(request) = self
                        .requests
                        .take_completed_speech(self.requests.binding().organ_generation)?
                    else {
                        return Ok(None);
                    };
                    self.current()?;
                    if !self.requests.permits_output(&event.scope)? {
                        return Err(HmiError::Fenced);
                    }
                    self.media.speak(request).await.map(Some)
                }
            }
        }
        .await;
        let (presentation, error, interruption) = match result {
            Ok(value) => (value, None, None),
            Err(error) => (None, Some(error.to_string()), Some(self.interrupt().await)),
        };
        HmiOwnerOutputOutcomeV1 {
            event,
            presentation,
            error,
            interruption,
        }
    }

    /// A source reference alone is not a user observation. Re-read/verify the
    /// controlled media, obtain the existing owner's matching observation receipt,
    /// recheck current authority, then use the same Core thread/queue identity.
    /// Failures retain the source/text and any already committed observation.
    pub async fn route_transcript(
        &self,
        input: HmiOwnerTranscriptV1,
        mode: ThreadQueueReconcileMode,
    ) -> HmiOwnerInputOutcomeV1 {
        let mut outcome = HmiOwnerInputOutcomeV1 {
            input,
            client_message_id: None,
            observation: None,
            admission: None,
            stage: "validate".into(),
            error: None,
            interruption: None,
        };
        let result: Result<(), HmiError> = async {
            self.current()?;
            let source = &outcome.input.source;
            let binding = self.requests.binding();
            let stream = &source.stream;
            if !outcome.input.finalized
                || outcome.input.text.trim().is_empty()
                || outcome.input.text.len() > MAX_TEXT_BYTES
                || outcome.input.connection_id != self.requests.connection_id()
                || stream.principal_id != binding.principal_id
                || stream.device_id != binding.device_id
                || stream.device_generation != binding.device_generation
                || stream.organ_id != binding.organ_id
                || stream.organ_generation != binding.organ_generation
                || stream.logical_session_id != binding.logical_session_id
                || source.capture_generation == 0
                || source.sequence == 0
                || source.sample_rate != 16_000
                || source.num_channels != 1
                || source.byte_length == 0
                || source.byte_length > 2 * 1024 * 1024
                || !source.byte_length.is_multiple_of(2)
                || source.start_sample != 0
                || source.end_sample != source.byte_length / 2
                || source.sha256.len() != 64
                || !source
                    .sha256
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
                || source.asset_id
                    != format!(
                        "capture-{}-{}.pcm16",
                        source.capture_generation, source.sequence
                    )
                || (mode == ThreadQueueReconcileMode::AllowIfAbsent
                    && source.capture_generation != self.media.capture_generation())
            {
                return Err(HmiError::Identity);
            }
            let _permit = self.input_slot.try_acquire().map_err(|_| HmiError::Busy)?;
            let previous = self
                .input
                .lock()
                .map_err(|_| HmiError::Fenced)?
                .last
                .clone();
            let digest = outcome.input.payload_sha256()?;
            let key = (source.capture_generation, source.sequence);
            let repeated = previous
                .as_ref()
                .is_some_and(|(generation, sequence, _, _)| (*generation, *sequence) == key);
            if let Some((generation, sequence, prior_digest, _)) = &previous {
                if repeated && prior_digest != &digest {
                    return Err(HmiError::Identity);
                }
                if mode == ThreadQueueReconcileMode::AllowIfAbsent && key < (*generation, *sequence)
                {
                    return Err(HmiError::Fenced);
                }
            }
            let request_id = format!(
                "capture:{}:{}:{}:{}",
                stream.device_generation,
                stream.organ_generation,
                source.capture_generation,
                source.sequence
            );
            let client_id = self.requests.client_message_id(&request_id)?;
            outcome.client_message_id = Some(client_id.clone());
            let effective_mode = if repeated {
                ThreadQueueReconcileMode::ReconcileOnly
            } else {
                mode
            };
            let mut hepta_sequence = if repeated {
                previous.as_ref().map_or(0, |entry| entry.3)
            } else {
                0
            };
            if effective_mode == ThreadQueueReconcileMode::AllowIfAbsent {
                let state = self
                    .requests
                    .shared
                    .state
                    .lock()
                    .map_err(|_| HmiError::Fenced)?;
                if state.pending.is_some() && !terminal_is_known(&state) {
                    return Err(HmiError::Busy);
                }
                hepta_sequence = state.sequence.checked_add(1).ok_or(HmiError::Fenced)?;
            }
            outcome.stage = "verifyMedia".into();
            self.media.verify_source(source).await?;
            self.current()?;
            self.input.lock().map_err(|_| HmiError::Fenced)?.last =
                Some((key.0, key.1, digest.clone(), hepta_sequence));
            outcome.stage = "observeFinal".into();
            let receipt = self
                .observations
                .observe_final(binding, &outcome.input, &client_id, &digest, effective_mode)
                .await?;
            let receipt_matches = receipt.payload_sha256 == digest
                && !receipt.observation_id.is_empty()
                && receipt.observation_id.len() <= 256
                && !receipt.observation_id.chars().any(char::is_control);
            outcome.observation = Some(receipt);
            if !receipt_matches {
                return Err(HmiError::Identity);
            }
            self.current()?;
            outcome.stage = "coreAdmission".into();
            outcome.admission = Some(
                self.requests
                    .submit_text(
                        binding.organ_generation,
                        hepta_sequence,
                        &request_id,
                        &outcome.input.text,
                        effective_mode,
                    )
                    .await?,
            );
            Ok(())
        }
        .await;
        if let Err(error) = result {
            outcome.error = Some(error.to_string().chars().take(4096).collect());
            if self.current().is_err() {
                outcome.interruption = Some(self.revoke().await);
            }
        }
        outcome
    }
}

#[cfg(test)]
#[path = "hmi_owner_tests.rs"]
mod tests;
