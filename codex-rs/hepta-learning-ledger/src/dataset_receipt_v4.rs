//! Self-describing row-committed dataset receipt for production training admission.
//!
//! V3 remains the immutable ledger/source-set receipt. V4 adds the exact row
//! schema, canonical row commitment, training profile, validity window, and a
//! versioned envelope digest. The additive envelope does not change V3 bytes or
//! grant model selection, activation, promotion, or release authority.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AuthenticatedPrincipalV1;
use crate::DatasetFreezePlanV2;
use crate::DatasetReceiptError;
use crate::DatasetSnapshotReceiptV3;
use crate::LearningEvidenceRoleV1;
use crate::LedgerRecord;
use crate::LedgerSnapshot;
use crate::LedgerWriter;
use crate::ProductionLedgerError;
use crate::SignedEvidenceError;
use crate::SignedLearningEvidenceV1;
use crate::dataset_freeze_signing_payload_v2;
use crate::freeze_dataset_from_ledger;
use crate::verify_dataset_snapshot_receipt_against_ledger_v3;
use crate::verify_dataset_snapshot_receipt_v3;

pub const DATASET_SNAPSHOT_RECEIPT_SCHEMA_V4: u32 = 4;
pub const MAX_DATASET_RECEIPT_ROWS_V4: u64 = 1_000_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DatasetRowCommitmentV1 {
    pub row_schema_digest: Digest32,
    pub row_commitment_root: Digest32,
    pub training_profile_digest: Digest32,
    pub row_count: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DatasetSnapshotReceiptV4 {
    pub schema_version: u32,
    pub base: DatasetSnapshotReceiptV3,
    pub rows: DatasetRowCommitmentV1,
    pub issued_at: u64,
    pub expires_at: u64,
    pub receipt_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DatasetReceiptV4Error {
    V3(DatasetReceiptError),
    Schema,
    EmptyDigest(&'static str),
    RowCount,
    ValidityWindow,
    DigestMismatch,
    Arithmetic,
}

impl fmt::Display for DatasetReceiptV4Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for DatasetReceiptV4Error {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::V3(error) => Some(error),
            Self::Schema
            | Self::EmptyDigest(_)
            | Self::RowCount
            | Self::ValidityWindow
            | Self::DigestMismatch
            | Self::Arithmetic => None,
        }
    }
}

impl From<DatasetReceiptError> for DatasetReceiptV4Error {
    fn from(value: DatasetReceiptError) -> Self {
        Self::V3(value)
    }
}

pub fn issue_dataset_snapshot_receipt_v4(
    base: DatasetSnapshotReceiptV3,
    rows: DatasetRowCommitmentV1,
    issued_at: u64,
    expires_at: u64,
) -> Result<DatasetSnapshotReceiptV4, DatasetReceiptV4Error> {
    let mut receipt = DatasetSnapshotReceiptV4 {
        schema_version: DATASET_SNAPSHOT_RECEIPT_SCHEMA_V4,
        base,
        rows,
        issued_at,
        expires_at,
        receipt_digest: Digest32::ZERO,
    };
    receipt.receipt_digest = dataset_snapshot_receipt_digest_v4(&receipt)?;
    verify_dataset_snapshot_receipt_v4(&receipt, issued_at)?;
    Ok(receipt)
}

pub fn verify_dataset_snapshot_receipt_v4(
    receipt: &DatasetSnapshotReceiptV4,
    now: u64,
) -> Result<(), DatasetReceiptV4Error> {
    if receipt.schema_version != DATASET_SNAPSHOT_RECEIPT_SCHEMA_V4 {
        return Err(DatasetReceiptV4Error::Schema);
    }
    verify_dataset_snapshot_receipt_v3(&receipt.base, now)?;
    validate_row_commitment(&receipt.rows)?;
    if receipt.issued_at == 0
        || receipt.issued_at > receipt.expires_at
        || now < receipt.issued_at
        || now > receipt.expires_at
    {
        return Err(DatasetReceiptV4Error::ValidityWindow);
    }
    if receipt.receipt_digest.is_zero()
        || dataset_snapshot_receipt_digest_v4(receipt)? != receipt.receipt_digest
    {
        return Err(DatasetReceiptV4Error::DigestMismatch);
    }
    Ok(())
}

pub fn verify_dataset_snapshot_receipt_against_ledger_v4(
    receipt: &DatasetSnapshotReceiptV4,
    ledger_snapshot: &LedgerSnapshot,
    now: u64,
) -> Result<(), DatasetReceiptV4Error> {
    verify_dataset_snapshot_receipt_v4(receipt, now)?;
    verify_dataset_snapshot_receipt_against_ledger_v3(&receipt.base, ledger_snapshot, now)?;
    Ok(())
}

pub fn dataset_snapshot_receipt_digest_v4(
    receipt: &DatasetSnapshotReceiptV4,
) -> Result<Digest32, DatasetReceiptV4Error> {
    let base = &receipt.base;
    let snapshot = &base.snapshot;
    let mut bytes = b"hepta.learning-ledger.dataset-snapshot-receipt.v4\0".to_vec();
    bytes.extend_from_slice(&receipt.schema_version.to_be_bytes());
    push_id(&mut bytes, &snapshot.snapshot_id)?;
    push_principal(&mut bytes, &base.producer)?;
    for digest in [
        snapshot.dataset_digest,
        snapshot.ledger_head_digest,
        snapshot.objective_digest,
        base.correction_cut_digest,
        base.revocation_cut_digest,
        base.inclusion_policy_digest,
        receipt.rows.row_schema_digest,
        receipt.rows.row_commitment_root,
        receipt.rows.training_profile_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&snapshot.eligible_frontier.to_be_bytes());
    bytes.extend_from_slice(&snapshot.outcome_watermark.to_be_bytes());
    bytes.extend_from_slice(&snapshot.pending_outcomes.to_be_bytes());
    bytes.extend_from_slice(&snapshot.censored_outcomes.to_be_bytes());
    bytes.extend_from_slice(&receipt.rows.row_count.to_be_bytes());
    bytes.extend_from_slice(&receipt.issued_at.to_be_bytes());
    bytes.extend_from_slice(&receipt.expires_at.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

fn validate_row_commitment(rows: &DatasetRowCommitmentV1) -> Result<(), DatasetReceiptV4Error> {
    for (label, digest) in [
        ("row schema", rows.row_schema_digest),
        ("row commitment", rows.row_commitment_root),
        ("training profile", rows.training_profile_digest),
    ] {
        if digest.is_zero() {
            return Err(DatasetReceiptV4Error::EmptyDigest(label));
        }
    }
    if rows.row_count == 0 || rows.row_count > MAX_DATASET_RECEIPT_ROWS_V4 {
        return Err(DatasetReceiptV4Error::RowCount);
    }
    Ok(())
}

fn push_principal(
    bytes: &mut Vec<u8>,
    principal: &AuthenticatedPrincipalV1,
) -> Result<(), DatasetReceiptV4Error> {
    push_id(bytes, &principal.principal_id)?;
    bytes.extend_from_slice(principal.credential_chain_digest.as_array());
    bytes.extend_from_slice(principal.signing_key_digest.as_array());
    bytes.extend_from_slice(principal.scope_digest.as_array());
    bytes.extend_from_slice(&principal.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&principal.authenticated_at.to_be_bytes());
    bytes.extend_from_slice(&principal.expires_at.to_be_bytes());
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), DatasetReceiptV4Error> {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(
        &u32::try_from(raw.len())
            .map_err(|_| DatasetReceiptV4Error::Arithmetic)?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(raw);
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DatasetFreezePlanV4 {
    pub base: DatasetFreezePlanV2,
    pub rows: DatasetRowCommitmentV1,
    pub expires_at: u64,
}

#[derive(Debug)]
pub enum DatasetFreezeV4Error {
    Production(ProductionLedgerError),
    Evidence(SignedEvidenceError),
    Receipt(DatasetReceiptV4Error),
}

impl fmt::Display for DatasetFreezeV4Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for DatasetFreezeV4Error {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Production(error) => Some(error),
            Self::Evidence(error) => Some(error),
            Self::Receipt(error) => Some(error),
        }
    }
}

impl From<ProductionLedgerError> for DatasetFreezeV4Error {
    fn from(value: ProductionLedgerError) -> Self {
        Self::Production(value)
    }
}

impl From<SignedEvidenceError> for DatasetFreezeV4Error {
    fn from(value: SignedEvidenceError) -> Self {
        Self::Evidence(value)
    }
}

impl From<DatasetReceiptV4Error> for DatasetFreezeV4Error {
    fn from(value: DatasetReceiptV4Error) -> Self {
        Self::Receipt(value)
    }
}

pub fn dataset_freeze_signing_payload_v4(
    snapshot: &LedgerSnapshot,
    plan: &DatasetFreezePlanV4,
) -> Result<Vec<u8>, DatasetFreezeV4Error> {
    validate_row_commitment(&plan.rows)?;
    if plan.expires_at == 0 {
        return Err(DatasetReceiptV4Error::ValidityWindow.into());
    }
    let base_payload = dataset_freeze_signing_payload_v2(snapshot, &plan.base)?;
    let mut bytes = b"hepta.learning-ledger.dataset-freeze-plan.v4\0".to_vec();
    bytes.extend_from_slice(Digest32::of_bytes(&base_payload).as_array());
    for digest in [
        plan.rows.row_schema_digest,
        plan.rows.row_commitment_root,
        plan.rows.training_profile_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&plan.rows.row_count.to_be_bytes());
    bytes.extend_from_slice(&plan.expires_at.to_be_bytes());
    Ok(bytes)
}

pub fn freeze_dataset_from_ledger_v4(
    snapshot: &LedgerSnapshot,
    plan: DatasetFreezePlanV4,
    producer: AuthenticatedPrincipalV1,
    issued_at: u64,
) -> Result<DatasetSnapshotReceiptV4, DatasetFreezeV4Error> {
    let base = freeze_dataset_from_ledger(snapshot, plan.base, producer, issued_at)?;
    issue_dataset_snapshot_receipt_v4(base, plan.rows, issued_at, plan.expires_at)
        .map_err(Into::into)
}

impl LedgerWriter {
    /// Freeze the exact current ledger and bind the training row commitment in
    /// the evaluator-signed payload. V3 remains available only as compatibility.
    pub fn freeze_dataset_v4(
        &self,
        plan: DatasetFreezePlanV4,
        evidence: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<DatasetSnapshotReceiptV4, DatasetFreezeV4Error> {
        let snapshot = self.snapshot()?;
        let payload = dataset_freeze_signing_payload_v4(&snapshot, &plan)?;
        let verified = self.verifier().verify(
            LearningEvidenceRoleV1::Evaluator,
            evidence,
            &payload,
            now,
        )?;
        freeze_dataset_from_ledger_v4(
            &snapshot,
            plan,
            verified.principal().clone(),
            now,
        )
    }

    pub fn revalidate_dataset_snapshot_v4(
        &self,
        receipt: &DatasetSnapshotReceiptV4,
        now: u64,
    ) -> Result<(), DatasetFreezeV4Error> {
        verify_dataset_snapshot_receipt_v4(receipt, now)?;
        self.revalidate_dataset_snapshot(&receipt.base, now)?;
        Ok(())
    }

    pub fn read_dataset_records_v4<'a>(
        &'a self,
        receipt: &DatasetSnapshotReceiptV4,
        now: u64,
    ) -> Result<Vec<&'a LedgerRecord>, DatasetFreezeV4Error> {
        self.revalidate_dataset_snapshot_v4(receipt, now)?;
        self.read_dataset_records(&receipt.base, now)
            .map_err(Into::into)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn v4_row_commitment_and_window_are_digest_bound() {
        let rows = DatasetRowCommitmentV1 {
            row_schema_digest: digest("schema"),
            row_commitment_root: digest("rows"),
            training_profile_digest: digest("training"),
            row_count: 4,
        };
        assert!(validate_row_commitment(&rows).is_ok());
        let mut invalid = rows;
        invalid.row_count = 0;
        assert_eq!(
            validate_row_commitment(&invalid),
            Err(DatasetReceiptV4Error::RowCount)
        );
    }
}
