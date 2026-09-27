//! Canonical, fully bound memory-write receipts.
//!
//! `lane_c::MemoryWriteReceiptV1` remains a compatibility input for existing
//! callers. The type in this module is the authoritative V1 receipt: it binds
//! the complete intent context and models commit/rejection as a tagged outcome,
//! so rejected writes carry no fabricated record identity.

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::contract::CANONICAL_JSON_V1_ID;
use crate::contract::ContractDigestDomainV1;
use crate::contract::ContractErrorCodeV1;
use crate::contract::ContractViolationV1;
use crate::contract::DIGEST_ALGORITHM_V1_ID;
use crate::contract::UNICODE_POLICY_V1_ID;
use crate::contract::ValidateContractV1;
use crate::hnmf::ContractDigestV1;
use crate::hnmf::ContractIdV1;
use crate::hnmf::HnmfContractError;
use crate::lane_c::LaneCContractError;
use crate::lane_c::MemoryWriteDisposition as LegacyMemoryWriteDisposition;
use crate::lane_c::MemoryWriteIntentV1 as LegacyMemoryWriteIntentV1;
use crate::lane_c::MemoryWriteReceiptV1 as LegacyMemoryWriteReceiptV1;
use crate::wire::CognitiveContractV1;

pub const MEMORY_WRITE_RECEIPT_CONTRACT_ID_V1: &str = "MemoryWriteReceiptV1";
pub const MEMORY_WRITE_RECEIPT_SCHEMA_ID_V1: &str = "hepta.cognitive.memory-write-receipt.v1";
pub const MEMORY_WRITE_RECEIPT_SCHEMA_VERSION_V1: u32 = 1;
pub const MAX_MEMORY_WRITE_RECEIPT_BYTES_V1: usize = 32_768;

