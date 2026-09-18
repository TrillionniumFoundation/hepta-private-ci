#![forbid(unsafe_code)]

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixTransactionId;
use codex_hepta_matrix_store::MatrixDispatchRecord;
use codex_hepta_matrix_store::MatrixDispatchState;
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
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    InvalidIdentity(&'static str),
    InvalidDigest(&'static str),
    InvalidGeneration,
    DeadlineExpired,
    PayloadMismatch,
    OperationConflict,
    SendNotFound,
    ObservationMismatch,
    TerminalEventMissing,
    Store,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

/// Thin compatibility facade over MatrixDurableStore.
///
/// This type intentionally owns no send map, event map, queue, sender, or
/// terminal truth. All dispatch state lives in the canonical durable owner.
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
            MatrixTransactionId::parse(&intent.transaction_id).map_err(|_| Error::InvalidIdentity("transaction"))?;
        let room_id =
            MatrixRoomId::parse(&intent.room_id).map_err(|_| Error::InvalidIdentity("room"))?;
        let record = self
            .store
            .dispatch_for_txn(&txn_id)
            .await
            .map_err(|_| Error::Store)?
            .ok_or(Error::SendNotFound)?;
        if record.operation_id != intent.operation_id
            || record.room_id != room_id
            || record.generation != intent.session_generation
            || record.payload_sha256 != intent.payload_digest
            || record
                .authority_epoch
                .is_some_and(|epoch| epoch != intent.authority_epoch)
            || record
                .grant_payload_digest
                .as_deref()
                .is_some_and(|digest| digest != intent.grant_payload_digest)
        {
            return Err(Error::OperationConflict);
        }
        Ok(receipt_from_record(&record))
    }

    pub async fn observe_send(
        &self,
        observed_at_ms: u64,
        observation: ServerObservation,
    ) -> Result<SendReceipt, Error> {
        validate_observation(&observation)?;
        let txn_id = MatrixTransactionId::parse(&observation.transaction_id)
            .map_err(|_| Error::InvalidIdentity("transaction"))?;
        let room_id =
            MatrixRoomId::parse(&observation.room_id).map_err(|_| Error::InvalidIdentity("room"))?;
        let current = self
            .store
            .dispatch_for_txn(&txn_id)
            .await
            .map_err(|_| Error::Store)?
            .ok_or(Error::SendNotFound)?;
        if current.operation_id != observation.operation_id
            || current.room_id != room_id
            || current.generation != observation.session_generation
        {
            return Err(Error::ObservationMismatch);
        }
        let record = if !observation.terminal_observed {
            self.store
                .record_transport_indeterminate(&txn_id, current.last_attempt, observed_at_ms)
                .await
                .map_err(|_| Error::Store)?
        } else if observation.accepted {
            let event_id = observation
                .server_event_id
                .as_deref()
                .ok_or(Error::TerminalEventMissing)
                .and_then(|value| {
                    MatrixEventId::parse(value)
                        .map_err(|_| Error::InvalidIdentity("server event"))
                })?;
            let digest = Sha256Digest::parse(observation.observation_digest)
                .map_err(|_| Error::InvalidDigest("observation"))?;
            self.store
                .observe_outbox_server_event(
                    &txn_id,
                    &room_id,
                    &event_id,
                    &digest,
                    observed_at_ms,
                )
                .await
                .map_err(|_| Error::Store)?
                .ok_or(Error::SendNotFound)?
        } else {
            if observation.server_event_id.is_some() {
                return Err(Error::ObservationMismatch);
            }
            self.store
                .mark_outbox_permanent_failure(&txn_id, current.last_attempt, observed_at_ms)
                .await
                .map_err(|_| Error::Store)?;
            self.store
                .record_transport_terminal_failure(
                    &txn_id,
                    current.last_attempt,
                    observed_at_ms,
                )
                .await
                .map_err(|_| Error::Store)?
        };
        Ok(receipt_from_record(&record))
    }

    pub async fn apply_redaction(
        &self,
        observed_at_ms: u64,
        server_event_id: &str,
        redaction_event_id: &str,
        redaction_digest: &str,
    ) -> Result<SendReceipt, Error> {
        let server_event_id = MatrixEventId::parse(server_event_id)
            .map_err(|_| Error::InvalidIdentity("server event"))?;
        let redaction_event_id = MatrixEventId::parse(redaction_event_id)
            .map_err(|_| Error::InvalidIdentity("redaction event"))?;
        let digest = Sha256Digest::parse(redaction_digest)
            .map_err(|_| Error::InvalidDigest("redaction"))?;
        let record = self
            .store
            .observe_outbox_redaction(
                &server_event_id,
                &redaction_event_id,
                &digest,
                observed_at_ms,
            )
            .await
            .map_err(|_| Error::Store)?
            .ok_or(Error::SendNotFound)?;
        Ok(receipt_from_record(&record))
    }

    pub async fn receipt(&self, transaction_id: &str) -> Result<Option<SendReceipt>, Error> {
        let txn_id = MatrixTransactionId::parse(transaction_id)
            .map_err(|_| Error::InvalidIdentity("transaction"))?;
        self.store
            .dispatch_for_txn(&txn_id)
            .await
            .map_err(|_| Error::Store)
            .map(|record| record.as_ref().map(receipt_from_record))
    }
}

