use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::ReconciliationOutcome;

use super::DurableOperationError;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PrepareOperationIntent {
    pub scope: StableId,
    pub operation_id: StableId,
    pub predecessor_digest: Option<Digest32>,
    pub payload_digest: Digest32,
    pub destination: StableId,
    pub owner_generation: Generation,
    pub authority_epoch: Generation,
}

impl PrepareOperationIntent {
    pub fn semantic_digest(&self) -> Result<Digest32, DurableOperationError> {
        self.validate()?;
        let mut bytes = b"hepta.kernel.operations.intent.v1\0".to_vec();
        append_stable_id(&mut bytes, &self.scope);
        append_stable_id(&mut bytes, &self.operation_id);
        match self.predecessor_digest {
            Some(digest) => {
                bytes.push(1);
                bytes.extend_from_slice(digest.as_array());
            }
            None => bytes.push(0),
        }
        bytes.extend_from_slice(self.payload_digest.as_array());
        append_stable_id(&mut bytes, &self.destination);
        Ok(Digest32::of_bytes(&bytes))
    }

    pub(crate) fn validate(&self) -> Result<(), DurableOperationError> {
        if self.payload_digest.is_zero() {
            return Err(DurableOperationError::Invalid("payload digest is zero"));
        }
        if self.predecessor_digest.is_some_and(Digest32::is_zero) {
            return Err(DurableOperationError::Invalid(
                "predecessor digest is zero",
            ));
        }
        Ok(())
    }
}

fn append_stable_id(bytes: &mut Vec<u8>, id: &StableId) {
    let value = id.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(value.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(value);
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
    pub const fn label(self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Dispatched => "dispatched",
            Self::Indeterminate => "indeterminate",
            Self::Applied => "applied",
            Self::NotApplied => "not_applied",
            Self::Quarantined => "quarantined",
        }
    }

    pub const fn is_terminal(self) -> bool {
        matches!(
            self,
            Self::Applied | Self::NotApplied | Self::Quarantined
        )
    }

    pub(crate) fn parse(value: &str) -> Result<Self, DurableOperationError> {
        match value {
            "pending" => Ok(Self::Pending),
            "dispatched" => Ok(Self::Dispatched),
            "indeterminate" => Ok(Self::Indeterminate),
            "applied" => Ok(Self::Applied),
            "not_applied" => Ok(Self::NotApplied),
            "quarantined" => Ok(Self::Quarantined),
            _ => Err(DurableOperationError::Corrupt(format!(
                "unknown operation state {value}"
            ))),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableOperationRecord {
    pub scope: StableId,
    pub operation_id: StableId,
    pub semantic_digest: Digest32,
    pub predecessor_digest: Option<Digest32>,
    pub payload_digest: Digest32,
    pub destination: StableId,
    pub owner_generation: Generation,
    pub authority_epoch: Generation,
    pub revision: Revision,
    pub state: DurableOperationState,
    pub dispatch_digest: Option<Digest32>,
    pub indeterminate_digest: Option<Digest32>,
    pub terminal_evidence_digest: Option<Digest32>,
    pub created_at_ms: i64,
    pub updated_at_ms: i64,
    pub terminal_at_ms: Option<i64>,
}

impl DurableOperationRecord {
    pub fn final_use_binding(&self) -> FinalUseBinding {
        FinalUseBinding {
            subject_id: self.operation_id.as_str().to_string(),
            destination_id: self.destination.as_str().to_string(),
            request_sha256: self.semantic_digest.into_array(),
            scope_sha256: Digest32::of_bytes(self.scope.as_str().as_bytes()).into_array(),
            payload_sha256: self.payload_digest.into_array(),
        }
    }
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
    pub(crate) fn parse(value: &str) -> Result<Self, DurableOperationError> {
        match value {
            "queued" => Ok(Self::Queued),
            "leased" => Ok(Self::Leased),
            "acknowledged" => Ok(Self::Acknowledged),
            "indeterminate" => Ok(Self::Indeterminate),
            "settled" => Ok(Self::Settled),
            "quarantined" => Ok(Self::Quarantined),
            _ => Err(DurableOperationError::Corrupt(format!(
                "unknown outbox state {value}"
            ))),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableOutboxStatus {
    pub scope: StableId,
    pub operation_id: StableId,
    pub destination: StableId,
    pub semantic_digest: Digest32,
    pub state: DurableOutboxState,
    pub fence: u64,
    pub attempts: u32,
    pub available_at_ms: i64,
    pub worker_id: Option<StableId>,
    pub lease_until_ms: Option<i64>,
    pub claim_generation: Option<Generation>,
    pub acknowledgement_digest: Option<Digest32>,
    pub last_error_digest: Option<Digest32>,
    pub created_at_ms: i64,
    pub updated_at_ms: i64,
    pub terminal_at_ms: Option<i64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DispatchLease {
    pub scope: StableId,
    pub operation_id: StableId,
    pub destination: StableId,
    pub semantic_digest: Digest32,
    pub payload_digest: Digest32,
    pub worker_id: StableId,
    pub owner_generation: Generation,
    pub fence: u64,
    pub expires_at_ms: i64,
    pub attempts: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DestinationReceipt {
    pub destination: StableId,
    pub operation_id: StableId,
    pub semantic_digest: Digest32,
    pub outcome: ReconciliationOutcome,
    pub evidence_digest: Digest32,
    pub recorded_at_ms: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperationsMetrics {
    pub total_operations: u64,
    pub pending_operations: u64,
    pub unresolved_operations: u64,
    pub terminal_operations: u64,
    pub queued_outbox: u64,
    pub leased_outbox: u64,
    pub acknowledged_outbox: u64,
    pub indeterminate_outbox: u64,
    pub total_attempts: u64,
    pub oldest_unresolved_age_ms: u64,
}
