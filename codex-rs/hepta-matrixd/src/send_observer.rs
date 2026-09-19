#![forbid(unsafe_code)]

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixTransactionId;
use codex_hepta_matrix_store::MatrixDispatchRecord;
use codex_hepta_matrix_store::MatrixDurableError;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::OutboxRecord;

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

/// Thin compatibility adapter over MatrixDurableStore.
///
/// This type owns no send state. The canonical dispatch ledger, transaction
/// identity, evidence history and crash recovery all live in MatrixDurableStore.
pub struct MatrixSendObserver<'a> {
    store: &'a MatrixDurableStore,
}

impl<'a> MatrixSendObserver<'a> {
    pub fn new(store: &'a MatrixDurableStore) -> Self {
        Self { store }
    }

    pub async fn prepare_send(
        &self,
        now_ms: u64,
        outbox: &OutboxRecord,
        intent: &SendIntent,
    ) -> Result<MatrixDispatchRecord, MatrixDurableError> {
        validate_intent(now_ms, intent)?;
        let txn_id =
            MatrixTransactionId::parse(&intent.transaction_id).map_err(|_| MatrixDurableError::Invalid)?;
        let room_id =
            MatrixRoomId::parse(&intent.room_id).map_err(|_| MatrixDurableError::Invalid)?;
        if txn_id != outbox.stable_txn_id
            || room_id != outbox.room_id
            || intent.payload_digest != Sha256Digest::for_bytes(&outbox.payload).as_str()
            || intent.payload_digest != intent.grant_payload_digest
        {
            return Err(MatrixDurableError::Conflict);
        }
        self.store.prepare_dispatch(outbox, now_ms).await?;
        self.store
            .bind_dispatch_authority(
                &txn_id,
                &intent.operation_id,
                &intent.homeserver_id,
                &intent.device_id,
                intent.session_generation,
                intent.authority_epoch,
                &intent.grant_payload_digest,
                intent.deadline_ms,
                now_ms,
            )
            .await
    }

    pub async fn observe_send(
        &self,
        observed_at_ms: u64,
        observation: &ServerObservation,
    ) -> Result<Option<MatrixDispatchRecord>, MatrixDurableError> {
        validate_observation(observation)?;
        let txn_id =
            MatrixTransactionId::parse(&observation.transaction_id).map_err(|_| MatrixDurableError::Invalid)?;
        let room_id =
            MatrixRoomId::parse(&observation.room_id).map_err(|_| MatrixDurableError::Invalid)?;
        let current = self.store.dispatch_record(&txn_id).await?;
        let Some(current) = current else {
            return Ok(None);
        };
        if current.operation_id != observation.operation_id
            || current.homeserver_id.as_deref() != Some(observation.homeserver_id.as_str())
            || current.session_generation != Some(observation.session_generation)
            || current.room_id != observation.room_id
        {
            return Err(MatrixDurableError::Conflict);
        }
        if !observation.terminal_observed {
            self.store
                .mark_dispatch_indeterminate(&txn_id, observed_at_ms)
                .await?;
            return self.store.dispatch_record(&txn_id).await;
        }
        if observation.accepted {
            let event_id = observation
                .server_event_id
                .as_deref()
                .ok_or(MatrixDurableError::Invalid)
                .and_then(|value| {
                    MatrixEventId::parse(value).map_err(|_| MatrixDurableError::Invalid)
                })?;
            self.store
                .observe_dispatch_terminal_success_if_known(
                    &txn_id,
                    &room_id,
                    &event_id,
                    &observation.observation_digest,
                    observed_at_ms,
                )
                .await?;
        } else {
            if observation.server_event_id.is_some() {
                return Err(MatrixDurableError::Conflict);
            }
            self.store
                .observe_dispatch_terminal_failure_if_known(
                    &txn_id,
                    &room_id,
                    &observation.observation_digest,
                    observed_at_ms,
                )
                .await?;
        }
        self.store.dispatch_record(&txn_id).await
    }

    pub async fn apply_redaction(
        &self,
        room_id: &str,
        server_event_id: &str,
        redaction_digest: &str,
        observed_at_ms: u64,
    ) -> Result<bool, MatrixDurableError> {
        let room_id = MatrixRoomId::parse(room_id).map_err(|_| MatrixDurableError::Invalid)?;
        let event_id =
            MatrixEventId::parse(server_event_id).map_err(|_| MatrixDurableError::Invalid)?;
        self.store
            .observe_dispatch_redaction_if_known(
                &room_id,
                &event_id,
                redaction_digest,
                observed_at_ms,
            )
            .await
    }
}

fn validate_intent(now_ms: u64, value: &SendIntent) -> Result<(), MatrixDurableError> {
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
    if value.session_generation == 0
        || value.authority_epoch == 0
        || value.deadline_ms <= now_ms
    {
        return Err(MatrixDurableError::Invalid);
    }
    Ok(())
}

fn validate_observation(value: &ServerObservation) -> Result<(), MatrixDurableError> {
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
        return Err(MatrixDurableError::Invalid);
    }
    if let Some(event) = &value.server_event_id {
        validate_identity(event)?;
    }
    Ok(())
}

fn validate_identity(value: &str) -> Result<(), MatrixDurableError> {
    if value.is_empty()
        || value.len() > 255
        || value.chars().any(char::is_whitespace)
        || value.chars().any(char::is_control)
    {
        return Err(MatrixDurableError::Invalid);
    }
    Ok(())
}

fn validate_digest(value: &str) -> Result<(), MatrixDurableError> {
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(MatrixDurableError::Invalid);
    }
    Ok(())
}
