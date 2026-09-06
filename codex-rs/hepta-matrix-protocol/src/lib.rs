//! Typed local contracts for one Hepta workspace Agent's Matrix sidecar.
//!
//! This crate deliberately contains no Matrix SDK, SQLite, App Server, or
//! supervisor implementation. Matrix timeline events never implement this
//! owner-local control protocol and therefore cannot approve tools or cancel a
//! turn.

#![forbid(unsafe_code)]

use std::collections::BTreeSet;
use std::fmt;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

mod sync_v2;

// Cross-crate visibility is required only because the Matrix store is a
// separate crate inside the same `channel.matrix` ownership boundary. These
// hidden exports are not an admitted inter-module protocol surface.
#[doc(hidden)]
pub use sync_v2::{
    MATRIX_SYNC_MUTATION_SCHEMA_VERSION_V2, MAX_MATRIX_SYNC_BATCH_PAYLOAD_BYTES_V2,
    MAX_MATRIX_SYNC_MUTATIONS_V2, MatrixSyncBatchV2, MatrixSyncDecisionV2,
    MatrixSyncMutationBodyV2, MatrixSyncMutationDispositionV2, MatrixSyncMutationOutcomeV2,
    MatrixSyncMutationV2, MatrixSyncResultV2,
};

pub const MATRIX_BINDING_SCHEMA_VERSION: u32 = 1;
pub const MATRIXD_CONTROL_SCHEMA_VERSION: u32 = 2;
/// One bounded owner-local control frame.
///
/// The bound is deliberately large enough for the protocol's maximum
/// approval/event batch and room roster, while still limiting each of the 32
/// concurrent UDS connections to one MiB of request/response buffering.
pub const MAX_MATRIXD_CONTROL_FRAME_BYTES: u64 = 1_048_576;
pub const MAX_MATRIXD_EVENT_BATCH: u16 = 256;
pub const MAX_PENDING_APPROVALS: usize = 256;
pub const MAX_PENDING_APPROVAL_SUMMARY_BYTES: usize = 1_024;
pub const MAX_RUNTIME_IDENTIFIER_BYTES: usize = 512;
pub const MAX_MATRIXD_ERROR_CODE_BYTES: usize = 64;
pub const MAX_MATRIXD_ERROR_MESSAGE_BYTES: usize = 1_024;
const MAX_MATRIX_IDENTIFIER_BYTES: usize = 255;
const MAX_MATRIX_BINDING_ENTRIES: usize = 256;
const CLIENT_MESSAGE_ID_DOMAIN: &[u8] = b"hepta.matrix.client-user-message.v1";
const ROOM_PROJECT_IDEMPOTENCY_DOMAIN: &[u8] = b"hepta.matrix.room-project.v1";
const OUTBOX_ID_DOMAIN: &[u8] = b"hepta.matrix.outbox.v1";
const MATRIX_TRANSACTION_ID_DOMAIN: &[u8] = b"hepta.matrix.transaction.v1";

macro_rules! matrix_server_identifier {
    ($name:ident, $prefix:literal, $label:literal) => {
        #[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
        #[serde(try_from = "String", into = "String")]
        pub struct $name(String);

        impl $name {
            pub fn parse(value: impl Into<String>) -> Result<Self, MatrixProtocolError> {
                let value = value.into();
                validate_matrix_server_identifier(&value, $prefix, $label)?;
                Ok(Self(value))
            }

            pub fn as_str(&self) -> &str {
                &self.0
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str(&self.0)
            }
        }

        impl TryFrom<String> for $name {
            type Error = MatrixProtocolError;

            fn try_from(value: String) -> Result<Self, Self::Error> {
                Self::parse(value)
            }
        }

        impl From<$name> for String {
            fn from(value: $name) -> Self {
                value.0
            }
        }
    };
}

matrix_server_identifier!(MatrixRoomId, '!', "Matrix room ID");
matrix_server_identifier!(MatrixUserId, '@', "Matrix user ID");

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(try_from = "String", into = "String")]
pub struct MatrixEventId(String);

