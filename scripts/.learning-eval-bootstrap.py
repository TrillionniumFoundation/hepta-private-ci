#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")


def replace(path: str, old: str, new: str, *, count: int = 1) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    actual = text.count(old)
    if actual != count:
        raise SystemExit(f"{path}: expected {count} occurrences, found {actual}: {old[:100]!r}")
    target.write_text(text.replace(old, new, count), encoding="utf-8")


def append_once(path: str, marker: str, content: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if marker in text:
        return
    target.write_text(text.rstrip() + "\n\n" + content.rstrip() + "\n", encoding="utf-8")


write(
    "codex-rs/hepta-intelligence-eval/src/product_admission.rs",
    r'''
//! Product-scoped admission facade for signed independent evaluation.
//!
//! The low-level V2 verifier remains crate-private. Repository consumers bind a
//! decision to one concrete product use and receive a sealed, authority-free
//! receipt instead of a raw verifier result.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::EvaluationClaimScopeV1;
use crate::IndependentEvaluationBundleV1;
use crate::MetricRoleContractV2;
use crate::SignedEvaluationDecisionV1;
use crate::SignedEvaluationError;
use crate::SignedEvaluationEvidenceV1;
use crate::decide_with_signed_evidence_v2;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductScopedEvaluationReceiptV1 {
    pub evaluation_id: StableId,
    pub candidate_id: StableId,
    pub objective_digest: Digest32,
    pub dataset_digest: Digest32,
    pub use_binding_digest: Digest32,
    pub decision: SignedEvaluationDecisionV1,
    pub evidence_digest: Digest32,
    pub authority: AuthorityPosture,
    receipt_seal: Digest32,
}

impl ProductScopedEvaluationReceiptV1 {
    pub fn validate_integrity(&self) -> Result<(), ProductScopedEvaluationErrorV1> {
        if self.objective_digest.is_zero()
            || self.dataset_digest.is_zero()
            || self.use_binding_digest.is_zero()
            || self.decision.decision.evidence_digest.is_zero()
            || self.decision.trust_digest.is_zero()
            || self.decision.authentication_digest.is_zero()
            || self.authority.grants_any()
            || self.decision.decision.authority.grants_any()
            || self.decision.decision.evaluation_id != self.evaluation_id
            || self.decision.decision.candidate_id != self.candidate_id
        {
            return Err(ProductScopedEvaluationErrorV1::Integrity(
                "product-scoped evaluation receipt",
            ));
        }
        let expected = product_scoped_evidence_digest(self);
        if self.evidence_digest != expected
            || self.receipt_seal != product_scoped_receipt_seal(self)
        {
            return Err(ProductScopedEvaluationErrorV1::Integrity(
                "product-scoped evaluation seal",
            ));
        }
        Ok(())
    }
}

pub fn admit_product_scoped_evaluation_v1(
    bundle: IndependentEvaluationBundleV1,
    metric_roles: Vec<MetricRoleContractV2>,
    evidence: &SignedEvaluationEvidenceV1,
    verifier: &LearningEvidenceVerifierV1,
    use_binding_digest: Digest32,
    now: u64,
) -> Result<ProductScopedEvaluationReceiptV1, ProductScopedEvaluationErrorV1> {
    if use_binding_digest.is_zero() {
        return Err(ProductScopedEvaluationErrorV1::Binding("product use"));
    }
    if bundle.claim_scope != EvaluationClaimScopeV1::Qualification {
        return Err(ProductScopedEvaluationErrorV1::Binding(
            "qualification claim scope",
        ));
    }
    let evaluation_id = bundle.evaluation_id.clone();
    let candidate_id = bundle.candidate_id.clone();
    let objective_digest = bundle.objective_digest;
    let dataset_digest = bundle.dataset_digest;
    let decision =
        decide_with_signed_evidence_v2(bundle, metric_roles, evidence, verifier, now)?;
    if decision.decision.authority.grants_any() {
        return Err(ProductScopedEvaluationErrorV1::Integrity(
            "evaluation authority",
        ));
    }
    let mut receipt = ProductScopedEvaluationReceiptV1 {
        evaluation_id,
        candidate_id,
        objective_digest,
        dataset_digest,
        use_binding_digest,
        decision,
        evidence_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
        receipt_seal: Digest32::ZERO,
    };
    receipt.evidence_digest = product_scoped_evidence_digest(&receipt);
    receipt.receipt_seal = product_scoped_receipt_seal(&receipt);
    receipt.validate_integrity()?;
    Ok(receipt)
}

fn product_scoped_evidence_digest(receipt: &ProductScopedEvaluationReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.intelligence-eval.product-scoped-admission.v1".to_vec();
    push_id(&mut bytes, &receipt.evaluation_id);
    push_id(&mut bytes, &receipt.candidate_id);
    for digest in [
        receipt.objective_digest,
        receipt.dataset_digest,
        receipt.use_binding_digest,
        receipt.decision.decision.evidence_digest,
        receipt.decision.trust_digest,
        receipt.decision.authentication_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.push(u8::from(receipt.authority.grants_any()));
    bytes.push(u8::from(receipt.decision.decision.authority.grants_any()));
    Digest32::of_bytes(&bytes)
}

fn product_scoped_receipt_seal(receipt: &ProductScopedEvaluationReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.intelligence-eval.product-scoped-receipt.v1".to_vec();
    bytes.extend_from_slice(product_scoped_evidence_digest(receipt).as_array());
    bytes.extend_from_slice(receipt.evidence_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    bytes.extend_from_slice(&(value.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_str().as_bytes());
}

#[derive(Debug)]
pub enum ProductScopedEvaluationErrorV1 {
    Binding(&'static str),
    Integrity(&'static str),
    Signed(SignedEvaluationError),
}

impl fmt::Display for ProductScopedEvaluationErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ProductScopedEvaluationErrorV1 {}

impl From<SignedEvaluationError> for ProductScopedEvaluationErrorV1 {
    fn from(value: SignedEvaluationError) -> Self {
        Self::Signed(value)
    }
}
''',
)

write(
    "codex-rs/hepta-intelligence-eval/src/evaluation_attempt.rs",
    r'''
//! Durable product-evaluation attempt journal.
//!
//! The journal makes post-holdout failures explicit. It is append-only,
//! checksum-bound, synchronously committed and replayed under one exclusive
//! file lock. Exact retries are idempotent; stage regression conflicts.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use codex_hepta_types::Digest32;

const MAGIC: &[u8; 8] = b"HEPTAJ01";
const HEADER: usize = 72;
const PAYLOAD: usize = 129;
const FRAME: usize = PAYLOAD + 32;
const MAX_BYTES: u64 = 32 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProductEvaluationAttemptStageV1 {
    ComparisonStarted,
    HoldoutConsumed,
    InputsReleased,
    CandidateEstimated,
    BaselineEstimated,
    ComparisonCompleted,
    QualificationStarted,
    QualificationDecided,
    EvidencePublished,
    Failed,
}

impl ProductEvaluationAttemptStageV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::ComparisonStarted => 0,
            Self::HoldoutConsumed => 1,
            Self::InputsReleased => 2,
            Self::CandidateEstimated => 3,
            Self::BaselineEstimated => 4,
            Self::ComparisonCompleted => 5,
            Self::QualificationStarted => 6,
            Self::QualificationDecided => 7,
            Self::EvidencePublished => 8,
            Self::Failed => 255,
        }
    }

    const fn rank(self) -> u16 {
        self.tag() as u16
    }

    fn decode(value: u8) -> Result<Self, ProductEvaluationAttemptErrorV1> {
        match value {
            0 => Ok(Self::ComparisonStarted),
            1 => Ok(Self::HoldoutConsumed),
            2 => Ok(Self::InputsReleased),
            3 => Ok(Self::CandidateEstimated),
            4 => Ok(Self::BaselineEstimated),
            5 => Ok(Self::ComparisonCompleted),
            6 => Ok(Self::QualificationStarted),
            7 => Ok(Self::QualificationDecided),
            8 => Ok(Self::EvidencePublished),
            255 => Ok(Self::Failed),
            _ => Err(ProductEvaluationAttemptErrorV1::Corrupt),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductEvaluationAttemptRecordV1 {
    pub attempt_digest: Digest32,
    pub stage: ProductEvaluationAttemptStageV1,
    pub stage_digest: Digest32,
    pub predecessor_digest: Digest32,
    pub record_digest: Digest32,
}

pub trait ProductEvaluationAttemptJournalV1 {
    fn append(
        &mut self,
        attempt_digest: Digest32,
        stage: ProductEvaluationAttemptStageV1,
        stage_digest: Digest32,
    ) -> Result<ProductEvaluationAttemptRecordV1, ProductEvaluationAttemptErrorV1>;

    fn latest(
        &mut self,
        attempt_digest: Digest32,
    ) -> Result<Option<ProductEvaluationAttemptRecordV1>, ProductEvaluationAttemptErrorV1>;
}

#[derive(Debug)]
pub struct LockedFileProductEvaluationAttemptJournalV1 {
    file: File,
    binding: Digest32,
    records: Vec<ProductEvaluationAttemptRecordV1>,
    length: u64,
    poisoned: bool,
}

impl LockedFileProductEvaluationAttemptJournalV1 {
    pub fn create(mut file: File, binding: Digest32) -> Result<Self, ProductEvaluationAttemptErrorV1> {
        acquire(&file, binding)?;
        if file.metadata().map_err(io_error)?.len() != 0 {
            return Err(ProductEvaluationAttemptErrorV1::AlreadyInitialized);
        }
        let mut header = MAGIC.to_vec();
        header.extend_from_slice(binding.as_array());
        header.extend_from_slice(Digest32::of_bytes(&header).as_array());
        file.seek(SeekFrom::Start(0)).map_err(io_error)?;
        file.write_all(&header)
            .and_then(|()| file.sync_all())
            .map_err(|_| ProductEvaluationAttemptErrorV1::Indeterminate)?;
        Ok(Self {
            file,
            binding,
            records: Vec::new(),
            length: HEADER as u64,
            poisoned: false,
        })
    }

    pub fn recover(mut file: File, binding: Digest32) -> Result<Self, ProductEvaluationAttemptErrorV1> {
        acquire(&file, binding)?;
        let length = file.metadata().map_err(io_error)?.len();
        if length > MAX_BYTES {
            return Err(ProductEvaluationAttemptErrorV1::Capacity);
        }
        file.seek(SeekFrom::Start(0)).map_err(io_error)?;
        let mut bytes = Vec::new();
        (&mut file)
            .take(MAX_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(io_error)?;
        if bytes.len() as u64 != length || bytes.len() < HEADER {
            return Err(ProductEvaluationAttemptErrorV1::Corrupt);
        }
        if &bytes[..8] != MAGIC
            || &bytes[8..40] != binding.as_array()
            || &bytes[40..HEADER] != Digest32::of_bytes(&bytes[..40]).as_array()
            || (bytes.len() - HEADER) % FRAME != 0
        {
            return Err(ProductEvaluationAttemptErrorV1::Corrupt);
        }
        let mut records = Vec::new();
        let mut cursor = HEADER;
        while cursor < bytes.len() {
            let payload = &bytes[cursor..cursor + PAYLOAD];
            let checksum = &bytes[cursor + PAYLOAD..cursor + FRAME];
            if checksum != Digest32::of_bytes(payload).as_array() {
                return Err(ProductEvaluationAttemptErrorV1::Corrupt);
            }
            let record = decode_record(binding, payload)?;
            validate_transition(&records, &record)?;
            records.push(record);
            cursor += FRAME;
        }
        Ok(Self {
            file,
            binding,
            records,
            length,
            poisoned: false,
        })
    }

    #[must_use]
    pub fn record_count(&self) -> usize {
        self.records.len()
    }
}

impl ProductEvaluationAttemptJournalV1 for LockedFileProductEvaluationAttemptJournalV1 {
    fn append(
        &mut self,
        attempt_digest: Digest32,
        stage: ProductEvaluationAttemptStageV1,
        stage_digest: Digest32,
    ) -> Result<ProductEvaluationAttemptRecordV1, ProductEvaluationAttemptErrorV1> {
        if self.poisoned {
            return Err(ProductEvaluationAttemptErrorV1::Indeterminate);
        }
        if attempt_digest.is_zero() || stage_digest.is_zero() {
            return Err(ProductEvaluationAttemptErrorV1::Binding);
        }
        let previous = self
            .records
            .iter()
            .rev()
            .find(|record| record.attempt_digest == attempt_digest);
        if let Some(previous) = previous {
            if previous.stage == stage && previous.stage_digest == stage_digest {
                return Ok(previous.clone());
            }
            if stage.rank() <= previous.stage.rank() {
                return Err(ProductEvaluationAttemptErrorV1::Conflict);
            }
        }
        let predecessor_digest = previous
            .map_or(Digest32::ZERO, |record| record.record_digest);
        let record_digest = record_digest(
            self.binding,
            attempt_digest,
            stage,
            stage_digest,
            predecessor_digest,
        );
        let record = ProductEvaluationAttemptRecordV1 {
            attempt_digest,
            stage,
            stage_digest,
            predecessor_digest,
            record_digest,
        };
        let payload = encode_record(&record);
        let next_length = self
            .length
            .checked_add(FRAME as u64)
            .filter(|value| *value <= MAX_BYTES)
            .ok_or(ProductEvaluationAttemptErrorV1::Capacity)?;
        let write = self
            .file
            .seek(SeekFrom::Start(self.length))
            .and_then(|_| self.file.write_all(&payload))
            .and_then(|_| self.file.write_all(Digest32::of_bytes(&payload).as_array()))
            .and_then(|()| self.file.sync_all());
        if write.is_err() {
            self.poisoned = true;
            return Err(ProductEvaluationAttemptErrorV1::Indeterminate);
        }
        self.records.push(record.clone());
        self.length = next_length;
        Ok(record)
    }

    fn latest(
        &mut self,
        attempt_digest: Digest32,
    ) -> Result<Option<ProductEvaluationAttemptRecordV1>, ProductEvaluationAttemptErrorV1> {
        if self.poisoned {
            return Err(ProductEvaluationAttemptErrorV1::Indeterminate);
        }
        Ok(self
            .records
            .iter()
            .rev()
            .find(|record| record.attempt_digest == attempt_digest)
            .cloned())
    }
}

fn encode_record(record: &ProductEvaluationAttemptRecordV1) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(PAYLOAD);
    bytes.extend_from_slice(record.attempt_digest.as_array());
    bytes.push(record.stage.tag());
    bytes.extend_from_slice(record.stage_digest.as_array());
    bytes.extend_from_slice(record.predecessor_digest.as_array());
    bytes.extend_from_slice(record.record_digest.as_array());
    bytes
}

fn decode_record(
    binding: Digest32,
    payload: &[u8],
) -> Result<ProductEvaluationAttemptRecordV1, ProductEvaluationAttemptErrorV1> {
    if payload.len() != PAYLOAD {
        return Err(ProductEvaluationAttemptErrorV1::Corrupt);
    }
    let attempt_digest = digest_at(payload, 0)?;
    let stage = ProductEvaluationAttemptStageV1::decode(payload[32])?;
    let stage_digest = digest_at(payload, 33)?;
    let predecessor_digest = digest_at(payload, 65)?;
    let stored_digest = digest_at(payload, 97)?;
    if attempt_digest.is_zero() || stage_digest.is_zero() {
        return Err(ProductEvaluationAttemptErrorV1::Corrupt);
    }
    let expected = record_digest(
        binding,
        attempt_digest,
        stage,
        stage_digest,
        predecessor_digest,
    );
    if stored_digest != expected {
        return Err(ProductEvaluationAttemptErrorV1::Corrupt);
    }
    Ok(ProductEvaluationAttemptRecordV1 {
        attempt_digest,
        stage,
        stage_digest,
        predecessor_digest,
        record_digest: stored_digest,
    })
}

fn validate_transition(
    records: &[ProductEvaluationAttemptRecordV1],
    next: &ProductEvaluationAttemptRecordV1,
) -> Result<(), ProductEvaluationAttemptErrorV1> {
    let previous = records
        .iter()
        .rev()
        .find(|record| record.attempt_digest == next.attempt_digest);
    match previous {
        None if next.predecessor_digest.is_zero() => Ok(()),
        Some(previous)
            if next.predecessor_digest == previous.record_digest
                && next.stage.rank() > previous.stage.rank() =>
        {
            Ok(())
        }
        _ => Err(ProductEvaluationAttemptErrorV1::Corrupt),
    }
}

fn record_digest(
    binding: Digest32,
    attempt_digest: Digest32,
    stage: ProductEvaluationAttemptStageV1,
    stage_digest: Digest32,
    predecessor_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.intelligence-eval.attempt-record.v1".to_vec();
    for digest in [binding, attempt_digest, stage_digest, predecessor_digest] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.push(stage.tag());
    Digest32::of_bytes(&bytes)
}

fn digest_at(bytes: &[u8], start: usize) -> Result<Digest32, ProductEvaluationAttemptErrorV1> {
    let raw = bytes
        .get(start..start + 32)
        .ok_or(ProductEvaluationAttemptErrorV1::Corrupt)?;
    let array = raw
        .try_into()
        .map_err(|_| ProductEvaluationAttemptErrorV1::Corrupt)?;
    Ok(Digest32::from_array(array))
}

fn acquire(file: &File, binding: Digest32) -> Result<(), ProductEvaluationAttemptErrorV1> {
    if binding.is_zero() {
        return Err(ProductEvaluationAttemptErrorV1::Binding);
    }
    if !file.metadata().map_err(io_error)?.is_file() {
        return Err(ProductEvaluationAttemptErrorV1::NotRegular);
    }
    file.try_lock().map_err(|error| match error {
        TryLockError::WouldBlock => ProductEvaluationAttemptErrorV1::Busy,
        TryLockError::Error(error) => ProductEvaluationAttemptErrorV1::Io(error.kind()),
    })
}

fn io_error(error: io::Error) -> ProductEvaluationAttemptErrorV1 {
    ProductEvaluationAttemptErrorV1::Io(error.kind())
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProductEvaluationAttemptErrorV1 {
    Binding,
    NotRegular,
    Busy,
    AlreadyInitialized,
    Corrupt,
    Conflict,
    Capacity,
    Indeterminate,
    Io(io::ErrorKind),
}

impl fmt::Display for ProductEvaluationAttemptErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ProductEvaluationAttemptErrorV1 {}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::fs::OpenOptions;
    use std::path::PathBuf;
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;

    static NEXT: AtomicU64 = AtomicU64::new(0);

    struct TempFile(PathBuf);

    impl TempFile {
        fn new() -> Self {
            Self(std::env::temp_dir().join(format!(
                "hepta-eval-attempt-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            )))
        }

        fn create(&self) -> File {
            OpenOptions::new()
                .create_new(true)
                .read(true)
                .write(true)
                .open(&self.0)
                .unwrap_or_else(|error| panic!("create attempt journal: {error}"))
        }

        fn open(&self) -> File {
            OpenOptions::new()
                .read(true)
                .write(true)
                .open(&self.0)
                .unwrap_or_else(|error| panic!("open attempt journal: {error}"))
        }
    }

    impl Drop for TempFile {
        fn drop(&mut self) {
            let _ = fs::remove_file(&self.0);
        }
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn attempt_journal_replays_and_rejects_regression() {
        let temp = TempFile::new();
        let mut journal = LockedFileProductEvaluationAttemptJournalV1::create(
            temp.create(),
            digest("binding"),
        )
        .unwrap_or_else(|error| panic!("create: {error}"));
        let first = journal
            .append(
                digest("attempt"),
                ProductEvaluationAttemptStageV1::ComparisonStarted,
                digest("plan"),
            )
            .unwrap_or_else(|error| panic!("append first: {error}"));
        let second = journal
            .append(
                digest("attempt"),
                ProductEvaluationAttemptStageV1::HoldoutConsumed,
                digest("holdout"),
            )
            .unwrap_or_else(|error| panic!("append second: {error}"));
        assert_eq!(second.predecessor_digest, first.record_digest);
        assert_eq!(
            journal
                .append(
                    digest("attempt"),
                    ProductEvaluationAttemptStageV1::ComparisonStarted,
                    digest("other"),
                )
                .err(),
            Some(ProductEvaluationAttemptErrorV1::Conflict)
        );
        drop(journal);
        let mut recovered = LockedFileProductEvaluationAttemptJournalV1::recover(
            temp.open(),
            digest("binding"),
        )
        .unwrap_or_else(|error| panic!("recover: {error}"));
        assert_eq!(recovered.record_count(), 2);
        assert_eq!(
            recovered
                .latest(digest("attempt"))
                .unwrap_or_else(|error| panic!("latest: {error}")),
            Some(second)
        );
    }
}
''',
)

write(
    "codex-rs/hepta-intelligence-eval/src/qualification_evidence_file.rs",
    r'''
//! Locked-file idempotent qualification-evidence sink.
//!
//! The sink reconciles an acknowledgement lost after a durable commit by
//! looking up the execution/decision identity. A truly uncertain write poisons
//! the handle and must be reopened and replayed before retry.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use codex_hepta_types::Digest32;

use crate::ProductEvidenceCommitV1;
use crate::ProductEvidenceSinkErrorV1;
use crate::ProductQualificationEvidenceSinkV1;
use crate::SignedEvaluationDecisionV1;
use crate::product_runner::product_decision_digest_v1;

const MAGIC: &[u8; 8] = b"HEPTEV01";
const HEADER: usize = 72;
const PAYLOAD: usize = 96;
const FRAME: usize = PAYLOAD + 32;
const MAX_BYTES: u64 = 32 * 1024 * 1024;

pub struct LockedFileQualificationEvidenceSinkV1 {
    file: File,
    binding: Digest32,
    records: Vec<ProductEvidenceCommitV1>,
    length: u64,
    poisoned: bool,
    #[cfg(test)]
    lose_ack_once: bool,
}

impl LockedFileQualificationEvidenceSinkV1 {
    pub fn create(mut file: File, binding: Digest32) -> Result<Self, LockedFileEvidenceErrorV1> {
        acquire(&file, binding)?;
        if file.metadata().map_err(io_error)?.len() != 0 {
            return Err(LockedFileEvidenceErrorV1::AlreadyInitialized);
        }
        let mut header = MAGIC.to_vec();
        header.extend_from_slice(binding.as_array());
        header.extend_from_slice(Digest32::of_bytes(&header).as_array());
        file.seek(SeekFrom::Start(0)).map_err(io_error)?;
        file.write_all(&header)
            .and_then(|()| file.sync_all())
            .map_err(|_| LockedFileEvidenceErrorV1::Indeterminate)?;
        Ok(Self {
            file,
            binding,
            records: Vec::new(),
            length: HEADER as u64,
            poisoned: false,
            #[cfg(test)]
            lose_ack_once: false,
        })
    }

    pub fn recover(mut file: File, binding: Digest32) -> Result<Self, LockedFileEvidenceErrorV1> {
        acquire(&file, binding)?;
        let length = file.metadata().map_err(io_error)?.len();
        if length > MAX_BYTES {
            return Err(LockedFileEvidenceErrorV1::Capacity);
        }
        file.seek(SeekFrom::Start(0)).map_err(io_error)?;
        let mut bytes = Vec::new();
        (&mut file)
            .take(MAX_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(io_error)?;
        if bytes.len() as u64 != length || bytes.len() < HEADER {
            return Err(LockedFileEvidenceErrorV1::Corrupt);
        }
        if &bytes[..8] != MAGIC
            || &bytes[8..40] != binding.as_array()
            || &bytes[40..HEADER] != Digest32::of_bytes(&bytes[..40]).as_array()
            || (bytes.len() - HEADER) % FRAME != 0
        {
            return Err(LockedFileEvidenceErrorV1::Corrupt);
        }
        let mut records = Vec::new();
        let mut cursor = HEADER;
        while cursor < bytes.len() {
            let payload = &bytes[cursor..cursor + PAYLOAD];
            let checksum = &bytes[cursor + PAYLOAD..cursor + FRAME];
            if checksum != Digest32::of_bytes(payload).as_array() {
                return Err(LockedFileEvidenceErrorV1::Corrupt);
            }
            let record = ProductEvidenceCommitV1 {
                execution_digest: digest_at(payload, 0)?,
                decision_digest: digest_at(payload, 32)?,
                publication_digest: digest_at(payload, 64)?,
            };
            if record.execution_digest.is_zero()
                || record.decision_digest.is_zero()
                || record.publication_digest.is_zero()
            {
                return Err(LockedFileEvidenceErrorV1::Corrupt);
            }
            if let Some(existing) = records
                .iter()
                .find(|existing: &&ProductEvidenceCommitV1| {
                    existing.execution_digest == record.execution_digest
                })
            {
                if **existing != record {
                    return Err(LockedFileEvidenceErrorV1::Conflict);
                }
            } else {
                records.push(record);
            }
            cursor += FRAME;
        }
        Ok(Self {
            file,
            binding,
            records,
            length,
            poisoned: false,
            #[cfg(test)]
            lose_ack_once: false,
        })
    }

    #[must_use]
    pub fn record_count(&self) -> usize {
        self.records.len()
    }

    #[cfg(test)]
    fn inject_ack_loss_once(&mut self) {
        self.lose_ack_once = true;
    }
}

impl ProductQualificationEvidenceSinkV1 for LockedFileQualificationEvidenceSinkV1 {
    fn lookup(
        &mut self,
        execution_digest: Digest32,
    ) -> Result<Option<ProductEvidenceCommitV1>, ProductEvidenceSinkErrorV1> {
        if self.poisoned {
            return Err(ProductEvidenceSinkErrorV1::Indeterminate);
        }
        Ok(self
            .records
            .iter()
            .find(|record| record.execution_digest == execution_digest)
            .copied())
    }

    fn persist(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        if self.poisoned {
            return Err(ProductEvidenceSinkErrorV1::Indeterminate);
        }
        let decision_digest = product_decision_digest_v1(decision);
        if execution_digest.is_zero() || decision_digest.is_zero() {
            return Err(ProductEvidenceSinkErrorV1::Rejected);
        }
        if let Some(existing) = self
            .records
            .iter()
            .find(|record| record.execution_digest == execution_digest)
        {
            return if existing.decision_digest == decision_digest {
                Ok(existing.publication_digest)
            } else {
                Err(ProductEvidenceSinkErrorV1::Conflict)
            };
        }
        let publication_digest = publication_digest(self.binding, execution_digest, decision_digest);
        let record = ProductEvidenceCommitV1 {
            execution_digest,
            decision_digest,
            publication_digest,
        };
        let payload = encode_record(record);
        let next_length = self
            .length
            .checked_add(FRAME as u64)
            .filter(|value| *value <= MAX_BYTES)
            .ok_or(ProductEvidenceSinkErrorV1::Rejected)?;
        let write = self
            .file
            .seek(SeekFrom::Start(self.length))
            .and_then(|_| self.file.write_all(&payload))
            .and_then(|_| self.file.write_all(Digest32::of_bytes(&payload).as_array()))
            .and_then(|()| self.file.sync_all());
        if write.is_err() {
            self.poisoned = true;
            return Err(ProductEvidenceSinkErrorV1::Indeterminate);
        }
        self.records.push(record);
        self.length = next_length;
        #[cfg(test)]
        if std::mem::take(&mut self.lose_ack_once) {
            return Err(ProductEvidenceSinkErrorV1::Indeterminate);
        }
        Ok(publication_digest)
    }
}

fn encode_record(record: ProductEvidenceCommitV1) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(PAYLOAD);
    bytes.extend_from_slice(record.execution_digest.as_array());
    bytes.extend_from_slice(record.decision_digest.as_array());
    bytes.extend_from_slice(record.publication_digest.as_array());
    bytes
}

fn publication_digest(
    binding: Digest32,
    execution_digest: Digest32,
    decision_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.intelligence-eval.qualification-publication.v1".to_vec();
    for digest in [binding, execution_digest, decision_digest] {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn digest_at(bytes: &[u8], start: usize) -> Result<Digest32, LockedFileEvidenceErrorV1> {
    let raw = bytes
        .get(start..start + 32)
        .ok_or(LockedFileEvidenceErrorV1::Corrupt)?;
    let array = raw
        .try_into()
        .map_err(|_| LockedFileEvidenceErrorV1::Corrupt)?;
    Ok(Digest32::from_array(array))
}

fn acquire(file: &File, binding: Digest32) -> Result<(), LockedFileEvidenceErrorV1> {
    if binding.is_zero() {
        return Err(LockedFileEvidenceErrorV1::Binding);
    }
    if !file.metadata().map_err(io_error)?.is_file() {
        return Err(LockedFileEvidenceErrorV1::NotRegular);
    }
    file.try_lock().map_err(|error| match error {
        TryLockError::WouldBlock => LockedFileEvidenceErrorV1::Busy,
        TryLockError::Error(error) => LockedFileEvidenceErrorV1::Io(error.kind()),
    })
}

fn io_error(error: io::Error) -> LockedFileEvidenceErrorV1 {
    LockedFileEvidenceErrorV1::Io(error.kind())
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LockedFileEvidenceErrorV1 {
    Binding,
    NotRegular,
    Busy,
    AlreadyInitialized,
    Corrupt,
    Conflict,
    Capacity,
    Indeterminate,
    Io(io::ErrorKind),
}

impl fmt::Display for LockedFileEvidenceErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for LockedFileEvidenceErrorV1 {}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::fs::OpenOptions;
    use std::path::PathBuf;
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;

    use codex_hepta_types::AuthorityPosture;
    use codex_hepta_types::StableId;

    use crate::IndependentEvaluationDecisionV1;
    use crate::IndependentEvaluationDispositionV1;

    static NEXT: AtomicU64 = AtomicU64::new(0);

    struct TempFile(PathBuf);

    impl TempFile {
        fn new() -> Self {
            Self(std::env::temp_dir().join(format!(
                "hepta-eval-evidence-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            )))
        }

        fn create(&self) -> File {
            OpenOptions::new()
                .create_new(true)
                .read(true)
                .write(true)
                .open(&self.0)
                .unwrap_or_else(|error| panic!("create evidence sink: {error}"))
        }

        fn open(&self) -> File {
            OpenOptions::new()
                .read(true)
                .write(true)
                .open(&self.0)
                .unwrap_or_else(|error| panic!("open evidence sink: {error}"))
        }
    }

    impl Drop for TempFile {
        fn drop(&mut self) {
            let _ = fs::remove_file(&self.0);
        }
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn id(value: &str) -> StableId {
        StableId::new(value).unwrap_or_else(|error| panic!("id: {error}"))
    }

    fn decision(label: &str) -> SignedEvaluationDecisionV1 {
        SignedEvaluationDecisionV1 {
            decision: IndependentEvaluationDecisionV1 {
                evaluation_id: id("evaluation"),
                candidate_id: id("candidate"),
                baseline_id: id("baseline"),
                disposition: IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
                failed_metrics: Vec::new(),
                evidence_digest: digest(label),
                authority: AuthorityPosture::DENY_ALL,
            },
            trust_digest: digest("trust"),
            authentication_digest: digest("authentication"),
        }
    }

    #[test]
    fn evidence_sink_reconciles_ack_loss_and_conflict() {
        let temp = TempFile::new();
        let mut sink = LockedFileQualificationEvidenceSinkV1::create(
            temp.create(),
            digest("binding"),
        )
        .unwrap_or_else(|error| panic!("create: {error}"));
        sink.inject_ack_loss_once();
        let committed = sink
            .persist_once(digest("execution"), &decision("decision-a"))
            .unwrap_or_else(|error| panic!("reconcile: {error}"));
        assert!(!committed.publication_digest.is_zero());
        assert_eq!(sink.record_count(), 1);
        assert_eq!(
            sink.persist_once(digest("execution"), &decision("decision-b"))
                .err(),
            Some(ProductEvidenceSinkErrorV1::Conflict)
        );
        drop(sink);
        let mut recovered = LockedFileQualificationEvidenceSinkV1::recover(
            temp.open(),
            digest("binding"),
        )
        .unwrap_or_else(|error| panic!("recover: {error}"));
        assert_eq!(
            recovered
                .lookup(digest("execution"))
                .unwrap_or_else(|error| panic!("lookup: {error}")),
            Some(committed)
        );
    }
}
''',
)

# lib.rs module and public surface.
replace(
    "codex-rs/hepta-intelligence-eval/src/lib.rs",
    "mod ope;\nmod product_runner;\nmod self_evolution_selection;",
    "mod evaluation_attempt;\nmod ope;\nmod product_admission;\nmod product_runner;\nmod qualification_evidence_file;\nmod self_evolution_selection;",
)
replace(
    "codex-rs/hepta-intelligence-eval/src/lib.rs",
    "pub use ope::estimate_ope;\npub use product_runner::FinalHoldoutProviderV1;",
    "pub use ope::estimate_ope;\npub use evaluation_attempt::LockedFileProductEvaluationAttemptJournalV1;\npub use evaluation_attempt::ProductEvaluationAttemptErrorV1;\npub use evaluation_attempt::ProductEvaluationAttemptJournalV1;\npub use evaluation_attempt::ProductEvaluationAttemptRecordV1;\npub use evaluation_attempt::ProductEvaluationAttemptStageV1;\npub use product_admission::ProductScopedEvaluationErrorV1;\npub use product_admission::ProductScopedEvaluationReceiptV1;\npub use product_admission::admit_product_scoped_evaluation_v1;\npub use product_runner::FinalHoldoutProviderV1;",
)
replace(
    "codex-rs/hepta-intelligence-eval/src/lib.rs",
    "pub use product_runner::ProductEvaluationError;\npub use product_runner::ProductEvaluationRunnerV1;\npub use product_runner::ProductEvidenceSinkErrorV1;",
    "pub use product_runner::ProductEvaluationError;\npub use product_runner::ProductEvaluationRunnerV1;\npub use product_runner::ProductEvidenceCommitV1;\npub use product_runner::ProductEvidenceSinkErrorV1;",
)
replace(
    "codex-rs/hepta-intelligence-eval/src/lib.rs",
    "pub use product_runner::freeze_product_evaluation_plan_v1;\npub use self_evolution_selection::PreparedSelfEvolutionSelectionV1;",
    "pub use product_runner::freeze_product_evaluation_plan_v1;\npub use qualification_evidence_file::LockedFileEvidenceErrorV1;\npub use qualification_evidence_file::LockedFileQualificationEvidenceSinkV1;\npub use self_evolution_selection::PreparedSelfEvolutionSelectionV1;",
)
replace(
    "codex-rs/hepta-intelligence-eval/src/lib.rs",
    "pub use signed_evaluation::decide_with_signed_evidence_v2;",
    "pub(crate) use signed_evaluation::decide_with_signed_evidence_v2;",
)

# Product runner: idempotent sink and journal-aware production wrappers.
replace(
    "codex-rs/hepta-intelligence-eval/src/product_runner.rs",
    "use crate::EvaluationIntervalV1;\nuse crate::FencedFinalHoldoutOwnerV1;",
    "use crate::EvaluationIntervalV1;\nuse crate::FencedFinalHoldoutOwnerV1;\nuse crate::ProductEvaluationAttemptErrorV1;\nuse crate::ProductEvaluationAttemptJournalV1;\nuse crate::ProductEvaluationAttemptStageV1;",
)
old_sink = r'''#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProductEvidenceSinkErrorV1 {
    Rejected,
    Unavailable,
    Indeterminate,
}

impl fmt::Display for ProductEvidenceSinkErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for ProductEvidenceSinkErrorV1 {}

pub trait ProductQualificationEvidenceSinkV1 {
    /// Persist the terminal qualification evidence through the declared
    /// evidence owner. Return a nonzero durable publication digest only after
    /// the publication is committed.
    fn persist(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1>;
}'''
new_sink = r'''#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProductEvidenceSinkErrorV1 {
    Rejected,
    Conflict,
    Unavailable,
    Indeterminate,
}

impl fmt::Display for ProductEvidenceSinkErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for ProductEvidenceSinkErrorV1 {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ProductEvidenceCommitV1 {
    pub execution_digest: Digest32,
    pub decision_digest: Digest32,
    pub publication_digest: Digest32,
}

pub trait ProductQualificationEvidenceSinkV1 {
    /// Return the committed record for an execution identity. Production sinks
    /// override this method so an accepted-but-unacknowledged append can be
    /// reconciled. Compatibility sinks may retain the default missing result.
    fn lookup(
        &mut self,
        _execution_digest: Digest32,
    ) -> Result<Option<ProductEvidenceCommitV1>, ProductEvidenceSinkErrorV1> {
        Ok(None)
    }

    /// Persist the terminal qualification evidence through the declared
    /// evidence owner. Return a nonzero durable publication digest only after
    /// the publication is committed.
    fn persist(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1>;

    fn persist_once(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<ProductEvidenceCommitV1, ProductEvidenceSinkErrorV1> {
        let decision_digest = product_decision_digest_v1(decision);
        if execution_digest.is_zero() || decision_digest.is_zero() {
            return Err(ProductEvidenceSinkErrorV1::Rejected);
        }
        if let Some(existing) = self.lookup(execution_digest)? {
            if existing.execution_digest != execution_digest
                || existing.decision_digest != decision_digest
                || existing.publication_digest.is_zero()
            {
                return Err(ProductEvidenceSinkErrorV1::Conflict);
            }
            return Ok(existing);
        }
        match self.persist(execution_digest, decision) {
            Ok(publication_digest) if !publication_digest.is_zero() => Ok(ProductEvidenceCommitV1 {
                execution_digest,
                decision_digest,
                publication_digest,
            }),
            Ok(_) => Err(ProductEvidenceSinkErrorV1::Rejected),
            Err(ProductEvidenceSinkErrorV1::Indeterminate) => {
                match self.lookup(execution_digest)? {
                    Some(existing)
                        if existing.execution_digest == execution_digest
                            && existing.decision_digest == decision_digest
                            && !existing.publication_digest.is_zero() => Ok(existing),
                    Some(_) => Err(ProductEvidenceSinkErrorV1::Conflict),
                    None => Err(ProductEvidenceSinkErrorV1::Indeterminate),
                }
            }
            Err(error) => Err(error),
        }
    }
}

pub(crate) fn product_decision_digest_v1(decision: &SignedEvaluationDecisionV1) -> Digest32 {
    let mut bytes = b"hepta.intelligence-eval.product-decision.v1".to_vec();
    push_id(&mut bytes, &decision.decision.evaluation_id);
    push_id(&mut bytes, &decision.decision.candidate_id);
    push_id(&mut bytes, &decision.decision.baseline_id);
    for digest in [
        decision.decision.evidence_digest,
        decision.trust_digest,
        decision.authentication_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.push(u8::from(decision.decision.authority.grants_any()));
    Digest32::of_bytes(&bytes)
}'''
replace("codex-rs/hepta-intelligence-eval/src/product_runner.rs", old_sink, new_sink)
replace(
    "codex-rs/hepta-intelligence-eval/src/product_runner.rs",
    "        let publication_digest = sink.persist(temporal.execution_digest, &decision)?;\n        if publication_digest.is_zero() {\n            return Err(ProductEvaluationError::Integrity(\"publication digest\"));\n        }",
    "        let publication = sink.persist_once(temporal.execution_digest, &decision)?;\n        let publication_digest = publication.publication_digest;",
)
# Add journal-aware comparison wrapper before qualification_bundle.
replace(
    "codex-rs/hepta-intelligence-eval/src/product_runner.rs",
    "    pub fn qualification_bundle(\n",
    r'''    pub fn evaluate_temporal_comparison_with_journal<
        P: FinalHoldoutProviderV1,
        J: ProductEvaluationAttemptJournalV1 + ?Sized,
    >(
        &mut self,
        product_plan: &ProductFrozenEvaluationPlanV1,
        candidate_plan: &TemporalEvaluationPlan,
        baseline_plan: &TemporalEvaluationPlan,
        provider: &mut P,
        journal: &mut J,
    ) -> Result<ProductTemporalEvaluationReceiptV1, ProductEvaluationError> {
        let attempt_digest = comparison_attempt_digest(
            product_plan,
            candidate_plan.plan_digest,
            baseline_plan.plan_digest,
        );
        journal.append(
            attempt_digest,
            ProductEvaluationAttemptStageV1::ComparisonStarted,
            product_plan.frozen_plan.plan_digest,
        )?;
        let state_before = self.holdout_state_digest();
        let result = self.evaluate_temporal_comparison(
            product_plan,
            candidate_plan,
            baseline_plan,
            provider,
        );
        match result {
            Ok(receipt) => {
                journal.append(
                    attempt_digest,
                    ProductEvaluationAttemptStageV1::HoldoutConsumed,
                    receipt.holdout.record_digest,
                )?;
                journal.append(
                    attempt_digest,
                    ProductEvaluationAttemptStageV1::InputsReleased,
                    released_identity_digest(&receipt.snapshot_ids, &receipt.future_window_ids),
                )?;
                journal.append(
                    attempt_digest,
                    ProductEvaluationAttemptStageV1::CandidateEstimated,
                    receipt.candidate.evidence_digest,
                )?;
                journal.append(
                    attempt_digest,
                    ProductEvaluationAttemptStageV1::BaselineEstimated,
                    receipt.baseline.evidence_digest,
                )?;
                journal.append(
                    attempt_digest,
                    ProductEvaluationAttemptStageV1::ComparisonCompleted,
                    receipt.execution_digest,
                )?;
                Ok(receipt)
            }
            Err(error) => {
                let state_after = self.holdout_state_digest();
                if state_after != state_before {
                    let _ = journal.append(
                        attempt_digest,
                        ProductEvaluationAttemptStageV1::HoldoutConsumed,
                        state_after,
                    );
                }
                let _ = journal.append(
                    attempt_digest,
                    ProductEvaluationAttemptStageV1::Failed,
                    Digest32::of_bytes(format!("{error:?}").as_bytes()),
                );
                Err(error)
            }
        }
    }

    pub fn qualification_bundle(
''',
)
# Add journal-aware qualification wrapper before impl closes.
replace(
    "codex-rs/hepta-intelligence-eval/src/product_runner.rs",
    "    }\n}\n\nfn product_qualification_evidence_digest(receipt: &ProductQualificationReceiptV1) -> Digest32 {",
    r'''    }

    #[allow(clippy::too_many_arguments)]
    pub fn qualify_and_persist_with_journal<J: ProductEvaluationAttemptJournalV1 + ?Sized>(
        &self,
        temporal: &ProductTemporalEvaluationReceiptV1,
        context: &ProductQualificationContextV1,
        evidence: &SignedEvaluationEvidenceV1,
        timing: ProductTimingEvidenceV1<'_>,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
        sink: &mut dyn ProductQualificationEvidenceSinkV1,
        journal: &mut J,
    ) -> Result<ProductQualificationReceiptV1, ProductEvaluationError> {
        let attempt_digest = temporal.execution_digest;
        journal.append(
            attempt_digest,
            ProductEvaluationAttemptStageV1::QualificationStarted,
            temporal.execution_digest,
        )?;
        let result = self.qualify_and_persist(
            temporal,
            context,
            evidence,
            timing,
            verifier,
            now,
            sink,
        );
        match result {
            Ok(receipt) => {
                journal.append(
                    attempt_digest,
                    ProductEvaluationAttemptStageV1::QualificationDecided,
                    receipt.decision.decision.evidence_digest,
                )?;
                journal.append(
                    attempt_digest,
                    ProductEvaluationAttemptStageV1::EvidencePublished,
                    receipt.publication_digest,
                )?;
                Ok(receipt)
            }
            Err(error) => {
                let _ = journal.append(
                    attempt_digest,
                    ProductEvaluationAttemptStageV1::Failed,
                    Digest32::of_bytes(format!("{error:?}").as_bytes()),
                );
                Err(error)
            }
        }
    }
}

fn comparison_attempt_digest(
    plan: &ProductFrozenEvaluationPlanV1,
    candidate_plan_digest: Digest32,
    baseline_plan_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.intelligence-eval.comparison-attempt.v1".to_vec();
    for digest in [
        plan.frozen_plan.plan_digest,
        plan.frozen_plan.final_holdout_digest,
        candidate_plan_digest,
        baseline_plan_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn released_identity_digest(snapshot_ids: &[StableId], future_window_ids: &[StableId]) -> Digest32 {
    let mut bytes = b"hepta.intelligence-eval.released-identities.v1".to_vec();
    push_ids(&mut bytes, snapshot_ids);
    push_ids(&mut bytes, future_window_ids);
    Digest32::of_bytes(&bytes)
}

fn product_qualification_evidence_digest(receipt: &ProductQualificationReceiptV1) -> Digest32 {''',
)
replace(
    "codex-rs/hepta-intelligence-eval/src/product_runner.rs",
    "    Sink(ProductEvidenceSinkErrorV1),\n}",
    "    Sink(ProductEvidenceSinkErrorV1),\n    Attempt(ProductEvaluationAttemptErrorV1),\n}",
)
replace(
    "codex-rs/hepta-intelligence-eval/src/product_runner.rs",
    "impl From<ProductEvidenceSinkErrorV1> for ProductEvaluationError {",
    "impl From<ProductEvaluationAttemptErrorV1> for ProductEvaluationError {\n    fn from(value: ProductEvaluationAttemptErrorV1) -> Self {\n        Self::Attempt(value)\n    }\n}\n\nimpl From<ProductEvidenceSinkErrorV1> for ProductEvaluationError {",
)

# Agentd consumes the sealed product-scoped facade, never the raw V2 primitive.
replace(
    "codex-rs/hepta-agentd/src/intelligence_evaluation.rs",
    "use codex_hepta_intelligence_eval::SignedEvaluationError;\nuse codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1;\nuse codex_hepta_intelligence_eval::decide_with_signed_evidence_v2;",
    "use codex_hepta_intelligence_eval::ProductScopedEvaluationErrorV1;\nuse codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1;\nuse codex_hepta_intelligence_eval::admit_product_scoped_evaluation_v1;",
)
replace(
    "codex-rs/hepta-agentd/src/intelligence_evaluation.rs",
    r'''        let result = decide_with_signed_evidence_v2(
            self.signed.bundle,
            self.signed.roles,
            &self.signed.evidence,
            self.trust.verifier(),
            now,
        )
        .map_err(AgentdIntelligenceEvaluationError::Evaluation)?;
        if result.decision.authority.grants_any()
            || result.decision.disposition
                != IndependentEvaluationDispositionV1::EligibleForIndependentSelection
        {
            return Err(AgentdIntelligenceEvaluationError::Ineligible);
        }
        let mut receipt = b"hepta.agentd.evaluation-consumption.v1\0".to_vec();
        receipt.extend_from_slice(Digest32::of_bytes(&payload).as_array());
        receipt.extend_from_slice(result.authentication_digest.as_array());
        receipt.extend_from_slice(self.trust.distribution_digest().as_array());''',
    r'''        let admission = admit_product_scoped_evaluation_v1(
            self.signed.bundle,
            self.signed.roles,
            &self.signed.evidence,
            self.trust.verifier(),
            Digest32::of_bytes(&payload),
            now,
        )
        .map_err(AgentdIntelligenceEvaluationError::Evaluation)?;
        if admission.decision.decision.authority.grants_any()
            || admission.decision.decision.disposition
                != IndependentEvaluationDispositionV1::EligibleForIndependentSelection
        {
            return Err(AgentdIntelligenceEvaluationError::Ineligible);
        }
        let mut receipt = b"hepta.agentd.evaluation-consumption.v2\0".to_vec();
        receipt.extend_from_slice(Digest32::of_bytes(&payload).as_array());
        receipt.extend_from_slice(admission.evidence_digest.as_array());
        receipt.extend_from_slice(admission.decision.authentication_digest.as_array());
        receipt.extend_from_slice(self.trust.distribution_digest().as_array());''',
)
replace(
    "codex-rs/hepta-agentd/src/intelligence_evaluation.rs",
    "    Evaluation(SignedEvaluationError),",
    "    Evaluation(ProductScopedEvaluationErrorV1),",
)

# Plasticity consumes the same sealed facade and binds it to the proposal use.
replace(
    "codex-rs/hepta-intelligence/src/plasticity_product.rs",
    "use codex_hepta_intelligence_eval::MetricRoleContractV2;\nuse codex_hepta_intelligence_eval::SignedEvaluationError;",
    "use codex_hepta_intelligence_eval::MetricRoleContractV2;\nuse codex_hepta_intelligence_eval::ProductScopedEvaluationErrorV1;\nuse codex_hepta_intelligence_eval::SignedEvaluationError;",
)
replace(
    "codex-rs/hepta-intelligence/src/plasticity_product.rs",
    "use codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1;\nuse codex_hepta_intelligence_eval::decide_with_signed_evidence_v2;",
    "use codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1;\nuse codex_hepta_intelligence_eval::admit_product_scoped_evaluation_v1;",
)
replace(
    "codex-rs/hepta-intelligence/src/plasticity_product.rs",
    "    Evaluation(SignedEvaluationError),\n    Ineligible(IndependentEvaluationDispositionV1),",
    "    Evaluation(SignedEvaluationError),\n    ProductEvaluation(ProductScopedEvaluationErrorV1),\n    Ineligible(IndependentEvaluationDispositionV1),",
)
replace(
    "codex-rs/hepta-intelligence/src/plasticity_product.rs",
    r'''        let decision =
            decide_with_signed_evidence_v2(bundle, metric_roles, &evidence, verifier, now)
                .map_err(E::Evaluation)?;
        if decision.decision.disposition
            != IndependentEvaluationDispositionV1::EligibleForIndependentSelection
        {
            return Err(E::Ineligible(decision.decision.disposition));
        }
        push_id(&mut evaluation_binding, &candidate_id);
        evaluation_binding.extend_from_slice(decision.decision.evidence_digest.as_array());
        evaluation_binding.extend_from_slice(decision.authentication_digest.as_array());
        evaluation_binding.extend_from_slice(decision.trust_digest.as_array());''',
    r'''        let mut use_binding = b"hepta.intelligence.plasticity-evaluation-use.v1\0".to_vec();
        push_id(&mut use_binding, &request.proposal_id);
        push_id(&mut use_binding, &candidate_id);
        for digest in [
            request.admission.owner_evidence_set_digest,
            request.admission.selected_artifact_digest,
            request.admission.qualification_evidence_head_digest,
            Digest32::of_bytes(&evaluator_payload),
        ] {
            use_binding.extend_from_slice(digest.as_array());
        }
        let admission = admit_product_scoped_evaluation_v1(
            bundle,
            metric_roles,
            &evidence,
            verifier,
            Digest32::of_bytes(&use_binding),
            now,
        )
        .map_err(E::ProductEvaluation)?;
        if admission.decision.decision.disposition
            != IndependentEvaluationDispositionV1::EligibleForIndependentSelection
        {
            return Err(E::Ineligible(admission.decision.decision.disposition));
        }
        push_id(&mut evaluation_binding, &candidate_id);
        evaluation_binding.extend_from_slice(admission.evidence_digest.as_array());
        evaluation_binding.extend_from_slice(
            admission.decision.decision.evidence_digest.as_array(),
        );
        evaluation_binding.extend_from_slice(
            admission.decision.authentication_digest.as_array(),
        );
        evaluation_binding.extend_from_slice(admission.decision.trust_digest.as_array());''',
)

# Crash-safe checkpoint candidate for append-only holdout storage.
replace(
    "codex-rs/hepta-intelligence-eval/src/fenced_holdout_file.rs",
    r'''    #[must_use]
    pub fn anchor(&self) -> Option<FinalHoldoutCasAnchorV1> {
        self.state.as_ref().map(record_anchor)
    }
}''',
    r'''    #[must_use]
    pub fn anchor(&self) -> Option<FinalHoldoutCasAnchorV1> {
        self.state.as_ref().map(record_anchor)
    }

    #[must_use]
    pub const fn storage_bytes(&self) -> u64 {
        self.length
    }

    /// Write a compact checkpoint candidate into a brand-new empty file.
    ///
    /// The source remains authoritative. The host must retain the returned
    /// anchor independently, fsync the containing directory and atomically
    /// install the candidate before deleting old generations.
    pub fn write_checkpoint_candidate(
        &self,
        mut target: File,
    ) -> Result<Option<FinalHoldoutCasAnchorV1>, LockedFileCasErrorV1> {
        if self.poisoned {
            return Err(LockedFileCasErrorV1::Indeterminate);
        }
        acquire(&target, self.binding)?;
        if target.metadata().map_err(io_error)?.len() != 0 {
            return Err(LockedFileCasErrorV1::AlreadyInitialized);
        }
        let mut header = MAGIC.to_vec();
        header.extend_from_slice(self.binding.as_array());
        header.extend_from_slice(Digest32::of_bytes(&header).as_array());
        target.seek(SeekFrom::Start(0)).map_err(io_error)?;
        target.write_all(&header).map_err(io_error)?;
        let mut length = HEADER as u64;
        if let Some(state) = &self.state {
            append_checkpoint_frame(&mut target, &encode_fence(&state.fence)?, &mut length)?;
            for record in &state.journal.records {
                let encoded = encode_holdout_plan(&record.plan)
                    .map_err(|_| LockedFileCasErrorV1::Corrupt)?;
                let mut payload = vec![EVENT_PLAN];
                payload.extend_from_slice(&encoded);
                append_checkpoint_frame(&mut target, &payload, &mut length)?;
            }
        }
        target
            .sync_all()
            .map_err(|_| LockedFileCasErrorV1::Indeterminate)?;
        Ok(self.state.as_ref().map(record_anchor))
    }
}''',
)
replace(
    "codex-rs/hepta-intelligence-eval/src/fenced_holdout_file.rs",
    "fn transition_payload(\n",
    r'''fn append_checkpoint_frame(
    file: &mut File,
    payload: &[u8],
    length: &mut u64,
) -> Result<(), LockedFileCasErrorV1> {
    if payload.is_empty() || payload.len() > MAX_FRAME {
        return Err(LockedFileCasErrorV1::Capacity);
    }
    let next = length
        .checked_add(4)
        .and_then(|value| value.checked_add(payload.len() as u64))
        .and_then(|value| value.checked_add(32))
        .filter(|value| *value <= MAX_BYTES)
        .ok_or(LockedFileCasErrorV1::Capacity)?;
    file.write_all(&(payload.len() as u32).to_be_bytes())
        .and_then(|_| file.write_all(payload))
        .and_then(|_| file.write_all(Digest32::of_bytes(payload).as_array()))
        .map_err(io_error)?;
    *length = next;
    Ok(())
}

fn transition_payload(
''',
)
append_once(
    "codex-rs/hepta-intelligence-eval/src/fenced_holdout_file_tests.rs",
    "fn checkpoint_compacts_and_recovers_exact_anchor()",
    r'''
#[test]
fn checkpoint_compacts_and_recovers_exact_anchor() {
    let source = TempFile::new();
    let checkpoint = TempFile::new();
    let store = LockedFileFinalHoldoutCasStoreV1::create(source.create(), digest("binding"))
        .unwrap_or_else(|error| panic!("create source: {error}"));
    let mut writer = owner(store, None);
    writer
        .consume(&plan("checkpoint-plan-a"))
        .unwrap_or_else(|error| panic!("consume a: {error}"));
    writer
        .consume(&plan("checkpoint-plan-b"))
        .unwrap_or_else(|error| panic!("consume b: {error}"));
    let expected = writer.anchor();
    let store = writer.into_store();
    let source_bytes = store.storage_bytes();
    let written = store
        .write_checkpoint_candidate(checkpoint.create())
        .unwrap_or_else(|error| panic!("write checkpoint: {error}"));
    assert_eq!(written, Some(expected));
    drop(store);
    let recovered = LockedFileFinalHoldoutCasStoreV1::recover(
        checkpoint.open(),
        digest("binding"),
        Some(expected),
    )
    .unwrap_or_else(|error| panic!("recover checkpoint: {error}"));
    assert_eq!(recovered.anchor(), Some(expected));
    assert!(recovered.storage_bytes() <= source_bytes);
}

#[test]
#[ignore = "capacity benchmark; executed by the Lane E qualification workflow"]
fn checkpoint_recovery_capacity_benchmark() {
    use std::time::Instant;

    let requested = std::env::var("HEPTA_EVAL_BENCH_RECORDS")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(512);
    let source = TempFile::new();
    let checkpoint = TempFile::new();
    let store = LockedFileFinalHoldoutCasStoreV1::create(source.create(), digest("binding"))
        .unwrap_or_else(|error| panic!("create source: {error}"));
    let mut writer = owner(store, None);
    let mut committed = 0usize;
    for index in 0..requested {
        match writer.consume(&plan(&format!("benchmark-{index}"))) {
            Ok(_) => committed += 1,
            Err(crate::FencedHoldoutError::Store(FinalHoldoutCasStoreError::Rejected)) => break,
            Err(error) => panic!("benchmark consume: {error}"),
        }
    }
    let expected = writer.anchor();
    let store = writer.into_store();
    let source_bytes = store.storage_bytes();
    store
        .write_checkpoint_candidate(checkpoint.create())
        .unwrap_or_else(|error| panic!("write checkpoint: {error}"));
    drop(store);
    let started = Instant::now();
    let recovered = LockedFileFinalHoldoutCasStoreV1::recover(
        checkpoint.open(),
        digest("binding"),
        Some(expected),
    )
    .unwrap_or_else(|error| panic!("recover checkpoint: {error}"));
    let recovery_micros = started.elapsed().as_micros();
    println!(
        "{{\"schema\":\"hepta.learning-eval.checkpoint-benchmark.v1\",\"records\":{committed},\"sourceBytes\":{source_bytes},\"checkpointBytes\":{},\"recoveryMicros\":{recovery_micros}}}",
        recovered.storage_bytes()
    );
}
''',
)

# Source-level API inventory and generated truth status.
write(
    "scripts/hepta-learning-eval-api-surface.py",
    r'''
#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "target" / "learning-eval-api-surface"


def run(source: str) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="hepta-eval-api-") as directory:
        root = Path(directory)
        (root / "src").mkdir()
        (root / "Cargo.toml").write_text(
            "[package]\nname='hepta-eval-api-fixture'\nversion='0.0.0'\nedition='2024'\n"
            "[workspace]\n"
            f"[dependencies]\ncodex-hepta-intelligence-eval={{path={str(ROOT / 'codex-rs/hepta-intelligence-eval')!r}}}\n",
            encoding="utf-8",
        )
        (root / "src/main.rs").write_text(source, encoding="utf-8")
        env = os.environ.copy()
        env["CARGO_TARGET_DIR"] = str(TARGET)
        return subprocess.run(
            ["cargo", "check", "--quiet", "--manifest-path", str(root / "Cargo.toml")],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )


def main() -> int:
    positive = run(
        "use codex_hepta_intelligence_eval::admit_product_scoped_evaluation_v1;\n"
        "fn main(){ let _ = admit_product_scoped_evaluation_v1; }\n"
    )
    if positive.returncode != 0:
        print(positive.stdout)
        return 1
    negative = run(
        "use codex_hepta_intelligence_eval::decide_with_signed_evidence_v2;\n"
        "fn main(){ let _ = decide_with_signed_evidence_v2; }\n"
    )
    if negative.returncode == 0:
        print("low-level V2 verifier remains externally importable")
        return 1
    if "private" not in negative.stdout and "no `decide_with_signed_evidence_v2`" not in negative.stdout:
        print(negative.stdout)
        return 1
    print("learning.eval API surface: facade public, low-level V2 private")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
)

write(
    "scripts/hepta-learning-eval-status.py",
    r'''
#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "docs/modules/learning.eval/CURRENT_STATUS.json"
MD_PATH = ROOT / "docs/modules/learning.eval/CURRENT_STATUS.md"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict:
    lib = (ROOT / "codex-rs/hepta-intelligence-eval/src/lib.rs").read_text(encoding="utf-8")
    external = []
    token = "decide_with_signed_evidence_v2"
    for path in (ROOT / "codex-rs").rglob("*.rs"):
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith("codex-rs/hepta-intelligence-eval/"):
            continue
        if token in path.read_text(encoding="utf-8"):
            external.append(relative)
    sources = [
        "codex-rs/hepta-intelligence-eval/src/lib.rs",
        "codex-rs/hepta-intelligence-eval/src/product_admission.rs",
        "codex-rs/hepta-intelligence-eval/src/product_runner.rs",
        "codex-rs/hepta-intelligence-eval/src/qualification_evidence_file.rs",
        "codex-rs/hepta-intelligence-eval/src/evaluation_attempt.rs",
        "codex-rs/hepta-intelligence-eval/src/fenced_holdout_file.rs",
        "codex-rs/hepta-agentd/src/intelligence_evaluation.rs",
        "codex-rs/hepta-intelligence/src/plasticity_product.rs",
    ]
    return {
        "schema": "hepta.learning-eval.current-status.v1",
        "module": "learning.eval",
        "candidateIdentity": "workflow-attested-exact-head-and-ordered-parent-merge",
        "sourcePresent": True,
        "lowLevelV2CratePrivate": "pub(crate) use signed_evaluation::decide_with_signed_evidence_v2;" in lib,
        "externalLowLevelV2Consumers": sorted(external),
        "productScopedFacadeImplemented": (ROOT / sources[1]).is_file(),
        "durableEvidenceReconciliationImplemented": (ROOT / sources[3]).is_file(),
        "durableAttemptJournalImplemented": (ROOT / sources[4]).is_file(),
        "checkpointCandidateImplemented": "write_checkpoint_candidate" in (ROOT / sources[5]).read_text(encoding="utf-8"),
        "productConsumers": [
            {
                "path": "codex-rs/hepta-agentd/src/intelligence_evaluation.rs",
                "surface": "admit_product_scoped_evaluation_v1",
            },
            {
                "path": "codex-rs/hepta-intelligence/src/plasticity_product.rs",
                "surface": "admit_product_scoped_evaluation_v1",
            },
            {
                "path": "codex-rs/hepta-intelligence/src/evaluated_shadow.rs",
                "surface": "ProductQualificationReceiptV1",
            },
        ],
        "qualification": {
            "exactHead": "required_per_candidate",
            "orderedParentSyntheticMerge": "required_per_candidate",
            "lineCoverageThresholdPct": 85,
            "provenanceAttestation": "required_per_candidate",
        },
        "externalGates": {
            "targetHostQualified": False,
            "realFutureCalendarEvidence": False,
            "privacyRetentionUnlearningAccepted": False,
            "independentOperatorAcceptance": False,
            "selectionCanaryPromotionRelease": False,
        },
        "sourceDigests": {path: digest(ROOT / path) for path in sources},
    }


def render_md(status: dict) -> str:
    yes = lambda value: "yes" if value else "no"
    external = status["externalGates"]
    return "\n".join(
        [
            "# learning.eval current status",
            "",
            "This file is generated by `scripts/hepta-learning-eval-status.py`.",
            "",
            f"- low-level V2 crate-private: **{yes(status['lowLevelV2CratePrivate'])}**",
            f"- external low-level V2 consumers: **{len(status['externalLowLevelV2Consumers'])}**",
            f"- product-scoped facade: **{yes(status['productScopedFacadeImplemented'])}**",
            f"- durable evidence reconciliation: **{yes(status['durableEvidenceReconciliationImplemented'])}**",
            f"- durable attempt journal: **{yes(status['durableAttemptJournalImplemented'])}**",
            f"- checkpoint candidate: **{yes(status['checkpointCandidateImplemented'])}**",
            "- exact-head and ordered-parent qualification: **candidate-specific CI evidence required**",
            f"- target host qualified: **{yes(external['targetHostQualified'])}**",
            f"- independent release authority: **{yes(external['selectionCanaryPromotionRelease'])}**",
            "",
        ]
    )


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "verify"
    status = build()
    encoded = json.dumps(status, indent=2, sort_keys=True) + "\n"
    markdown = render_md(status)
    if mode == "generate":
        JSON_PATH.write_text(encoded, encoding="utf-8")
        MD_PATH.write_text(markdown, encoding="utf-8")
        return 0
    if mode != "verify":
        raise SystemExit("usage: hepta-learning-eval-status.py [generate|verify]")
    if not JSON_PATH.is_file() or JSON_PATH.read_text(encoding="utf-8") != encoded:
        print("learning.eval CURRENT_STATUS.json is stale")
        return 1
    if not MD_PATH.is_file() or MD_PATH.read_text(encoding="utf-8") != markdown:
        print("learning.eval CURRENT_STATUS.md is stale")
        return 1
    if status["externalLowLevelV2Consumers"]:
        print("external low-level V2 consumers remain:", status["externalLowLevelV2Consumers"])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
)

write(
    "scripts/hepta-learning-eval-target-host.py",
    r'''
#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "qualification/learning-eval/TARGET_HOST_EVIDENCE.template.json"
HEX32 = re.compile(r"^[0-9a-f]{64}$")
SHA = re.compile(r"^[0-9a-f]{40}$")


def validate(data: dict, *, allow_template: bool) -> list[str]:
    errors: list[str] = []
    if data.get("schema") != "hepta.learning-eval.target-host-evidence.v1":
        errors.append("schema")
    if not allow_template and not SHA.fullmatch(str(data.get("candidateSha", ""))):
        errors.append("candidateSha")
    required_digests = [
        "hostProfileDigest",
        "trustRootDigest",
        "holdoutNamespaceDigest",
        "evidenceStoreDigest",
        "futureWindowEvidenceDigest",
        "privacyReviewDigest",
        "retentionEvidenceDigest",
        "unlearningEvidenceDigest",
        "operatorAcceptanceDigest",
        "releaseDecisionDigest",
    ]
    for name in required_digests:
        value = str(data.get(name, ""))
        if allow_template and value == "EXTERNAL_EVIDENCE_REQUIRED":
            continue
        if not HEX32.fullmatch(value) or value == "0" * 64:
            errors.append(name)
    gates = data.get("gates")
    if not isinstance(gates, dict):
        errors.append("gates")
    else:
        for name in [
            "hostStorageQualified",
            "realFutureCalendarObserved",
            "privacyRetentionUnlearningAccepted",
            "independentOperatorAccepted",
            "selectionCanaryPromotionReleaseAuthorized",
        ]:
            expected = False if allow_template else True
            if gates.get(name) is not expected:
                errors.append(f"gates.{name}")
    return errors


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "lint-template":
        errors = validate(json.loads(TEMPLATE.read_text(encoding="utf-8")), allow_template=True)
    elif len(sys.argv) == 3 and sys.argv[1] == "verify":
        errors = validate(json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")), allow_template=False)
    else:
        raise SystemExit("usage: hepta-learning-eval-target-host.py lint-template | verify FILE")
    if errors:
        print("invalid target-host evidence:", ", ".join(errors))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
)

write(
    "qualification/learning-eval/TARGET_HOST_EVIDENCE.template.json",
    json.dumps(
        {
            "schema": "hepta.learning-eval.target-host-evidence.v1",
            "candidateSha": "EXTERNAL_EVIDENCE_REQUIRED",
            "hostId": "EXTERNAL_EVIDENCE_REQUIRED",
            "hostProfileDigest": "EXTERNAL_EVIDENCE_REQUIRED",
            "trustRootDigest": "EXTERNAL_EVIDENCE_REQUIRED",
            "holdoutNamespaceDigest": "EXTERNAL_EVIDENCE_REQUIRED",
            "evidenceStoreDigest": "EXTERNAL_EVIDENCE_REQUIRED",
            "futureWindowEvidenceDigest": "EXTERNAL_EVIDENCE_REQUIRED",
            "privacyReviewDigest": "EXTERNAL_EVIDENCE_REQUIRED",
            "retentionEvidenceDigest": "EXTERNAL_EVIDENCE_REQUIRED",
            "unlearningEvidenceDigest": "EXTERNAL_EVIDENCE_REQUIRED",
            "operatorAcceptanceDigest": "EXTERNAL_EVIDENCE_REQUIRED",
            "releaseDecisionDigest": "EXTERNAL_EVIDENCE_REQUIRED",
            "gates": {
                "hostStorageQualified": False,
                "realFutureCalendarObserved": False,
                "privacyRetentionUnlearningAccepted": False,
                "independentOperatorAccepted": False,
                "selectionCanaryPromotionReleaseAuthorized": False,
            },
        },
        indent=2,
        sort_keys=True,
    ),
)

write(
    "docs/modules/learning.eval/TARGET_HOST_QUALIFICATION.md",
    r'''
# learning.eval target-host qualification

Repository source qualification and target-host acceptance are separate gates.
A target host is accepted only when an independent evidence package passes
`scripts/hepta-learning-eval-target-host.py verify FILE` and binds the exact
candidate SHA, host trust root, final-holdout namespace, idempotent qualification
evidence store, real future-calendar observations, privacy/retention/unlearning
review, independent operator acceptance and release decision.

The template at `qualification/learning-eval/TARGET_HOST_EVIDENCE.template.json`
is intentionally non-qualifying. Repository automation must never replace its
external-evidence markers with synthetic or self-issued values.
''',
)

# Closure verifier: enforce source boundary and generated status.
replace(
    "scripts/hepta-lane-e-closure.py",
    "\n\ndef verify_product_writer_exclusivity(findings: Findings) -> None:",
    r'''

    admission_path = ROOT / "codex-rs/hepta-intelligence-eval/src/product_admission.rs"
    attempt_path = ROOT / "codex-rs/hepta-intelligence-eval/src/evaluation_attempt.rs"
    evidence_path = ROOT / "codex-rs/hepta-intelligence-eval/src/qualification_evidence_file.rs"
    status_path = ROOT / "docs/modules/learning.eval/CURRENT_STATUS.json"
    for path in (admission_path, attempt_path, evidence_path, status_path):
        findings.require(
            path.is_file(),
            "learning_eval_boundary_file_missing",
            f"missing learning.eval closure file: {path.relative_to(ROOT)}",
        )
    if admission_path.is_file():
        text = admission_path.read_text(encoding="utf-8")
        for token in (
            "pub fn admit_product_scoped_evaluation_v1(",
            "pub struct ProductScopedEvaluationReceiptV1",
            "AuthorityPosture::DENY_ALL",
        ):
            findings.require(
                token in text,
                "learning_eval_product_facade",
                f"product-scoped facade is missing {token}",
            )
    if attempt_path.is_file():
        text = attempt_path.read_text(encoding="utf-8")
        for token in (
            "pub trait ProductEvaluationAttemptJournalV1",
            "LockedFileProductEvaluationAttemptJournalV1",
            "ProductEvaluationAttemptStageV1::Failed",
        ):
            findings.require(
                token in text,
                "learning_eval_attempt_journal",
                f"attempt journal is missing {token}",
            )
    if evidence_path.is_file():
        text = evidence_path.read_text(encoding="utf-8")
        for token in (
            "LockedFileQualificationEvidenceSinkV1",
            "fn lookup(",
            "lose_ack_once",
        ):
            findings.require(
                token in text,
                "learning_eval_evidence_reconciliation",
                f"evidence reconciliation is missing {token}",
            )
    forbidden = "decide_with_signed_evidence_v2"
    eval_root = ROOT / "codex-rs/hepta-intelligence-eval"
    for path in (ROOT / "codex-rs").rglob("*.rs"):
        if path.is_relative_to(eval_root):
            continue
        findings.require(
            forbidden not in path.read_text(encoding="utf-8"),
            "learning_eval_low_level_external_consumer",
            f"external crate directly references crate-private {forbidden}: {path.relative_to(ROOT)}",
        )
    if status_path.is_file():
        status = json.loads(status_path.read_text(encoding="utf-8"))
        findings.require(
            status.get("externalLowLevelV2Consumers") == [],
            "learning_eval_status_external_consumer",
            "generated status reports external low-level V2 consumers",
        )
        findings.require(
            status.get("lowLevelV2CratePrivate") is True,
            "learning_eval_status_private_api",
            "generated status does not report crate-private V2",
        )


def verify_product_writer_exclusivity(findings: Findings) -> None:''',
)

# Workflow verifies generated truth, compile-fail API fixture, faults and benchmark.
workflow_path = ".github/workflows/hepta-lane-e-gap-closure.yml"
workflow = read(workflow_path)
workflow = workflow.replace(
    "python3 scripts/hepta-lane-e-closure.py verify",
    "python3 scripts/hepta-learning-eval-status.py verify\n          python3 scripts/hepta-learning-eval-target-host.py lint-template\n          python3 scripts/hepta-lane-e-closure.py verify",
)
marker = "      - name: Evaluator line coverage threshold\n"
if marker not in workflow:
    raise SystemExit("Lane E workflow coverage marker missing")
fault_step = r'''      - name: Durable evaluation fault matrix and checkpoint benchmark
        shell: bash
        run: |
          set -euo pipefail
          mkdir -p .hepta-evidence/learning-eval
          (
            cd codex-rs
            just test --locked -p codex-hepta-intelligence-eval evidence_sink_reconciles_ack_loss_and_conflict --test-threads=1
            just test --locked -p codex-hepta-intelligence-eval attempt_journal_replays_and_rejects_regression --test-threads=1
            just test --locked -p codex-hepta-intelligence-eval checkpoint_compacts_and_recovers_exact_anchor --test-threads=1
            HEPTA_EVAL_BENCH_RECORDS=512 cargo test --locked -p codex-hepta-intelligence-eval checkpoint_recovery_capacity_benchmark -- --ignored --exact --nocapture
          ) 2>&1 | tee .hepta-evidence/learning-eval/checkpoint-benchmark.log
          cat .hepta-evidence/learning-eval/checkpoint-benchmark.log >> .hepta-evidence/learning-eval/stress.log

      - name: Enforce learning.eval public API surface
        shell: bash
        run: python3 scripts/hepta-learning-eval-api-surface.py

'''
workflow = workflow.replace(marker, fault_step + marker, 1)
write(workflow_path, workflow)

# Documentation truth is additive and explicit about remaining external gates.
append_once(
    "codex-rs/hepta-intelligence-eval/PRODUCTION_CONTRACT.md",
    "## Product-scoped admission and recoverable publication",
    r'''
## Product-scoped admission and recoverable publication

Repository consumers that already own a separately durable product transaction
must use `admit_product_scoped_evaluation_v1`. It invokes the crate-private V2
verifier, binds the result to a nonzero product-use digest and returns a sealed
`ProductScopedEvaluationReceiptV1` with `DENY_ALL` authority. Agentd and governed
plasticity use this facade; no external crate may import the low-level verifier.

The canonical temporal runner uses `persist_once`. Production evidence sinks must
support lookup by execution identity so a commit followed by acknowledgement loss
is reconciled as the same publication rather than duplicated. The repository
provides `LockedFileQualificationEvidenceSinkV1` as a checksummed, fsynced,
replayable implementation.

Production temporal composition uses the journal-aware runner methods with
`LockedFileProductEvaluationAttemptJournalV1`. The journal records comparison,
holdout-consumption, estimation, qualification, publication and terminal failure
stages. A missing terminal stage after a committed holdout is therefore an
explicit recoverable incident, not permission to reuse the holdout.

`LockedFileFinalHoldoutCasStoreV1::write_checkpoint_candidate` writes a compact
new generation without modifying the authoritative source. Installation remains
a host transaction: retain the returned anchor independently, fsync the target
and directory, atomically rename, reopen against the anchor, then retire the old
generation.
''',
)
append_once(
    "codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md",
    "## Production-boundary convergence",
    r'''
## Production-boundary convergence

| Boundary | Native symbol | Status |
|---|---|---|
| product-scoped signed admission | `admit_product_scoped_evaluation_v1` | implemented sealed facade; raw V2 crate-private |
| idempotent durable publication | `LockedFileQualificationEvidenceSinkV1` | implemented replay and acknowledgement-loss reconciliation |
| evaluation attempt audit | `LockedFileProductEvaluationAttemptJournalV1` | implemented append-only stage journal |
| holdout checkpoint candidate | `LockedFileFinalHoldoutCasStoreV1::write_checkpoint_candidate` | implemented; host atomic installation required |

The machine-generated current state is `docs/modules/learning.eval/CURRENT_STATUS.json`.
''',
)
append_once(
    "codex-rs/hepta-intelligence-eval/EVIDENCE_ADMISSION.md",
    "## Product-use binding and publication reconciliation",
    r'''
## Product-use binding and publication reconciliation

Raw signed V2 admission is crate-private. Product consumers bind an admitted
decision to their exact run/proposal context through
`admit_product_scoped_evaluation_v1`; the sealed receipt remains authority-free.
Temporal qualification additionally uses an idempotent evidence sink. An
`Indeterminate` acknowledgement is resolved by reading the execution identity;
a conflicting decision under the same execution identity is terminal.

The attempt journal and final-holdout journal are separate facts. The former
explains where an evaluation stopped; the latter remains the authority that a
final holdout was consumed. Failure after consumption never authorizes reuse.
''',
)
append_once(
    "docs/modules/learning.eval/TECHNICAL.md",
    "## 15. Machine-generated current state",
    r'''
## 15. Machine-generated current state

`CURRENT_STATUS.json` and `CURRENT_STATUS.md` are generated by
`scripts/hepta-learning-eval-status.py`. CI rejects drift, any external direct
reference to the crate-private V2 verifier, or a false target-host/release claim.
Target-host evidence is governed by `TARGET_HOST_QUALIFICATION.md` and remains an
independent gate.
''',
)
append_once(
    "qualification/module-execution-dossiers/detail/learning.eval.md",
    "- EVAL-08:",
    r'''
- EVAL-08: Agentd and plasticity consume sealed product-scoped admission receipts; no external crate imports the low-level V2 verifier.
- EVAL-09: A durable evidence commit followed by acknowledgement loss reconciles to one publication; a changed decision under the same execution identity conflicts.
- EVAL-10: Attempt replay exposes post-holdout failures, and checkpoint recovery reproduces the exact retained anchor before old-generation retirement.
''',
)

# Machine-readable implementation/caller inventory.
map_path = ROOT / "docs/modules/learning.eval/IMPLEMENTATION_MAP.json"
implementation = json.loads(map_path.read_text(encoding="utf-8"))
new_operations = {
    "admit_product_scoped_evaluation_v1": {
        "operation": "admit_product_scoped_evaluation_v1",
        "nativeSymbol": "admit_product_scoped_evaluation_v1",
        "sourcePath": "codex-rs/hepta-intelligence-eval/src/product_admission.rs",
        "state": "source_product_scoped_facade_implemented",
        "authority": "deny_all",
        "tests": [
            "codex-rs/hepta-agentd/src/intelligence_evaluation_tests.rs",
            "codex-rs/hepta-intelligence/src/plasticity_product_tests.rs",
        ],
        "sourcePathExists": True,
        "designOperation": "product_scoped_signed_admission",
        "mappingClass": "owner_native",
        "delegatedCallees": [
            {
                "path": "codex-rs/hepta-intelligence-eval/src/signed_evaluation.rs",
                "symbol": "decide_with_signed_evidence_v2",
            }
        ],
    },
    "LockedFileQualificationEvidenceSinkV1": {
        "operation": "LockedFileQualificationEvidenceSinkV1",
        "nativeSymbol": "LockedFileQualificationEvidenceSinkV1",
        "sourcePath": "codex-rs/hepta-intelligence-eval/src/qualification_evidence_file.rs",
        "state": "source_durable_idempotent_reconciliation_implemented",
        "authority": "deny_all",
        "tests": [
            "codex-rs/hepta-intelligence-eval/src/qualification_evidence_file.rs"
        ],
        "sourcePathExists": True,
        "designOperation": "qualification_evidence_persist_once",
        "mappingClass": "owner_native",
        "delegatedCallees": [],
    },
    "LockedFileProductEvaluationAttemptJournalV1": {
        "operation": "LockedFileProductEvaluationAttemptJournalV1",
        "nativeSymbol": "LockedFileProductEvaluationAttemptJournalV1",
        "sourcePath": "codex-rs/hepta-intelligence-eval/src/evaluation_attempt.rs",
        "state": "source_durable_attempt_journal_implemented",
        "authority": "deny_all",
        "tests": ["codex-rs/hepta-intelligence-eval/src/evaluation_attempt.rs"],
        "sourcePathExists": True,
        "designOperation": "evaluation_attempt_audit",
        "mappingClass": "owner_native",
        "delegatedCallees": [],
    },
    "write_checkpoint_candidate": {
        "operation": "LockedFileFinalHoldoutCasStoreV1::write_checkpoint_candidate",
        "nativeSymbol": "LockedFileFinalHoldoutCasStoreV1::write_checkpoint_candidate",
        "sourcePath": "codex-rs/hepta-intelligence-eval/src/fenced_holdout_file.rs",
        "state": "source_checkpoint_candidate_implemented_host_install_external",
        "authority": "deny_all",
        "tests": [
            "codex-rs/hepta-intelligence-eval/src/fenced_holdout_file_tests.rs"
        ],
        "sourcePathExists": True,
        "designOperation": "holdout_checkpoint_compaction",
        "mappingClass": "owner_native",
        "delegatedCallees": [],
    },
}
existing = {item.get("operation") for item in implementation.get("operations", [])}
for name, value in new_operations.items():
    if name not in existing and value["operation"] not in existing:
        implementation.setdefault("operations", []).append(value)
implementation["productCallerState"] = "sealed_product_scoped_facades_and_product_qualification_receipt_consumers"
implementation["productionWriterState"] = "concrete_idempotent_locked_file_sink_implemented_target_host_binding_unproved"
implementation["productCallers"] = [
    {
        "sourcePath": "codex-rs/hepta-agentd/src/intelligence_evaluation.rs",
        "nativeSymbol": "AgentdEvaluationSessionV1::evaluate",
        "surface": "admit_product_scoped_evaluation_v1",
        "state": "product_scoped_sealed_admission_consumer",
    },
    {
        "sourcePath": "codex-rs/hepta-intelligence/src/plasticity_product.rs",
        "nativeSymbol": "propose_authenticated_parameter_plasticity_v1",
        "surface": "admit_product_scoped_evaluation_v1",
        "state": "product_scoped_sealed_admission_then_durable_proposal_append",
    },
    {
        "sourcePath": "codex-rs/hepta-intelligence/src/evaluated_shadow.rs",
        "nativeSymbol": "run_evaluated_shadow_v1",
        "surface": "ProductQualificationReceiptV1",
        "state": "sealed_product_qualification_consumer_not_default_canonical_daemon",
    },
]
claim = implementation.setdefault("claimBoundary", {})
claim.update(
    {
        "lowLevelSignedAdmissionCratePrivate": True,
        "externalLowLevelConsumers": False,
        "productScopedFacadeImplemented": True,
        "durableEvidenceReconciliationImplemented": True,
        "durableAttemptJournalImplemented": True,
        "checkpointCandidateImplemented": True,
        "targetHostQualified": False,
        "independentAcceptance": False,
        "activation": False,
        "release": False,
    }
)
implementation.setdefault("currentQualificationTruth", {})["currentStatus"] = (
    "docs/modules/learning.eval/CURRENT_STATUS.json"
)
map_path.write_text(json.dumps(implementation, indent=2, sort_keys=False) + "\n", encoding="utf-8")

matrix_path = ROOT / "docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json"
matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
module = next(item for item in matrix["modules"] if item.get("module") == "learning.eval")
module["implementationState"] = "source_converged_private_verifier_sealed_consumers_durable_reconciliation_current_candidate_qualification_required"
matrix_ops = {item.get("operation") for item in module.get("operations", [])}
for operation, symbol, source, status in [
    (
        "admit_product_scoped_evaluation_v1",
        "codex_hepta_intelligence_eval::admit_product_scoped_evaluation_v1",
        "codex-rs/hepta-intelligence-eval/src/product_admission.rs",
        "implemented_sealed_deny_all_facade",
    ),
    (
        "LockedFileQualificationEvidenceSinkV1",
        "codex_hepta_intelligence_eval::LockedFileQualificationEvidenceSinkV1",
        "codex-rs/hepta-intelligence-eval/src/qualification_evidence_file.rs",
        "implemented_idempotent_reconciliation",
    ),
    (
        "LockedFileProductEvaluationAttemptJournalV1",
        "codex_hepta_intelligence_eval::LockedFileProductEvaluationAttemptJournalV1",
        "codex-rs/hepta-intelligence-eval/src/evaluation_attempt.rs",
        "implemented_durable_stage_replay",
    ),
    (
        "write_checkpoint_candidate",
        "codex_hepta_intelligence_eval::LockedFileFinalHoldoutCasStoreV1::write_checkpoint_candidate",
        "codex-rs/hepta-intelligence-eval/src/fenced_holdout_file.rs",
        "implemented_host_atomic_install_required",
    ),
]:
    if operation not in matrix_ops:
        module.setdefault("operations", []).append(
            {
                "operation": operation,
                "nativeSymbol": symbol,
                "source": source,
                "status": status,
            }
        )
matrix_path.write_text(json.dumps(matrix, indent=2, sort_keys=False) + "\n", encoding="utf-8")

# Generate status only after every source mutation is complete.
subprocess.run(
    ["python3", "scripts/hepta-learning-eval-status.py", "generate"],
    cwd=ROOT,
    check=True,
)

# Refresh source-object entries for the touched implementation map where possible.
implementation = json.loads(map_path.read_text(encoding="utf-8"))
objects = {item.get("path"): item for item in implementation.get("sourceObjects", [])}
for path in [
    "codex-rs/hepta-intelligence-eval/src/lib.rs",
    "codex-rs/hepta-intelligence-eval/src/product_admission.rs",
    "codex-rs/hepta-intelligence-eval/src/product_runner.rs",
    "codex-rs/hepta-intelligence-eval/src/qualification_evidence_file.rs",
    "codex-rs/hepta-intelligence-eval/src/evaluation_attempt.rs",
    "codex-rs/hepta-intelligence-eval/src/fenced_holdout_file.rs",
    "codex-rs/hepta-agentd/src/intelligence_evaluation.rs",
    "codex-rs/hepta-intelligence/src/plasticity_product.rs",
]:
    object_id = subprocess.check_output(["git", "hash-object", path], cwd=ROOT, text=True).strip()
    objects[path] = {"path": path, "object": object_id}
implementation["sourceObjects"] = list(objects.values())
map_path.write_text(json.dumps(implementation, indent=2, sort_keys=False) + "\n", encoding="utf-8")

print("learning.eval convergence patch applied")
