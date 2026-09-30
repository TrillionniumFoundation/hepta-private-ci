fn apply_dispatch(record: &mut NativeRunRecord, dispatch: NativeDispatch) -> Result<(), Error> {
    if record.state != NativeReservationState::Reserved {
        return Err(Error::InvalidTransition);
    }
    validate_identity(&dispatch.thread_id, "native thread")?;
    validate_identity(&dispatch.model_provider, "native provider")?;
    validate_digest(&dispatch.context_digest, "native context")?;
    if let Some(value) = &dispatch.owner_context_digest {
        validate_digest(value, "native owner context")?;
    }

    let codex_fields = [
        dispatch.codex_payload_digest.is_some(),
        dispatch.codex_request_digest.is_some(),
        dispatch.app_server_version.is_some(),
        dispatch.protocol_id.is_some(),
    ];
    if codex_fields.iter().any(|present| *present)
        && !codex_fields.iter().all(|present| *present)
    {
        return Err(Error::InvalidIdentity("native codex dispatch binding"));
    }
    let extended_codex_fields = [
        dispatch.codex_source_admission_digest.is_some(),
        dispatch.codex_home_digest.is_some(),
        dispatch.codex_connection_id.is_some(),
        dispatch.codex_session_id.is_some(),
        dispatch.codex_deadline_ms.is_some(),
        dispatch.codex_authority_witness_sha256.is_some(),
    ];
    if extended_codex_fields.iter().any(|present| *present)
        && (!codex_fields.iter().all(|present| *present)
            || !extended_codex_fields.iter().all(|present| *present))
    {
        return Err(Error::InvalidIdentity(
            "native codex extended dispatch binding",
        ));
    }
    let frontier_fields = [
        dispatch.codex_authority_epoch.is_some(),
        dispatch.codex_revocation_revision.is_some(),
        dispatch.codex_revocation_head_sha256.is_some(),
    ];
    if frontier_fields.iter().any(|present| *present)
        && (!extended_codex_fields.iter().all(|present| *present)
            || !frontier_fields.iter().all(|present| *present))
    {
        return Err(Error::InvalidIdentity(
            "native codex authority frontier binding",
        ));
    }
    for (value, field) in [
        (&dispatch.codex_payload_digest, "native codex payload"),
        (&dispatch.codex_request_digest, "native codex request"),
        (
            &dispatch.codex_source_admission_digest,
            "native codex source admission",
        ),
        (&dispatch.codex_home_digest, "native codex home"),
        (
            &dispatch.codex_revocation_head_sha256,
            "native codex revocation head",
        ),
        (
            &dispatch.codex_authority_witness_sha256,
            "native codex authority witness",
        ),
    ] {
        if let Some(value) = value {
            validate_digest(value, field)?;
        }
    }
    if let Some(version) = &dispatch.app_server_version
        && (version.is_empty()
            || version.len() > 128
            || version.bytes().any(|byte| byte.is_ascii_control()))
    {
        return Err(Error::InvalidIdentity("native app server version"));
    }
    if let Some(value) = &dispatch.protocol_id {
        validate_identity(value, "native app server protocol")?;
    }
    if dispatch.codex_connection_id == Some(0) {
        return Err(Error::InvalidIdentity("native codex connection"));
    }
    if let Some(value) = &dispatch.codex_session_id {
        validate_identity(value, "native codex session")?;
    }
    if dispatch.codex_deadline_ms == Some(0) {
        return Err(Error::InvalidIdentity("native codex deadline"));
    }
    if dispatch.codex_authority_epoch == Some(0) {
        return Err(Error::InvalidIdentity("native codex authority epoch"));
    }
    if dispatch.codex_revocation_revision == Some(0) {
        return Err(Error::InvalidIdentity("native codex revocation revision"));
    }
    record.dispatch = Some(dispatch);
    record.state = NativeReservationState::Dispatching;
    Ok(())
}

fn apply_started(
    record: &mut NativeRunRecord,
    turn_id: String,
    effect_entered_at_unix_ms: Option<u64>,
) -> Result<(), Error> {
    if record.state != NativeReservationState::Dispatching
        || record.dispatch_rejection.is_some()
        || effect_entered_at_unix_ms == Some(0)
    {
        return Err(Error::InvalidTransition);
    }
    validate_identity(&turn_id, "native turn")?;
    record.turn_id = Some(turn_id);
    record.effect_entered_at_unix_ms = effect_entered_at_unix_ms;
    record.state = NativeReservationState::Running;
    Ok(())
}

