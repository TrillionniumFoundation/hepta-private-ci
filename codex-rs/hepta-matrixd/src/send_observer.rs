#![forbid(unsafe_code)]

use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixTransactionId;
use codex_hepta_matrix_store::MatrixDispatchAuthorityDraft;
use codex_hepta_matrix_store::MatrixDispatchRecord;
use codex_hepta_matrix_store::MatrixDispatchState;
use codex_hepta_matrix_store::MatrixDurableError;
use codex_hepta_matrix_store::MatrixDurableStore;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SendIntent {
    pub operation_id: String,
    pub transaction_id: String,
    pub homeserver_id: String,
    pub room_id: String,
    pub device_id: String,
    pub session_generation: u64,
    pub authority_epoch: u64,
    pub payload_digest: String,
    pub grant_payload_digest: String,
    pub deadline_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ServerObservation {
    pub operation_id: String,
    pub transaction_id: String,
    pub homeserver_id: String,
    pub room_id: String,
    pub session_generation: u64,
    pub terminal_observed: bool,
    pub accepted: bool,
    pub server_event_id: Option<String>,
    pub observation_digest: String,
    pub observed_at_ms: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SendState {
    Prepared,
    Indeterminate,
    Succeeded,
    Failed,
    Redacted,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SendReceipt {
    pub operation_id: String,
    pub transaction_id: String,
    pub state: SendState,
    pub server_event_id: Option<String>,
    pub send_observation_digest: Option<String>,
    pub redaction_observation_digest: Option<String>,
    pub terminal_observed: bool,
    pub idempotent: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum Error {
    #[error("invalid Matrix send identity")]
    InvalidIdentity,
    #[error("invalid Matrix send digest")]
    InvalidDigest,
    #[error("invalid Matrix generation")]
    InvalidGeneration,
    #[error("Matrix send deadline expired")]
    DeadlineExpired,
    #[error("Matrix send payload does not match its grant")]
    PayloadMismatch,
    #[error("Matrix send state conflicts with durable truth")]
    OperationConflict,
    #[error("Matrix send was not found")]
    SendNotFound,
    #[error("Matrix server observation does not match the prepared send")]
    ObservationMismatch,
    #[error("terminal Matrix acceptance omitted the server event")]
    TerminalEventMissing,
    #[error("Matrix durable store is unavailable")]
    StoreUnavailable,
}

/// Reusable facade over the one canonical durable Matrix dispatch ledger.
///
/// This type deliberately owns no map, queue or persistence of its own. The
/// MatrixDurableStore remains the single writer for outbox transaction
/// identity, boundary uncertainty, terminal observation and redaction lineage.
#[derive(Clone)]
pub struct MatrixSendObserver {
    store: MatrixDurableStore,
}

impl MatrixSendObserver {
    pub fn new(store: MatrixDurableStore) -> Self {
        Self { store }
    }

    pub fn store(&self) -> &MatrixDurableStore {
        &self.store
    }

    pub async fn prepare_send(
        &self,
        now_ms: u64,
        intent: SendIntent,
    ) -> Result<SendReceipt, Error> {
        validate_intent(now_ms, &intent)?;
        if intent.payload_digest != intent.grant_payload_digest {
            return Err(Error::PayloadMismatch);
        }
        let txn_id =
            MatrixTransactionId::parse(intent.transaction_id.clone()).map_err(|_| Error::InvalidIdentity)?;
        let room_id =
            MatrixRoomId::parse(intent.room_id.clone()).map_err(|_| Error::InvalidIdentity)?;
        let before = self
            .store
            .dispatch_record(&txn_id)
            .await
            .map_err(map_store)?
            .ok_or(Error::SendNotFound)?;
        let exact_before = authority_matches(&before, &intent);
        let record = self
            .store
            .bind_dispatch_authority(&MatrixDispatchAuthorityDraft {
                operation_id: intent.operation_id,
                stable_txn_id: txn_id,
                homeserver_id: intent.homeserver_id,
                room_id,
                device_id: intent.device_id,
                session_generation: intent.session_generation,
                authority_epoch: intent.authority_epoch,
                payload_digest: intent.payload_digest,
                grant_payload_digest: intent.grant_payload_digest,
                deadline_ms: intent.deadline_ms,
                prepared_at_ms: now_ms,
            })
            .await
            .map_err(map_store)?;
        Ok(receipt(&record, exact_before))
    }

    pub async fn observe_send(
        &self,
        observation: ServerObservation,
    ) -> Result<SendReceipt, Error> {
        validate_observation(&observation)?;
        let txn_id = MatrixTransactionId::parse(observation.transaction_id.clone())
            .map_err(|_| Error::InvalidIdentity)?;
        let room_id =
            MatrixRoomId::parse(observation.room_id.clone()).map_err(|_| Error::InvalidIdentity)?;
        let current = self
            .store
            .dispatch_record(&txn_id)
            .await
            .map_err(map_store)?
            .ok_or(Error::SendNotFound)?;
        if current.operation_id != observation.operation_id
            || current.homeserver_id.as_deref() != Some(observation.homeserver_id.as_str())
            || current.room_id != room_id
            || current.session_generation != observation.session_generation
        {
            return Err(Error::ObservationMismatch);
        }

        if !observation.terminal_observed {
            let result = if current.state == MatrixDispatchState::Dispatched
                && current.last_attempt > 0
            {
                self.store
                    .mark_outbox_indeterminate(
                        &txn_id,
                        current.last_attempt,
                        observation.observed_at_ms,
                    )
                    .await
                    .map_err(map_store)?
            } else {
                current.clone()
            };
            let idempotent = result == current;
            return Ok(receipt(&result, idempotent));
        }

        if observation.accepted {
            let event_id = observation
                .server_event_id
                .as_deref()
                .ok_or(Error::TerminalEventMissing)
                .and_then(|value| MatrixEventId::parse(value).map_err(|_| Error::InvalidIdentity))?;
            let idempotent = matches!(
                current.state,
                MatrixDispatchState::Succeeded | MatrixDispatchState::Redacted
            ) && current.terminal_event_id.as_ref() == Some(&event_id)
                && current.send_observation_digest.as_deref()
                    == Some(observation.observation_digest.as_str());
            let result = self
                .store
                .observe_dispatch_terminal_success(
                    &txn_id,
                    &event_id,
                    &observation.observation_digest,
                    observation.observed_at_ms,
                )
                .await
                .map_err(map_store)?;
            Ok(receipt(&result, idempotent))
        } else {
            if observation.server_event_id.is_some() {
                return Err(Error::ObservationMismatch);
            }
            let idempotent = current.state == MatrixDispatchState::Failed
                && current.send_observation_digest.as_deref()
                    == Some(observation.observation_digest.as_str());
            let result = self
                .store
                .observe_dispatch_terminal_failure(
                    &txn_id,
                    &observation.observation_digest,
                    observation.observed_at_ms,
                )
                .await
                .map_err(map_store)?;
            Ok(receipt(&result, idempotent))
        }
    }

    pub async fn apply_redaction(
        &self,
        server_event_id: &str,
        redaction_digest: &str,
        observed_at_ms: u64,
    ) -> Result<SendReceipt, Error> {
        validate_digest(redaction_digest)?;
        let event_id =
            MatrixEventId::parse(server_event_id).map_err(|_| Error::InvalidIdentity)?;
        let result = self
            .store
            .apply_dispatch_redaction(&event_id, redaction_digest, observed_at_ms)
            .await
            .map_err(map_store)?;
        Ok(receipt(&result, false))
    }

    pub async fn receipt(&self, operation_id: &str) -> Result<Option<SendReceipt>, Error> {
        validate_identity(operation_id)?;
        self.store
            .dispatch_record_for_operation(operation_id)
            .await
            .map_err(map_store)
            .map(|value| value.map(|record| receipt(&record, false)))
    }

    pub async fn receipt_for_txn(
        &self,
        transaction_id: &str,
    ) -> Result<Option<SendReceipt>, Error> {
        let txn_id =
            MatrixTransactionId::parse(transaction_id).map_err(|_| Error::InvalidIdentity)?;
        self.store
            .dispatch_record(&txn_id)
            .await
            .map_err(map_store)
            .map(|value| value.map(|record| receipt(&record, false)))
    }
}

fn receipt(record: &MatrixDispatchRecord, idempotent: bool) -> SendReceipt {
    let state = match record.state {
        MatrixDispatchState::Prepared => SendState::Prepared,
        MatrixDispatchState::Succeeded => SendState::Succeeded,
        MatrixDispatchState::Failed => SendState::Failed,
        MatrixDispatchState::Redacted => SendState::Redacted,
        MatrixDispatchState::Dispatched
        | MatrixDispatchState::RetryScheduled
        | MatrixDispatchState::Accepted
        | MatrixDispatchState::Indeterminate
        | MatrixDispatchState::LegacyUnverified => SendState::Indeterminate,
    };
    SendReceipt {
        operation_id: record.operation_id.clone(),
        transaction_id: record.stable_txn_id.as_str().to_string(),
        state,
        server_event_id: record
            .terminal_event_id
            .as_ref()
            .or(record.accepted_event_id.as_ref())
            .map(|value| value.as_str().to_string()),
        send_observation_digest: record.send_observation_digest.clone(),
        redaction_observation_digest: record.redaction_observation_digest.clone(),
        terminal_observed: record.state.is_terminal(),
        idempotent,
    }
}

fn authority_matches(record: &MatrixDispatchRecord, intent: &SendIntent) -> bool {
    record.operation_id == intent.operation_id
        && record.stable_txn_id.as_str() == intent.transaction_id
        && record.homeserver_id.as_deref() == Some(intent.homeserver_id.as_str())
        && record.room_id.as_str() == intent.room_id
        && record.device_id.as_deref() == Some(intent.device_id.as_str())
        && record.session_generation == intent.session_generation
        && record.authority_epoch == Some(intent.authority_epoch)
        && record.payload_digest == intent.payload_digest
        && record.grant_payload_digest.as_deref() == Some(intent.grant_payload_digest.as_str())
        && record.deadline_ms == Some(intent.deadline_ms)
}

fn validate_intent(now_ms: u64, value: &SendIntent) -> Result<(), Error> {
    for field in [
        &value.operation_id,
        &value.transaction_id,
        &value.homeserver_id,
        &value.room_id,
        &value.device_id,
    ] {
        validate_identity(field)?;
    }
    validate_digest(&value.payload_digest)?;
    validate_digest(&value.grant_payload_digest)?;
    if value.session_generation == 0 || value.authority_epoch == 0 {
        return Err(Error::InvalidGeneration);
    }
    if value.deadline_ms <= now_ms {
        return Err(Error::DeadlineExpired);
    }
    Ok(())
}

fn validate_observation(value: &ServerObservation) -> Result<(), Error> {
    for field in [
        &value.operation_id,
        &value.transaction_id,
        &value.homeserver_id,
        &value.room_id,
    ] {
        validate_identity(field)?;
    }
    validate_digest(&value.observation_digest)?;
    if value.session_generation == 0 {
        return Err(Error::InvalidGeneration);
    }
    if let Some(event) = &value.server_event_id {
        validate_identity(event)?;
    }
    Ok(())
}

fn validate_identity(value: &str) -> Result<(), Error> {
    if value.is_empty()
        || value.len() > 255
        || value.chars().any(char::is_whitespace)
        || value.chars().any(char::is_control)
    {
        return Err(Error::InvalidIdentity);
    }
    Ok(())
}

fn validate_digest(value: &str) -> Result<(), Error> {
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(Error::InvalidDigest);
    }
    Ok(())
}

fn map_store(error: MatrixDurableError) -> Error {
    match error {
        MatrixDurableError::Unavailable => Error::StoreUnavailable,
        MatrixDurableError::Invalid => Error::InvalidIdentity,
        MatrixDurableError::AccessDenied
        | MatrixDurableError::Conflict
        | MatrixDurableError::Corrupt => Error::OperationConflict,
    }
}

#[cfg(test)]
#[path = "send_observer_tests.rs"]
mod tests;
