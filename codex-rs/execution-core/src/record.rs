use std::error::Error as StdError;
use std::fmt;

use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

pub const EXECUTION_SCHEMA_VERSION: u32 = 1;
pub const MAX_EXECUTION_RECORD_BYTES: usize = 32 * 1024;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Currentness {
    Current,
    Stale,
    Unknown,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum FinalUse {
    NotGranted,
    Verified {
        grant_digest: String,
        verifier_receipt_digest: String,
    },
}

// A tagged unit variant may silently discard extra fields. Decode through
// strict struct variants, then retain the established public unit variant.
// Verified remains an untrusted wire claim; independent verification is still
// required at the existing journal's start and effect boundaries.
impl<'de> Deserialize<'de> for FinalUse {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
        enum Wire {
            NotGranted {},
            Verified {
                grant_digest: String,
                verifier_receipt_digest: String,
            },
        }
        match Wire::deserialize(deserializer)? {
            Wire::NotGranted {} => Ok(Self::NotGranted),
            Wire::Verified {
                grant_digest,
                verifier_receipt_digest,
            } => Ok(Self::Verified {
                grant_digest,
                verifier_receipt_digest,
            }),
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ExecutionClass {
    ReadOnlyInspection,
    FileRead,
    NonDestructiveBuild,
    RestrictedFileWrite,
    DurableProcess,
    PrivilegedAction,
    CrossHostDevice,
}

impl ExecutionClass {
    pub const fn needs_final_use(self) -> bool {
        !matches!(self, Self::ReadOnlyInspection | Self::FileRead)
    }

    pub const fn needs_approval(self) -> bool {
        matches!(self, Self::PrivilegedAction | Self::CrossHostDevice)
    }
}

/// Every record carries the entire exact intent and authority correlation.
///
/// The Verified variant is a claim on the wire, never proof of authorization.
/// The execution host must check a real signed grant via ExecutionVerifier.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionBinding {
    pub schema_version: u32,
    pub run_id: String,
    pub turn_id: String,
    pub cell_id: Option<String>,
    pub organ_id: Option<String>,
    pub operation_id: String,
    pub principal: String,
    pub objective_digest: String,
    pub policy_digest: String,
    pub candidate_digest: String,
    pub host: String,
    pub generation: u64,
    pub idempotency_key: String,
    pub predecessor: Option<String>,
    pub currentness: Currentness,
    pub final_use: FinalUse,
    pub rollback_reference: Option<String>,
}

impl ExecutionBinding {
    pub fn validate(&self) -> Result<(), ExecutionError> {
        if self.schema_version != EXECUTION_SCHEMA_VERSION || self.generation == 0 {
            return Err(ExecutionError::Binding("schema or generation"));
        }
        for value in [
            &self.run_id,
            &self.turn_id,
            &self.operation_id,
            &self.principal,
            &self.host,
            &self.idempotency_key,
        ] {
            validate_text(value)?;
        }
        match (&self.cell_id, &self.organ_id) {
            (Some(cell), None) | (None, Some(cell)) => validate_text(cell)?,
            _ => return Err(ExecutionError::Binding("exactly one cell or organ")),
        }
        for digest in [
            &self.objective_digest,
            &self.policy_digest,
            &self.candidate_digest,
        ] {
            validate_digest(digest)?;
        }
        if let Some(predecessor) = &self.predecessor {
            validate_digest(predecessor)?;
        }
        if let Some(reference) = &self.rollback_reference {
            validate_text(reference)?;
        }
        if let FinalUse::Verified {
            grant_digest,
            verifier_receipt_digest,
        } = &self.final_use
        {
            validate_digest(grant_digest)?;
            validate_digest(verifier_receipt_digest)?;
        }
        Ok(())
    }

    pub(crate) fn same_operation(&self, other: &Self) -> bool {
        self.schema_version == other.schema_version
            && self.run_id == other.run_id
            && self.turn_id == other.turn_id
            && self.cell_id == other.cell_id
            && self.organ_id == other.organ_id
            && self.operation_id == other.operation_id
            && self.principal == other.principal
            && self.objective_digest == other.objective_digest
            && self.policy_digest == other.policy_digest
            && self.candidate_digest == other.candidate_digest
            && self.host == other.host
            && self.generation == other.generation
            && self.idempotency_key == other.idempotency_key
            && self.rollback_reference == other.rollback_reference
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionIntent {
    pub binding: ExecutionBinding,
    pub class: ExecutionClass,
    pub payload_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionReservation {
    pub binding: ExecutionBinding,
    pub lease_digest: String,
    pub expires_at_unix_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ApprovalRequest {
    pub binding: ExecutionBinding,
    pub scope_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionStarted {
    pub binding: ExecutionBinding,
    pub reservation_digest: String,
    pub approval_receipt_digest: Option<String>,
    pub started_at_unix_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionOutputChunk {
    pub binding: ExecutionBinding,
    pub sequence: u32,
    pub byte_count: u32,
    pub content_digest: String,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CompletionStatus {
    Succeeded,
    Failed,
    Indeterminate,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionCompleted {
    pub binding: ExecutionBinding,
    pub status: CompletionStatus,
    pub output_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionCancelled {
    pub binding: ExecutionBinding,
    pub reason_code: String,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ReconciliationStatus {
    NoEffect,
    EffectObserved,
    Indeterminate,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionReconciled {
    pub binding: ExecutionBinding,
    pub status: ReconciliationStatus,
    pub observation_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EffectReceipt {
    pub binding: ExecutionBinding,
    pub effect_digest: String,
    pub verifier_receipt_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(
    tag = "kind",
    content = "record",
    rename_all = "snake_case",
    deny_unknown_fields
)]
pub enum ExecutionRecord {
    ExecutionIntent(ExecutionIntent),
    ExecutionReservation(ExecutionReservation),
    ApprovalRequest(ApprovalRequest),
    ExecutionStarted(ExecutionStarted),
    ExecutionOutputChunk(ExecutionOutputChunk),
    ExecutionCompleted(ExecutionCompleted),
    ExecutionCancelled(ExecutionCancelled),
    ExecutionReconciled(ExecutionReconciled),
    EffectReceipt(EffectReceipt),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ExecutionError {
    Binding(&'static str),
    Sequence(&'static str),
    VerifierRequired,
    AuthorizationDenied,
    Oversized,
    Encoding,
}

impl fmt::Display for ExecutionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ExecutionError {}

impl ExecutionRecord {
    pub fn binding(&self) -> &ExecutionBinding {
        match self {
            Self::ExecutionIntent(v) => &v.binding,
            Self::ExecutionReservation(v) => &v.binding,
            Self::ApprovalRequest(v) => &v.binding,
            Self::ExecutionStarted(v) => &v.binding,
            Self::ExecutionOutputChunk(v) => &v.binding,
            Self::ExecutionCompleted(v) => &v.binding,
            Self::ExecutionCancelled(v) => &v.binding,
            Self::ExecutionReconciled(v) => &v.binding,
            Self::EffectReceipt(v) => &v.binding,
        }
    }

    pub fn validate(&self) -> Result<(), ExecutionError> {
        self.binding().validate()?;
        match self {
            Self::ExecutionIntent(v) => {
                validate_digest(&v.payload_digest)?;
                if v.class.needs_final_use() && v.binding.rollback_reference.is_none() {
                    return Err(ExecutionError::Binding("missing rollback reference"));
                }
            }
            Self::ExecutionReservation(v) => {
                validate_digest(&v.lease_digest)?;
                if v.expires_at_unix_ms == 0 {
                    return Err(ExecutionError::Binding("empty lease deadline"));
                }
            }
            Self::ApprovalRequest(v) => validate_digest(&v.scope_digest)?,
            Self::ExecutionStarted(v) => {
                validate_digest(&v.reservation_digest)?;
                if let Some(digest) = &v.approval_receipt_digest {
                    validate_digest(digest)?;
                }
                if v.started_at_unix_ms == 0 {
                    return Err(ExecutionError::Binding("empty start time"));
                }
            }
            Self::ExecutionOutputChunk(v) => {
                validate_digest(&v.content_digest)?;
                if v.sequence == 0 || v.byte_count == 0 || v.byte_count > 16 * 1024 {
                    return Err(ExecutionError::Binding("invalid output chunk"));
                }
            }
            Self::ExecutionCompleted(v) => validate_digest(&v.output_digest)?,
            Self::ExecutionCancelled(v) => validate_text(&v.reason_code)?,
            Self::ExecutionReconciled(v) => validate_digest(&v.observation_digest)?,
            Self::EffectReceipt(v) => {
                validate_digest(&v.effect_digest)?;
                validate_digest(&v.verifier_receipt_digest)?;
            }
        }
        if serde_json::to_vec(self)
            .map_err(|_| ExecutionError::Encoding)?
            .len()
            > MAX_EXECUTION_RECORD_BYTES
        {
            return Err(ExecutionError::Oversized);
        }
        Ok(())
    }

    pub fn digest(&self) -> Result<String, ExecutionError> {
        self.validate()?;
        let encoded = serde_json::to_vec(self).map_err(|_| ExecutionError::Encoding)?;
        let mut hash = Sha256::new();
        hash.update(b"codex.execution-record.v1\0");
        hash.update(encoded);
        Ok(format!("{:x}", hash.finalize()))
    }
}

fn validate_text(value: &str) -> Result<(), ExecutionError> {
    if value.is_empty() || value.len() > 256 || !value.bytes().all(|byte| byte.is_ascii_graphic()) {
        return Err(ExecutionError::Binding("invalid identity or reference"));
    }
    Ok(())
}

fn validate_digest(value: &str) -> Result<(), ExecutionError> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        || value.bytes().all(|byte| byte == b'0')
    {
        return Err(ExecutionError::Binding("invalid digest"));
    }
    Ok(())
}