fn apply_dispatch_rejection(
    record: &mut NativeRunRecord,
    rejection: NativeDispatchRejection,
) -> Result<(), Error> {
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
    let safe = rejection.retry_safe_before_admission;
    record.dispatch_rejection = Some(rejection);
    record.state = if safe {
        NativeReservationState::Released
    } else {
        NativeReservationState::Indeterminate
    };
    Ok(())
}

fn apply_safe_stop(
    record: &mut NativeRunRecord,
    reason: String,
    after_dispatch: bool,
) -> Result<(), Error> {
    let allowed = if after_dispatch {
        record.state == NativeReservationState::Dispatching
            && record.observation.is_none()
            && record.dispatch_rejection.is_none()
            && !record.cancel_requested
    } else {
        record.state == NativeReservationState::Reserved
    };
    if !allowed
        || record.turn_id.is_some()
        || reason.is_empty()
        || reason.len() > 4096
    {
        return Err(Error::InvalidTransition);
    }
    record.pre_dispatch_stop = Some(reason);
    record.state = NativeReservationState::Released;
    Ok(())
}

fn apply_authority_observation(
    record: &mut NativeRunRecord,
    observation: NativeAuthorityObservation,
) -> Result<(), Error> {
    validate_identity(&observation.issuer, "native authority issuer")?;
    validate_identity(&observation.grant_id, "native authority grant")?;
    for (value, field) in [
        (
            &observation.revocation_head_digest,
            "native authority revocation head",
        ),
        (
            &observation.grant_witness_digest,
            "native authority grant witness",
        ),
        (
            &observation.authority_snapshot_digest,
            "native authority snapshot",
        ),
    ] {
        validate_digest(value, field)?;
    }
    if observation.authority_epoch == 0
        || observation.revocation_revision == 0
        || observation.observed_at_unix_ms == 0
    {
        return Err(Error::InvalidTime);
    }
    if let Some(previous) = &record.authority_observation {
        if observation.authority_epoch < previous.authority_epoch
            || (observation.authority_epoch == previous.authority_epoch
                && observation.revocation_revision < previous.revocation_revision)
            || observation.observed_at_unix_ms < previous.observed_at_unix_ms
            || (observation.authority_epoch == previous.authority_epoch
                && observation.revocation_revision == previous.revocation_revision
                && observation.revocation_head_digest != previous.revocation_head_digest)
            || (observation.observed_at_unix_ms == previous.observed_at_unix_ms
                && observation.authority_snapshot_digest
                    != previous.authority_snapshot_digest)
            || (previous.revoked && !observation.revoked)
        {
            return Err(Error::Conflict);
        }
        if previous == &observation {
            return Ok(());
        }
    }
    record.authority_observation = Some(observation);
    Ok(())
}

fn validate_interrupt(observation: &NativeInterruptObservation) -> Result<(), Error> {
    if observation.reason.is_empty()
        || observation.reason.len() > 4096
        || observation.requested_at_unix_ms == 0
        || observation
            .observed_at_unix_ms
            .is_some_and(|observed| observed < observation.requested_at_unix_ms)
    {
        return Err(Error::InvalidTime);
    }
    if let Some(value) = &observation.evidence_digest {
        validate_digest(value, "native interrupt evidence")?;
    }
    Ok(())
}

fn apply_interrupt_intent(
    record: &mut NativeRunRecord,
    observation: NativeInterruptObservation,
) -> Result<(), Error> {
    validate_interrupt(&observation)?;
    if observation.outcome != NativeInterruptOutcome::Requested
        || observation.observed_at_unix_ms.is_some()
        || record.effect_entered_at_unix_ms.is_none()
        || record.state == NativeReservationState::Released
    {
        return Err(Error::InvalidTransition);
    }
    if let Some(previous) = &record.interrupt_observation {
        return if previous == &observation {
            Ok(())
        } else {
            Err(Error::Conflict)
        };
    }
    record.cancel_requested = true;
    record.state = NativeReservationState::Cancelling;
    record.interrupt_observation = Some(observation);
    Ok(())
}

