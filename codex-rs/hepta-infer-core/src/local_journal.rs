//! Replay and live transitions use the same checked local-owner reducer.

use super::*;
use crate::durable_control::validate_digest;
use crate::durable_control::validate_identity;

impl LocalJournal {
    pub(in crate::durable_control) fn replay(&mut self, json: &str) -> Result<(), Error> {
        self.apply(serde_json::from_str(json).map_err(|_| Error::CorruptJournal("local decode"))?)
    }

    pub(super) fn apply(&mut self, event: Event) -> Result<(), Error> {
        match event {
            Event::Reserve { request, now } => self.reserve(request, now),
            Event::Fence { device, generation } => {
                validate_identity(&device, "local device")?;
                if generation == 0 {
                    return Err(Error::InvalidTime);
                }
                self.fenced.insert((device, generation));
                Ok(())
            }
            Event::Prepare { id, dispatch } => {
                validate_identity(&dispatch.grant_id, "local grant")?;
                validate_digest(
                    &dispatch.authority_witness_digest,
                    "local authority witness",
                )?;
                validate_digest(&dispatch.nonce_digest, "local nonce")?;
                let source = self.records.get(&id).ok_or(Error::RequestNotFound)?;
                if let Some(load_id) = &source.request.model_operation_id {
                    let loaded = self.records.get(load_id).ok_or(Error::AssignmentMismatch)?;
                    if loaded.state != LocalState::Resident
                        || loaded
                            .observation
                            .as_ref()
                            .and_then(|value| value.physical_handle_id.as_ref())
                            != dispatch.physical_handle_id.as_ref()
                    {
                        return Err(Error::AssignmentMismatch);
                    }
                }
                let record = self.records.get_mut(&id).ok_or(Error::RequestNotFound)?;
                if record.state != LocalState::Reserved
                    || self.fenced.contains(&(
                        record.request.device_lease_id.clone(),
                        record.request.worker_generation,
                    ))
                {
                    return Err(Error::InvalidTransition);
                }
                if let Some(handle) = &dispatch.physical_handle_id {
                    validate_identity(handle, "local handle")?;
                }
                if (record.request.kind == LocalOperationKind::Run)
                    != dispatch.physical_handle_id.is_some()
                {
                    return Err(Error::AssignmentMismatch);
                }
                record.dispatch = Some(dispatch);
                record.state = LocalState::Dispatching;
                bump(record)
            }
            Event::Abort { id, revision } => {
                let record = self.records.get_mut(&id).ok_or(Error::RequestNotFound)?;
                if record.state != LocalState::Dispatching || record.revision != revision {
                    return Err(Error::StaleRevision);
                }
                record.state = LocalState::Cancelled;
                record.cancellation_requested = true;
                bump(record)
            }
            Event::Cancel { id, now } => {
                let record = self.records.get_mut(&id).ok_or(Error::RequestNotFound)?;
                if now < record.admitted_at_unix_ms {
                    return Err(Error::InvalidTime);
                }
                record.state = match record.state {
                    LocalState::Reserved => LocalState::Cancelled,
                    LocalState::Dispatching | LocalState::Indeterminate => {
                        record.first_indeterminate_at_unix_ms.get_or_insert(now);
                        LocalState::Indeterminate
                    }
                    _ => return Err(Error::InvalidTransition),
                };
                record.cancellation_requested = true;
                bump(record)
            }
            Event::Unknown { id, now } => {
                let record = self.records.get_mut(&id).ok_or(Error::RequestNotFound)?;
                if !matches!(
                    record.state,
                    LocalState::Dispatching | LocalState::Indeterminate
                ) || now < record.admitted_at_unix_ms
                {
                    return Err(Error::InvalidTransition);
                }
                record.state = LocalState::Indeterminate;
                record.first_indeterminate_at_unix_ms.get_or_insert(now);
                bump(record)
            }
            Event::Observe { id, observation } => {
                let record = self.records.get_mut(&id).ok_or(Error::RequestNotFound)?;
                observe(record, observation)
            }
            Event::BeginUnload { id } => {
                if self.records.values().any(|record| {
                    record.request.model_operation_id.as_deref() == Some(&id)
                        && record.state.holds_resources()
                }) {
                    return Err(Error::InvalidTransition);
                }
                let record = self.records.get_mut(&id).ok_or(Error::RequestNotFound)?;
                if record.state != LocalState::Resident {
                    return Err(Error::InvalidTransition);
                }
                record.state = LocalState::Unloading;
                bump(record)
            }
            Event::Unloaded {
                id,
                observation_digest,
            } => {
                validate_digest(&observation_digest, "local unload observation")?;
                let record = self.records.get_mut(&id).ok_or(Error::RequestNotFound)?;
                if record.state != LocalState::Unloading {
                    return Err(Error::InvalidTransition);
                }
                record.state = LocalState::Released;
                record.unload_observation_digest = Some(observation_digest);
                bump(record)
            }
        }
    }

