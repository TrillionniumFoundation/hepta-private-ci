
use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_infer_core::control_contract::SettlementTerminalV1;
use codex_hepta_infer_core::control_contract::SignedSettlementReceiptV1;
use codex_hepta_infer_core::control_contract::VerifiedRetirementReceiptV1;
use codex_hepta_infer_core::control_contract::VerifiedSettlementReceiptV1;
use codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus;
use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;
use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
use codex_hepta_infer_core::durable_control::native::NativeRunStatus;
use serde::Serialize;

const MAX_EVIDENCE_BYTES: u64 = 2 * 1024 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ReconciliationEvidenceError {
    InvalidNamespace,
    ReceiptMismatch,
    EvidenceConflict,
    EvidenceTooLarge,
    Encoding,
    Io(String),
}

impl fmt::Display for ReconciliationEvidenceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ReconciliationEvidenceError {}

impl From<std::io::Error> for ReconciliationEvidenceError {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value.to_string())
    }
}

#[derive(Clone, Debug)]
pub struct ReconciliationEvidenceStore {
    directory: PathBuf,
    namespace: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PersistedSettlementEvidence {
    receipt_sha256: [u8; 32],
    path: PathBuf,
}

impl PersistedSettlementEvidence {
    pub const fn receipt_sha256(&self) -> [u8; 32] {
        self.receipt_sha256
    }

    pub fn path(&self) -> &Path {
        &self.path
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PersistedRetirementEvidence {
    receipt_sha256: [u8; 32],
    path: PathBuf,
}

impl PersistedRetirementEvidence {
    pub const fn receipt_sha256(&self) -> [u8; 32] {
        self.receipt_sha256
    }

    pub fn path(&self) -> &Path {
        &self.path
    }
}

#[derive(Serialize)]
#[serde(deny_unknown_fields)]
struct RetirementAuditRecord<'a> {
    schema_version: u32,
    proposal: &'a codex_hepta_infer_core::control_contract::IndeterminateRetirementProposalV1,
    proposal_sha256: [u8; 32],
    approval_key_ids: &'a [String],
    retirement_receipt_sha256: [u8; 32],
}

impl ReconciliationEvidenceStore {
    pub fn open(
        directory: impl AsRef<Path>,
        namespace: impl Into<String>,
    ) -> Result<Self, ReconciliationEvidenceError> {
        let namespace = namespace.into();
        if namespace.is_empty()
            || namespace.len() > 128
            || !namespace
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
        {
            return Err(ReconciliationEvidenceError::InvalidNamespace);
        }
        let directory = directory.as_ref().to_path_buf();
        fs::create_dir_all(&directory)?;
        ensure_private_directory(&directory)?;
        sync_directory(&directory)?;
        Ok(Self {
            directory,
            namespace,
        })
    }

    pub fn persist_settlement(
        &self,
        verified: &VerifiedSettlementReceiptV1,
        signed: &SignedSettlementReceiptV1,
    ) -> Result<PersistedSettlementEvidence, ReconciliationEvidenceError> {
        if verified.receipt() != &signed.receipt
            || verified.trust_key_id() != signed.signer_key_id
        {
            return Err(ReconciliationEvidenceError::ReceiptMismatch);
        }
        let receipt_sha256 = verified.receipt_sha256();
        let bytes = serde_json::to_vec(signed)
            .map_err(|_| ReconciliationEvidenceError::Encoding)?;
        let path = self.evidence_path("settlement", receipt_sha256);
        persist_exact(&self.directory, &path, &bytes)?;
        Ok(PersistedSettlementEvidence {
            receipt_sha256,
            path,
        })
    }

    pub fn persist_retirement(
        &self,
        verified: &VerifiedRetirementReceiptV1,
    ) -> Result<PersistedRetirementEvidence, ReconciliationEvidenceError> {
        let record = RetirementAuditRecord {
            schema_version: 1,
            proposal: verified.proposal(),
            proposal_sha256: verified.proposal_sha256(),
            approval_key_ids: verified.approval_key_ids(),
            retirement_receipt_sha256: verified.receipt_sha256(),
        };
        let bytes = serde_json::to_vec(&record)
            .map_err(|_| ReconciliationEvidenceError::Encoding)?;
        let receipt_sha256 = verified.receipt_sha256();
        let path = self.evidence_path("retirement", receipt_sha256);
        persist_exact(&self.directory, &path, &bytes)?;
        Ok(PersistedRetirementEvidence {
            receipt_sha256,
            path,
        })
    }

    fn evidence_path(&self, kind: &str, digest: [u8; 32]) -> PathBuf {
        self.directory.join(format!(
            "{}.{}-{}.json",
            self.namespace,
            kind,
            hex_digest(digest)
        ))
    }
}

/// Map already-verified and already-persisted provider evidence to the current
/// native settlement type.  Plaintext output is deliberately empty; consumers
/// recover the output digest and retention reference from the signed evidence.
