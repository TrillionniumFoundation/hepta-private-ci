use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::OperationError;
use crate::ReconciliationOutcome;

pub const MAX_DURABLE_ACTIVE_OPERATIONS: i64 = 100_000;
pub const MAX_DURABLE_OUTBOX_ROWS: i64 = 100_000;
pub const MAX_DURABLE_OUTBOX_ATTEMPTS: u32 = 16;
pub const MAX_DURABLE_CLAIM_BATCH: u32 = 256;
pub const MAX_DURABLE_LEASE_MS: i64 = 60_000;
pub const DEFAULT_TERMINAL_RETENTION_MS: i64 = 7 * 24 * 60 * 60 * 1_000;
pub const DEFAULT_TERMINAL_RETAINED_ROWS: i64 = 100_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableStoreConfig {
    pub maximum_active_operations: i64,
    pub maximum_outbox_rows: i64,
    pub terminal_retention_ms: i64,
    pub terminal_retained_rows: i64,
}

impl Default for DurableStoreConfig {
    fn default() -> Self {
        Self {
            maximum_active_operations: MAX_DURABLE_ACTIVE_OPERATIONS,
            maximum_outbox_rows: MAX_DURABLE_OUTBOX_ROWS,
            terminal_retention_ms: DEFAULT_TERMINAL_RETENTION_MS,
            terminal_retained_rows: DEFAULT_TERMINAL_RETAINED_ROWS,
        }
    }
}

impl DurableStoreConfig {
    pub(crate) fn validate(&self) -> Result<(), OperationError> {
        if self.maximum_active_operations <= 0
            || self.maximum_active_operations > MAX_DURABLE_ACTIVE_OPERATIONS
        {
            return Err(OperationError::CapacityExceeded {
                resource: "durable active operations",
                maximum: usize::try_from(MAX_DURABLE_ACTIVE_OPERATIONS).unwrap_or(usize::MAX),
            });
        }
        if self.maximum_outbox_rows <= 0
            || self.maximum_outbox_rows > MAX_DURABLE_OUTBOX_ROWS
        {
            return Err(OperationError::CapacityExceeded {
                resource: "durable outbox rows",
                maximum: usize::try_from(MAX_DURABLE_OUTBOX_ROWS).unwrap_or(usize::MAX),
            });
        }
        if self.terminal_retention_ms < 0 || self.terminal_retained_rows < 0 {
            return Err(OperationError::InvalidTransition {
                from: "configuration",
                to: "negative_retention",
            });
        }
        Ok(())
    }
}

/// Exact durable intent. `scope_digest`, `request_digest` and `payload_digest`
/// bind the final request independently from human-readable identifiers.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableOperationIntent {
    pub scope_id: StableId,
    pub operation_id: StableId,
    pub scope_digest: Digest32,
    pub request_digest: Digest32,
    pub payload_digest: Digest32,
    pub destination_id: StableId,
    pub expected_predecessor: Option<StableId>,
    pub writer_generation: Generation,
    pub authority_epoch: Generation,
}

