use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use sqlx::Row;
use sqlx::sqlite::SqliteRow;

use crate::AuthBusAdmissionError;
use crate::EvidenceError;
use crate::schema_validation::classify_sqlx_error;

/// Queue bounds are independent of the separately bounded replay-key registry.
pub const AUTHBUS_OUTBOX_MAX_ROWS: i64 = 4096;
pub const AUTHBUS_OUTBOX_MAX_PAYLOAD_BYTES: usize = 16_384;
pub const AUTHBUS_OUTBOX_MAX_ATTEMPTS: i64 = 16;
pub const AUTHBUS_OUTBOX_MAX_LEASE_MS: i64 = 60_000;
pub(crate) const TERMINAL_RETENTION_MS: i64 = 86_400_000;
pub(crate) const TERMINAL_RETAINED_ROWS: i64 = 1024;

#[derive(Debug, thiserror::Error)]
pub enum AuthBusOutboxError {
    #[error(transparent)]
    Admission(#[from] AuthBusAdmissionError),
    #[error(transparent)]
    Storage(#[from] EvidenceError),
    #[error("AuthBus outbox is full; active messages are never evicted")]
    Capacity,
    #[error("AuthBus delivery is absent or its terminal history was pruned")]
    NotFound,
    #[error("AuthBus delivery is unavailable, terminal, or owned by another lease")]
    Unavailable,
    #[error("AuthBus delivery lease has expired or lost its fence")]
    StaleLease,
    #[error("invalid AuthBus delivery request: {0}")]
    InvalidRequest(&'static str),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AuthBusDeliveryState {
    Queued,
    Leased,
    Acked,
    Expired,
    Quarantined,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthBusDeliveryStatus {
    pub delivery_id: Digest32,
    pub issuer_id: StableId,
    pub key_epoch: Generation,
    pub state: AuthBusDeliveryState,
    pub fence: i64,
    pub attempts: i64,
    pub available_at_ms: i64,
    pub lease_until_ms: Option<i64>,
    pub acknowledgement: Option<Digest32>,
}

/// Owner-issued message delivery lease, not authority to perform an effect.
/// A new fence invalidates every token held by the previous worker.
#[derive(Debug)]
pub struct AuthBusLease {
    pub(crate) delivery_id: Digest32,
    pub(crate) worker_id: StableId,
    pub(crate) fence: i64,
    pub(crate) expires_at_ms: i64,
}

impl AuthBusLease {
    pub fn delivery_id(&self) -> Digest32 {
        self.delivery_id
    }

    pub fn expires_at_ms(&self) -> i64 {
        self.expires_at_ms
    }
}

/// Immutable signed message, its bounded payload, and its current delivery lease.
/// Consumers deduplicate by delivery ID before any effect-specific processing.
pub struct AuthBusDelivery {
    pub lease: AuthBusLease,
    pub message: SignedMessage,
    pub payload: Vec<u8>,
}

/// Host-selected routing and ownership. Neither field is inferred from payload.
pub struct AuthBusClaimRequest<'a> {
    pub delivery_id: Digest32,
    pub subject_id: &'a StableId,
    pub scope_digest: Digest32,
    pub worker_id: &'a StableId,
    pub lease_ms: i64,
}

pub(crate) struct OutboxRecord {
    pub message: SignedMessage,
    pub payload: Vec<u8>,
    pub status: AuthBusDeliveryStatus,
    pub worker_id: Option<String>,
    pub updated_at_ms: i64,
}

impl OutboxRecord {
    pub fn decode(row: SqliteRow) -> Result<Self, EvidenceError> {
        let id = |column| -> Result<StableId, EvidenceError> {
            StableId::new(
                row.try_get::<String, _>(column)
                    .map_err(classify_sqlx_error)?,
            )
            .map_err(|_| EvidenceError::Corrupt("invalid AuthBus stored ID".into()))
        };
        let message = SignedMessage {
            claims: SignedMessageClaims {
                issuer_id: id("issuer_id")?,
                key_epoch: Generation::new(u64::from_be_bytes(blob(&row, "key_epoch")?))
                    .map_err(|_| EvidenceError::Corrupt("invalid AuthBus key epoch".into()))?,
                message_id: id("message_id")?,
                subject_id: id("subject_id")?,
                scope_digest: Digest32::from_array(blob(&row, "scope_digest")?),
                payload_digest: Digest32::from_array(blob(&row, "payload_digest")?),
                sequence: u64::from_be_bytes(blob(&row, "sequence")?),
                expires_at_ms: u64::from_be_bytes(blob(&row, "expires_at_ms")?),
            },
            signature: blob(&row, "signature")?,
        };
        let state: String = row.try_get("state").map_err(classify_sqlx_error)?;
        let state = match state.as_str() {
            "queued" => AuthBusDeliveryState::Queued,
            "leased" => AuthBusDeliveryState::Leased,
            "acked" => AuthBusDeliveryState::Acked,
            "expired" => AuthBusDeliveryState::Expired,
            "quarantined" => AuthBusDeliveryState::Quarantined,
            _ => return Err(EvidenceError::Corrupt("invalid AuthBus queue state".into())),
        };
        let acknowledgement: Option<Vec<u8>> = row
            .try_get("acknowledgement")
            .map_err(classify_sqlx_error)?;
        let acknowledgement = acknowledgement
            .map(|bytes| bytes.try_into().map(Digest32::from_array))
            .transpose()
            .map_err(|_| EvidenceError::Corrupt("invalid AuthBus acknowledgement".into()))?;
        let status = AuthBusDeliveryStatus {
            delivery_id: Digest32::from_array(blob(&row, "delivery_id")?),
            issuer_id: message.claims.issuer_id.clone(),
            key_epoch: message.claims.key_epoch,
            state,
            fence: row.try_get("fence").map_err(classify_sqlx_error)?,
            attempts: row.try_get("attempts").map_err(classify_sqlx_error)?,
            available_at_ms: row
                .try_get("available_at_ms")
                .map_err(classify_sqlx_error)?,
            lease_until_ms: row.try_get("lease_until_ms").map_err(classify_sqlx_error)?,
            acknowledgement,
        };
        let payload: Vec<u8> = row.try_get("payload").map_err(classify_sqlx_error)?;
        if payload.len() > AUTHBUS_OUTBOX_MAX_PAYLOAD_BYTES
            || Digest32::of_bytes(&payload) != message.claims.payload_digest
        {
            return Err(EvidenceError::Corrupt(
                "invalid AuthBus stored payload".into(),
            ));
        }
        Ok(Self {
            message,
            payload,
            status,
            worker_id: row.try_get("worker_id").map_err(classify_sqlx_error)?,
            updated_at_ms: row.try_get("updated_at_ms").map_err(classify_sqlx_error)?,
        })
    }
}

fn blob<const N: usize>(row: &SqliteRow, column: &str) -> Result<[u8; N], EvidenceError> {
    row.try_get::<Vec<u8>, _>(column)
        .map_err(classify_sqlx_error)?
        .try_into()
        .map_err(|_| EvidenceError::Corrupt(format!("invalid AuthBus {column} width")))
}
