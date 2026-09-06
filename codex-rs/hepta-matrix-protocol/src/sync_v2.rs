//! Owner-local native types for the Matrix sync persistence seam.
//!
//! They are not a registered Hepta inter-module or network contract. Callers
//! outside the `channel.matrix` owner boundary must not depend on them.

use std::collections::BTreeSet;

use crate::MatrixEventId;
use crate::MatrixProtocolError;
use crate::MatrixRoomId;
use crate::MatrixUserId;

/// Version of the owner-local typed persistence seam.
///
/// This is not a registered cross-module wire schema. These types deliberately
/// do not implement `Deserialize`; an eventual ingress contract must impose an
/// encoded-frame bound before decoding and provide provenance/completeness
/// evidence outside this seam.
pub const MATRIX_SYNC_MUTATION_SCHEMA_VERSION_V2: u32 = 2;
pub const MAX_MATRIX_SYNC_MUTATIONS_V2: usize = 512;
pub const MAX_MATRIX_SYNC_BATCH_PAYLOAD_BYTES_V2: usize = 16 * 1024 * 1024;
const MAX_MATRIX_SYNC_TOKEN_BYTES: usize = 4_096;
const MAX_MATRIX_SYNC_OPERATION_ID_BYTES: usize = 128;
const MAX_MATRIX_SYNC_EVENT_TYPE_BYTES: usize = 128;
const MAX_MATRIX_SYNC_PAYLOAD_BYTES: usize = 1024 * 1024;

/// One caller-normalized Matrix `/sync` batch of explicit mutations.
///
/// This is additive to the V1 message-only inbox contract. It carries no
/// authority claim. The checkpoint revision and generation fence the Agent's
/// account-wide cursor only; every mutation carries its own room binding
/// fence. The type does not attest server provenance or completeness.
#[derive(Clone, Eq, PartialEq)]
pub struct MatrixSyncBatchV2 {
    pub schema_version: u32,
    /// Caller-stable idempotency identity for lost-response reconciliation.
    pub operation_id: String,
    /// Account-wide cursor CAS epoch; it is not any room's binding revision.
    pub checkpoint_revision: u64,
    /// Account-wide cursor generation; room generations live on mutations.
    pub checkpoint_generation: u64,
    pub expected_next_batch: Option<String>,
    pub next_batch: String,
    pub observed_at_ms: u64,
    pub mutations: Vec<MatrixSyncMutationV2>,
}

impl MatrixSyncBatchV2 {
    pub fn validate(&self) -> Result<(), MatrixProtocolError> {
        if self.schema_version != MATRIX_SYNC_MUTATION_SCHEMA_VERSION_V2
            || self.checkpoint_revision == 0
            || self.checkpoint_generation == 0
            || self.mutations.len() > MAX_MATRIX_SYNC_MUTATIONS_V2
        {
            return Err(invalid("Matrix sync V2 batch metadata is invalid"));
        }
        validate_operation_id(&self.operation_id)?;
        validate_sync_token(&self.next_batch)?;
        if let Some(expected) = &self.expected_next_batch {
            validate_sync_token(expected)?;
        }
        let mut source_event_ids = BTreeSet::new();
        let mut payload_bytes = 0_usize;
        for mutation in &self.mutations {
            mutation.validate()?;
            if let MatrixSyncMutationBodyV2::Timeline { payload, .. } = &mutation.body {
                payload_bytes = payload_bytes
                    .checked_add(payload.len())
                    .ok_or_else(|| invalid("Matrix sync V2 batch payload size overflowed"))?;
                if payload_bytes > MAX_MATRIX_SYNC_BATCH_PAYLOAD_BYTES_V2 {
                    return Err(invalid("Matrix sync V2 batch payload is out of bounds"));
                }
            }
            if mutation.received_at_ms > self.observed_at_ms {
                return Err(invalid(
                    "Matrix sync V2 mutation cannot postdate its enclosing batch",
                ));
            }
            if !source_event_ids.insert(&mutation.source_event_id) {
                return Err(invalid(
                    "Matrix sync V2 source event identities must be unique within a batch",
                ));
            }
        }
        Ok(())
    }
}

/// A caller's explicit choice to persist its normalized observations or cancel.
///
/// Cancellation is not success and must leave the durable cursor unchanged.
#[derive(Clone, Eq, PartialEq)]
pub enum MatrixSyncDecisionV2 {
    Commit { batch: MatrixSyncBatchV2 },
    Cancel {
        schema_version: u32,
        operation_id: String,
        checkpoint_revision: u64,
        checkpoint_generation: u64,
        expected_next_batch: Option<String>,
    },
}

impl MatrixSyncDecisionV2 {
    pub fn validate(&self) -> Result<(), MatrixProtocolError> {
        match self {
            Self::Commit { batch } => batch.validate(),
            Self::Cancel {
                schema_version,
                operation_id,
                checkpoint_revision,
                checkpoint_generation,
                expected_next_batch,
            } => {
                if *schema_version != MATRIX_SYNC_MUTATION_SCHEMA_VERSION_V2
                    || *checkpoint_revision == 0
                    || *checkpoint_generation == 0
                {
                    return Err(invalid("Matrix sync V2 cancellation fence is invalid"));
                }
                validate_operation_id(operation_id)?;
                if let Some(expected) = expected_next_batch {
                    validate_sync_token(expected)?;
                }
                Ok(())
            }
        }
    }
}

