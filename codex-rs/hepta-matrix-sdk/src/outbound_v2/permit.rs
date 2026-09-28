use std::fmt;
use std::sync::Arc;

use codex_hepta_contracts::EnteredUseToken;
use codex_hepta_contracts::FinalUseBinding;

use super::*;
use crate::content::outbound_payload_digest;

/// Single-use admission to one exact Matrix adapter invocation.
///
/// This value is private to `outbound_v2`: only the final-poll gate constructs
/// it after consuming a genuine kernel token, and only the module-private
/// authorized adapter validates and consumes it. It cannot be cloned,
/// deserialized, exported, or replaced by a transport implementation.
pub(super) struct MatrixSendPermit {
    proof: Arc<EnteredUseToken>,
    binding: FinalUseBinding,
    identity: MatrixOutboundIdentity,
    transaction_id: String,
    attempt: u64,
    room_id: String,
    binding_revision: u64,
    generation: u64,
}

impl fmt::Debug for MatrixSendPermit {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("MatrixSendPermit([SEALED ENTRY])")
    }
}

impl MatrixSendPermit {
    pub(super) fn new(
        proof: Arc<EnteredUseToken>,
        binding: &FinalUseBinding,
        identity: &MatrixOutboundIdentity,
        record: &OutboxRecord,
    ) -> Result<Self, MatrixTransportError> {
        let permit = Self {
            proof,
            binding: binding.clone(),
            identity: identity.clone(),
            transaction_id: record.stable_txn_id.as_str().to_string(),
            attempt: record.attempts,
            room_id: record.room_id.as_str().to_string(),
            binding_revision: record.binding_revision,
            generation: record.generation,
        };
        permit.validate(record, identity)?;
        Ok(permit)
    }

    pub(super) fn validate(
        &self,
        record: &OutboxRecord,
        identity: &MatrixOutboundIdentity,
    ) -> Result<(), MatrixTransportError> {
        if !self.proof.matches(&self.binding)
            || &self.identity != identity
            || self.transaction_id != record.stable_txn_id.as_str()
            || self.attempt != record.attempts
            || self.room_id != record.room_id.as_str()
            || self.binding_revision != record.binding_revision
            || self.generation != record.generation
            || outbound_payload_digest(record)
                .map_err(|_| MatrixTransportError::Permanent)?
                .as_str()
                != hex_digest(self.binding.payload_sha256)
        {
            return Err(MatrixTransportError::Permanent);
        }
        Ok(())
    }
}
