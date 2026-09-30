impl NativeJournal {
    pub(super) fn replay(&mut self, json: &str) -> Result<(), Error> {
        let event =
            serde_json::from_str(json).map_err(|_| Error::CorruptJournal("native decode"))?;
        self.apply(event)
    }

    fn apply(&mut self, event: Event) -> Result<(), Error> {
        if let Event::CheckpointReference {
            generation,
            checkpoint_path,
            checkpoint_digest,
            archive_segment_digest,
            archive_chain_digest,
        } = event
        {
            return self.apply_checkpoint_reference(
                generation,
                &checkpoint_path,
                &checkpoint_digest,
                &archive_segment_digest,
                &archive_chain_digest,
            );
        }
        if let Event::Reserve {
            request,
            maximum_in_flight,
        } = event
        {
            validate_native_request(&request)?;
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
                    request,
                    revision: 1,
                    state: NativeReservationState::Reserved,
                    dispatch: None,
                    turn_id: None,
                    cancel_requested: false,
                    pre_dispatch_stop: None,
                    dispatch_rejection: None,
                    observation: None,
                    execution_binding: None,
                    protected_output: None,
                    reconciliation: None,
                    retirement: None,
                },
            );
            return Ok(());
        }
        let id = match &event {
            Event::Reserve { .. } | Event::CheckpointReference { .. } => {
                return Err(Error::InvalidTransition);
            }
            Event::BindExecution { request_id, .. }
            | Event::Dispatch { request_id, .. }
            | Event::Started { request_id, .. }
            | Event::RejectBeforeStart { request_id, .. }
            | Event::Cancel { request_id }
            | Event::Stop { request_id, .. }
            | Event::AbortBeforeEffect { request_id, .. }
            | Event::Observe { request_id, .. }
            | Event::Reconcile { request_id, .. }
            | Event::Retire { request_id, .. } => request_id,
        };
        let record = self.records.get_mut(id).ok_or(Error::RequestNotFound)?;
        match event {
            Event::Reserve { .. } | Event::CheckpointReference { .. } => {
                return Err(Error::InvalidTransition);
            }
            Event::BindExecution { binding, .. } => {
                if record.state != NativeReservationState::Reserved
                    || record.execution_binding.is_some()
                {
                    return Err(Error::InvalidTransition);
                }
                validate_execution_binding(record, &binding)?;
                record.execution_binding = Some(binding);
            }
            Event::Dispatch { dispatch, .. } => {
                if record.state != NativeReservationState::Reserved {
                    return Err(Error::InvalidTransition);
                }
                validate_dispatch(&dispatch)?;
                if let Some(binding) = &record.execution_binding
                    && dispatch.model_provider != binding.provider_id
                {
                    return Err(Error::AssignmentMismatch);
                }
                record.dispatch = Some(dispatch);
                record.state = NativeReservationState::Dispatching;
            }
            Event::Started { turn_id, .. } => {
                if record.state != NativeReservationState::Dispatching
                    || record.dispatch_rejection.is_some()
                {
                    return Err(Error::InvalidTransition);
                }
                validate_identity(&turn_id, "native turn")?;
                record.turn_id = Some(turn_id);
                record.state = NativeReservationState::Running;
            }
            Event::RejectBeforeStart { rejection, .. } => {
                if record.state != NativeReservationState::Dispatching
                    || record.turn_id.is_some()
                    || record.observation.is_some()
                    || rejection.reason.is_empty()
                    || rejection.reason.len() > 4096
                {
                    return Err(Error::InvalidTransition);
                }
                validate_digest(&rejection.response_digest, "native dispatch rejection")?;
                if rejection.retry_safe_before_admission
                    && !matches!(
                        rejection.status,
                        NativeDispatchRejectionStatus::Overloaded
                            | NativeDispatchRejectionStatus::Unavailable
                    )
                {
                    return Err(Error::InvalidTransition);
                }
                let safe_before_admission = rejection.retry_safe_before_admission;
                record.dispatch_rejection = Some(rejection);
                record.state = if safe_before_admission {
                    NativeReservationState::Released
                } else {
                    NativeReservationState::Indeterminate
                };
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
            Event::Stop { reason, .. } => {
                if record.state != NativeReservationState::Reserved
                    || record.turn_id.is_some()
                    || reason.is_empty()
                    || reason.len() > 4096
                {
                    return Err(Error::InvalidTransition);
                }
                record.pre_dispatch_stop = Some(reason);
                record.state = NativeReservationState::Released;
            }
            Event::AbortBeforeEffect { reason, .. } => {
                if record.state != NativeReservationState::Dispatching
                    || record.turn_id.is_some()
                    || record.observation.is_some()
                    || record.dispatch_rejection.is_some()
                    || record.cancel_requested
                    || reason.is_empty()
                    || reason.len() > 4096
                {
                    return Err(Error::InvalidTransition);
                }
                record.pre_dispatch_stop = Some(reason);
                record.state = NativeReservationState::Released;
            }
            Event::Observe {
                output,
                protected_output,
                ..
            } => {
                if record.dispatch_rejection.is_some()
                    || record.pre_dispatch_stop.is_some()
                    || record.retirement.is_some()
                {
                    return Err(Error::InvalidTransition);
                }
                if let Some(protected) = &protected_output {
                    let marker = protected
                        .journal_marker()
                        .map_err(|_| Error::InvalidIdentity("native protected output"))?;
                    if output.output != marker {
                        return Err(Error::AssignmentMismatch);
                    }
                } else if record.execution_binding.is_some()
                    && (!output.output.is_empty() || output.terminal_observed)
                {
                    return Err(Error::InvalidIdentity("native protected output"));
                }
                apply_observation(record, output, /*reconciliation*/ None)?;
                record.protected_output = protected_output;
            }
            Event::Reconcile { output, audit, .. } => {
                if !matches!(
                    record.state,
                    NativeReservationState::Dispatching
                        | NativeReservationState::Running
                        | NativeReservationState::Cancelling
                        | NativeReservationState::Indeterminate
                        | NativeReservationState::Released
                ) || record.execution_binding.is_none()
                    || record.dispatch_rejection.is_some()
                    || record.pre_dispatch_stop.is_some()
                    || record.retirement.is_some()
                    || (record.state == NativeReservationState::Released
                        && record.reconciliation.is_none())
                {
                    return Err(Error::InvalidTransition);
                }
                let expected_output = audit
                    .output_digest
                    .as_ref()
                    .map(|digest| format!("hepta-reconciled-output-v1:{digest}"))
                    .unwrap_or_default();
                if !output.terminal_observed
                    || output.codex_terminal_correlation_digest.as_ref()
                        != Some(&audit.receipt_digest)
                    || output.output != expected_output
                    || (output.status == NativeRunStatus::Completed
                        && audit.output_digest.is_none())
                {
                    return Err(Error::InvalidIdentity(
                        "native reconciliation observation binding",
                    ));
                }
                validate_digest(&audit.receipt_digest, "native reconciliation receipt")?;
                validate_identity(&audit.authenticated_key_id, "native reconciliation key")?;
                if audit.terminal_sequence == 0 {
                    return Err(Error::InvalidIdentity(
                        "native reconciliation terminal sequence",
                    ));
                }
                if let Some(digest) = &audit.output_digest {
                    validate_digest(digest, "native reconciliation output")?;
                }
                if let Some(previous) = &record.reconciliation
                    && (audit.terminal_sequence <= previous.terminal_sequence
                        || previous.usage_microunits.is_some_and(|usage| {
                            audit.usage_microunits.is_none_or(|next| next < usage)
                        }))
                {
                    return Err(Error::Conflict);
                }
                if let Some(protected) = &record.protected_output {
                    // Earlier partial output may have a different digest from
                    // the final receipt, but its retained metadata must be valid.
                    protected
                        .journal_marker()
                        .map_err(|_| Error::InvalidIdentity("native protected output"))?;
                }
                apply_observation(record, output, Some(&audit))?;
                record.reconciliation = Some(audit);
            }
            Event::Retire { audit, .. } => {
                if record.state != NativeReservationState::Indeterminate
                    || record
                        .retirement
                        .as_ref()
                        .is_some_and(|previous| previous.independent_operator_key_digests.is_some())
                    || audit.reason.is_empty()
                    || audit.reason.len() > 4096
                {
                    return Err(Error::InvalidTransition);
                }
                validate_digest(&audit.retirement_digest, "native retirement")?;
                validate_identity(&audit.operator_ids[0], "native retirement operator")?;
                validate_identity(&audit.operator_ids[1], "native retirement operator")?;
                validate_identity(&audit.key_ids[0], "native retirement key")?;
                validate_identity(&audit.key_ids[1], "native retirement key")?;
                if audit.operator_ids[0] == audit.operator_ids[1]
                    || audit.key_ids[0] == audit.key_ids[1]
                {
                    return Err(Error::InvalidTransition);
                }
                record.state = if let Some(keys) = &audit.independent_operator_key_digests {
                    validate_digest(&keys[0], "native retirement verifying key")?;
                    validate_digest(&keys[1], "native retirement verifying key")?;
                    if keys[0] == keys[1] {
                        return Err(Error::InvalidTransition);
                    }
                    NativeReservationState::Released
                } else {
                    // Legacy key IDs alone cannot prove independent operators.
                    NativeReservationState::Indeterminate
                };
                record.retirement = Some(audit);
            }
        }
        record.revision = record
            .revision
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;
        Ok(())
    }

    fn apply_checkpoint_reference(
        &mut self,
        generation: u64,
        checkpoint_path: &str,
        checkpoint_digest: &str,
        archive_segment_digest: &str,
        archive_chain_digest: &str,
    ) -> Result<(), Error> {
        if generation == 0
            || generation <= self.checkpoint_generation
            || !self.records.is_empty()
            || self.maximum_in_flight.is_some()
            || !Path::new(checkpoint_path).is_absolute()
        {
            return Err(Error::CorruptJournal("native checkpoint generation"));
        }
        validate_digest(checkpoint_digest, "native checkpoint")?;
        validate_digest(archive_segment_digest, "native archive segment")?;
        validate_digest(archive_chain_digest, "native archive chain")?;
        let path = Path::new(checkpoint_path);
        if path
            .file_name()
            .and_then(|name| name.to_str())
            .is_none_or(|name| name != format!("{checkpoint_digest}.json"))
        {
            return Err(Error::CorruptJournal("native checkpoint path"));
        }
        let metadata = fs::metadata(path)?;
        if metadata.len() > MAX_CHECKPOINT_BYTES {
            return Err(Error::CapacityExceeded);
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if metadata.permissions().mode() & 0o077 != 0 {
                return Err(Error::CorruptJournal("native checkpoint permissions"));
            }
        }
        let bytes = read_bounded(path, MAX_CHECKPOINT_BYTES)?;
        if sha256_hex(b"hepta.inference-control.checkpoint.v1\0", &bytes) != checkpoint_digest {
            return Err(Error::CorruptJournal("native checkpoint digest"));
        }
        let mut checkpoint: NativeCheckpoint = serde_json::from_slice(&bytes)
            .map_err(|_| Error::CorruptJournal("native checkpoint decode"))?;
        if !matches!(checkpoint.schema_version, 1 | CHECKPOINT_SCHEMA_VERSION)
            || checkpoint.generation != generation
            || checkpoint.archive_segment_digest != archive_segment_digest
            || checkpoint.archive_chain_digest != archive_chain_digest
            || checkpoint.records.len() > super::MAX_RECORDS
            || (!checkpoint.records.is_empty() && checkpoint.maximum_in_flight.is_none())
            || checkpoint
                .maximum_in_flight
                .is_some_and(|limit| !(1..=256).contains(&limit))
        {
            return Err(Error::CorruptJournal("native checkpoint binding"));
        }
        for (id, record) in &mut checkpoint.records {
            // Version 1 reconciliations manufactured readiness without host
            // evidence. Keep terminal/usage facts but deny that success claim.
            if checkpoint.schema_version == 1
                && record.reconciliation.is_some()
                && let Some(observation) = &mut record.observation
                && observation.owner_authority == NativeOwnerAuthority::ObservedReady
            {
                observation.owner_authority = NativeOwnerAuthority::Unverified;
            }
            // Historical retirement IDs alone cannot prove independent keys.
            // A newer checkpoint may contain a historical audit too.
            if record.state == NativeReservationState::Released
                && record
                    .retirement
                    .as_ref()
                    .is_some_and(|retirement| retirement.independent_operator_key_digests.is_none())
            {
                record.state = NativeReservationState::Indeterminate;
            }
            if id != &record.request.request_id {
                return Err(Error::CorruptJournal("native checkpoint request key"));
            }
            validate_checkpoint_record(record)?;
        }
        if let Some(limit) = checkpoint.maximum_in_flight
            && checkpoint
                .records
                .values()
                .filter(|record| record.state != NativeReservationState::Released)
                .count()
                > limit
        {
            return Err(Error::CorruptJournal("native checkpoint capacity"));
        }
        self.maximum_in_flight = checkpoint.maximum_in_flight;
        self.records = checkpoint.records;
        self.checkpoint_generation = generation;
        self.archive_chain_digest = Some(archive_chain_digest.to_string());
        self.checkpoint_digest = Some(checkpoint_digest.to_string());
        Ok(())
    }
}
