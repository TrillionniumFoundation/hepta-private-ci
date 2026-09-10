use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::OperationError;

/// Stable operation identity plus the exact final payload digest.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct OperationKey {
    pub id: StableId,
    pub payload_digest: Digest32,
}

impl OperationKey {
    pub(crate) fn validate(&self) -> Result<(), OperationError> {
        if self.payload_digest.is_zero() {
            return Err(OperationError::InvalidDigest("operation payload"));
        }
        Ok(())
    }
}

/// Reference-model witness used to exercise operation transitions.
///
/// This value is deliberately named `ReferenceAuthorityWitness`: it is not a
/// cryptographic credential, cannot authenticate a caller and must never be
/// accepted by a production effect adapter. Product composition consumes the
/// non-serializable final-use token owned by `kernel.authority` instead.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReferenceAuthorityWitness {
    operation_id: StableId,
    final_payload_digest: Digest32,
    authority_generation: Generation,
    expires_at_unix_ms: u64,
    witness_digest: Digest32,
}

impl ReferenceAuthorityWitness {
    pub fn new(
        operation_id: StableId,
        final_payload_digest: Digest32,
        authority_generation: Generation,
        expires_at_unix_ms: u64,
        witness_digest: Digest32,
    ) -> Result<Self, OperationError> {
        if final_payload_digest.is_zero() {
            return Err(OperationError::InvalidDigest("authority payload"));
        }
        if witness_digest.is_zero() {
            return Err(OperationError::InvalidDigest("authority witness"));
        }
        if expires_at_unix_ms == 0 {
            return Err(OperationError::AuthorityRejected);
        }
        Ok(Self {
            operation_id,
            final_payload_digest,
            authority_generation,
            expires_at_unix_ms,
            witness_digest,
        })
    }

    pub fn validates(&self, key: &OperationKey, now_unix_ms: u64) -> bool {
        key.validate().is_ok()
            && self.operation_id == key.id
            && self.final_payload_digest == key.payload_digest
            && now_unix_ms < self.expires_at_unix_ms
            && !self.witness_digest.is_zero()
    }

    pub const fn authority_generation(&self) -> Generation {
        self.authority_generation
    }

    pub const fn witness_digest(&self) -> Digest32 {
        self.witness_digest
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ReconciliationOutcome {
    Applied,
    NotApplied,
    Quarantined,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OperationState {
    Pending,
    Authorized {
        witness_digest: Digest32,
        authority_generation: Generation,
    },
    Dispatched {
        dispatch_digest: Digest32,
    },
    Indeterminate {
        reason_digest: Digest32,
    },
    Applied {
        outcome_digest: Digest32,
    },
    NotApplied {
        outcome_digest: Digest32,
    },
    Quarantined {
        reason_digest: Digest32,
    },
}

impl OperationState {
    pub const fn label(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Authorized { .. } => "authorized",
            Self::Dispatched { .. } => "dispatched",
            Self::Indeterminate { .. } => "indeterminate",
            Self::Applied { .. } => "applied",
            Self::NotApplied { .. } => "not_applied",
            Self::Quarantined { .. } => "quarantined",
        }
    }

    pub const fn is_terminal(&self) -> bool {
        matches!(
            self,
            Self::Applied { .. } | Self::NotApplied { .. } | Self::Quarantined { .. }
        )
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperationRecord {
    pub key: OperationKey,
    pub owner_generation: Generation,
    pub revision: Revision,
    pub state: OperationState,
}
