//! Additive PREPARE-ONLY bridge into the original Evidence SQLite owner.
//!
//! The HeptaEvidenceStore persists a complete, digest-bound execution request
//! envelope in its existing provider-effect intent table and existing SQLite
//! writer. It does not authorize, dispatch, reconcile or complete an effect.
//! An independent Final-use token and original owner effect journal remain
//! mandatory for any later tool execution. No new database or writer exists.

use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::execution_contract_v1::ExecutionIntentV1;

use crate::AppendDisposition;
use crate::EvidenceError;
use crate::HeptaEvidenceStore;

const EXECUTION_PREPARE_PROVIDER_SCOPE_V1: &str = "hepta.execution.prepare-only.v1";

pub const EXECUTION_PREPARE_P2A_FINAL_USE_AUTHORITY: bool = false;
pub const EXECUTION_PREPARE_P2A_PRODUCTION_CALLER: bool = false;
pub const EXECUTION_PREPARE_P2A_EXECUTE_ALLOWED: bool = false;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExecutionPreparationReadbackStatusV1 {
    /// This original logical occurrence has no matching Evidence record.
    Absent,
    /// A durable intent is present, but no actual effect was authorized.
    RecordedOnly,
    /// A mutation beyond preparation was observed in this reserved namespace.
    /// Only the original owner may reconcile; no dispatch or retry is granted.
    OriginalOwnerReconciliationRequired,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExecutionPreparationReadbackV1 {
    pub provider_effect_key: ProviderEffectKey,
    pub request_sha256: [u8; 32],
    pub stored_envelope_sha256: Sha256Digest,
    pub status: ExecutionPreparationReadbackStatusV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExecutionPreparationReceiptV1 {
    pub readback: ExecutionPreparationReadbackV1,
    pub disposition: AppendDisposition,
}

struct PreparedEnvelope {
    original: ProviderEffectIntent,
    request_sha256: [u8; 32],
}

fn validate_preparation(intent: &ExecutionIntentV1) -> Result<PreparedEnvelope, EvidenceError> {
    let proposal = intent
        .binding_proposal()
        .map_err(|error| EvidenceError::InvalidRecord(format!("execution intent: {error}")))?;

    // The V1 identity grammar prohibits '|', so this concatenation cannot
    // alias an alternate subject/scope pair. The key must NOT encode the
    // candidate target, generation, fence, epoch, deadline or payload: those
    // differences must conflict against the original logical operation.
    let occurrence = format!("{}|{}", intent.subject_id, intent.scope_id);
    let key = ProviderEffectKey::for_operation(
        EXECUTION_PREPARE_PROVIDER_SCOPE_V1,
        &occurrence,
        &intent.operation_id,
    )
    .map_err(|error| EvidenceError::InvalidRecord(format!("execution key: {error:?}")))?;

    // This reserved entry represents the exact control envelope, NOT the raw
    // external tool bytes. A physical executor must never use its stored
    // digest as a tool effect receipt or provider payload identity.
    let envelope = serde_json::to_vec(intent)
        .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
    let original = ProviderEffectIntent::new(key, Sha256Digest::for_bytes(&envelope));
    Ok(PreparedEnvelope {
        original,
        request_sha256: proposal.request_sha256,
    })
}

impl HeptaEvidenceStore {
    /// Validate original physical request bytes; write the non-executing
    /// envelope via the existing Evidence BEGIN IMMEDIATE transaction; read
    /// back committed state before returning a local prepare-only receipt.
    ///
    /// Same-operation changes conflict rather than create another effect.
    /// After a crash, identical stage requests are idempotent and never send.
    pub async fn prepare_execution_intent_v1(
        &self,
        intent: &ExecutionIntentV1,
        payload: &[u8],
    ) -> Result<ExecutionPreparationReceiptV1, EvidenceError> {
        intent
            .verify_payload(payload)
            .map_err(|error| EvidenceError::InvalidRecord(format!("execution payload: {error}")))?;

        let prepared = validate_preparation(intent)?;
        let disposition = self
            .append_provider_effect_intent(&prepared.original)
            .await?;
        let readback = self.read_execution_preparation_v1(intent).await?;
        if readback.status != ExecutionPreparationReadbackStatusV1::RecordedOnly {
            return Err(EvidenceError::Corrupt(
                "execution preparation did not remain prepare-only".to_owned(),
            ));
        }
        Ok(ExecutionPreparationReceiptV1 {
            readback,
            disposition,
        })
    }

    /// Cold/read-only original Evidence lookup. The caller must separately
    /// authenticate the source of the supplied intent: matching bytes alone
    /// do not make a Final-use grant, tool execution or provider outcome true.
    pub async fn read_execution_preparation_v1(
        &self,
        intent: &ExecutionIntentV1,
    ) -> Result<ExecutionPreparationReadbackV1, EvidenceError> {
        let prepared = validate_preparation(intent)?;
        let expected = &prepared.original;
        let observed = self.get_provider_effect(&expected.key).await?;
        let status = match observed {
            None => ExecutionPreparationReadbackStatusV1::Absent,
            Some(record) => {
                if &record.intent.intent != expected {
                    return Err(EvidenceError::IdempotencyConflict {
                        record_id: expected.key.as_str().to_owned(),
                    });
                }
                if record.acknowledgements.is_empty() && record.uncertainties.is_empty() {
                    ExecutionPreparationReadbackStatusV1::RecordedOnly
                } else {
                    ExecutionPreparationReadbackStatusV1::OriginalOwnerReconciliationRequired
                }
            }
        };
        Ok(ExecutionPreparationReadbackV1 {
            provider_effect_key: expected.key.clone(),
            request_sha256: prepared.request_sha256,
            stored_envelope_sha256: expected.payload_sha256.clone(),
            status,
        })
    }
}