impl DurableOperationIntent {
    pub(crate) fn validate(&self) -> Result<(), OperationError> {
        if self.scope_digest.is_zero() {
            return Err(OperationError::InvalidDigest("operation scope"));
        }
        if self.request_digest.is_zero() {
            return Err(OperationError::InvalidDigest("operation request"));
        }
        if self.payload_digest.is_zero() {
            return Err(OperationError::InvalidDigest("operation payload"));
        }
        if self
            .expected_predecessor
            .as_ref()
            .is_some_and(|value| value == &self.operation_id)
        {
            return Err(OperationError::Conflict(self.operation_id.clone()));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DurableOperationState {
    Pending,
    Dispatched,
    Indeterminate,
    Applied,
    NotApplied,
    Quarantined,
}

impl DurableOperationState {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Dispatched => "dispatched",
            Self::Indeterminate => "indeterminate",
            Self::Applied => "applied",
            Self::NotApplied => "not_applied",
            Self::Quarantined => "quarantined",
        }
    }

    pub(crate) fn parse(value: &str) -> Option<Self> {
        match value {
            "pending" => Some(Self::Pending),
            "dispatched" => Some(Self::Dispatched),
            "indeterminate" => Some(Self::Indeterminate),
            "applied" => Some(Self::Applied),
            "not_applied" => Some(Self::NotApplied),
            "quarantined" => Some(Self::Quarantined),
            _ => None,
        }
    }

    pub const fn is_terminal(self) -> bool {
        matches!(self, Self::Applied | Self::NotApplied | Self::Quarantined)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableOperationRecord {
    pub intent: DurableOperationIntent,
    pub revision: Revision,
    pub state: DurableOperationState,
    pub dispatch_digest: Option<Digest32>,
    pub terminal_digest: Option<Digest32>,
    pub created_at_ms: i64,
    pub updated_at_ms: i64,
    pub terminal_at_ms: Option<i64>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DurableOutboxState {
    Queued,
    Leased,
    Acknowledged,
    Indeterminate,
    Settled,
    Quarantined,
}

impl DurableOutboxState {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Queued => "queued",
            Self::Leased => "leased",
            Self::Acknowledged => "acknowledged",
            Self::Indeterminate => "indeterminate",
            Self::Settled => "settled",
            Self::Quarantined => "quarantined",
        }
    }

    pub(crate) fn parse(value: &str) -> Option<Self> {
        match value {
            "queued" => Some(Self::Queued),
            "leased" => Some(Self::Leased),
            "acknowledged" => Some(Self::Acknowledged),
            "indeterminate" => Some(Self::Indeterminate),
            "settled" => Some(Self::Settled),
            "quarantined" => Some(Self::Quarantined),
            _ => None,
        }
    }

    pub const fn is_terminal(self) -> bool {
        matches!(self, Self::Settled | Self::Quarantined)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableOutboxRecord {
    pub scope_id: StableId,
    pub operation_id: StableId,
    pub destination_id: StableId,
    pub payload_digest: Digest32,
    pub state: DurableOutboxState,
    pub fence: u64,
    pub claim_generation: Option<Generation>,
    pub attempts: u32,
    pub worker_id: Option<StableId>,
    pub lease_until_ms: Option<i64>,
    pub next_eligible_ms: i64,
    pub acknowledgement_digest: Option<Digest32>,
    pub reason_digest: Option<Digest32>,
    pub created_at_ms: i64,
    pub updated_at_ms: i64,
    pub terminal_at_ms: Option<i64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DispatchLease {
    pub scope_id: StableId,
    pub operation_id: StableId,
    pub destination_id: StableId,
    pub worker_id: StableId,
    pub writer_generation: Generation,
    pub fence: u64,
    pub expires_at_ms: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DispatchClaim {
    pub operation: DurableOperationRecord,
    pub outbox: DurableOutboxRecord,
    pub lease: DispatchLease,
}

/// Returned after the dispatch boundary is durably armed. From this point a
/// process crash is an unknown external-effect outcome and must reconcile; the
/// row is deliberately no longer eligible for ordinary lease takeover.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArmedDispatch {
    pub operation: DurableOperationRecord,
    pub fence: u64,
    pub worker_id: StableId,
    pub writer_generation: Generation,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DispatchObservation {
    /// Transport/handler acceptance only. This is not terminal effect success.
    Acknowledged {
        acknowledgement_digest: Digest32,
    },
    /// A trusted destination observer supplied a terminal outcome.
    Terminal {
        outcome: ReconciliationOutcome,
        evidence_digest: Digest32,
        acknowledgement_digest: Option<Digest32>,
    },
    /// The effect may have crossed the boundary but no terminal observation is
    /// trustworthy yet. Blind retry is forbidden.
    Indeterminate {
        reason_digest: Digest32,
    },
}

impl DispatchObservation {
    pub(crate) fn validate(self) -> Result<Self, OperationError> {
        let digest = match self {
            Self::Acknowledged {
                acknowledgement_digest,
            } => acknowledgement_digest,
            Self::Terminal {
                evidence_digest, ..
            } => evidence_digest,
            Self::Indeterminate { reason_digest } => reason_digest,
        };
        if digest.is_zero() {
            return Err(OperationError::InvalidDigest("dispatch observation"));
        }
        match self {
            Self::Terminal {
                acknowledgement_digest: Some(acknowledgement_digest),
                ..
            } if acknowledgement_digest.is_zero() => {
                Err(OperationError::InvalidDigest("outbox acknowledgement"))
            }
            _ => Ok(self),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableOperationMetrics {
    pub active_operations: i64,
    pub terminal_operations: i64,
    pub queued_outbox: i64,
    pub leased_outbox: i64,
    pub acknowledged_outbox: i64,
    pub indeterminate_outbox: i64,
    pub oldest_ready_age_ms: Option<i64>,
    pub tombstones: i64,
}
