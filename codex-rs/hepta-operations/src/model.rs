use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::OperationError;

pub const OPERATION_INTENT_V1_SCHEMA_VERSION: u32 = 1;

/// Canonical authority-free operation intent produced by `kernel.operations`.
///
/// This value binds the semantic fields that every cross-owner effect adapter
/// must agree on before final-use authority is consumed. It grants no authority
/// by itself and does not claim durable operation-ledger persistence.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperationIntentV1 {
    operation_id: StableId,
    subject_id: StableId,
    destination_id: StableId,
    payload_digest: Digest32,
    scope_digest: Digest32,
    policy_generation: Generation,
    expected_predecessor: Option<Digest32>,
}

impl OperationIntentV1 {
    pub fn new(
        operation_id: StableId,
        subject_id: StableId,
        destination_id: StableId,
        payload_digest: Digest32,
        scope_digest: Digest32,
        policy_generation: Generation,
        expected_predecessor: Option<Digest32>,
    ) -> Result<Self, OperationError> {
        if payload_digest.is_zero() {
            return Err(OperationError::InvalidDigest("operation intent payload"));
        }
        if scope_digest.is_zero() {
            return Err(OperationError::InvalidDigest("operation intent scope"));
        }
        if expected_predecessor.is_some_and(Digest32::is_zero) {
            return Err(OperationError::InvalidDigest(
                "operation intent expected predecessor",
            ));
        }
        Ok(Self {
            operation_id,
            subject_id,
            destination_id,
            payload_digest,
            scope_digest,
            policy_generation,
            expected_predecessor,
        })
    }

    /// Domain-separated canonical semantic identity for cross-owner use.
    pub fn semantic_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.kernel.operations.operation-intent.v1\0".to_vec();
        push_stable_id(&mut bytes, &self.operation_id);
        push_stable_id(&mut bytes, &self.subject_id);
        push_stable_id(&mut bytes, &self.destination_id);
        bytes.extend_from_slice(self.payload_digest.as_array());
        bytes.extend_from_slice(self.scope_digest.as_array());
        bytes.extend_from_slice(&self.policy_generation.get().to_be_bytes());
        match self.expected_predecessor {
            Some(predecessor) => {
                bytes.push(1);
                bytes.extend_from_slice(predecessor.as_array());
            }
            None => bytes.push(0),
        }
        Digest32::of_bytes(&bytes)
    }

    pub fn operation_key(&self) -> OperationKey {
        OperationKey {
            id: self.operation_id.clone(),
            payload_digest: self.payload_digest,
        }
    }

    pub fn operation_id(&self) -> &StableId {
        &self.operation_id
    }

    pub fn subject_id(&self) -> &StableId {
        &self.subject_id
    }

    pub fn destination_id(&self) -> &StableId {
        &self.destination_id
    }

    pub const fn payload_digest(&self) -> Digest32 {
        self.payload_digest
    }

    pub const fn scope_digest(&self) -> Digest32 {
        self.scope_digest
    }

    pub const fn policy_generation(&self) -> Generation {
        self.policy_generation
    }

    pub const fn expected_predecessor(&self) -> Option<Digest32> {
        self.expected_predecessor
    }
}

fn push_stable_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

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
    pub owner_generation: Generation,
    pub revision: Revision,
    pub state: OperationState,
}

#[cfg(test)]
mod operation_intent_tests {
    use super::*;

    fn intent(
        operation: &str,
        subject: &str,
        destination: &str,
        payload: &[u8],
        scope: &[u8],
        generation: u64,
        predecessor: Option<&[u8]>,
    ) -> OperationIntentV1 {
        OperationIntentV1::new(
            StableId::new(operation).expect("operation"),
            StableId::new(subject).expect("subject"),
            StableId::new(destination).expect("destination"),
            Digest32::of_bytes(payload),
            Digest32::of_bytes(scope),
            Generation::new(generation).expect("generation"),
            predecessor.map(Digest32::of_bytes),
        )
        .expect("intent")
    }

    #[test]
    fn canonical_intent_digest_binds_every_kernel_semantic_field() {
        let base = intent(
            "matrix.send",
            "agent.one",
            "provider.matrix",
            b"payload",
            b"scope",
            7,
            Some(b"predecessor"),
        );
        let expected = base.semantic_digest();
        for changed in [
            intent("matrix.edit", "agent.one", "provider.matrix", b"payload", b"scope", 7, Some(b"predecessor")),
            intent("matrix.send", "agent.two", "provider.matrix", b"payload", b"scope", 7, Some(b"predecessor")),
            intent("matrix.send", "agent.one", "provider.other", b"payload", b"scope", 7, Some(b"predecessor")),
            intent("matrix.send", "agent.one", "provider.matrix", b"other", b"scope", 7, Some(b"predecessor")),
            intent("matrix.send", "agent.one", "provider.matrix", b"payload", b"other", 7, Some(b"predecessor")),
            intent("matrix.send", "agent.one", "provider.matrix", b"payload", b"scope", 8, Some(b"predecessor")),
            intent("matrix.send", "agent.one", "provider.matrix", b"payload", b"scope", 7, Some(b"other-predecessor")),
            intent("matrix.send", "agent.one", "provider.matrix", b"payload", b"scope", 7, None),
        ] {
            assert_ne!(expected, changed.semantic_digest());
        }
    }

    #[test]
    fn zero_semantic_digests_are_rejected() {
        let result = OperationIntentV1::new(
            StableId::new("operation").expect("operation"),
            StableId::new("subject").expect("subject"),
            StableId::new("destination").expect("destination"),
            Digest32::ZERO,
            Digest32::of_bytes(b"scope"),
            Generation::new(1).expect("generation"),
            None,
        );
        assert!(matches!(result, Err(OperationError::InvalidDigest(_))));
    }
}