fn apply_interrupt_outcome(
    record: &mut NativeRunRecord,
    observation: NativeInterruptObservation,
) -> Result<(), Error> {
    validate_interrupt(&observation)?;
    let Some(intent) = &record.interrupt_observation else {
        return Err(Error::InvalidTransition);
    };
    if intent.outcome != NativeInterruptOutcome::Requested
        || observation.outcome == NativeInterruptOutcome::Requested
        || observation.reason != intent.reason
        || observation.requested_at_unix_ms != intent.requested_at_unix_ms
        || observation.observed_at_unix_ms.is_none()
    {
        return Err(Error::InvalidTransition);
    }
    record.interrupt_observation = Some(observation);
    Ok(())
}

fn apply_observation(
    record: &mut NativeRunRecord,
    mut output: NativeRunOutput,
    evidence: NativeObservationEvidence,
) -> Result<(), Error> {
    let dispatch = record.dispatch.as_ref().ok_or(Error::AssignmentMismatch)?;
    if output.thread_id != dispatch.thread_id
        || output.model_provider != dispatch.model_provider
        || output.model != record.request.model
        || record
            .turn_id
            .as_ref()
            .is_some_and(|turn| turn != &output.turn_id)
    {
        return Err(Error::AssignmentMismatch);
    }
    if output.output.len() > 1024 * 1024
        || output
            .stop_reason
            .as_ref()
            .is_some_and(|reason| reason.len() > 4096)
    {
        return Err(Error::CapacityExceeded);
    }
    if let Some(value) = &output.codex_terminal_correlation_digest {
        validate_digest(value, "native codex terminal correlation")?;
    }
    let complete_frontier = dispatch.codex_authority_epoch.is_some()
        && dispatch.codex_revocation_revision.is_some()
        && dispatch.codex_revocation_head_sha256.is_some();
    if output.terminal_observed
        && output.boundary_status == NativeBoundaryStatus::Succeeded
        && dispatch.codex_request_digest.is_some()
        && !complete_frontier
    {
        output.boundary_status = NativeBoundaryStatus::Quarantined;
        output.stop_reason = Some(
            "historical runtime.codex dispatch lacks claim-time authority frontier; terminal truth retained but success qualification denied"
                .to_string(),
        );
    }
    if output.terminal_observed
        && dispatch.codex_request_digest.is_some()
        && (output.codex_terminal_correlation_digest.is_none()
            || output.boundary_status == NativeBoundaryStatus::Indeterminate)
    {
        return Err(Error::TerminalObservationMissing);
    }
    if let NativeOwnerAuthority::Lost { reason } = &output.owner_authority
        && (reason.is_empty() || reason.len() > 4096)
    {
        return Err(Error::InvalidIdentity("owner authority loss reason"));
    }
    if output.terminal_observed == (output.status == NativeRunStatus::Indeterminate)
        || (output.turn_id.is_empty()
            && (output.terminal_observed
                || output.observed_output_tokens.is_some()
                || !output.output.is_empty()))
    {
        return Err(Error::TerminalObservationMissing);
    }
    if let Some(previous) = &record.observation {
        if (matches!(previous.owner_authority, NativeOwnerAuthority::Lost { .. })
            && previous.owner_authority != output.owner_authority)
            || (previous.terminal_observed
                && previous.owner_authority == NativeOwnerAuthority::Unverified
                && output.owner_authority == NativeOwnerAuthority::ObservedReady)
        {
            return Err(Error::Conflict);
        }
        if previous.terminal_observed
            && (previous.status != output.status
                || previous.boundary_status != output.boundary_status
                || !output.terminal_observed
                || previous.output != output.output
                || previous.codex_terminal_correlation_digest
                    != output.codex_terminal_correlation_digest)
        {
            return Err(Error::Conflict);
        }
        if previous.observed_output_tokens.is_some_and(|tokens| {
            output
                .observed_output_tokens
                .is_none_or(|next| next < tokens)
        }) {
            return Err(Error::Conflict);
        }
    }
    if !output.turn_id.is_empty() {
        validate_identity(&output.turn_id, "native turn")?;
        record.turn_id = Some(output.turn_id.clone());
    }

    let hold_local_quarantine = output.terminal_observed
        && output.boundary_status == NativeBoundaryStatus::Quarantined
        && dispatch.model_provider == LOCAL_MODEL_PROVIDER_ID;
    record.state = if output.terminal_observed && !hold_local_quarantine {
        NativeReservationState::Released
    } else {
        NativeReservationState::Indeterminate
    };
    record.observation = Some(output);
    apply_observation_evidence(record, evidence)
}

