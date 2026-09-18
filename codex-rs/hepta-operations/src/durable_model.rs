use std::fmt;
use std::time::Duration;

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::ReconciliationOutcome;

pub const MAX_DURABLE_PENDING_OPERATIONS: i64 = 100_000;
pub const MAX_DURABLE_OUTBOX_ATTEMPTS: u32 = 16;
pub const MAX_DURABLE_CLAIM_BATCH: u32 = 256;
pub const MAX_DURABLE_LEASE_MS: u64 = 60_000;

/// Version-1 durable operation intent owned by `kernel.operations`.
///
/// The semantic identity deliberately excludes writer generation. Generation is
/// a fencing property of the current owner, not part of the logical operation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperationIntentV1 {
    pub scope_id: StableId,
    pub operation_id: StableId,
    pub expected_predecessor: Option<StableId>,
    pub destination: StableId,
    pub payload_digest: Digest32,
    pub owner_generation: Generation,
}

impl OperationIntentV1 {
    pub fn validate(&self) -> Result<(), DurableOperationError> {
        if self.payload_digest.is_zero() {
            return Err(DurableOperationError::Invalid("operation payload digest"));
        }
        Ok(())
    }

    #[must_use]
    pub fn semantic_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.kernel.operations.intent.v1\0".to_vec();
        push_id(&mut bytes, &self.scope_id);
        push_id(&mut bytes, &self.operation_id);
        match self.expected_predecessor.as_ref() {
            Some(predecessor) => {
                bytes.push(1);
                push_id(&mut bytes, predecessor);
            }
            None => bytes.push(0),
        }
        push_id(&mut bytes, &self.destination);
        bytes.extend_from_slice(self.payload_digest.as_array());
        Digest32::of_bytes(&bytes)
    }

    /// Binding consumed by `kernel.authority` at the final dispatch boundary.
    #[must_use]
    pub fn final_use_binding(&self) -> FinalUseBinding {
        let mut scope = b"hepta.kernel.operations.scope.v1\0".to_vec();
        push_id(&mut scope, &self.scope_id);
        FinalUseBinding {
            subject_id: self.operation_id.as_str().to_owned(),
            destination_id: self.destination.as_str().to_owned(),
            request_sha256: self.semantic_digest().into_array(),
            scope_sha256: Digest32::of_bytes(&scope).into_array(),
            payload_sha256: self.payload_digest.into_array(),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PrepareDisposition {
    Inserted,
    AlreadyPresent,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DurableOperationState {
    Prepared,
    Dispatching,
    Dispatched,
    Indeterminate,
    Applied,
    NotApplied,
    Quarantined,
}

impl DurableOperationState {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Prepared => "prepared",
            Self::Dispatching => "dispatching",
            Self::Dispatched => "dispatched",
            Self::Indeterminate => "indeterminate",
            Self::Applied => "applied",
            Self::NotApplied => "not_applied",
            Self::Quarantined => "quarantined",
        }
    }

    pub(crate) fn parse(value: &str) -> Result<Self, DurableOperationError> {
        match value {
            "prepared" => Ok(Self::Prepared),
            "dispatching" => Ok(Self::Dispatching),
            "dispatched" => Ok(Self::Dispatched),
            "indeterminate" => Ok(Self::Indeterminate),
            "applied" => Ok(Self::Applied),
            "not_applied" => Ok(Self::NotApplied),
            "quarantined" => Ok(Self::Quarantined),
            _ => Err(DurableOperationError::Corrupt(format!(
                "unknown durable operation state {value}"
            ))),
        }
    }

    #[must_use]
    pub const fn is_terminal(self) -> bool {
        matches!(self, Self::Applied | Self::NotApplied | Self::Quarantined)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableOperationRecord {
    pub intent: OperationIntentV1,
    pub semantic_digest: Digest32,
    pub revision: u64,
    pub writer_fence: u64,
    pub state: DurableOperationState,
    pub authority_epoch: Option<u64>,
    pub authority_digest: Option<Digest32>,
    pub dispatch_digest: Option<Digest32>,
    pub indeterminate_digest: Option<Digest32>,
    pub terminal_outcome: Option<ReconciliationOutcome>,
    pub terminal_evidence_digest: Option<Digest32>,
    pub terminal_observer_id: Option<StableId>,
    pub terminal_observer_generation: Option<Generation>,
    pub created_at_unix_ms: u64,
    pub updated_at_unix_ms: u64,
    pub terminal_at_unix_ms: Option<u64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedIntent {
    pub disposition: PrepareDisposition,
    pub record: DurableOperationRecord,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DurableOutboxState {
    Queued,
    Leased,
    Acknowledged,
    Indeterminate,
    Quarantined,
}

impl DurableOutboxState {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Queued => "queued",
            Self::Leased => "leased",
            Self::Acknowledged => "acked",
            Self::Indeterminate => "indeterminate",
            Self::Quarantined => "quarantined",
        }
    }

    pub(crate) fn parse(value: &str) -> Result<Self, DurableOperationError> {
        match value {
            "queued" => Ok(Self::Queued),
            "leased" => Ok(Self::Leased),
            "acked" => Ok(Self::Acknowledged),
            "indeterminate" => Ok(Self::Indeterminate),
            "quarantined" => Ok(Self::Quarantined),
            _ => Err(DurableOperationError::Corrupt(format!(
                "unknown durable outbox state {value}"
            ))),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OutboxStatusV1 {
    pub intent: OperationIntentV1,
    pub state: DurableOutboxState,
    pub fence: u64,
    pub attempts: u32,
    pub worker_id: Option<StableId>,
    pub lease_until_unix_ms: Option<u64>,
    pub next_eligible_unix_ms: u64,
    pub acknowledgement_digest: Option<Digest32>,
    pub created_at_unix_ms: u64,
    pub updated_at_unix_ms: u64,
    pub terminal_at_unix_ms: Option<u64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DispatchClaim {
    pub intent: OperationIntentV1,
    pub worker_id: StableId,
    pub owner_generation: Generation,
    pub fence: u64,
    pub attempts: u32,
    pub expires_at_unix_ms: u64,
}

impl DispatchClaim {
    #[must_use]
    pub fn lease_duration_remaining(&self, now_unix_ms: u64) -> Duration {
        Duration::from_millis(self.expires_at_unix_ms.saturating_sub(now_unix_ms))
    }
}

/// Result of entering one downstream effect boundary under a live final-use
/// token. `NotDispatched` is the only result eligible for automatic retry.
#[derive(Debug)]
pub enum DispatchEffect<T> {
    Dispatched {
        value: T,
        dispatch_digest: Digest32,
        acknowledgement_digest: Option<Digest32>,
    },
    NotDispatched {
        value: T,
        reason_digest: Digest32,
        retry_after: Duration,
    },
    Indeterminate {
        value: T,
        reason_digest: Digest32,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReconciliationReceiptV1 {
    pub outcome: ReconciliationOutcome,
    pub evidence_digest: Digest32,
    pub observer_id: StableId,
    pub observer_generation: Generation,
}

impl ReconciliationReceiptV1 {
    pub fn validate(&self) -> Result<(), DurableOperationError> {
        if self.evidence_digest.is_zero() {
            return Err(DurableOperationError::Invalid(
                "reconciliation evidence digest",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DestinationRetirementReadinessV1 {
    pub destination: StableId,
    pub active_operations: u64,
    pub unsettled_effects: u64,
    pub pending_outbox: u64,
    pub retirable: bool,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct OperationBacklogMetrics {
    pub active_operations: u64,
    pub queued_outbox: u64,
    pub leased_outbox: u64,
    pub acknowledged_outbox: u64,
    pub indeterminate_operations: u64,
    pub terminal_operations: u64,
    pub oldest_active_outbox_age_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DestinationOperationIdentity {
    pub destination: StableId,
    pub scope_id: StableId,
    pub operation_id: StableId,
    pub payload_digest: Digest32,
}

impl DestinationOperationIdentity {
    pub fn validate(&self) -> Result<(), DurableOperationError> {
        if self.payload_digest.is_zero() {
            return Err(DurableOperationError::Invalid(
                "destination payload digest",
            ));
        }
        Ok(())
    }

    #[must_use]
    pub fn semantic_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.kernel.operations.destination-dedupe.v1\0".to_vec();
        push_id(&mut bytes, &self.destination);
        push_id(&mut bytes, &self.scope_id);
        push_id(&mut bytes, &self.operation_id);
        bytes.extend_from_slice(self.payload_digest.as_array());
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DestinationApplyReceipt {
    pub identity: DestinationOperationIdentity,
    pub semantic_digest: Digest32,
    pub outcome_digest: Digest32,
    pub applied_at_unix_ms: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DestinationApplyDisposition {
    Applied,
    AlreadyApplied,
}

#[derive(Debug)]
pub enum DurableOperationError {
    Invalid(&'static str),
    Missing(StableId),
    Conflict(StableId),
    Retired(StableId),
    Capacity,
    StaleGeneration,
    StaleLease,
    InvalidTransition {
        from: DurableOperationState,
        to: &'static str,
    },
    ClockRollback,
    Authority(FinalUseError),
    Corrupt(String),
    Unavailable(String),
}

impl fmt::Display for DurableOperationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Invalid(field) => write!(formatter, "invalid durable operation {field}"),
            Self::Missing(id) => write!(formatter, "durable operation is missing: {id}"),
            Self::Conflict(id) => write!(formatter, "durable operation conflicts: {id}"),
            Self::Retired(id) => write!(formatter, "durable operation identity is retired: {id}"),
            Self::Capacity => formatter.write_str("durable operation capacity exceeded"),
            Self::StaleGeneration => formatter.write_str("durable owner generation is stale"),
            Self::StaleLease => formatter.write_str("durable outbox lease is stale"),
            Self::InvalidTransition { from, to } => {
                write!(formatter, "invalid durable transition from {from:?} to {to}")
            }
            Self::ClockRollback => formatter.write_str("wall clock moved behind durable state"),
            Self::Authority(error) => write!(formatter, "final-use authority rejected: {error}"),
            Self::Corrupt(message) => write!(formatter, "durable operation store corrupt: {message}"),
            Self::Unavailable(message) => {
                write!(formatter, "durable operation store unavailable: {message}")
            }
        }
    }
}

impl std::error::Error for DurableOperationError {}

impl From<FinalUseError> for DurableOperationError {
    fn from(error: FinalUseError) -> Self {
        Self::Authority(error)
    }
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    let value = id.as_str().as_bytes();
    let length = u32::try_from(value.len()).unwrap_or(u32::MAX);
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value);
}