impl MatrixEventId {
    pub fn parse(value: impl Into<String>) -> Result<Self, MatrixProtocolError> {
        let value = value.into();
        validate_opaque_identifier(&value, "Matrix event ID")?;
        if !value.starts_with('$') || value.len() == 1 {
            return Err(MatrixProtocolError::Invalid(
                "Matrix event ID must begin with '$' and include an opaque event identifier"
                    .to_string(),
            ));
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for MatrixEventId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl TryFrom<String> for MatrixEventId {
    type Error = MatrixProtocolError;

    fn try_from(value: String) -> Result<Self, Self::Error> {
        Self::parse(value)
    }
}

impl From<MatrixEventId> for String {
    fn from(value: MatrixEventId) -> Self {
        value.0
    }
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(try_from = "String", into = "String")]
pub struct MatrixDeviceId(String);

impl MatrixDeviceId {
    pub fn parse(value: impl Into<String>) -> Result<Self, MatrixProtocolError> {
        let value = value.into();
        validate_opaque_identifier(&value, "Matrix device ID")?;
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl TryFrom<String> for MatrixDeviceId {
    type Error = MatrixProtocolError;

    fn try_from(value: String) -> Result<Self, Self::Error> {
        Self::parse(value)
    }
}

impl From<MatrixDeviceId> for String {
    fn from(value: MatrixDeviceId) -> Self {
        value.0
    }
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(try_from = "String", into = "String")]
pub struct MatrixTransactionId(String);

impl MatrixTransactionId {
    pub fn parse(value: impl Into<String>) -> Result<Self, MatrixProtocolError> {
        let value = value.into();
        validate_opaque_identifier(&value, "Matrix transaction ID")?;
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for MatrixTransactionId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl TryFrom<String> for MatrixTransactionId {
    type Error = MatrixProtocolError;

    fn try_from(value: String) -> Result<Self, Self::Error> {
        Self::parse(value)
    }
}

impl From<MatrixTransactionId> for String {
    fn from(value: MatrixTransactionId) -> Self {
        value.0
    }
}

/// Stable App Server idempotency identity for one exact Matrix timeline event.
pub fn client_user_message_id(
    agent_id: &AgentId,
    room_id: &MatrixRoomId,
    event_id: &MatrixEventId,
) -> String {
    format!(
        "hepta-matrix-v1-{}",
        framed_digest(
            CLIENT_MESSAGE_ID_DOMAIN,
            &[
                agent_id.as_str().as_bytes(),
                room_id.as_str().as_bytes(),
                event_id.as_str().as_bytes(),
            ],
        )
        .as_str()
    )
}

/// Stable key used with Codex App Server's idempotent `project/create` API.
pub fn room_project_idempotency_key(agent_id: &AgentId, room_id: &MatrixRoomId) -> String {
    format!(
        "hepta-matrix-room-v1-{}",
        framed_digest(
            ROOM_PROJECT_IDEMPOTENCY_DOMAIN,
            &[agent_id.as_str().as_bytes(), room_id.as_str().as_bytes()],
        )
        .as_str()
    )
}

/// Stable logical identity for one outbound Matrix projection.
pub fn outbox_id(
    agent_id: &AgentId,
    room_id: &MatrixRoomId,
    thread_id: &str,
    turn_id: &str,
    item_id: &str,
    kind: &str,
) -> String {
    framed_digest(
        OUTBOX_ID_DOMAIN,
        &[
            agent_id.as_str().as_bytes(),
            room_id.as_str().as_bytes(),
            thread_id.as_bytes(),
            turn_id.as_bytes(),
            item_id.as_bytes(),
            kind.as_bytes(),
        ],
    )
    .as_str()
    .to_string()
}

/// Stable Matrix transaction ID for one immutable outbox revision.
pub fn transaction_id(
    logical_outbox_id: &str,
    revision: u64,
) -> Result<MatrixTransactionId, MatrixProtocolError> {
    let revision = revision.to_be_bytes();
    MatrixTransactionId::parse(format!(
        "hepta-v1-{}",
        framed_digest(
            MATRIX_TRANSACTION_ID_DOMAIN,
            &[logical_outbox_id.as_bytes(), &revision],
        )
        .as_str()
    ))
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(try_from = "String", into = "String")]
pub struct MatrixHomeserverUrl(String);

impl MatrixHomeserverUrl {
    pub fn parse(value: impl Into<String>) -> Result<Self, MatrixProtocolError> {
        let value = value.into();
        let parsed = url::Url::parse(&value).map_err(|_| {
            MatrixProtocolError::Invalid("Matrix homeserver URL is invalid".to_string())
        })?;
        let secure = parsed.scheme() == "https";
        let local_http = parsed.scheme() == "http"
            && match parsed.host() {
                Some(url::Host::Domain(host)) => host.eq_ignore_ascii_case("localhost"),
                Some(url::Host::Ipv4(ip)) => ip.is_loopback(),
                Some(url::Host::Ipv6(ip)) => ip.is_loopback(),
                None => false,
            };
        if !secure && !local_http {
            return Err(MatrixProtocolError::Invalid(
                "Matrix homeserver must use HTTPS, except loopback HTTP in local tests".to_string(),
            ));
        }
        if parsed.username() != ""
            || parsed.password().is_some()
            || parsed.query().is_some()
            || parsed.fragment().is_some()
        {
            return Err(MatrixProtocolError::Invalid(
                "Matrix homeserver URL must not contain credentials, query, or fragment"
                    .to_string(),
            ));
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl TryFrom<String> for MatrixHomeserverUrl {
    type Error = MatrixProtocolError;

    fn try_from(value: String) -> Result<Self, Self::Error> {
        Self::parse(value)
    }
}

impl From<MatrixHomeserverUrl> for String {
    fn from(value: MatrixHomeserverUrl) -> Self {
        value.0
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MatrixBindingV1 {
    pub schema_version: u32,
    pub agent_id: AgentId,
    pub revision: u64,
    pub homeserver: MatrixHomeserverUrl,
    pub expected_mxid: MatrixUserId,
    pub expected_device_id: MatrixDeviceId,
    pub allowed_rooms: Vec<MatrixRoomId>,
    pub allowed_senders: Vec<MatrixUserId>,
    pub require_explicit_mention: bool,
}

impl MatrixBindingV1 {
    pub fn validate(&self) -> Result<(), MatrixProtocolError> {
        if self.schema_version != MATRIX_BINDING_SCHEMA_VERSION || self.revision == 0 {
            return Err(MatrixProtocolError::Invalid(
                "Matrix binding schema and revision must be current and non-zero".to_string(),
            ));
        }
        validate_unique_bounded(&self.allowed_rooms, "allowed Matrix rooms")?;
        validate_unique_bounded(&self.allowed_senders, "allowed Matrix senders")?;
        if self.allowed_rooms.is_empty() || self.allowed_senders.is_empty() {
            return Err(MatrixProtocolError::Invalid(
                "Matrix binding must allow at least one exact room and sender".to_string(),
            ));
        }
        Ok(())
    }
}

pub fn matrix_binding_digest(
    binding: &MatrixBindingV1,
) -> Result<Sha256Digest, MatrixProtocolError> {
    binding.validate()?;
    serde_json::to_vec(binding)
        .map(|bytes| Sha256Digest::for_bytes(&bytes))
        .map_err(|error| MatrixProtocolError::Invalid(error.to_string()))
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MatrixdFence {
    pub binding_revision: u64,
    pub binding_digest: Sha256Digest,
    pub attached_agent_generation: u64,
    pub process_incarnation: String,
    pub plane_epoch: u64,
}

impl MatrixdFence {
    pub fn validate(&self) -> Result<(), MatrixProtocolError> {
        if self.binding_revision == 0
            || self.attached_agent_generation == 0
            || self.plane_epoch == 0
        {
            return Err(MatrixProtocolError::Invalid(
                "Matrix fence generations, revision, and epoch must be non-zero".to_string(),
            ));
        }
        Sha256Digest::parse(self.binding_digest.as_str().to_string()).map_err(|error| {
            MatrixProtocolError::Invalid(format!("Matrix binding digest is invalid: {error}"))
        })?;
        validate_runtime_identifier(&self.process_incarnation, "Matrix process incarnation")?;
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MatrixdRequest {
    pub schema_version: u32,
    pub request_id: u64,
    pub agent_id: AgentId,
    pub fence: Option<MatrixdFence>,
    pub method: MatrixdMethod,
}

impl MatrixdRequest {
    pub fn validate(&self) -> Result<(), MatrixProtocolError> {
        if self.schema_version != MATRIXD_CONTROL_SCHEMA_VERSION || self.request_id == 0 {
            return Err(MatrixProtocolError::Invalid(
                "Matrix control schema must be current and request ID non-zero".to_string(),
            ));
        }
        match (&self.method, &self.fence) {
            (MatrixdMethod::Health | MatrixdMethod::Snapshot, None) => Ok(()),
            (MatrixdMethod::Health | MatrixdMethod::Snapshot, Some(_)) => {
                Err(MatrixProtocolError::Invalid(
                    "Matrix Health and Snapshot are unfenced bootstrap methods".to_string(),
                ))
            }
            (_, Some(fence)) => {
                fence.validate()?;
                self.method.validate()
            }
            (_, None) => Err(MatrixProtocolError::Invalid(
                "Matrix mutation and event methods require an exact fence".to_string(),
            )),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum MatrixdMethod {
    Health,
    Snapshot,
    Events {
        after_cursor: u64,
        limit: u16,
    },
    CancelTurn {
        thread_id: String,
        turn_id: String,
    },
    ResolveApproval {
        approval_key: String,
        decision: LocalApprovalDecision,
    },
}

impl MatrixdMethod {
    fn validate(&self) -> Result<(), MatrixProtocolError> {
        match self {
            Self::Health | Self::Snapshot => Ok(()),
            Self::Events { limit, .. } => {
                if !(1..=MAX_MATRIXD_EVENT_BATCH).contains(limit) {
                    return Err(MatrixProtocolError::Invalid(
                        "Matrix event batch limit is out of bounds".to_string(),
                    ));
                }
                Ok(())
            }
            Self::CancelTurn { thread_id, turn_id } => {
                validate_runtime_identifier(thread_id, "Matrix cancel thread ID")?;
                validate_runtime_identifier(turn_id, "Matrix cancel turn ID")
            }
            Self::ResolveApproval { approval_key, .. } => {
                validate_runtime_identifier(approval_key, "Matrix approval key")
            }
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LocalApprovalDecision {
    Accept,
    AcceptForSession,
    Decline,
    Cancel,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PendingApproval {
    pub approval_key: String,
    pub kind: String,
    pub thread_id: String,
    pub turn_id: String,
    pub summary: String,
    pub created_at_ms: u64,
    pub allowed_decisions: Vec<LocalApprovalDecision>,
}

impl PendingApproval {
    pub fn validate(&self) -> Result<(), MatrixProtocolError> {
        validate_runtime_identifier(&self.approval_key, "Matrix approval key")?;
        validate_runtime_identifier(&self.kind, "Matrix approval kind")?;
        validate_runtime_identifier(&self.thread_id, "Matrix approval thread ID")?;
        validate_runtime_identifier(&self.turn_id, "Matrix approval turn ID")?;
        if self.summary.is_empty()
            || self.summary.len() > MAX_PENDING_APPROVAL_SUMMARY_BYTES
            || self.summary.chars().any(is_forbidden_summary_character)
        {
            return Err(MatrixProtocolError::Invalid(
                "Matrix approval summary must be 1..=1024 safe UTF-8 bytes".to_string(),
            ));
        }
        if self.created_at_ms == 0 {
            return Err(MatrixProtocolError::Invalid(
                "Matrix approval creation time must be non-zero".to_string(),
            ));
        }
        if self.allowed_decisions.is_empty()
            || self.allowed_decisions.len() > 4
            || self
                .allowed_decisions
                .iter()
                .copied()
                .collect::<BTreeSet<_>>()
                .len()
                != self.allowed_decisions.len()
        {
            return Err(MatrixProtocolError::Invalid(
                "Matrix approval decisions must contain 1..=4 unique values".to_string(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MatrixdResponse {
    pub schema_version: u32,
    pub request_id: u64,
    pub agent_id: AgentId,
    pub release_id: String,
    pub binding_revision: u64,
    pub binding_digest: Sha256Digest,
    pub attached_agent_generation: u64,
    pub process_incarnation: String,
    pub plane_epoch: u64,
    pub payload: MatrixdPayload,
}

impl MatrixdResponse {
    pub fn fence(&self) -> MatrixdFence {
        MatrixdFence {
            binding_revision: self.binding_revision,
            binding_digest: self.binding_digest.clone(),
            attached_agent_generation: self.attached_agent_generation,
            process_incarnation: self.process_incarnation.clone(),
            plane_epoch: self.plane_epoch,
        }
    }

    pub fn validate(&self) -> Result<(), MatrixProtocolError> {
        if self.schema_version != MATRIXD_CONTROL_SCHEMA_VERSION || self.request_id == 0 {
            return Err(MatrixProtocolError::Invalid(
                "Matrix response schema must be current and request ID non-zero".to_string(),
            ));
        }
        validate_runtime_identifier(&self.release_id, "Matrix release ID")?;
        self.fence().validate()?;
        match &self.payload {
            MatrixdPayload::Health(health) => health.validate(),
            MatrixdPayload::Snapshot(snapshot) => snapshot.validate(),
            MatrixdPayload::Events(events) => events.validate_shape(),
            MatrixdPayload::Error { code, message } => validate_error(code, message),
            MatrixdPayload::Accepted => Ok(()),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum MatrixdPayload {
    Health(MatrixdHealth),
    Snapshot(MatrixdSnapshot),
    Events(MatrixdEventBatch),
    Accepted,
    Error { code: String, message: String },
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MatrixdLifecycle {
    Starting,
    Syncing,
    Ready,
    Degraded,
    Draining,
    Fenced,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MatrixdHealth {
    pub lifecycle: MatrixdLifecycle,
    pub process_id: u32,
    pub agentd_connected: bool,
    pub matrix_sync_connected: bool,
    pub fenced: bool,
}

impl MatrixdHealth {
    pub fn validate(&self) -> Result<(), MatrixProtocolError> {
        if self.process_id == 0 || self.fenced != (self.lifecycle == MatrixdLifecycle::Fenced) {
            return Err(MatrixProtocolError::Invalid(
                "Matrix health lifecycle and fence state are inconsistent".to_string(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MatrixdSnapshot {
    pub lifecycle: MatrixdLifecycle,
    pub expected_mxid: MatrixUserId,
    pub active_rooms: Vec<MatrixRoomId>,
    pub inbox_depth: u32,
    pub outbox_depth: u32,
    pub oldest_inbox_age_seconds: Option<u64>,
    pub oldest_outbox_age_seconds: Option<u64>,
    pub active_thread_id: Option<String>,
    pub active_turn_id: Option<String>,
    pub pending_approvals: Vec<PendingApproval>,
    pub resync_required: bool,
    pub event_cursor: u64,
}

impl MatrixdSnapshot {
    pub fn validate(&self) -> Result<(), MatrixProtocolError> {
        validate_unique_bounded(&self.active_rooms, "active Matrix rooms")?;
        if let Some(thread_id) = &self.active_thread_id {
            validate_runtime_identifier(thread_id, "Matrix active thread ID")?;
        }
        if let Some(turn_id) = &self.active_turn_id {
            validate_runtime_identifier(turn_id, "Matrix active turn ID")?;
        }
        if self.active_thread_id.is_some() != self.active_turn_id.is_some() {
            return Err(MatrixProtocolError::Invalid(
                "Matrix active thread and turn IDs must both be present or absent".to_string(),
            ));
        }
        if self.pending_approvals.len() > MAX_PENDING_APPROVALS {
            return Err(MatrixProtocolError::Invalid(
                "Matrix pending approval snapshot exceeds its bound".to_string(),
            ));
        }
        let mut keys = BTreeSet::new();
        for approval in &self.pending_approvals {
            approval.validate()?;
            if !keys.insert(approval.approval_key.as_str()) {
                return Err(MatrixProtocolError::Invalid(
                    "Matrix pending approval keys must be unique".to_string(),
                ));
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MatrixdEvent {
    pub cursor: u64,
    pub kind: MatrixdEventKind,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum MatrixdEventKind {
    Lifecycle { lifecycle: MatrixdLifecycle },
    AgentConnection { connected: bool, generation: u64 },
    MatrixConnection { connected: bool },
    QueueDepth { inbox: u32, outbox: u32 },
    TurnStarted { thread_id: String, turn_id: String },
    TurnCompleted { thread_id: String, turn_id: String },
    ApprovalPending { approval: PendingApproval },
    ApprovalResolved { approval_key: String },
    ResyncRequired { reason_code: String },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MatrixdEventBatch {
    pub events: Vec<MatrixdEvent>,
    pub gap: bool,
    pub next_cursor: u64,
    pub latest_cursor: u64,
}

impl MatrixdEventBatch {
    pub fn validate_after(&self, after_cursor: u64) -> Result<(), MatrixProtocolError> {
        self.validate_shape()?;
        if self.gap {
            if !self.events.is_empty() || self.next_cursor != after_cursor {
                return Err(MatrixProtocolError::Invalid(
                    "Matrix event gap must be an empty non-advancing batch".to_string(),
                ));
            }
            return Ok(());
        }
        let mut expected = after_cursor;
        for event in &self.events {
            expected = expected.checked_add(1).ok_or_else(|| {
                MatrixProtocolError::Invalid("Matrix event cursor overflow".to_string())
            })?;
            if event.cursor != expected {
                return Err(MatrixProtocolError::Invalid(
                    "Matrix event cursors must be strictly contiguous".to_string(),
                ));
            }
        }
        if self.next_cursor != expected || self.latest_cursor < self.next_cursor {
            return Err(MatrixProtocolError::Invalid(
                "Matrix event cursors do not describe the consumed batch and server head"
                    .to_string(),
            ));
        }
        Ok(())
    }

    fn validate_shape(&self) -> Result<(), MatrixProtocolError> {
        if self.events.len() > usize::from(MAX_MATRIXD_EVENT_BATCH)
            || self.latest_cursor < self.next_cursor
        {
            return Err(MatrixProtocolError::Invalid(
                "Matrix event batch shape is invalid".to_string(),
            ));
        }
        for event in &self.events {
            if event.cursor == 0 {
                return Err(MatrixProtocolError::Invalid(
                    "Matrix event cursor must be non-zero".to_string(),
                ));
            }
            match &event.kind {
                MatrixdEventKind::TurnStarted { thread_id, turn_id }
                | MatrixdEventKind::TurnCompleted { thread_id, turn_id } => {
                    validate_runtime_identifier(thread_id, "Matrix event thread ID")?;
                    validate_runtime_identifier(turn_id, "Matrix event turn ID")?;
                }
                MatrixdEventKind::ApprovalPending { approval } => approval.validate()?,
                MatrixdEventKind::ApprovalResolved { approval_key } => {
                    validate_runtime_identifier(approval_key, "Matrix approval key")?;
                }
                MatrixdEventKind::ResyncRequired { reason_code } => {
                    validate_error_code(reason_code, "Matrix resync reason code")?;
                }
                MatrixdEventKind::AgentConnection { generation, .. } if *generation == 0 => {
                    return Err(MatrixProtocolError::Invalid(
                        "Matrix Agent connection generation must be non-zero".to_string(),
                    ));
                }
                MatrixdEventKind::Lifecycle { .. }
                | MatrixdEventKind::AgentConnection { .. }
                | MatrixdEventKind::MatrixConnection { .. }
                | MatrixdEventKind::QueueDepth { .. } => {}
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, thiserror::Error)]
pub enum MatrixProtocolError {
    #[error("invalid Matrix protocol value: {0}")]
    Invalid(String),
}

fn validate_matrix_server_identifier(
    value: &str,
    prefix: char,
    label: &str,
) -> Result<(), MatrixProtocolError> {
    validate_opaque_identifier(value, label)?;
    let Some((localpart, server_name)) = value.split_once(':') else {
        return Err(MatrixProtocolError::Invalid(format!(
            "{label} must begin with {prefix:?} and contain a server-name separator"
        )));
    };
    if !localpart.starts_with(prefix) || localpart.len() == 1 || server_name.is_empty() {
        return Err(MatrixProtocolError::Invalid(format!(
            "{label} must contain non-empty local and server-name parts"
        )));
    }
    Ok(())
}

fn validate_opaque_identifier(value: &str, label: &str) -> Result<(), MatrixProtocolError> {
    if value.is_empty()
        || value.len() > MAX_MATRIX_IDENTIFIER_BYTES
        || value.chars().any(char::is_control)
        || value.chars().any(char::is_whitespace)
    {
        return Err(MatrixProtocolError::Invalid(format!(
            "{label} must contain 1..={MAX_MATRIX_IDENTIFIER_BYTES} non-control, non-whitespace bytes"
        )));
    }
    Ok(())
}

fn validate_runtime_identifier(value: &str, label: &str) -> Result<(), MatrixProtocolError> {
    if value.is_empty()
        || value.len() > MAX_RUNTIME_IDENTIFIER_BYTES
        || value.chars().any(char::is_control)
        || value.chars().any(char::is_whitespace)
        || value.chars().any(is_forbidden_directional_character)
    {
        return Err(MatrixProtocolError::Invalid(format!(
            "{label} must contain 1..={MAX_RUNTIME_IDENTIFIER_BYTES} non-control, non-whitespace bytes"
        )));
    }
    Ok(())
}

fn is_forbidden_summary_character(character: char) -> bool {
    character.is_control() || is_forbidden_directional_character(character)
}

fn is_forbidden_directional_character(character: char) -> bool {
    matches!(
        character,
        '\u{061c}'
            | '\u{200e}'..='\u{200f}'
            | '\u{202a}'..='\u{202e}'
            | '\u{2066}'..='\u{2069}'
    )
}

fn validate_error(code: &str, message: &str) -> Result<(), MatrixProtocolError> {
    validate_error_code(code, "Matrix error code")?;
    if message.is_empty()
        || message.len() > MAX_MATRIXD_ERROR_MESSAGE_BYTES
        || message.chars().any(is_forbidden_summary_character)
    {
        return Err(MatrixProtocolError::Invalid(
            "Matrix error message must be bounded safe UTF-8".to_string(),
        ));
    }
    Ok(())
}

fn validate_error_code(value: &str, label: &str) -> Result<(), MatrixProtocolError> {
    if value.is_empty()
        || value.len() > MAX_MATRIXD_ERROR_CODE_BYTES
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'_')
    {
        return Err(MatrixProtocolError::Invalid(format!(
            "{label} must contain 1..={MAX_MATRIXD_ERROR_CODE_BYTES} lowercase ASCII letters, digits, or underscores"
        )));
    }
    Ok(())
}

fn validate_unique_bounded<T: Ord + Clone>(
    values: &[T],
    label: &str,
) -> Result<(), MatrixProtocolError> {
    if values.len() > MAX_MATRIX_BINDING_ENTRIES
        || values.iter().cloned().collect::<BTreeSet<_>>().len() != values.len()
    {
        return Err(MatrixProtocolError::Invalid(format!(
            "{label} must be unique and contain at most {MAX_MATRIX_BINDING_ENTRIES} entries"
        )));
    }
    Ok(())
}

fn framed_digest(domain: &[u8], fields: &[&[u8]]) -> Sha256Digest {
    let capacity = domain.len()
        + fields
            .iter()
            .map(|field| std::mem::size_of::<u64>() + field.len())
            .sum::<usize>();
    let mut framed = Vec::with_capacity(capacity);
    framed.extend_from_slice(domain);
    for field in fields {
        framed.extend_from_slice(&(field.len() as u64).to_be_bytes());
        framed.extend_from_slice(field);
    }
    Sha256Digest::for_bytes(&framed)
}

#[cfg(test)]
mod tests {
    use super::*;

    const BINDING_DIGEST: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

    fn agent_id() -> AgentId {
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("valid agent id")
    }

    fn fence() -> MatrixdFence {
        MatrixdFence {
            binding_revision: 7,
            binding_digest: Sha256Digest::parse(BINDING_DIGEST).expect("digest"),
            attached_agent_generation: 11,
            process_incarnation: "matrixd-incarnation-19".to_string(),
            plane_epoch: 19,
        }
    }

    fn pending_approval() -> PendingApproval {
        PendingApproval {
            approval_key: "approval-1".to_string(),
            kind: "command_execution".to_string(),
            thread_id: "thread-1".to_string(),
            turn_id: "turn-1".to_string(),
            summary: "Run a local command".to_string(),
            created_at_ms: 1_777_777_777_000,
            allowed_decisions: vec![
                LocalApprovalDecision::Accept,
                LocalApprovalDecision::AcceptForSession,
                LocalApprovalDecision::Decline,
                LocalApprovalDecision::Cancel,
            ],
        }
    }

    fn response(payload: MatrixdPayload) -> MatrixdResponse {
        let fence = fence();
        MatrixdResponse {
            schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
            request_id: 1,
            agent_id: agent_id(),
            release_id: "release-7".to_string(),
            binding_revision: fence.binding_revision,
            binding_digest: fence.binding_digest,
            attached_agent_generation: fence.attached_agent_generation,
            process_incarnation: fence.process_incarnation,
            plane_epoch: fence.plane_epoch,
            payload,
        }
    }

    #[test]
    fn binding_is_exact_unique_and_secret_free() {
        let binding = MatrixBindingV1 {
            schema_version: MATRIX_BINDING_SCHEMA_VERSION,
            agent_id: agent_id(),
            revision: 7,
            homeserver: MatrixHomeserverUrl::parse("https://matrix.example.test")
                .expect("homeserver"),
            expected_mxid: MatrixUserId::parse("@hepta-a:example.test").expect("mxid"),
            expected_device_id: MatrixDeviceId::parse("HEPTA_A_DEVICE").expect("device id"),
            allowed_rooms: vec![MatrixRoomId::parse("!room-a:example.test").expect("room")],
            allowed_senders: vec![MatrixUserId::parse("@owner:example.test").expect("sender")],
            require_explicit_mention: true,
        };
        binding.validate().expect("binding should be valid");
        let json = serde_json::to_string(&binding).expect("serialize binding");
        assert!(!json.contains("token"));
        assert!(!json.contains("passphrase"));
        assert_eq!(
            serde_json::from_str::<MatrixBindingV1>(&json).expect("parse binding"),
            binding
        );
    }

    #[test]
    fn insecure_remote_homeservers_and_identifier_drift_are_rejected() {
        assert!(MatrixHomeserverUrl::parse("http://matrix.example.test").is_err());
        assert!(MatrixHomeserverUrl::parse("http://127.0.0.1:8008").is_ok());
        assert!(MatrixHomeserverUrl::parse("https://user:secret@example.test").is_err());
        assert!(MatrixRoomId::parse("room-without-sigil:example.test").is_err());
        assert!(MatrixRoomId::parse("!:example.test").is_err());
        assert!(MatrixUserId::parse("@owner:").is_err());
        assert!(MatrixUserId::parse("@contains whitespace:example.test").is_err());
        assert!(MatrixEventId::parse("$modern-serverless-event-id").is_ok());
        assert!(MatrixEventId::parse("$").is_err());
        assert!(MatrixTransactionId::parse("hepta-v1-0123456789abcdef").is_ok());
    }

    #[test]
    fn control_wire_binds_agent_revision_generation_and_exact_turn() {
        let request = MatrixdRequest {
            schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
            request_id: 9,
            agent_id: agent_id(),
            fence: Some(fence()),
            method: MatrixdMethod::CancelTurn {
                thread_id: "thr-1".to_string(),
                turn_id: "turn-2".to_string(),
            },
        };
        request.validate().expect("request should validate");
        let bytes = serde_json::to_vec(&request).expect("serialize request");
        assert!(bytes.len() as u64 <= MAX_MATRIXD_CONTROL_FRAME_BYTES);
        assert_eq!(
            serde_json::from_slice::<MatrixdRequest>(&bytes).expect("parse request"),
            request
        );

        let mut malformed = serde_json::to_value(&request).expect("request value");
        malformed["fence"]["binding_digest"] = serde_json::json!("bad");
        let malformed =
            serde_json::from_value::<MatrixdRequest>(malformed).expect("transparent digest parses");
        assert!(malformed.validate().is_err());
    }

    #[test]
    fn bootstrap_and_fenced_methods_are_disjoint() {
        let mut request = MatrixdRequest {
            schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
            request_id: 1,
            agent_id: agent_id(),
            fence: None,
            method: MatrixdMethod::Snapshot,
        };
        request.validate().expect("snapshot bootstrap");
        request.fence = Some(fence());
        assert!(request.validate().is_err());
        request.method = MatrixdMethod::Events {
            after_cursor: 0,
            limit: 32,
        };
        request.validate().expect("fenced events");
        request.fence = None;
        assert!(request.validate().is_err());
    }

    #[test]
    fn pending_approval_rejects_uninitialized_unsafe_or_duplicate_values() {
        let mut approval = pending_approval();
        approval.validate().expect("approval should validate");
        approval.created_at_ms = 0;
        assert!(approval.validate().is_err());
        approval = pending_approval();
        approval.summary = "spoof\u{202e}txt".to_string();
        assert!(approval.validate().is_err());
        approval = pending_approval();
        approval.allowed_decisions =
            vec![LocalApprovalDecision::Accept, LocalApprovalDecision::Accept];
        assert!(approval.validate().is_err());
    }

    #[test]
    fn runtime_identifiers_are_bounded_separately_from_matrix_identifiers() {
        let long_runtime_id = "x".repeat(300);
        validate_runtime_identifier(&long_runtime_id, "runtime").expect("runtime ID");
        assert!(MatrixDeviceId::parse(long_runtime_id).is_err());
        assert!(validate_runtime_identifier(&"x".repeat(513), "runtime").is_err());
        assert!(validate_runtime_identifier("spoof\u{202e}txt", "runtime").is_err());
        assert!(validate_runtime_identifier("spoof\u{2066}txt", "runtime").is_err());
    }

    #[test]
    fn response_payload_semantics_are_fail_closed() {
        let mut health = MatrixdHealth {
            lifecycle: MatrixdLifecycle::Ready,
            process_id: 7,
            agentd_connected: true,
            matrix_sync_connected: true,
            fenced: false,
        };
        response(MatrixdPayload::Health(health.clone()))
            .validate()
            .expect("coherent health");
        health.process_id = 0;
        assert!(
            response(MatrixdPayload::Health(health.clone()))
                .validate()
                .is_err()
        );
        health.process_id = 7;
        health.fenced = true;
        assert!(response(MatrixdPayload::Health(health)).validate().is_err());

        assert!(
            response(MatrixdPayload::Error {
                code: "Stale-Fence".to_string(),
                message: "safe message".to_string(),
            })
            .validate()
            .is_err()
        );
        assert!(
            response(MatrixdPayload::Error {
                code: "stale_fence".to_string(),
                message: "spoof\u{202e}txt".to_string(),
            })
            .validate()
            .is_err()
        );

        let events = |kind| {
            MatrixdPayload::Events(MatrixdEventBatch {
                events: vec![MatrixdEvent { cursor: 1, kind }],
                gap: false,
                next_cursor: 1,
                latest_cursor: 1,
            })
        };
        assert!(
            response(events(MatrixdEventKind::AgentConnection {
                connected: true,
                generation: 0,
            }))
            .validate()
            .is_err()
        );
        assert!(
            response(events(MatrixdEventKind::ResyncRequired {
                reason_code: "Unsafe-Reason".to_string(),
            }))
            .validate()
            .is_err()
        );
    }

    #[test]
    fn event_cursor_contract_requires_contiguous_or_empty_gap() {
        MatrixdEventBatch {
            events: vec![
                MatrixdEvent {
                    cursor: 8,
                    kind: MatrixdEventKind::QueueDepth {
                        inbox: 1,
                        outbox: 2,
                    },
                },
                MatrixdEvent {
                    cursor: 9,
                    kind: MatrixdEventKind::ApprovalPending {
                        approval: pending_approval(),
                    },
                },
            ],
            gap: false,
            next_cursor: 9,
            latest_cursor: 12,
        }
        .validate_after(7)
        .expect("contiguous batch");

        MatrixdEventBatch {
            events: Vec::new(),
            gap: true,
            next_cursor: 7,
            latest_cursor: 12,
        }
        .validate_after(7)
        .expect("non-advancing gap");

        assert!(
            MatrixdEventBatch {
                events: vec![MatrixdEvent {
                    cursor: 9,
                    kind: MatrixdEventKind::QueueDepth {
                        inbox: 0,
                        outbox: 0
                    },
                }],
                gap: false,
                next_cursor: 9,
                latest_cursor: 9,
            }
            .validate_after(7)
            .is_err()
        );
    }

    #[test]
    fn frozen_control_json_fixtures_are_exact() {
        let request = MatrixdRequest {
            schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
            request_id: 41,
            agent_id: agent_id(),
            fence: Some(fence()),
            method: MatrixdMethod::ResolveApproval {
                approval_key: "approval-1".to_string(),
                decision: LocalApprovalDecision::Accept,
            },
        };
        let request_json = serde_json::to_string(&request).expect("serialize request");
        assert_eq!(
            request_json,
            r#"{"schema_version":2,"request_id":41,"agent_id":"018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12","fence":{"binding_revision":7,"binding_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","attached_agent_generation":11,"process_incarnation":"matrixd-incarnation-19","plane_epoch":19},"method":{"type":"resolve_approval","approval_key":"approval-1","decision":"accept"}}"#
        );

        let response = MatrixdResponse {
            schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
            request_id: 41,
            agent_id: agent_id(),
            release_id: "release-7".to_string(),
            binding_revision: 7,
            binding_digest: Sha256Digest::parse(BINDING_DIGEST).expect("digest"),
            attached_agent_generation: 11,
            process_incarnation: "matrixd-incarnation-19".to_string(),
            plane_epoch: 19,
            payload: MatrixdPayload::Snapshot(MatrixdSnapshot {
                lifecycle: MatrixdLifecycle::Ready,
                expected_mxid: MatrixUserId::parse("@hepta-a:example.test").expect("mxid"),
                active_rooms: vec![MatrixRoomId::parse("!room-a:example.test").expect("room")],
                inbox_depth: 1,
                outbox_depth: 2,
                oldest_inbox_age_seconds: Some(3),
                oldest_outbox_age_seconds: None,
                active_thread_id: Some("thread-1".to_string()),
                active_turn_id: Some("turn-1".to_string()),
                pending_approvals: vec![pending_approval()],
                resync_required: false,
                event_cursor: 9,
            }),
        };
        response.validate().expect("response should validate");
        let response_json = serde_json::to_string(&response).expect("serialize response");
        assert_eq!(
            response_json,
            r#"{"schema_version":2,"request_id":41,"agent_id":"018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12","release_id":"release-7","binding_revision":7,"binding_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","attached_agent_generation":11,"process_incarnation":"matrixd-incarnation-19","plane_epoch":19,"payload":{"type":"snapshot","lifecycle":"ready","expected_mxid":"@hepta-a:example.test","active_rooms":["!room-a:example.test"],"inbox_depth":1,"outbox_depth":2,"oldest_inbox_age_seconds":3,"oldest_outbox_age_seconds":null,"active_thread_id":"thread-1","active_turn_id":"turn-1","pending_approvals":[{"approval_key":"approval-1","kind":"command_execution","thread_id":"thread-1","turn_id":"turn-1","summary":"Run a local command","created_at_ms":1777777777000,"allowed_decisions":["accept","accept_for_session","decline","cancel"]}],"resync_required":false,"event_cursor":9}}"#
        );

        let error = MatrixdResponse {
            payload: MatrixdPayload::Error {
                code: "stale_fence".to_string(),
                message: "request fence does not match this process".to_string(),
            },
            ..response
        };
        assert_eq!(
            serde_json::to_string(&error).expect("serialize error"),
            r#"{"schema_version":2,"request_id":41,"agent_id":"018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12","release_id":"release-7","binding_revision":7,"binding_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","attached_agent_generation":11,"process_incarnation":"matrixd-incarnation-19","plane_epoch":19,"payload":{"type":"error","code":"stale_fence","message":"request fence does not match this process"}}"#
        );
    }

    #[test]
    fn maximum_valid_snapshot_and_event_batch_fit_one_control_frame() {
        let runtime_id = |prefix: &str, index: usize| {
            let prefix = format!("{prefix}-{index}-");
            format!(
                "{prefix}{}",
                "x".repeat(MAX_RUNTIME_IDENTIFIER_BYTES - prefix.len())
            )
        };
        let approvals = (0..MAX_PENDING_APPROVALS)
            .map(|index| PendingApproval {
                approval_key: runtime_id("approval", index),
                kind: runtime_id("kind", index),
                thread_id: runtime_id("thread", index),
                turn_id: runtime_id("turn", index),
                summary: "s".repeat(MAX_PENDING_APPROVAL_SUMMARY_BYTES),
                created_at_ms: 1,
                allowed_decisions: vec![
                    LocalApprovalDecision::Accept,
                    LocalApprovalDecision::AcceptForSession,
                    LocalApprovalDecision::Decline,
                    LocalApprovalDecision::Cancel,
                ],
            })
            .collect::<Vec<_>>();
        let rooms = (0..MAX_MATRIX_BINDING_ENTRIES)
            .map(|index| {
                MatrixRoomId::parse(format!("!room-{index}-{}:example.test", "r".repeat(210)))
                    .expect("maximum room fixture")
            })
            .collect::<Vec<_>>();
        let response = MatrixdResponse {
            schema_version: MATRIXD_CONTROL_SCHEMA_VERSION,
            request_id: 1,
            agent_id: agent_id(),
            release_id: runtime_id("release", 0),
            binding_revision: 1,
            binding_digest: Sha256Digest::parse(BINDING_DIGEST).expect("digest"),
            attached_agent_generation: 1,
            process_incarnation: runtime_id("incarnation", 0),
            plane_epoch: 1,
            payload: MatrixdPayload::Snapshot(MatrixdSnapshot {
                lifecycle: MatrixdLifecycle::Ready,
                expected_mxid: MatrixUserId::parse("@hepta:example.test").expect("mxid"),
                active_rooms: rooms,
                inbox_depth: u32::MAX,
                outbox_depth: u32::MAX,
                oldest_inbox_age_seconds: Some(u64::MAX),
                oldest_outbox_age_seconds: Some(u64::MAX),
                active_thread_id: Some(runtime_id("active-thread", 0)),
                active_turn_id: Some(runtime_id("active-turn", 0)),
                pending_approvals: approvals.clone(),
                resync_required: false,
                event_cursor: MAX_PENDING_APPROVALS as u64,
            }),
        };
        response.validate().expect("maximum snapshot validates");
        assert!(
            (serde_json::to_vec(&response).expect("snapshot JSON").len() as u64)
                < MAX_MATRIXD_CONTROL_FRAME_BYTES
        );

        let events = approvals
            .into_iter()
            .enumerate()
            .map(|(index, approval)| MatrixdEvent {
                cursor: index as u64 + 1,
                kind: MatrixdEventKind::ApprovalPending { approval },
            })
            .collect::<Vec<_>>();
        let batch = MatrixdEventBatch {
            events,
            gap: false,
            next_cursor: MAX_PENDING_APPROVALS as u64,
            latest_cursor: MAX_PENDING_APPROVALS as u64,
        };
        batch
            .validate_after(0)
            .expect("maximum event batch validates");
        let response = MatrixdResponse {
            payload: MatrixdPayload::Events(batch),
            ..response
        };
        assert!(
            (serde_json::to_vec(&response).expect("event JSON").len() as u64)
                < MAX_MATRIXD_CONTROL_FRAME_BYTES
        );
    }

    #[test]
    fn matrix_binding_rejects_duplicates_and_empty_authority_sets() {
        let room = MatrixRoomId::parse("!room-a:example.test").expect("room");
        let mut binding = MatrixBindingV1 {
            schema_version: MATRIX_BINDING_SCHEMA_VERSION,
            agent_id: agent_id(),
            revision: 1,
            homeserver: MatrixHomeserverUrl::parse("https://matrix.example.test")
                .expect("homeserver"),
            expected_mxid: MatrixUserId::parse("@hepta-a:example.test").expect("mxid"),
            expected_device_id: MatrixDeviceId::parse("DEVICE").expect("device"),
            allowed_rooms: vec![room.clone(), room],
            allowed_senders: vec![MatrixUserId::parse("@owner:example.test").expect("sender")],
            require_explicit_mention: false,
        };
        assert!(binding.validate().is_err());
        binding.allowed_rooms.clear();
        assert!(binding.validate().is_err());
    }

    #[test]
    fn deterministic_bridge_ids_are_domain_separated_and_revision_bound() {
        let agent = agent_id();
        let room = MatrixRoomId::parse("!room-a:example.test").expect("room");
        let event = MatrixEventId::parse("$event-a").expect("event");
        let client_id = client_user_message_id(&agent, &room, &event);
        assert_eq!(client_id, client_user_message_id(&agent, &room, &event));
        assert_ne!(
            client_id,
            room_project_idempotency_key(&agent, &room),
            "different identity domains must never alias"
        );

        let logical_outbox = outbox_id(&agent, &room, "thread-a", "turn-a", "item-a", "final");
        let revision_one = transaction_id(&logical_outbox, 1).expect("transaction");
        let revision_two = transaction_id(&logical_outbox, 2).expect("transaction");
        assert_ne!(revision_one, revision_two);
        assert!(revision_one.as_str().starts_with("hepta-v1-"));
    }
}
