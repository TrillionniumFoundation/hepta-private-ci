impl NativeJournal {
    pub(super) fn replay(&mut self, json: &str) -> Result<(), Error> {
        let event =
            serde_json::from_str(json).map_err(|_| Error::CorruptJournal("native decode"))?;
        self.apply(event)
    }

    fn apply(&mut self, event: Event) -> Result<(), Error> {
        if let Event::Reserve {
            request,
            maximum_in_flight,
        } = event
        {
            validate_identity(&request.request_id, "native request")?;
            validate_identity(&request.principal_id, "native principal")?;
            validate_digest(&request.payload_digest, "native payload")?;
            if request.worker_generation == 0
                || request.model.is_empty()
                || request.model.len() > 256
            {
                return Err(Error::InvalidIdentity("native worker/model"));
            }
            if !(1..=256).contains(&maximum_in_flight) {
                return Err(Error::CapacityExceeded);
            }
            if self
                .maximum_in_flight
                .is_some_and(|limit| limit != maximum_in_flight)
                || self.records.contains_key(&request.request_id)
            {
                return Err(Error::Conflict);
            }
            if self
                .records
                .values()
                .filter(|record| record.state != NativeReservationState::Released)
                .count()
                >= maximum_in_flight
            {
                return Err(Error::CapacityExceeded);
            }
            self.maximum_in_flight = Some(maximum_in_flight);
            self.records.insert(
                request.request_id.clone(),
                NativeRunRecord {
                    schema_version: NATIVE_RECORD_SCHEMA_VERSION,
                    request,
                    revision: 1,
                    state: NativeReservationState::Reserved,
                    dispatch: None,
                    turn_id: None,
                    cancel_requested: false,
                    pre_dispatch_stop: None,
                    dispatch_rejection: None,
                    observation: None,
                    observed_usage_units: None,
                    first_indeterminate_at_unix_ms: None,
                    last_observed_at_unix_ms: None,
                    effect_entered_at_unix_ms: None,
                    authority_observation: None,
                    interrupt_observation: None,
                    usage_authority: NativeUsageAuthority::Unknown,
                    resource_attestation_digest: None,
                    terminal_evidence_digest: None,
                    quarantine_reason: None,
                    generation_fence_identity: None,
                    capacity_release_evidence: None,
                },
            );
            return Ok(());
        }

        let id = event
            .request_id()
            .ok_or(Error::InvalidTransition)?
            .to_string();
        let record = self.records.get_mut(&id).ok_or(Error::RequestNotFound)?;
        match event {
            Event::Reserve { .. } => return Err(Error::InvalidTransition),
            Event::Dispatch { dispatch, .. } => apply_dispatch(record, dispatch)?,
            Event::Started { turn_id, .. } => apply_started(record, turn_id, None)?,
            Event::StartedAt {
                turn_id,
                effect_entered_at_unix_ms,
                ..
            } => apply_started(record, turn_id, Some(effect_entered_at_unix_ms))?,
            Event::RejectBeforeStart { rejection, .. } => {
                apply_dispatch_rejection(record, rejection)?
            }
            Event::Cancel { .. } => {
                if record.state == NativeReservationState::Released
                    || record.state == NativeReservationState::Reserved
                {
                    return Err(Error::InvalidTransition);
                }
                record.cancel_requested = true;
                record.state = NativeReservationState::Cancelling;
            }
            Event::Stop { reason, .. } => apply_safe_stop(record, reason, false)?,
            Event::AbortBeforeEffect { reason, .. } => apply_safe_stop(record, reason, true)?,
            Event::Observe {
                output,
                observed_at_unix_ms,
                usage_units,
                ..
            } => {
                let evidence = NativeObservationEvidence {
                    observed_at_unix_ms,
                    usage_units,
                    usage_authority: if usage_units.is_some() {
                        NativeUsageAuthority::DriverObserved
                    } else {
                        NativeUsageAuthority::Unknown
                    },
                    terminal_evidence_digest: output
                        .codex_terminal_correlation_digest
                        .clone(),
                    quarantine_reason: (output.boundary_status
                        == NativeBoundaryStatus::Quarantined)
                        .then(|| output.stop_reason.clone())
                        .flatten(),
                    ..NativeObservationEvidence::default()
                };
                apply_observation(record, output, evidence)?;
            }
            Event::ObserveV2 {
                output, evidence, ..
            } => apply_observation(record, output, evidence)?,
            Event::AuthorityObserved { observation, .. } => {
                apply_authority_observation(record, observation)?
            }
            Event::InterruptIntent { observation, .. } => {
                apply_interrupt_intent(record, observation)?
            }
            Event::InterruptOutcome { observation, .. } => {
                apply_interrupt_outcome(record, observation)?
            }
            Event::ReleaseQuarantine { evidence, .. } => {
                apply_quarantine_release(record, evidence)?
            }
        }
        record.schema_version = NATIVE_RECORD_SCHEMA_VERSION;
        record.revision = record
            .revision
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;
        Ok(())
    }
}

impl Event {
    fn request_id(&self) -> Option<&str> {
        match self {
            Self::Reserve { .. } => None,
            Self::Dispatch { request_id, .. }
            | Self::Started { request_id, .. }
            | Self::StartedAt { request_id, .. }
            | Self::RejectBeforeStart { request_id, .. }
            | Self::Cancel { request_id }
            | Self::Stop { request_id, .. }
            | Self::AbortBeforeEffect { request_id, .. }
            | Self::Observe { request_id, .. }
            | Self::ObserveV2 { request_id, .. }
            | Self::AuthorityObserved { request_id, .. }
            | Self::InterruptIntent { request_id, .. }
            | Self::InterruptOutcome { request_id, .. }
            | Self::ReleaseQuarantine { request_id, .. } => Some(request_id),
        }
    }
}
