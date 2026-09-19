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

/// Full semantic identity for a cross-owner operation.
///
/// The legacy `OperationKey` remains the compact reference identity. Production
/// preparation binds the key to an owner/scope/destination and optional
/// predecessor so a retry cannot silently drift any dispatch-relevant field.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct OperationIntent {
    pub key: OperationKey,
    pub scope: StableId,
    pub owner: StableId,
    pub destination: StableId,
    pub expected_predecessor: Option<Digest32>,
}

impl OperationIntent {
    pub fn validate(&self) -> Result<(), OperationError> {
        self.key.validate()
    }

    /// Canonical semantic digest used to bind a durable outbox row to the
    /// exact prepared operation.
    pub fn semantic_digest(&self) -> Digest32 {
        let mut bytes = Vec::with_capacity(512);
        bytes.extend_from_slice(b"hepta.kernel.operations.intent.v1\0");
        push_text(&mut bytes, self.key.id.as_str());
        bytes.extend_from_slice(self.key.payload_digest.as_array());
        push_text(&mut bytes, self.scope.as_str());
        push_text(&mut bytes, self.owner.as_str());
        push_text(&mut bytes, self.destination.as_str());
        match self.expected_predecessor {
            Some(digest) => {
                bytes.push(1);
                bytes.extend_from_slice(digest.as_array());
            }
            None => bytes.push(0),
        }
        Digest32::of_bytes(&bytes)
    }
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    let length = u32::try_from(value.len()).unwrap_or(u32::MAX);
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

/// Reference-model witness used to exercise operation transitions.
///
/// This value is deliberately named `ReferenceAuthorityWitness`.
/// It is not a cryptographic credential, cannot authenticate a caller and must
/// never be accepted by a production effect adapter. Product composition
/// consumes the non-serializable final-use token owned by `kernel.authority`
/// instead.
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
        if expires_at_unix_ms == 0 {
            return Err(OperationError::AuthorityRejected);
        }
        let expected = Self::expected_digest(
            &operation_id,
            final_payload_digest,
            authority_generation,
            expires_at_unix_ms,
        );
        if witness_digest != expected {
            return Err(OperationError::AuthorityWitnessDigestMismatch);
        }
        Ok(Self {
            operation_id,
            final_payload_digest,
            authority_generation,
            expires_at_unix_ms,
            witness_digest,
        })
    }

    /// Canonical semantic digest for one reference witness.
    ///
    /// The digest binds operation identity, final payload, authority generation
    /// and expiry. It is deterministic test/reference evidence only, not a
    /// signature or production credential.
    pub fn expected_digest(
        operation_id: &StableId,
        final_payload_digest: Digest32,
        authority_generation: Generation,
        expires_at_unix_ms: u64,
    ) -> Digest32 {
        let operation_id = operation_id.as_str().as_bytes();
        let mut bytes = Vec::with_capacity(96 + operation_id.len());
        bytes.extend_from_slice(b"hepta.kernel.operations.reference-authority-witness.v1\0");
        bytes.extend_from_slice(
            &u32::try_from(operation_id.len())
                .unwrap_or(u32::MAX)
                .to_be_bytes(),
        );
        bytes.extend_from_slice(operation_id);
        bytes.extend_from_slice(final_payload_digest.as_array());
        bytes.extend_from_slice(&authority_generation.get().to_be_bytes());
        bytes.extend_from_slice(&expires_at_unix_ms.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }

    pub fn validates(&self, key: &OperationKey, now_unix_ms: u64) -> bool {
        key.validate().is_ok()
            && self.operation_id == key.id
            && self.final_payload_digest == key.payload_digest
            && now_unix_ms < self.expires_at_unix_ms
            && self.witness_digest
                == Self::expected_digest(
                    &self.operation_id,
                    self.final_payload_digest,
                    self.authority_generation,
                    self.expires_at_unix_ms,
                )
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
    /// Present for the full cross-owner semantic contract. Legacy `begin`
    /// records intentionally keep this absent and cannot be used with the
    /// bound outbox API.
    pub intent: Option<OperationIntent>,
    pub owner_generation: Generation,
    pub revision: Revision,
    pub state: OperationState,
}