fn apply_observation_evidence(
    record: &mut NativeRunRecord,
    evidence: NativeObservationEvidence,
) -> Result<(), Error> {
    if evidence.observed_at_unix_ms != 0 {
        if record
            .last_observed_at_unix_ms
            .is_some_and(|previous| evidence.observed_at_unix_ms < previous)
        {
            return Err(Error::Conflict);
        }
        record.last_observed_at_unix_ms = Some(evidence.observed_at_unix_ms);
        if record.state == NativeReservationState::Indeterminate
            && record.first_indeterminate_at_unix_ms.is_none()
        {
            record.first_indeterminate_at_unix_ms = Some(evidence.observed_at_unix_ms);
        }
    }
    if let Some(usage) = evidence.usage_units {
        if record
            .observed_usage_units
            .is_some_and(|previous| usage < previous)
            || evidence.usage_authority.rank() < record.usage_authority.rank()
        {
            return Err(Error::Conflict);
        }
        record.observed_usage_units = Some(usage);
        record.usage_authority = evidence.usage_authority;
    } else if evidence.usage_authority.rank() < record.usage_authority.rank() {
        return Err(Error::Conflict);
    }
    for (value, field) in [
        (
            &evidence.resource_attestation_digest,
            "native resource attestation",
        ),
        (
            &evidence.terminal_evidence_digest,
            "native terminal evidence",
        ),
        (
            &evidence.generation_fence_identity,
            "native generation fence",
        ),
    ] {
        if let Some(value) = value {
            validate_digest(value, field)?;
        }
    }
    if let Some(reason) = &evidence.quarantine_reason
        && (reason.is_empty() || reason.len() > 4096)
    {
        return Err(Error::InvalidIdentity("native quarantine reason"));
    }
    update_optional_digest(
        &mut record.resource_attestation_digest,
        evidence.resource_attestation_digest,
    )?;
    let terminal_evidence = evidence.terminal_evidence_digest.or_else(|| {
        record
            .observation
            .as_ref()
            .and_then(|output| output.codex_terminal_correlation_digest.clone())
    });
    update_optional_digest(&mut record.terminal_evidence_digest, terminal_evidence)?;
    update_optional_digest(
        &mut record.generation_fence_identity,
        evidence.generation_fence_identity,
    )?;
    if let Some(reason) = evidence.quarantine_reason.or_else(|| {
        record.observation.as_ref().and_then(|output| {
            (output.boundary_status == NativeBoundaryStatus::Quarantined)
                .then(|| output.stop_reason.clone())
                .flatten()
        })
    }) {
        if record
            .quarantine_reason
            .as_ref()
            .is_some_and(|previous| previous != &reason)
        {
            return Err(Error::Conflict);
        }
        record.quarantine_reason = Some(reason);
    }
    Ok(())
}

fn update_optional_digest(target: &mut Option<String>, next: Option<String>) -> Result<(), Error> {
    if let Some(next) = next {
        if target.as_ref().is_some_and(|previous| previous != &next) {
            return Err(Error::Conflict);
        }
        *target = Some(next);
    }
    Ok(())
}

fn apply_quarantine_release(
    record: &mut NativeRunRecord,
    evidence: NativeCapacityReleaseEvidence,
) -> Result<(), Error> {
    let output = record
        .observation
        .as_ref()
        .ok_or(Error::InvalidTransition)?;
    let dispatch = record.dispatch.as_ref().ok_or(Error::InvalidTransition)?;
    if dispatch.model_provider != LOCAL_MODEL_PROVIDER_ID
        || record.state != NativeReservationState::Indeterminate
        || !output.terminal_observed
        || output.boundary_status != NativeBoundaryStatus::Quarantined
        || evidence.observed_at_unix_ms == 0
        || evidence.reason.is_empty()
        || evidence.reason.len() > 4096
        || record
            .last_observed_at_unix_ms
            .is_some_and(|previous| evidence.observed_at_unix_ms < previous)
    {
        return Err(Error::InvalidTransition);
    }
    validate_digest(&evidence.evidence_digest, "native capacity release")?;
    if let Some(previous) = &record.capacity_release_evidence {
        return if previous == &evidence {
            Ok(())
        } else {
            Err(Error::Conflict)
        };
    }
    record.last_observed_at_unix_ms = Some(evidence.observed_at_unix_ms);
    record.capacity_release_evidence = Some(evidence);
    record.state = NativeReservationState::Released;
    Ok(())
}

fn host_unix_time_ms() -> Result<u64, Error> {
    let elapsed = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|_| Error::InvalidTime)?;
    u64::try_from(elapsed.as_millis()).map_err(|_| Error::InvalidTime)
}
