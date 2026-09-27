use std::fmt;
use std::sync::Arc;

use codex_hepta_contracts::EnteredUseToken;
use codex_hepta_contracts::FinalUseBinding;

use super::*;
use crate::content::outbound_payload_digest;

/// Single-use admission to one exact Matrix adapter invocation.
///
/// Only the final-poll gate can construct this value, after consuming a genuine
/// kernel token. It cannot be cloned, deserialized, or constructed from receipt
/// strings. Holding it is entry evidence, not permission to retry or to ignore
/// subsequent cancellation/revocation checks performed by the gate.
///
/// ```compile_fail
/// let forged = codex_hepta_matrix_sdk::MatrixSendPermit {};
/// ```
pub struct MatrixSendPermit {
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

    pub(crate) fn validate(
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