fn receipt_from_record(record: &MatrixDispatchRecord) -> SendReceipt {
    let state = match record.state {
        MatrixDispatchState::Dispatched => SendState::Prepared,
        MatrixDispatchState::Accepted | MatrixDispatchState::Indeterminate => {
            SendState::Indeterminate
        }
        MatrixDispatchState::ObservedTerminal => SendState::Succeeded,
        MatrixDispatchState::TerminalFailure => SendState::Failed,
        MatrixDispatchState::Redacted => SendState::Redacted,
    };
    SendReceipt {
        operation_id: record.operation_id.clone(),
        transaction_id: record.stable_txn_id.as_str().to_string(),
        state,
        server_event_id: record
            .terminal_event_id
            .as_ref()
            .map(|event_id| event_id.as_str().to_string()),
        send_observation_digest: record.send_observation_digest.clone(),
        redaction_observation_digest: record.redaction_observation_digest.clone(),
        terminal_observed: matches!(
            record.state,
            MatrixDispatchState::ObservedTerminal
                | MatrixDispatchState::TerminalFailure
                | MatrixDispatchState::Redacted
        ),
    }
}

fn validate_intent(now_ms: u64, value: &SendIntent) -> Result<(), Error> {
    for (field, name) in [
        (&value.operation_id, "operation"),
        (&value.transaction_id, "transaction"),
        (&value.homeserver_id, "homeserver"),
        (&value.room_id, "room"),
        (&value.device_id, "device"),
    ] {
        validate_identity(field, name)?;
    }
    validate_digest(&value.payload_digest, "payload")?;
    validate_digest(&value.grant_payload_digest, "grant payload")?;
    if value.session_generation == 0 || value.authority_epoch == 0 {
        return Err(Error::InvalidGeneration);
    }
    if value.deadline_ms <= now_ms {
        return Err(Error::DeadlineExpired);
    }
    Ok(())
}

fn validate_observation(value: &ServerObservation) -> Result<(), Error> {
    for (field, name) in [
        (&value.operation_id, "operation"),
        (&value.transaction_id, "transaction"),
        (&value.homeserver_id, "homeserver"),
        (&value.room_id, "room"),
    ] {
        validate_identity(field, name)?;
    }
    validate_digest(&value.observation_digest, "observation")?;
    if value.session_generation == 0 {
        return Err(Error::InvalidGeneration);
    }
    if let Some(event) = &value.server_event_id {
        validate_identity(event, "server event")?;
    }
    Ok(())
}

fn validate_identity(value: &str, field: &'static str) -> Result<(), Error> {
    if value.is_empty()
        || value.len() > 255
        || value.chars().any(char::is_whitespace)
        || value.chars().any(char::is_control)
    {
        return Err(Error::InvalidIdentity(field));
    }
    Ok(())
}

fn validate_digest(value: &str, field: &'static str) -> Result<(), Error> {
    Sha256Digest::parse(value.to_string())
        .map(|_| ())
        .map_err(|_| Error::InvalidDigest(field))
}