const INTENT_BINDING_DOMAIN_V1: &[u8] = b"hepta.cognitive.memory-write-intent.binding.v1\0";

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryWriteCommitDispositionV1 {
    Inserted,
    Unchanged,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryWriteRejectionCodeV1 {
    AuthorizationRejected,
    SnapshotConflict,
    WriterFenceMismatch,
    CandidateRejected,
    CapacityExceeded,
    DuplicateIntentConflict,
    Indeterminate,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(
    tag = "state",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum MemoryWriteOutcomeV1 {
    Committed {
        record_id: ContractIdV1,
        record_digest: ContractDigestV1,
        committed_memory_frontier: u64,
        committed_snapshot_digest: ContractDigestV1,
        disposition: MemoryWriteCommitDispositionV1,
    },
    Rejected {
        rejection_code: MemoryWriteRejectionCodeV1,
        observed_snapshot_digest: Option<ContractDigestV1>,
        retryable: bool,
    },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MemoryWriteReceiptV1 {
    intent_id: ContractIdV1,
    intent_digest: ContractDigestV1,
    candidate_digest: ContractDigestV1,
    authorization_digest: ContractDigestV1,
    writer_fence_digest: ContractDigestV1,
    expected_snapshot_digest: ContractDigestV1,
    expected_memory_frontier: u64,
    writer_id: ContractIdV1,
    issued_at_unix_ms: u64,
    outcome: MemoryWriteOutcomeV1,
    receipt_digest: ContractDigestV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum MemoryWriteReceiptErrorV1 {
    LegacyContract(LaneCContractError),
    LegacyRejectedDisposition,
    IntentIdentityMismatch,
    SnapshotBindingMismatch,
    FrontierBindingMismatch,
    ZeroIssuedAt,
    DigestMismatch,
    Identifier(String),
    Digest(String),
}

impl std::fmt::Display for MemoryWriteReceiptErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for MemoryWriteReceiptErrorV1 {}

impl MemoryWriteReceiptV1 {
    pub fn from_legacy_committed(
        intent: &LegacyMemoryWriteIntentV1,
        writer_id: impl Into<String>,
        issued_at_unix_ms: u64,
        legacy: &LegacyMemoryWriteReceiptV1,
    ) -> Result<Self, MemoryWriteReceiptErrorV1> {
        intent
            .validate()
            .map_err(MemoryWriteReceiptErrorV1::LegacyContract)?;
        legacy
            .validate()
            .map_err(MemoryWriteReceiptErrorV1::LegacyContract)?;
        if intent.intent_id != legacy.intent_id {
            return Err(MemoryWriteReceiptErrorV1::IntentIdentityMismatch);
        }
        let disposition = match legacy.disposition {
            LegacyMemoryWriteDisposition::Inserted => MemoryWriteCommitDispositionV1::Inserted,
            LegacyMemoryWriteDisposition::Unchanged => MemoryWriteCommitDispositionV1::Unchanged,
            LegacyMemoryWriteDisposition::Rejected => {
                return Err(MemoryWriteReceiptErrorV1::LegacyRejectedDisposition);
            }
        };
        let expected_frontier = intent.expected_snapshot.vector.memory_ledger_frontier;
        let committed_frontier = legacy.committed_frontier;
        match disposition {
            MemoryWriteCommitDispositionV1::Inserted
                if expected_frontier.checked_add(1) != Some(committed_frontier) =>
            {
                return Err(MemoryWriteReceiptErrorV1::FrontierBindingMismatch);
            }
            MemoryWriteCommitDispositionV1::Unchanged
                if expected_frontier != committed_frontier =>
            {
                return Err(MemoryWriteReceiptErrorV1::FrontierBindingMismatch);
            }
            _ => {}
        }
        if matches!(disposition, MemoryWriteCommitDispositionV1::Unchanged)
            && intent.expected_snapshot.vector_digest != legacy.snapshot_key.vector_digest
        {
            return Err(MemoryWriteReceiptErrorV1::SnapshotBindingMismatch);
        }

        let mut receipt = Self {
            intent_id: ContractIdV1::new(intent.intent_id.to_string())
                .map_err(|error| MemoryWriteReceiptErrorV1::Identifier(error.to_string()))?,
            intent_digest: digest_contract(intent_binding_digest_v1(intent))?,
            candidate_digest: digest_contract(intent.candidate_digest)?,
            authorization_digest: digest_contract(intent.authorization_digest)?,
            writer_fence_digest: digest_contract(intent.writer_fence_digest)?,
            expected_snapshot_digest: digest_contract(intent.expected_snapshot.vector_digest)?,
            expected_memory_frontier: expected_frontier,
            writer_id: ContractIdV1::new(writer_id.into())
                .map_err(|error| MemoryWriteReceiptErrorV1::Identifier(error.to_string()))?,
            issued_at_unix_ms,
            outcome: MemoryWriteOutcomeV1::Committed {
                record_id: ContractIdV1::new(legacy.record_id.to_string())
                    .map_err(|error| MemoryWriteReceiptErrorV1::Identifier(error.to_string()))?,
                record_digest: digest_contract(legacy.record_digest)?,
                committed_memory_frontier: committed_frontier,
                committed_snapshot_digest: digest_contract(legacy.snapshot_key.vector_digest)?,
                disposition,
            },
            receipt_digest: digest_contract(Digest32::of_bytes(b"pending"))?,
        };
        receipt.receipt_digest = digest_contract(receipt.compute_receipt_digest())?;
        receipt.validate()?;
        Ok(receipt)
    }

    pub fn rejected(
        intent: &LegacyMemoryWriteIntentV1,
        writer_id: impl Into<String>,
        issued_at_unix_ms: u64,
        rejection_code: MemoryWriteRejectionCodeV1,
        observed_snapshot_digest: Option<Digest32>,
        retryable: bool,
    ) -> Result<Self, MemoryWriteReceiptErrorV1> {
        intent
            .validate()
            .map_err(MemoryWriteReceiptErrorV1::LegacyContract)?;
        let mut receipt = Self {
            intent_id: ContractIdV1::new(intent.intent_id.to_string())
                .map_err(|error| MemoryWriteReceiptErrorV1::Identifier(error.to_string()))?,
            intent_digest: digest_contract(intent_binding_digest_v1(intent))?,
            candidate_digest: digest_contract(intent.candidate_digest)?,
            authorization_digest: digest_contract(intent.authorization_digest)?,
            writer_fence_digest: digest_contract(intent.writer_fence_digest)?,
            expected_snapshot_digest: digest_contract(intent.expected_snapshot.vector_digest)?,
            expected_memory_frontier: intent.expected_snapshot.vector.memory_ledger_frontier,
            writer_id: ContractIdV1::new(writer_id.into())
                .map_err(|error| MemoryWriteReceiptErrorV1::Identifier(error.to_string()))?,
            issued_at_unix_ms,
            outcome: MemoryWriteOutcomeV1::Rejected {
                rejection_code,
                observed_snapshot_digest: observed_snapshot_digest.map(digest_contract).transpose()?,
                retryable,
            },
            receipt_digest: digest_contract(Digest32::of_bytes(b"pending"))?,
        };
        receipt.receipt_digest = digest_contract(receipt.compute_receipt_digest())?;
        receipt.validate()?;
        Ok(receipt)
    }

    pub fn validate(&self) -> Result<(), MemoryWriteReceiptErrorV1> {
        if self.issued_at_unix_ms == 0 {
            return Err(MemoryWriteReceiptErrorV1::ZeroIssuedAt);
        }
        match &self.outcome {
            MemoryWriteOutcomeV1::Committed {
                committed_memory_frontier,
                committed_snapshot_digest,
                disposition,
                ..
            } => match disposition {
                MemoryWriteCommitDispositionV1::Inserted => {
                    if self.expected_memory_frontier.checked_add(1)
                        != Some(*committed_memory_frontier)
                        || committed_snapshot_digest == &self.expected_snapshot_digest
                    {
                        return Err(MemoryWriteReceiptErrorV1::FrontierBindingMismatch);
                    }
                }
                MemoryWriteCommitDispositionV1::Unchanged => {
                    if self.expected_memory_frontier != *committed_memory_frontier
                        || committed_snapshot_digest != &self.expected_snapshot_digest
                    {
                        return Err(MemoryWriteReceiptErrorV1::FrontierBindingMismatch);
                    }
                }
            },
            MemoryWriteOutcomeV1::Rejected { .. } => {}
        }
        if self.receipt_digest.digest() != self.compute_receipt_digest() {
            return Err(MemoryWriteReceiptErrorV1::DigestMismatch);
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_receipt_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(MEMORY_WRITE_RECEIPT_SCHEMA_ID_V1.as_bytes());
        bytes.push(0);
        bytes.extend_from_slice(&MEMORY_WRITE_RECEIPT_SCHEMA_VERSION_V1.to_be_bytes());
        bytes.push(0);
        push_text(&mut bytes, self.intent_id.as_str());
        push_digest(&mut bytes, self.intent_digest.digest());
        push_digest(&mut bytes, self.candidate_digest.digest());
        push_digest(&mut bytes, self.authorization_digest.digest());
        push_digest(&mut bytes, self.writer_fence_digest.digest());
        push_digest(&mut bytes, self.expected_snapshot_digest.digest());
        push_u64(&mut bytes, self.expected_memory_frontier);
        push_text(&mut bytes, self.writer_id.as_str());
        push_u64(&mut bytes, self.issued_at_unix_ms);
        match &self.outcome {
            MemoryWriteOutcomeV1::Committed {
                record_id,
                record_digest,
                committed_memory_frontier,
                committed_snapshot_digest,
                disposition,
            } => {
                bytes.push(0);
                push_text(&mut bytes, record_id.as_str());
                push_digest(&mut bytes, record_digest.digest());
                push_u64(&mut bytes, *committed_memory_frontier);
                push_digest(&mut bytes, committed_snapshot_digest.digest());
                bytes.push(match disposition {
                    MemoryWriteCommitDispositionV1::Inserted => 0,
                    MemoryWriteCommitDispositionV1::Unchanged => 1,
                });
            }
            MemoryWriteOutcomeV1::Rejected {
                rejection_code,
                observed_snapshot_digest,
                retryable,
            } => {
                bytes.push(1);
                bytes.push(rejection_code_code(*rejection_code));
                match observed_snapshot_digest {
                    Some(digest) => {
                        bytes.push(1);
                        push_digest(&mut bytes, digest.digest());
                    }
                    None => bytes.push(0),
                }
                bytes.push(u8::from(*retryable));
            }
        }
        digest_domain_v1().digest(&bytes)
    }

    #[must_use]
    pub const fn outcome(&self) -> &MemoryWriteOutcomeV1 {
        &self.outcome
    }

    #[must_use]
    pub const fn intent_id(&self) -> &ContractIdV1 {
        &self.intent_id
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> ContractDigestV1 {
        self.receipt_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

impl ValidateContractV1 for MemoryWriteReceiptV1 {
    fn validate_contract_v1(&self) -> Result<(), ContractViolationV1> {
        self.validate().map_err(|error| {
            ContractViolationV1::new(
                match error {
                    MemoryWriteReceiptErrorV1::DigestMismatch => ContractErrorCodeV1::DigestMismatch,
                    MemoryWriteReceiptErrorV1::ZeroIssuedAt => ContractErrorCodeV1::ZeroValue,
                    _ => ContractErrorCodeV1::BindingMismatch,
                },
                "memoryWriteReceipt",
                error.to_string(),
            )
            .unwrap_or_else(|violation| violation)
        })
    }
}

impl CognitiveContractV1 for MemoryWriteReceiptV1 {
    const CONTRACT_ID: &'static str = MEMORY_WRITE_RECEIPT_CONTRACT_ID_V1;
    const SCHEMA_ID: &'static str = MEMORY_WRITE_RECEIPT_SCHEMA_ID_V1;
    const MAX_ENCODED_BYTES: usize = MAX_MEMORY_WRITE_RECEIPT_BYTES_V1;

    fn validate_contract(&self) -> Result<(), HnmfContractError> {
        self.validate()
            .map_err(|_| HnmfContractError::Invalid("memory write receipt"))
    }
}

#[must_use]
pub fn intent_binding_digest_v1(intent: &LegacyMemoryWriteIntentV1) -> Digest32 {
    let mut bytes = INTENT_BINDING_DOMAIN_V1.to_vec();
    push_text(&mut bytes, intent.intent_id.as_str());
    push_digest(&mut bytes, intent.candidate_digest);
    push_digest(&mut bytes, intent.expected_snapshot.vector_digest);
    push_digest(&mut bytes, intent.writer_fence_digest);
    push_digest(&mut bytes, intent.authorization_digest);
    Digest32::of_bytes(&bytes)
}

const fn rejection_code_code(value: MemoryWriteRejectionCodeV1) -> u8 {
    match value {
        MemoryWriteRejectionCodeV1::AuthorizationRejected => 0,
        MemoryWriteRejectionCodeV1::SnapshotConflict => 1,
        MemoryWriteRejectionCodeV1::WriterFenceMismatch => 2,
        MemoryWriteRejectionCodeV1::CandidateRejected => 3,
        MemoryWriteRejectionCodeV1::CapacityExceeded => 4,
        MemoryWriteRejectionCodeV1::DuplicateIntentConflict => 5,
        MemoryWriteRejectionCodeV1::Indeterminate => 6,
    }
}

const fn digest_domain_v1() -> ContractDigestDomainV1 {
    ContractDigestDomainV1 {
        schema_id: MEMORY_WRITE_RECEIPT_SCHEMA_ID_V1,
        schema_version: MEMORY_WRITE_RECEIPT_SCHEMA_VERSION_V1,
        contract_id: MEMORY_WRITE_RECEIPT_CONTRACT_ID_V1,
        canonicalization_id: CANONICAL_JSON_V1_ID,
        unicode_policy_id: UNICODE_POLICY_V1_ID,
        digest_algorithm_id: DIGEST_ALGORITHM_V1_ID,
    }
}

fn digest_contract(value: Digest32) -> Result<ContractDigestV1, MemoryWriteReceiptErrorV1> {
    ContractDigestV1::from_digest(value)
        .map_err(|error| MemoryWriteReceiptErrorV1::Digest(error.to_string()))
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    push_u64(bytes, u64::try_from(value.len()).unwrap_or(u64::MAX));
    bytes.extend_from_slice(value.as_bytes());
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}
