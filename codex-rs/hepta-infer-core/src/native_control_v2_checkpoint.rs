// Restore a checkpoint through the same transition rules as its event journal.

fn validate_checkpoint_record(record: &NativeRunRecord) -> Result<(), Error> {
    if record.revision == 0 {
        return Err(Error::CorruptJournal("native checkpoint revision"));
    }
    let request_id = record.request.request_id.clone();
    let mut replay = NativeJournal::default();
    replay.apply(Event::Reserve {
        request: record.request.clone(),
        maximum_in_flight: 1,
    })?;
    if let Some(binding) = &record.execution_binding {
        replay.apply(Event::BindExecution {
            request_id: request_id.clone(),
            binding: binding.clone(),
        })?;
    }
    if let Some(dispatch) = &record.dispatch {
        replay.apply(Event::Dispatch {
            request_id: request_id.clone(),
            dispatch: dispatch.clone(),
        })?;
    }
    if let Some(turn_id) = &record.turn_id {
        replay.apply(Event::Started {
            request_id: request_id.clone(),
            turn_id: turn_id.clone(),
        })?;
    }
    if let Some(reason) = &record.pre_dispatch_stop {
        replay.apply(if record.dispatch.is_some() {
            Event::AbortBeforeEffect {
                request_id: request_id.clone(),
                reason: reason.clone(),
            }
        } else {
            Event::Stop {
                request_id: request_id.clone(),
                reason: reason.clone(),
            }
        })?;
    }
    if let Some(rejection) = &record.dispatch_rejection {
        replay.apply(Event::RejectBeforeStart {
            request_id: request_id.clone(),
            rejection: rejection.clone(),
        })?;
    }
    let cancel_after_observation = record.state == NativeReservationState::Cancelling;
    if record.cancel_requested && !cancel_after_observation {
        replay.apply(Event::Cancel {
            request_id: request_id.clone(),
        })?;
    }
    if let Some(output) = &record.observation {
        if let Some(audit) = &record.reconciliation {
            if !output.terminal_observed
                || output.codex_terminal_correlation_digest.as_ref() != Some(&audit.receipt_digest)
                || output.output
                    != audit.output_digest.as_ref()
                        .map(|digest| format!("hepta-reconciled-output-v1:{digest}"))
                        .unwrap_or_default()
                || (output.status == NativeRunStatus::Completed && audit.output_digest.is_none())
                || audit.encrypted_output_reference.as_ref().is_some_and(|reference| {
                    reference.is_empty()
                        || reference.len() > 2048
                        || reference.bytes().any(|byte| byte.is_ascii_control())
                })
            {
                return Err(Error::CorruptJournal("native checkpoint reconciliation"));
            }
            // The checkpoint retains the previous host-authority projection,
            // not a fresh claim minted by provider reconciliation. Schema
            // migration downgrades historical unsupported ready projections.
            let restored = replay.records.get_mut(&request_id).ok_or(Error::RequestNotFound)?;
            let mut authority_projection = output.clone();
            authority_projection.terminal_observed = false;
            authority_projection.status = NativeRunStatus::Indeterminate;
            authority_projection.boundary_status = NativeBoundaryStatus::Indeterminate;
            restored.observation = Some(authority_projection);
            restored.state = NativeReservationState::Indeterminate;
            restored.protected_output = record.protected_output.clone();
            replay.apply(Event::Reconcile {
                request_id: request_id.clone(),
                output: output.clone(),
                audit: audit.clone(),
            })?;
        } else {
            replay.apply(Event::Observe {
                request_id: request_id.clone(),
                output: output.clone(),
                protected_output: record.protected_output.clone(),
            })?;
        }
    } else if record.reconciliation.is_some() || record.protected_output.is_some() {
        return Err(Error::CorruptJournal("native checkpoint observation missing"));
    }
    if let Some(audit) = &record.retirement {
        if audit.reason_code.is_empty()
            || audit.reason_code.len() > 128
            || !audit.reason_code.bytes().all(|byte| {
                byte.is_ascii_alphanumeric() || b"._:-/".contains(&byte)
            })
        {
            return Err(Error::CorruptJournal("native checkpoint retirement reason"));
        }
        replay.apply(Event::Retire {
            request_id: request_id.clone(),
            audit: audit.clone(),
        })?;
    }
    if record.cancel_requested && cancel_after_observation {
        replay.apply(Event::Cancel { request_id: request_id.clone() })?;
    }
    let restored = replay.records.get_mut(&request_id).ok_or(Error::RequestNotFound)?;
    // Checkpoints omit the number and order of repeated usage refinements.
    // Preserve their logical revision while validating the complete final cut.
    restored.revision = record.revision;
    if &*restored != record {
        return Err(Error::CorruptJournal("native checkpoint state evidence"));
    }
    Ok(())
}

#[cfg(test)]
#[path = "native_checkpoint_validation_tests.rs"]
mod checkpoint_validation_tests;