    fn reserve(&mut self, request: LocalRequest, now: u64) -> Result<(), Error> {
        for (value, name) in [
            (&request.operation_id, "local operation"),
            (&request.worker_id, "local worker"),
            (&request.device_lease_id, "local device"),
        ] {
            validate_identity(value, name)?;
        }
        for (value, name) in [
            (&request.model_digest, "local model"),
            (&request.model_tuple_digest, "local tuple"),
            (&request.request_digest, "local request"),
            (&request.payload_digest, "local payload"),
            (&request.runtime_digest, "local runtime"),
        ] {
            validate_digest(value, name)?;
        }
        let policy = &request.policy;
        if now == 0 || request.deadline_unix_ms <= now || request.worker_generation == 0 {
            return Err(Error::InvalidTime);
        }
        if request.maximum_tokens == 0 || request.maximum_tokens > super::super::MAX_TOKENS {
            return Err(Error::InvalidTokens);
        }
        if policy.maximum_memory_bytes == 0
            || !(1..=8).contains(&policy.maximum_models)
            || !(1..=256).contains(&policy.maximum_active_requests)
            || request.reservation_bytes > policy.maximum_memory_bytes
        {
            return Err(Error::CapacityExceeded);
        }
        if self.records.contains_key(&request.operation_id)
            || self
                .policies
                .get(&request.device_lease_id)
                .is_some_and(|existing| existing != policy)
            || self
                .fenced
                .contains(&(request.device_lease_id.clone(), request.worker_generation))
        {
            return Err(Error::Conflict);
        }
        match (&request.kind, &request.model_operation_id) {
            (LocalOperationKind::Load, None) if request.reservation_bytes > 0 => {}
            (LocalOperationKind::Run, Some(load_id)) => {
                let loaded = self.records.get(load_id).ok_or(Error::AssignmentMismatch)?;
                if loaded.state != LocalState::Resident
                    || loaded.request.kind != LocalOperationKind::Load
                    || loaded.request.worker_id != request.worker_id
                    || loaded.request.worker_generation != request.worker_generation
                    || loaded.request.device_lease_id != request.device_lease_id
                    || loaded.request.model_tuple_digest != request.model_tuple_digest
                    || loaded.request.model_digest != request.model_digest
                    || loaded.request.runtime_digest != request.runtime_digest
                {
                    return Err(Error::AssignmentMismatch);
                }
            }
            _ => return Err(Error::AssignmentMismatch),
        }
        let held: Vec<_> = self
            .records
            .values()
            .filter(|record| {
                record.request.device_lease_id == request.device_lease_id
                    && record.state.holds_resources()
            })
            .collect();
        let bytes = held
            .iter()
            .try_fold(request.reservation_bytes, |total, record| {
                total
                    .checked_add(record.request.reservation_bytes)
                    .ok_or(Error::ArithmeticOverflow)
            })?;
        let same_kind = held
            .iter()
            .filter(|record| record.request.kind == request.kind)
            .count();
        let limit = match request.kind {
            LocalOperationKind::Load => policy.maximum_models,
            LocalOperationKind::Run => policy.maximum_active_requests,
        };
        if bytes > policy.maximum_memory_bytes || same_kind >= usize::from(limit) {
            return Err(Error::CapacityExceeded);
        }
        self.policies
            .insert(request.device_lease_id.clone(), policy.clone());
        self.records.insert(
            request.operation_id.clone(),
            LocalRecord {
                request,
                revision: 1,
                state: LocalState::Reserved,
                admitted_at_unix_ms: now,
                first_indeterminate_at_unix_ms: None,
                dispatch: None,
                observation: None,
                cancellation_requested: false,
                unload_observation_digest: None,
            },
        );
        Ok(())
    }
}

fn bump(record: &mut LocalRecord) -> Result<(), Error> {
    record.revision = record
        .revision
        .checked_add(1)
        .ok_or(Error::ArithmeticOverflow)?;
    Ok(())
}

fn observe(record: &mut LocalRecord, observation: LocalObservation) -> Result<(), Error> {
    if !matches!(
        record.state,
        LocalState::Dispatching | LocalState::Indeterminate
    ) {
        return Err(Error::InvalidTransition);
    }
    validate_digest(
        &observation.correlation_digest,
        "local terminal correlation",
    )?;
    if observation
        .consumed_tokens
        .is_some_and(|tokens| tokens > u64::from(record.request.maximum_tokens))
    {
        return Err(Error::UsageExceeded);
    }
    if observation.observed_memory_bytes > record.request.reservation_bytes {
        return Err(Error::CapacityExceeded);
    }
    if observation
        .output
        .as_ref()
        .is_some_and(|output| output.len() > 1024 * 1024)
    {
        return Err(Error::CapacityExceeded);
    }
    if let Some(handle) = &observation.physical_handle_id {
        validate_identity(handle, "local observed handle")?;
    }
    let dispatch = record.dispatch.as_ref().ok_or(Error::AssignmentMismatch)?;
    if record.request.kind == LocalOperationKind::Run
        && observation.physical_handle_id != dispatch.physical_handle_id
    {
        return Err(Error::AssignmentMismatch);
    }
    record.state = match observation.status {
        LocalTerminalStatus::Succeeded if record.request.kind == LocalOperationKind::Load => {
            if observation.physical_handle_id.is_none() {
                return Err(Error::AssignmentMismatch);
            }
            LocalState::Resident
        }
        LocalTerminalStatus::Succeeded => {
            if observation.output.is_none() {
                return Err(Error::TerminalObservationMissing);
            }
            LocalState::Succeeded
        }
        // A failed load reporting a live handle still owns physical resources.
        LocalTerminalStatus::Failed | LocalTerminalStatus::Cancelled
            if record.request.kind == LocalOperationKind::Load
                && observation.physical_handle_id.is_some() =>
        {
            LocalState::Unloading
        }
        LocalTerminalStatus::Failed => LocalState::Failed,
        LocalTerminalStatus::Cancelled => LocalState::Cancelled,
    };
    record.observation = Some(observation);
    bump(record)
}
