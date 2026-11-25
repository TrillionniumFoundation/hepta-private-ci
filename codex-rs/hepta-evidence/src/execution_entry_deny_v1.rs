//! Read-only P2b admission audit: NO implementation can enter a physical tool effect.
//!
//! The existing owner can inspect a durable P2a preparation, but the original
//! signed Final-use + current trusted frontier + durable physical dispatch
//! linearization are not composed yet. A boolean, caller-provided witness,
//! digest or claimed signature cannot fill those missing trust boundaries.

use codex_hepta_contracts::execution_contract_v1::ExecutionIntentV1;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::execution_preparation_v1::ExecutionPreparationReadbackStatusV1;

/// Negative-only reason codes. No affirmative permit is representable.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExecutionEffectEntryDeniedV1 {
    NoOriginalPreparation,
    OriginalOwnerReconciliationRequired,
    IndependentFinalUseAndPhysicalOwnerUnavailable,
}

/// Read-only verdict. Not a token, capability, grant, lease, or receipt.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExecutionEffectEntryAuditV1 {
    pub operation_id: String,
    pub request_sha256: [u8; 32],
    pub generation: u64,
    pub fence: u64,
    pub denied: ExecutionEffectEntryDeniedV1,
}

pub const EXECUTION_EFFECT_ENTRY_P2B_PERMITTED: bool = false;

impl HeptaEvidenceStore {
    /// Verify original prepared envelope against this same real Evidence
    /// database before refusing physical effect entry.
    ///
    /// A successful return means ONLY that the deny decision was reached.
    /// It does not prove independent signer freshness, a provider receipt,
    /// or the absence of an external effect from an earlier process.
    pub async fn audit_execution_effect_entry_denied_v1(
        &self,
        intent: &ExecutionIntentV1,
        payload: &[u8],
    ) -> Result<ExecutionEffectEntryAuditV1, EvidenceError> {
        intent.verify_payload(payload).map_err(|error| {
            EvidenceError::InvalidRecord(format!("execution entry payload: {error}"))
        })?;
        let original = self.read_execution_preparation_v1(intent).await?;
        let reason = match original.status {
            ExecutionPreparationReadbackStatusV1::Absent => {
                ExecutionEffectEntryDeniedV1::NoOriginalPreparation
            }
            ExecutionPreparationReadbackStatusV1::OriginalOwnerReconciliationRequired => {
                ExecutionEffectEntryDeniedV1::OriginalOwnerReconciliationRequired
            }
            ExecutionPreparationReadbackStatusV1::RecordedOnly => {
                // This is the crucial fail-closed barrier: even an exactly
                // matching durable preparation cannot create Final-use.
                ExecutionEffectEntryDeniedV1::IndependentFinalUseAndPhysicalOwnerUnavailable
            }
        };
        Ok(ExecutionEffectEntryAuditV1 {
            operation_id: intent.operation_id.clone(),
            request_sha256: original.request_sha256,
            generation: intent.generation,
            fence: intent.fence,
            denied: reason,
        })
    }
}