/// One untrusted sync mutation observation; this type grants no authority.
/// Its binding fence applies only to `room_id`, so one account sync page can
/// safely contain rooms at different binding revisions.
#[derive(Clone, Eq, PartialEq)]
pub struct MatrixSyncMutationV2 {
    pub source_event_id: MatrixEventId,
    pub room_id: MatrixRoomId,
    pub sender: MatrixUserId,
    pub binding_revision: u64,
    pub generation: u64,
    pub origin_server_ts_ms: u64,
    pub received_at_ms: u64,
    pub body: MatrixSyncMutationBodyV2,
}

impl MatrixSyncMutationV2 {
    pub fn validate(&self) -> Result<(), MatrixProtocolError> {
        if self.binding_revision == 0 || self.generation == 0 {
            return Err(invalid("Matrix sync V2 mutation binding fence is invalid"));
        }
        match &self.body {
            MatrixSyncMutationBodyV2::Timeline {
                event_type,
                payload,
            } => {
                validate_event_type(event_type)?;
                if payload.is_empty() || payload.len() > MAX_MATRIX_SYNC_PAYLOAD_BYTES {
                    return Err(invalid("Matrix sync V2 timeline payload is out of bounds"));
                }
            }
            MatrixSyncMutationBodyV2::Redaction { target_event_id } => {
                if target_event_id == &self.source_event_id {
                    return Err(invalid("Matrix redaction cannot target its source event"));
                }
            }
            MatrixSyncMutationBodyV2::RoomLeave { .. } => {}
            MatrixSyncMutationBodyV2::RoomTombstone {
                replacement_room_id,
            } => {
                if replacement_room_id == &self.room_id {
                    return Err(invalid("Matrix room tombstone replacement must differ"));
                }
            }
        }
        Ok(())
    }
}

/// Native mutation body for the owner-local store candidate.
///
/// It deliberately implements neither serde direction. The durable store
/// constructs a bounded digest projection explicitly, so this type cannot be
/// mistaken for an admitted wire decoder or encoder.
#[derive(Clone, Eq, PartialEq)]
pub enum MatrixSyncMutationBodyV2 {
    Timeline {
        event_type: String,
        payload: Vec<u8>,
    },
    Redaction {
        target_event_id: MatrixEventId,
    },
    RoomLeave {
        departed_user_id: MatrixUserId,
    },
    RoomTombstone {
        replacement_room_id: MatrixRoomId,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MatrixSyncMutationDispositionV2 {
    Applied,
    Duplicate,
    /// The redaction target was absent; its anti-resurrection tombstone was persisted.
    Missing,
    /// A prior event- or room-scoped tombstone suppressed this timeline event.
    Tombstoned,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MatrixSyncMutationOutcomeV2 {
    pub source_event_id: MatrixEventId,
    pub disposition: MatrixSyncMutationDispositionV2,
}

/// Durable outcome of an explicit V2 decision. `Committed` reports only the
/// atomic persistence boundary; each mutation disposition remains mandatory
/// to inspect and `Missing` is not relabeled as applied. `Cancelled` is
/// disjoint from a committed transaction and cannot advance `next_batch`.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum MatrixSyncResultV2 {
    Committed {
        schema_version: u32,
        operation_id: String,
        checkpoint_revision: u64,
        checkpoint_generation: u64,
        next_batch: String,
        outcomes: Vec<MatrixSyncMutationOutcomeV2>,
    },
    Cancelled {
        schema_version: u32,
        operation_id: String,
        checkpoint_revision: u64,
        checkpoint_generation: u64,
        retained_next_batch: Option<String>,
    },
    /// The immutable local journal has reached its fixed hard bound.
    /// Nothing was persisted and the cursor did not advance; blind retry is
    /// not a recovery action for this terminal local-store condition.
    CapacityExhausted {
        schema_version: u32,
        operation_id: String,
        checkpoint_revision: u64,
        checkpoint_generation: u64,
    },
}

fn validate_operation_id(value: &str) -> Result<(), MatrixProtocolError> {
    if !(1..=MAX_MATRIX_SYNC_OPERATION_ID_BYTES).contains(&value.len())
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'-'))
    {
        return Err(invalid("Matrix sync V2 operation identity is invalid"));
    }
    Ok(())
}

fn validate_sync_token(value: &str) -> Result<(), MatrixProtocolError> {
    if !(1..=MAX_MATRIX_SYNC_TOKEN_BYTES).contains(&value.len())
        || !value.bytes().all(|byte| (b' '..=b'~').contains(&byte))
    {
        return Err(invalid("Matrix sync V2 token is out of bounds"));
    }
    Ok(())
}

fn validate_event_type(value: &str) -> Result<(), MatrixProtocolError> {
    if !(1..=MAX_MATRIX_SYNC_EVENT_TYPE_BYTES).contains(&value.len())
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
    {
        return Err(invalid("Matrix sync V2 event type is invalid"));
    }
    Ok(())
}

fn invalid(message: &str) -> MatrixProtocolError {
    MatrixProtocolError::Invalid(message.to_string())
}
