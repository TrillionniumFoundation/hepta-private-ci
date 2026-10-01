//! Root frozen scope and public authority pins used before credential effects.
use super::ConsumerPortError;
use crate::BaoSecretReceipt;
use crate::role_client::AuthorityTimeSource;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_types::Digest32;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use std::path::PathBuf;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ConsumerReceiptPolicy {
    pub(crate) authority: AuthorityTimeSource,
    pub(crate) issuer_id: String,
    pub(crate) issuer_verifying_key: [u8; 32],
    pub(crate) approver_id: String,
    pub(crate) approver_verifying_key: [u8; 32],
    pub(crate) frozen_binding: FinalUseBinding,
    pub(crate) version: u64,
    pub(crate) credential_bytes: usize,
    pub(crate) preparation_lifetime_ms: u64,
    pub(crate) cost: u64,
    pub(crate) settlement_issuer_id: String,
    pub(crate) settlement_key_epoch: u64,
    pub(crate) settlement_signing_key_file: PathBuf,
    pub(crate) settlement_verifying_key: [u8; 32],
    pub(crate) settlement_lifetime_ms: u64,
}
impl ConsumerReceiptPolicy {
    pub(super) fn validate(
        &self,
        credential_digest: &[u8; 32],
        ack_key: &[u8; 32],
    ) -> Result<[u8; 32], ConsumerPortError> {
        if self.version == 0
            || self.cost == 0
            || self.credential_bytes == 0
            || self.credential_bytes > 8192
            || self.preparation_lifetime_ms == 0
            || self.preparation_lifetime_ms > 5_000
            || self.settlement_lifetime_ms == 0
            || self.settlement_lifetime_ms > 10_000
            || self.frozen_binding.destination_id != "provider:heptabao"
            || self.frozen_binding.payload_sha256 != *credential_digest
            || self.frozen_binding.request_sha256 == [0; 32]
            || self.frozen_binding.scope_sha256 == [0; 32]
        {
            return Err(ConsumerPortError::Invalid);
        }
        let pins = [
            *ack_key,
            self.issuer_verifying_key,
            self.approver_verifying_key,
            self.authority.verifying_key,
            self.settlement_verifying_key,
        ];
        if pins
            .iter()
            .copied()
            .collect::<std::collections::BTreeSet<_>>()
            .len()
            != pins.len()
        {
            return Err(ConsumerPortError::Invalid);
        }
        for pin in pins {
            if VerifyingKey::from_bytes(&pin)
                .map_err(|_| ConsumerPortError::Invalid)?
                .is_weak()
            {
                return Err(ConsumerPortError::Invalid);
            }
        }
        codex_hepta_types::StableId::new(&self.settlement_issuer_id)
            .map_err(|_| ConsumerPortError::Invalid)?;
        codex_hepta_types::Generation::new(self.settlement_key_epoch)
            .map_err(|_| ConsumerPortError::Invalid)?;
        // Paths do not change the immutable purpose/policy identity.
        let encoding = serde_json::to_vec(&(
            "hepta.secrets.consumer.receipt-policy.v2",
            (
                &self.issuer_id,
                self.issuer_verifying_key,
                &self.approver_id,
                self.approver_verifying_key,
                &self.frozen_binding,
                self.version,
                self.credential_bytes,
                self.preparation_lifetime_ms,
                self.cost,
            ),
            (
                &self.settlement_issuer_id,
                self.settlement_key_epoch,
                self.settlement_verifying_key,
                &self.authority.issuer_id,
                self.authority.key_epoch,
                self.authority.verifying_key,
                self.settlement_lifetime_ms,
                ack_key,
            ),
        ))
        .map_err(|_| ConsumerPortError::Invalid)?;
        Ok(Digest32::of_bytes(&encoding).into_array())
    }
    pub(super) fn verify_receipt(
        &self,
        receipt: &BaoSecretReceipt,
    ) -> Result<(), ConsumerPortError> {
        if receipt.request_sha256 != self.frozen_binding.request_sha256
            || receipt.secret_sha256 != self.frozen_binding.payload_sha256
            || receipt.version != self.version
            || receipt.secret_bytes != self.credential_bytes
            || receipt.response_sha256 == [0; 32]
        {
            return Err(ConsumerPortError::Rejected);
        }
        Ok(())
    }
}
