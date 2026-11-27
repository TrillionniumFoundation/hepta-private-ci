#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}: {old[:100]!r}")
    write(path, text.replace(old, new, 1))


def insert_before_once(path: str, marker: str, content: str) -> None:
    text = read(path)
    if content.strip() in text:
        return
    count = text.count(marker)
    if count != 1:
        raise RuntimeError(f"{path}: expected one marker, found {count}: {marker[:100]!r}")
    write(path, text.replace(marker, content.rstrip() + "\n\n" + marker, 1))


def append_once(path: str, marker: str, content: str) -> None:
    text = read(path)
    if marker in text:
        return
    write(path, text.rstrip() + "\n\n" + content.rstrip() + "\n")


QUALIFICATION_SINK = r'''//! Durable, idempotent qualification-evidence publication.
//!
//! This locked-file implementation gives the product runner a concrete local
//! persistence/reconciliation boundary. A response lost after `sync_all` is
//! reported as `Indeterminate`; `reconcile` reloads the authoritative file and
//! returns the committed digest only when every decision binding matches.

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

use crate::ProductEvidenceSinkErrorV1;
use crate::ProductQualificationEvidenceSinkV1;
use crate::SignedEvaluationDecisionV1;

const MAGIC: &[u8; 8] = b"HEPQEV01";
const HEADER: usize = 72;
const FRAME_PAYLOAD: usize = 32 * 5;
const MAX_BYTES: u64 = 32 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LockedFileQualificationSinkErrorV1 {
    Binding,
    NotRegular,
    Busy,
    AlreadyInitialized,
    MissingHeader,
    Corrupt,
    Conflict,
    Capacity,
    Indeterminate,
    Io(io::ErrorKind),
}

impl fmt::Display for LockedFileQualificationSinkErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for LockedFileQualificationSinkErrorV1 {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct QualificationRecordV1 {
    execution_digest: Digest32,
    decision_digest: Digest32,
    trust_digest: Digest32,
    authentication_digest: Digest32,
    publication_digest: Digest32,
}

pub struct LockedFileQualificationEvidenceSinkV1 {
    file: File,
    binding: Digest32,
    records: Vec<QualificationRecordV1>,
    length: u64,
    poisoned: bool,
    #[cfg(test)]
    indeterminate_after_sync_once: bool,
}

impl LockedFileQualificationEvidenceSinkV1 {
    pub fn create(
        mut file: File,
        binding: Digest32,
    ) -> Result<Self, LockedFileQualificationSinkErrorV1> {
        acquire(&file, binding)?;
        if file.metadata().map_err(io_error)?.len() != 0 {
            return Err(LockedFileQualificationSinkErrorV1::AlreadyInitialized);
        }
        let mut header = MAGIC.to_vec();
        header.extend_from_slice(binding.as_array());
        header.extend_from_slice(Digest32::of_bytes(&header).as_array());
        file.seek(SeekFrom::Start(0)).map_err(io_error)?;
        file.write_all(&header)
            .and_then(|()| file.sync_all())
            .map_err(|_| LockedFileQualificationSinkErrorV1::Indeterminate)?;
        Ok(Self {
            file,
            binding,
            records: Vec::new(),
            length: HEADER as u64,
            poisoned: false,
            #[cfg(test)]
            indeterminate_after_sync_once: false,
        })
    }

    pub fn recover(
        mut file: File,
        binding: Digest32,
    ) -> Result<Self, LockedFileQualificationSinkErrorV1> {
        acquire(&file, binding)?;
        let (records, length) = read_records(&mut file, binding)?;
        Ok(Self {
            file,
            binding,
            records,
            length,
            poisoned: false,
            #[cfg(test)]
            indeterminate_after_sync_once: false,
        })
    }

    #[must_use]
    pub fn record_count(&self) -> usize {
        self.records.len()
    }

    #[cfg(test)]
    pub(crate) fn inject_indeterminate_after_sync_once(&mut self) {
        self.indeterminate_after_sync_once = true;
    }

    fn record_for(
        &self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<QualificationRecordV1, LockedFileQualificationSinkErrorV1> {
        if execution_digest.is_zero()
            || decision.decision.evidence_digest.is_zero()
            || decision.trust_digest.is_zero()
            || decision.authentication_digest.is_zero()
            || decision.decision.authority.grants_any()
        {
            return Err(LockedFileQualificationSinkErrorV1::Binding);
        }
        let mut bytes = b"hepta.learning-eval.qualification-publication.v1\0".to_vec();
        bytes.extend_from_slice(self.binding.as_array());
        for digest in [
            execution_digest,
            decision.decision.evidence_digest,
            decision.trust_digest,
            decision.authentication_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        let publication_digest = Digest32::of_bytes(&bytes);
        Ok(QualificationRecordV1 {
            execution_digest,
            decision_digest: decision.decision.evidence_digest,
            trust_digest: decision.trust_digest,
            authentication_digest: decision.authentication_digest,
            publication_digest,
        })
    }

    fn lookup(
        &self,
        expected: QualificationRecordV1,
    ) -> Result<Option<Digest32>, LockedFileQualificationSinkErrorV1> {
        match self
            .records
            .iter()
            .find(|record| record.execution_digest == expected.execution_digest)
        {
            Some(record) if record == &expected => Ok(Some(record.publication_digest)),
            Some(_) => Err(LockedFileQualificationSinkErrorV1::Conflict),
            None => Ok(None),
        }
    }

    fn persist_record(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, LockedFileQualificationSinkErrorV1> {
        if self.poisoned {
            return Err(LockedFileQualificationSinkErrorV1::Indeterminate);
        }
        let expected = self.record_for(execution_digest, decision)?;
        if let Some(publication) = self.lookup(expected)? {
            return Ok(publication);
        }
        if self.file.metadata().map_err(io_error)?.len() != self.length {
            self.poisoned = true;
            return Err(LockedFileQualificationSinkErrorV1::Indeterminate);
        }
        let payload = encode_record(expected);
        let next_length = self
            .length
            .checked_add(4 + payload.len() as u64 + 32)
            .filter(|length| *length <= MAX_BYTES)
            .ok_or(LockedFileQualificationSinkErrorV1::Capacity)?;
        let mut frame = (payload.len() as u32).to_be_bytes().to_vec();
        frame.extend_from_slice(&payload);
        frame.extend_from_slice(Digest32::of_bytes(&payload).as_array());
        if self
            .file
            .seek(SeekFrom::Start(self.length))
            .and_then(|_| self.file.write_all(&frame))
            .and_then(|()| self.file.sync_all())
            .is_err()
        {
            self.poisoned = true;
            return Err(LockedFileQualificationSinkErrorV1::Indeterminate);
        }
        self.length = next_length;
        #[cfg(test)]
        if self.indeterminate_after_sync_once {
            self.indeterminate_after_sync_once = false;
            self.poisoned = true;
            return Err(LockedFileQualificationSinkErrorV1::Indeterminate);
        }
        self.records.push(expected);
        Ok(expected.publication_digest)
    }

    fn reconcile_record(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Option<Digest32>, LockedFileQualificationSinkErrorV1> {
        let expected = self.record_for(execution_digest, decision)?;
        let (records, length) = read_records(&mut self.file, self.binding)?;
        self.records = records;
        self.length = length;
        self.poisoned = false;
        self.lookup(expected)
    }
}

impl ProductQualificationEvidenceSinkV1 for LockedFileQualificationEvidenceSinkV1 {
    fn persist(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        self.persist_record(execution_digest, decision)
            .map_err(map_sink_error)
    }

    fn reconcile(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Option<Digest32>, ProductEvidenceSinkErrorV1> {
        self.reconcile_record(execution_digest, decision)
            .map_err(map_sink_error)
    }
}

fn encode_record(record: QualificationRecordV1) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(FRAME_PAYLOAD);
    for digest in [
        record.execution_digest,
        record.decision_digest,
        record.trust_digest,
        record.authentication_digest,
        record.publication_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes
}

fn decode_record(payload: &[u8]) -> Result<QualificationRecordV1, LockedFileQualificationSinkErrorV1> {
    if payload.len() != FRAME_PAYLOAD {
        return Err(LockedFileQualificationSinkErrorV1::Corrupt);
    }
    Ok(QualificationRecordV1 {
        execution_digest: digest_at(payload, 0)?,
        decision_digest: digest_at(payload, 32)?,
        trust_digest: digest_at(payload, 64)?,
        authentication_digest: digest_at(payload, 96)?,
        publication_digest: digest_at(payload, 128)?,
    })
}

fn digest_at(
    bytes: &[u8],
    offset: usize,
) -> Result<Digest32, LockedFileQualificationSinkErrorV1> {
    let raw: [u8; 32] = bytes
        .get(offset..offset + 32)
        .ok_or(LockedFileQualificationSinkErrorV1::Corrupt)?
        .try_into()
        .map_err(|_| LockedFileQualificationSinkErrorV1::Corrupt)?;
    Ok(Digest32::from_array(raw))
}

fn read_records(
    file: &mut File,
    binding: Digest32,
) -> Result<(Vec<QualificationRecordV1>, u64), LockedFileQualificationSinkErrorV1> {
    let length = file.metadata().map_err(io_error)?.len();
    if length > MAX_BYTES {
        return Err(LockedFileQualificationSinkErrorV1::Capacity);
    }
    file.seek(SeekFrom::Start(0)).map_err(io_error)?;
    let mut bytes = Vec::new();
    file.take(MAX_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(io_error)?;
    if bytes.len() as u64 != length {
        return Err(LockedFileQualificationSinkErrorV1::Corrupt);
    }
    if bytes.len() < HEADER {
        return Err(LockedFileQualificationSinkErrorV1::MissingHeader);
    }
    if &bytes[..8] != MAGIC
        || &bytes[8..40] != binding.as_array()
        || &bytes[40..HEADER] != Digest32::of_bytes(&bytes[..40]).as_array()
    {
        return Err(LockedFileQualificationSinkErrorV1::Corrupt);
    }
    let mut records = Vec::new();
    let mut cursor = HEADER;
    while cursor < bytes.len() {
        let raw = bytes
            .get(cursor..cursor + 4)
            .ok_or(LockedFileQualificationSinkErrorV1::Corrupt)?;
        let count = u32::from_be_bytes([raw[0], raw[1], raw[2], raw[3]]) as usize;
        cursor += 4;
        if count != FRAME_PAYLOAD {
            return Err(LockedFileQualificationSinkErrorV1::Corrupt);
        }
        let payload = bytes
            .get(cursor..cursor + count)
            .ok_or(LockedFileQualificationSinkErrorV1::Corrupt)?;
        cursor += count;
        let checksum = bytes
            .get(cursor..cursor + 32)
            .ok_or(LockedFileQualificationSinkErrorV1::Corrupt)?;
        cursor += 32;
        if checksum != Digest32::of_bytes(payload).as_array() {
            return Err(LockedFileQualificationSinkErrorV1::Corrupt);
        }
        let record = decode_record(payload)?;
        if records.iter().any(|existing: &QualificationRecordV1| {
            existing.execution_digest == record.execution_digest && existing != &record
        }) {
            return Err(LockedFileQualificationSinkErrorV1::Conflict);
        }
        if !records.contains(&record) {
            records.push(record);
        }
    }
    Ok((records, length))
}

fn acquire(file: &File, binding: Digest32) -> Result<(), LockedFileQualificationSinkErrorV1> {
    if binding.is_zero() {
        return Err(LockedFileQualificationSinkErrorV1::Binding);
    }
    if !file.metadata().map_err(io_error)?.is_file() {
        return Err(LockedFileQualificationSinkErrorV1::NotRegular);
    }
    file.try_lock().map_err(|error| match error {
        TryLockError::WouldBlock => LockedFileQualificationSinkErrorV1::Busy,
        TryLockError::Error(error) => LockedFileQualificationSinkErrorV1::Io(error.kind()),
    })
}

fn io_error(error: io::Error) -> LockedFileQualificationSinkErrorV1 {
    LockedFileQualificationSinkErrorV1::Io(error.kind())
}

fn map_sink_error(error: LockedFileQualificationSinkErrorV1) -> ProductEvidenceSinkErrorV1 {
    match error {
        LockedFileQualificationSinkErrorV1::Indeterminate => {
            ProductEvidenceSinkErrorV1::Indeterminate
        }
        LockedFileQualificationSinkErrorV1::Busy
        | LockedFileQualificationSinkErrorV1::Io(_) => ProductEvidenceSinkErrorV1::Unavailable,
        _ => ProductEvidenceSinkErrorV1::Rejected,
    }
}

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
                "hepta-qualification-sink-{}-{}",
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
                .unwrap_or_else(|error| panic!("create sink: {error}"))
        }
        fn open(&self) -> File {
            OpenOptions::new()
                .read(true)
                .write(true)
                .open(&self.0)
                .unwrap_or_else(|error| panic!("open sink: {error}"))
        }
    }
    impl Drop for TempFile {
        fn drop(&mut self) {
            let _ = fs::remove_file(&self.0);
        }
    }

    fn id(value: &str) -> StableId {
        StableId::new(value).unwrap_or_else(|error| panic!("id: {error}"))
    }
    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }
    fn decision() -> SignedEvaluationDecisionV1 {
        SignedEvaluationDecisionV1 {
            decision: IndependentEvaluationDecisionV1 {
                evaluation_id: id("evaluation"),
                candidate_id: id("candidate"),
                baseline_id: id("baseline"),
                disposition: IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
                failed_metrics: Vec::new(),
                evidence_digest: digest("decision"),
                authority: AuthorityPosture::DENY_ALL,
            },
            trust_digest: digest("trust"),
            authentication_digest: digest("authentication"),
        }
    }

    #[test]
    fn accepted_but_unknown_publication_is_reconciled_exactly_once() {
        let temp = TempFile::new();
        let binding = digest("binding");
        let execution = digest("execution");
        let decision = decision();
        let mut sink = LockedFileQualificationEvidenceSinkV1::create(temp.create(), binding)
            .unwrap_or_else(|error| panic!("create: {error}"));
        sink.inject_indeterminate_after_sync_once();
        assert_eq!(
            sink.persist(execution, &decision),
            Err(ProductEvidenceSinkErrorV1::Indeterminate)
        );
        let committed = sink
            .reconcile(execution, &decision)
            .unwrap_or_else(|error| panic!("reconcile: {error:?}"))
            .unwrap_or_else(|| panic!("missing committed publication"));
        assert!(!committed.is_zero());
        assert_eq!(sink.persist(execution, &decision), Ok(committed));
        assert_eq!(sink.record_count(), 1);
        drop(sink);
        let mut recovered = LockedFileQualificationEvidenceSinkV1::recover(temp.open(), binding)
            .unwrap_or_else(|error| panic!("recover: {error}"));
        assert_eq!(recovered.reconcile(execution, &decision), Ok(Some(committed)));
    }

    #[test]
    fn conflicting_decision_for_one_execution_is_rejected() {
        let temp = TempFile::new();
        let mut sink = LockedFileQualificationEvidenceSinkV1::create(
            temp.create(),
            digest("binding"),
        )
        .unwrap_or_else(|error| panic!("create: {error}"));
        let execution = digest("execution");
        let first = decision();
        sink.persist(execution, &first)
            .unwrap_or_else(|error| panic!("persist: {error:?}"));
        let mut changed = first;
        changed.authentication_digest = digest("changed-authentication");
        assert_eq!(
            sink.persist(execution, &changed),
            Err(ProductEvidenceSinkErrorV1::Rejected)
        );
    }
}
'''


ATTEMPT_JOURNAL = r'''//! Durable product-evaluation attempt journal.
//!
//! The journal records progress after the final holdout is consumed, so a
//! provider/estimator/publication failure remains queryable and cannot be
//! mistaken for an unused holdout. Frames are checksum-bound, globally chained,
//! synchronously persisted and replayed under one exclusive file lock.

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
use codex_hepta_types::StableId;

const MAGIC: &[u8; 8] = b"HEPEVA01";
const HEADER: usize = 72;
const MAX_BYTES: u64 = 32 * 1024 * 1024;
const MAX_FRAME: usize = 512;
const MAX_RECORDS: usize = 1_000_000;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ProductEvaluationAttemptStageV1 {
    Started,
    HoldoutConsumed,
    HoldoutReleased,
    CandidateEstimated,
    BaselineEstimated,
    ComparisonSealed,
    QualificationVerified,
    Published,
    Failed,
}

impl ProductEvaluationAttemptStageV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Started => 0,
            Self::HoldoutConsumed => 1,
            Self::HoldoutReleased => 2,
            Self::CandidateEstimated => 3,
            Self::BaselineEstimated => 4,
            Self::ComparisonSealed => 5,
            Self::QualificationVerified => 6,
            Self::Published => 7,
            Self::Failed => 255,
        }
    }

    fn from_tag(tag: u8) -> Option<Self> {
        Some(match tag {
            0 => Self::Started,
            1 => Self::HoldoutConsumed,
            2 => Self::HoldoutReleased,
            3 => Self::CandidateEstimated,
            4 => Self::BaselineEstimated,
            5 => Self::ComparisonSealed,
            6 => Self::QualificationVerified,
            7 => Self::Published,
            255 => Self::Failed,
            _ => return None,
        })
    }

    const fn terminal(self) -> bool {
        matches!(self, Self::Published | Self::Failed)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductEvaluationAttemptEventV1 {
    pub attempt_id: StableId,
    pub stage: ProductEvaluationAttemptStageV1,
    pub evidence_digest: Digest32,
    pub error_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProductEvaluationAttemptSinkErrorV1 {
    Rejected,
    Unavailable,
    Indeterminate,
}

impl fmt::Display for ProductEvaluationAttemptSinkErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for ProductEvaluationAttemptSinkErrorV1 {}

pub trait ProductEvaluationAttemptSinkV1 {
    fn record(
        &mut self,
        event: &ProductEvaluationAttemptEventV1,
    ) -> Result<Digest32, ProductEvaluationAttemptSinkErrorV1>;
}

pub struct NoopProductEvaluationAttemptSinkV1;
impl ProductEvaluationAttemptSinkV1 for NoopProductEvaluationAttemptSinkV1 {
    fn record(
        &mut self,
        event: &ProductEvaluationAttemptEventV1,
    ) -> Result<Digest32, ProductEvaluationAttemptSinkErrorV1> {
        validate_event(event).map_err(|_| ProductEvaluationAttemptSinkErrorV1::Rejected)?;
        Ok(event_digest(Digest32::ZERO, Digest32::ZERO, event))
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LockedFileAttemptJournalErrorV1 {
    Binding,
    NotRegular,
    Busy,
    AlreadyInitialized,
    MissingHeader,
    Corrupt,
    Conflict,
    Capacity,
    Indeterminate,
    Io(io::ErrorKind),
}

impl fmt::Display for LockedFileAttemptJournalErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for LockedFileAttemptJournalErrorV1 {}

#[derive(Clone, Debug, Eq, PartialEq)]
struct AttemptRecordV1 {
    event: ProductEvaluationAttemptEventV1,
    previous_digest: Digest32,
    record_digest: Digest32,
}

pub struct LockedFileProductEvaluationAttemptJournalV1 {
    file: File,
    binding: Digest32,
    records: Vec<AttemptRecordV1>,
    head_digest: Digest32,
    length: u64,
    poisoned: bool,
}

impl LockedFileProductEvaluationAttemptJournalV1 {
    pub fn create(
        mut file: File,
        binding: Digest32,
    ) -> Result<Self, LockedFileAttemptJournalErrorV1> {
        acquire(&file, binding)?;
        if file.metadata().map_err(io_error)?.len() != 0 {
            return Err(LockedFileAttemptJournalErrorV1::AlreadyInitialized);
        }
        let mut header = MAGIC.to_vec();
        header.extend_from_slice(binding.as_array());
        header.extend_from_slice(Digest32::of_bytes(&header).as_array());
        file.seek(SeekFrom::Start(0)).map_err(io_error)?;
        file.write_all(&header)
            .and_then(|()| file.sync_all())
            .map_err(|_| LockedFileAttemptJournalErrorV1::Indeterminate)?;
        Ok(Self {
            file,
            binding,
            records: Vec::new(),
            head_digest: Digest32::ZERO,
            length: HEADER as u64,
            poisoned: false,
        })
    }

    pub fn recover(
        mut file: File,
        binding: Digest32,
    ) -> Result<Self, LockedFileAttemptJournalErrorV1> {
        acquire(&file, binding)?;
        let (records, head_digest, length) = read_records(&mut file, binding)?;
        Ok(Self {
            file,
            binding,
            records,
            head_digest,
            length,
            poisoned: false,
        })
    }

    #[must_use]
    pub fn head_digest(&self) -> Digest32 {
        self.head_digest
    }

    #[must_use]
    pub fn record_count(&self) -> usize {
        self.records.len()
    }

    #[must_use]
    pub fn events(&self) -> Vec<ProductEvaluationAttemptEventV1> {
        self.records.iter().map(|record| record.event.clone()).collect()
    }

    fn append(
        &mut self,
        event: &ProductEvaluationAttemptEventV1,
    ) -> Result<Digest32, LockedFileAttemptJournalErrorV1> {
        if self.poisoned {
            return Err(LockedFileAttemptJournalErrorV1::Indeterminate);
        }
        validate_event(event)?;
        if let Some(existing) = self
            .records
            .iter()
            .find(|record| record.event == *event)
        {
            return Ok(existing.record_digest);
        }
        validate_transition(&self.records, event)?;
        if self.records.len() >= MAX_RECORDS {
            return Err(LockedFileAttemptJournalErrorV1::Capacity);
        }
        let record_digest = event_digest(self.binding, self.head_digest, event);
        let record = AttemptRecordV1 {
            event: event.clone(),
            previous_digest: self.head_digest,
            record_digest,
        };
        let payload = encode_record(&record)?;
        let next_length = self
            .length
            .checked_add(4 + payload.len() as u64 + 32)
            .filter(|length| *length <= MAX_BYTES)
            .ok_or(LockedFileAttemptJournalErrorV1::Capacity)?;
        let mut frame = (payload.len() as u32).to_be_bytes().to_vec();
        frame.extend_from_slice(&payload);
        frame.extend_from_slice(Digest32::of_bytes(&payload).as_array());
        if self
            .file
            .seek(SeekFrom::Start(self.length))
            .and_then(|_| self.file.write_all(&frame))
            .and_then(|()| self.file.sync_all())
            .is_err()
        {
            self.poisoned = true;
            return Err(LockedFileAttemptJournalErrorV1::Indeterminate);
        }
        self.length = next_length;
        self.head_digest = record_digest;
        self.records.push(record);
        Ok(record_digest)
    }
}

impl ProductEvaluationAttemptSinkV1 for LockedFileProductEvaluationAttemptJournalV1 {
    fn record(
        &mut self,
        event: &ProductEvaluationAttemptEventV1,
    ) -> Result<Digest32, ProductEvaluationAttemptSinkErrorV1> {
        self.append(event).map_err(map_sink_error)
    }
}

fn validate_event(
    event: &ProductEvaluationAttemptEventV1,
) -> Result<(), LockedFileAttemptJournalErrorV1> {
    if event.evidence_digest.is_zero()
        || (event.stage == ProductEvaluationAttemptStageV1::Failed
            && event.error_digest.is_zero())
        || (event.stage != ProductEvaluationAttemptStageV1::Failed
            && !event.error_digest.is_zero())
    {
        return Err(LockedFileAttemptJournalErrorV1::Binding);
    }
    Ok(())
}

fn validate_transition(
    records: &[AttemptRecordV1],
    event: &ProductEvaluationAttemptEventV1,
) -> Result<(), LockedFileAttemptJournalErrorV1> {
    let previous = records
        .iter()
        .rev()
        .find(|record| record.event.attempt_id == event.attempt_id);
    match previous {
        None if event.stage == ProductEvaluationAttemptStageV1::Started => Ok(()),
        None => Err(LockedFileAttemptJournalErrorV1::Conflict),
        Some(previous) if previous.event.stage.terminal() => {
            Err(LockedFileAttemptJournalErrorV1::Conflict)
        }
        Some(previous) if event.stage == ProductEvaluationAttemptStageV1::Failed => Ok(()),
        Some(previous) if event.stage.tag() > previous.event.stage.tag() => Ok(()),
        Some(_) => Err(LockedFileAttemptJournalErrorV1::Conflict),
    }
}

fn event_digest(
    binding: Digest32,
    previous: Digest32,
    event: &ProductEvaluationAttemptEventV1,
) -> Digest32 {
    let mut bytes = b"hepta.learning-eval.attempt-event.v1\0".to_vec();
    bytes.extend_from_slice(binding.as_array());
    bytes.extend_from_slice(previous.as_array());
    push_id(&mut bytes, &event.attempt_id);
    bytes.push(event.stage.tag());
    bytes.extend_from_slice(event.evidence_digest.as_array());
    bytes.extend_from_slice(event.error_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn encode_record(record: &AttemptRecordV1) -> Result<Vec<u8>, LockedFileAttemptJournalErrorV1> {
    let id = record.event.attempt_id.as_str().as_bytes();
    let length = u16::try_from(id.len()).map_err(|_| LockedFileAttemptJournalErrorV1::Capacity)?;
    let mut bytes = Vec::new();
    bytes.push(record.event.stage.tag());
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(id);
    bytes.extend_from_slice(record.event.evidence_digest.as_array());
    bytes.extend_from_slice(record.event.error_digest.as_array());
    bytes.extend_from_slice(record.previous_digest.as_array());
    bytes.extend_from_slice(record.record_digest.as_array());
    if bytes.len() > MAX_FRAME {
        return Err(LockedFileAttemptJournalErrorV1::Capacity);
    }
    Ok(bytes)
}

fn decode_record(
    binding: Digest32,
    previous: Digest32,
    payload: &[u8],
) -> Result<AttemptRecordV1, LockedFileAttemptJournalErrorV1> {
    if payload.len() < 1 + 2 + 32 * 4 {
        return Err(LockedFileAttemptJournalErrorV1::Corrupt);
    }
    let stage = ProductEvaluationAttemptStageV1::from_tag(payload[0])
        .ok_or(LockedFileAttemptJournalErrorV1::Corrupt)?;
    let id_length = u16::from_be_bytes([payload[1], payload[2]]) as usize;
    let id_start = 3;
    let id_end = id_start + id_length;
    let evidence_end = id_end + 32;
    let error_end = evidence_end + 32;
    let previous_end = error_end + 32;
    let record_end = previous_end + 32;
    if record_end != payload.len() {
        return Err(LockedFileAttemptJournalErrorV1::Corrupt);
    }
    let id = std::str::from_utf8(
        payload
            .get(id_start..id_end)
            .ok_or(LockedFileAttemptJournalErrorV1::Corrupt)?,
    )
    .map_err(|_| LockedFileAttemptJournalErrorV1::Corrupt)?;
    let event = ProductEvaluationAttemptEventV1 {
        attempt_id: StableId::new(id).map_err(|_| LockedFileAttemptJournalErrorV1::Corrupt)?,
        stage,
        evidence_digest: digest_at(payload, id_end)?,
        error_digest: digest_at(payload, evidence_end)?,
    };
    validate_event(&event).map_err(|_| LockedFileAttemptJournalErrorV1::Corrupt)?;
    let encoded_previous = digest_at(payload, error_end)?;
    let encoded_record = digest_at(payload, previous_end)?;
    if encoded_previous != previous
        || encoded_record != event_digest(binding, previous, &event)
    {
        return Err(LockedFileAttemptJournalErrorV1::Corrupt);
    }
    Ok(AttemptRecordV1 {
        event,
        previous_digest: encoded_previous,
        record_digest: encoded_record,
    })
}

fn digest_at(
    bytes: &[u8],
    offset: usize,
) -> Result<Digest32, LockedFileAttemptJournalErrorV1> {
    let raw: [u8; 32] = bytes
        .get(offset..offset + 32)
        .ok_or(LockedFileAttemptJournalErrorV1::Corrupt)?
        .try_into()
        .map_err(|_| LockedFileAttemptJournalErrorV1::Corrupt)?;
    Ok(Digest32::from_array(raw))
}

fn read_records(
    file: &mut File,
    binding: Digest32,
) -> Result<(Vec<AttemptRecordV1>, Digest32, u64), LockedFileAttemptJournalErrorV1> {
    let length = file.metadata().map_err(io_error)?.len();
    if length > MAX_BYTES {
        return Err(LockedFileAttemptJournalErrorV1::Capacity);
    }
    file.seek(SeekFrom::Start(0)).map_err(io_error)?;
    let mut bytes = Vec::new();
    file.take(MAX_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(io_error)?;
    if bytes.len() as u64 != length {
        return Err(LockedFileAttemptJournalErrorV1::Corrupt);
    }
    if bytes.len() < HEADER {
        return Err(LockedFileAttemptJournalErrorV1::MissingHeader);
    }
    if &bytes[..8] != MAGIC
        || &bytes[8..40] != binding.as_array()
        || &bytes[40..HEADER] != Digest32::of_bytes(&bytes[..40]).as_array()
    {
        return Err(LockedFileAttemptJournalErrorV1::Corrupt);
    }
    let mut cursor = HEADER;
    let mut records = Vec::new();
    let mut head = Digest32::ZERO;
    while cursor < bytes.len() {
        let raw = bytes
            .get(cursor..cursor + 4)
            .ok_or(LockedFileAttemptJournalErrorV1::Corrupt)?;
        let count = u32::from_be_bytes([raw[0], raw[1], raw[2], raw[3]]) as usize;
        cursor += 4;
        if !(1..=MAX_FRAME).contains(&count) {
            return Err(LockedFileAttemptJournalErrorV1::Capacity);
        }
        let payload = bytes
            .get(cursor..cursor + count)
            .ok_or(LockedFileAttemptJournalErrorV1::Corrupt)?;
        cursor += count;
        let checksum = bytes
            .get(cursor..cursor + 32)
            .ok_or(LockedFileAttemptJournalErrorV1::Corrupt)?;
        cursor += 32;
        if checksum != Digest32::of_bytes(payload).as_array() {
            return Err(LockedFileAttemptJournalErrorV1::Corrupt);
        }
        let record = decode_record(binding, head, payload)?;
        validate_transition(&records, &record.event)
            .map_err(|_| LockedFileAttemptJournalErrorV1::Corrupt)?;
        head = record.record_digest;
        records.push(record);
        if records.len() > MAX_RECORDS {
            return Err(LockedFileAttemptJournalErrorV1::Capacity);
        }
    }
    Ok((records, head, length))
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn acquire(file: &File, binding: Digest32) -> Result<(), LockedFileAttemptJournalErrorV1> {
    if binding.is_zero() {
        return Err(LockedFileAttemptJournalErrorV1::Binding);
    }
    if !file.metadata().map_err(io_error)?.is_file() {
        return Err(LockedFileAttemptJournalErrorV1::NotRegular);
    }
    file.try_lock().map_err(|error| match error {
        TryLockError::WouldBlock => LockedFileAttemptJournalErrorV1::Busy,
        TryLockError::Error(error) => LockedFileAttemptJournalErrorV1::Io(error.kind()),
    })
}

fn io_error(error: io::Error) -> LockedFileAttemptJournalErrorV1 {
    LockedFileAttemptJournalErrorV1::Io(error.kind())
}

fn map_sink_error(error: LockedFileAttemptJournalErrorV1) -> ProductEvaluationAttemptSinkErrorV1 {
    match error {
        LockedFileAttemptJournalErrorV1::Indeterminate => {
            ProductEvaluationAttemptSinkErrorV1::Indeterminate
        }
        LockedFileAttemptJournalErrorV1::Busy | LockedFileAttemptJournalErrorV1::Io(_) => {
            ProductEvaluationAttemptSinkErrorV1::Unavailable
        }
        _ => ProductEvaluationAttemptSinkErrorV1::Rejected,
    }
}

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
                "hepta-evaluation-attempt-{}-{}",
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
                .unwrap_or_else(|error| panic!("create journal: {error}"))
        }
        fn open(&self) -> File {
            OpenOptions::new()
                .read(true)
                .write(true)
                .open(&self.0)
                .unwrap_or_else(|error| panic!("open journal: {error}"))
        }
    }
    impl Drop for TempFile {
        fn drop(&mut self) {
            let _ = fs::remove_file(&self.0);
        }
    }

    fn id(value: &str) -> StableId {
        StableId::new(value).unwrap_or_else(|error| panic!("id: {error}"))
    }
    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }
    fn event(stage: ProductEvaluationAttemptStageV1) -> ProductEvaluationAttemptEventV1 {
        ProductEvaluationAttemptEventV1 {
            attempt_id: id("attempt"),
            stage,
            evidence_digest: digest(match stage {
                ProductEvaluationAttemptStageV1::Started => "started",
                ProductEvaluationAttemptStageV1::HoldoutConsumed => "consumed",
                ProductEvaluationAttemptStageV1::HoldoutReleased => "released",
                ProductEvaluationAttemptStageV1::CandidateEstimated => "candidate",
                ProductEvaluationAttemptStageV1::BaselineEstimated => "baseline",
                ProductEvaluationAttemptStageV1::ComparisonSealed => "sealed",
                ProductEvaluationAttemptStageV1::QualificationVerified => "qualified",
                ProductEvaluationAttemptStageV1::Published => "published",
                ProductEvaluationAttemptStageV1::Failed => "failed",
            }),
            error_digest: if stage == ProductEvaluationAttemptStageV1::Failed {
                digest("provider-failure")
            } else {
                Digest32::ZERO
            },
        }
    }

    #[test]
    fn consumed_holdout_then_failure_is_durable_and_replayable() {
        let temp = TempFile::new();
        let binding = digest("binding");
        let mut journal = LockedFileProductEvaluationAttemptJournalV1::create(
            temp.create(),
            binding,
        )
        .unwrap_or_else(|error| panic!("create: {error}"));
        for stage in [
            ProductEvaluationAttemptStageV1::Started,
            ProductEvaluationAttemptStageV1::HoldoutConsumed,
            ProductEvaluationAttemptStageV1::Failed,
        ] {
            journal
                .record(&event(stage))
                .unwrap_or_else(|error| panic!("record: {error:?}"));
        }
        let head = journal.head_digest();
        drop(journal);
        let recovered = LockedFileProductEvaluationAttemptJournalV1::recover(
            temp.open(),
            binding,
        )
        .unwrap_or_else(|error| panic!("recover: {error}"));
        assert_eq!(recovered.head_digest(), head);
        assert_eq!(recovered.record_count(), 3);
        assert_eq!(
            recovered.events().last().map(|value| value.stage),
            Some(ProductEvaluationAttemptStageV1::Failed)
        );
    }

    #[test]
    fn terminal_attempt_cannot_be_reopened() {
        let temp = TempFile::new();
        let mut journal = LockedFileProductEvaluationAttemptJournalV1::create(
            temp.create(),
            digest("binding"),
        )
        .unwrap_or_else(|error| panic!("create: {error}"));
        journal
            .record(&event(ProductEvaluationAttemptStageV1::Started))
            .unwrap_or_else(|error| panic!("started: {error:?}"));
        journal
            .record(&event(ProductEvaluationAttemptStageV1::Failed))
            .unwrap_or_else(|error| panic!("failed: {error:?}"));
        assert_eq!(
            journal.record(&event(ProductEvaluationAttemptStageV1::Published)),
            Err(ProductEvaluationAttemptSinkErrorV1::Rejected)
        );
    }
}
'''


STATUS_SCRIPT = r'''#!/usr/bin/env python3
"""Generate the bounded current-state view for learning.eval."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "docs/modules/learning.eval/CURRENT_STATUS.json"
MD_PATH = ROOT / "docs/modules/learning.eval/CURRENT_STATUS.md"
FORBIDDEN = re.compile(r"\bdecide_with_signed_(?:longitudinal_)?evidence_v[23]\b")
OWNER = ROOT / "codex-rs/hepta-intelligence-eval"


def external_direct_callers() -> list[str]:
    callers: list[str] = []
    for source in (ROOT / "codex-rs").rglob("*.rs"):
        if source == OWNER or OWNER in source.parents:
            continue
        if FORBIDDEN.search(source.read_text(encoding="utf-8")):
            callers.append(source.relative_to(ROOT).as_posix())
    return sorted(callers)


def admitted_callers() -> list[str]:
    callers: list[str] = []
    for source in (ROOT / "codex-rs").rglob("*.rs"):
        if source == OWNER or OWNER in source.parents:
            continue
        if "admit_signed_evaluation_v2" in source.read_text(encoding="utf-8"):
            callers.append(source.relative_to(ROOT).as_posix())
    return sorted(callers)


def state() -> dict[str, object]:
    implementation = json.loads(
        (ROOT / "docs/modules/learning.eval/IMPLEMENTATION_MAP.json").read_text(
            encoding="utf-8"
        )
    )
    direct = external_direct_callers()
    admitted = admitted_callers()
    return {
        "schema": "hepta.learning-eval.current-state.v1",
        "module": "learning.eval",
        "generatedFrom": [
            "docs/modules/learning.eval/IMPLEMENTATION_MAP.json",
            "codex-rs/hepta-intelligence-eval/src/lib.rs",
            "codex-rs/hepta-agentd/src/intelligence_evaluation.rs",
            "codex-rs/hepta-intelligence/src/plasticity_product.rs",
            ".github/workflows/hepta-lane-e-gap-closure.yml",
        ],
        "source": {
            "rootPresent": (ROOT / "codex-rs/hepta-intelligence-eval").is_dir(),
            "productCompositionImplemented": bool(
                implementation.get("claimBoundary", {}).get("productAdapterComposed")
            ),
            "consumerAdmissionFacadeImplemented": (
                ROOT / "codex-rs/hepta-intelligence-eval/src/signed_admission.rs"
            ).is_file(),
            "durableQualificationSinkImplemented": (
                ROOT / "codex-rs/hepta-intelligence-eval/src/qualification_sink_file.rs"
            ).is_file(),
            "durableAttemptJournalImplemented": (
                ROOT / "codex-rs/hepta-intelligence-eval/src/attempt_journal.rs"
            ).is_file(),
            "checkpointCompactionImplemented": "checkpoint_to"
            in (ROOT / "codex-rs/hepta-intelligence-eval/src/fenced_holdout_file.rs").read_text(
                encoding="utf-8"
            ),
        },
        "apiBoundary": {
            "externalDirectDecisionCallers": direct,
            "consumerAdmissionCallers": admitted,
            "closed": not direct,
        },
        "qualification": {
            "exactHead": "requires_passing_commit_addressed_workflow_artifact",
            "orderedParentSyntheticMerge": "requires_passing_commit_addressed_workflow_artifact",
            "lineCoverageFloorPct": 85,
            "provenanceAttestation": "requires_current_workflow_artifact",
        },
        "externalEvidence": {
            "targetHostQualified": False,
            "realFutureCalendarEvidence": False,
            "privacyAndSubgroupAcceptance": False,
            "retentionAndUnlearningAcceptance": False,
            "independentOperatorAcceptance": False,
            "releaseAuthorized": False,
        },
        "claim": "repository_source_candidate_not_production_admission",
    }


def markdown(value: dict[str, object]) -> str:
    source = value["source"]
    api = value["apiBoundary"]
    qualification = value["qualification"]
    external = value["externalEvidence"]
    lines = [
        "# learning.eval current state",
        "",
        "This file is generated by `scripts/hepta-learning-eval-status.py`; edit the generator or implementation map, not this file.",
        "",
        "## Repository-controlled source",
        "",
    ]
    for key, item in source.items():
        lines.append(f"- `{key}`: `{str(item).lower()}`")
    lines.extend(["", "## API boundary", ""])
    lines.append(f"- closed: `{str(api['closed']).lower()}`")
    lines.append(f"- direct low-level callers: `{len(api['externalDirectDecisionCallers'])}`")
    for caller in api["consumerAdmissionCallers"]:
        lines.append(f"- admitted consumer: `{caller}`")
    lines.extend(["", "## Current-candidate qualification", ""])
    for key, item in qualification.items():
        lines.append(f"- `{key}`: `{item}`")
    lines.extend(["", "## External evidence gates", ""])
    for key, item in external.items():
        lines.append(f"- `{key}`: `{str(item).lower()}`")
    lines.extend(
        [
            "",
            "Repository source evidence cannot self-issue target-host, future-calendar, privacy, independent acceptance, promotion or release evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def render() -> tuple[str, str]:
    value = state()
    return json.dumps(value, indent=2, sort_keys=True) + "\n", markdown(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("write", "verify"), nargs="?", default="verify")
    args = parser.parse_args()
    json_text, md_text = render()
    if args.command == "write":
        JSON_PATH.write_text(json_text, encoding="utf-8")
        MD_PATH.write_text(md_text, encoding="utf-8")
        return 0
    mismatches = []
    if not JSON_PATH.is_file() or JSON_PATH.read_text(encoding="utf-8") != json_text:
        mismatches.append(str(JSON_PATH.relative_to(ROOT)))
    if not MD_PATH.is_file() or MD_PATH.read_text(encoding="utf-8") != md_text:
        mismatches.append(str(MD_PATH.relative_to(ROOT)))
    if mismatches:
        raise SystemExit("stale generated learning.eval status: " + ", ".join(mismatches))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


TARGET_HOST_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "hepta.learning-eval.target-host-evidence.v1",
    "title": "learning.eval target-host evidence",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema",
        "sourceSha",
        "hostIdentity",
        "qualificationSink",
        "holdoutNamespace",
        "futureWindows",
        "privacyReview",
        "retentionAndUnlearning",
        "independentAcceptance",
    ],
    "properties": {
        "schema": {"const": "hepta.learning-eval.target-host-evidence.v1"},
        "sourceSha": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
        "hostIdentity": {"type": "object"},
        "qualificationSink": {"type": "object"},
        "holdoutNamespace": {"type": "object"},
        "futureWindows": {"type": "array", "minItems": 2},
        "privacyReview": {"type": "object"},
        "retentionAndUnlearning": {"type": "object"},
        "independentAcceptance": {"type": "object"},
    },
}

TARGET_HOST_DOC = r'''# learning.eval target-host qualification

This checklist defines evidence that must come from the selected target host or
an independent authority. Repository source and CI cannot self-issue these facts.

A target-host dossier must validate against
`TARGET_HOST_EVIDENCE_SCHEMA.json` and bind one exact source SHA. It must include:

1. authenticated host identity, authority epoch and revocation source;
2. a durable `ProductQualificationEvidenceSinkV1` namespace with idempotent
   publication, accepted-but-unknown reconciliation and independent backup;
3. a final-holdout namespace with linearizable CAS/fencing, retained anti-rollback
   anchor, crash tests and documented cross-host lock/fsync semantics;
4. real future-calendar observations from independent collectors, not virtual
   timestamps or repository fixtures;
5. subgroup, privacy, poisoning and negative-transfer review;
6. retention, change-point and unlearning/non-resurrection evidence;
7. independent semantic/operator acceptance and separately authorized canary,
   promotion and release decisions.

Until all fields are independently supplied and verified, `targetHostQualified`,
`independentOperatorAcceptance` and `releaseAuthorized` remain false in
`CURRENT_STATUS.json`.
'''


def patch_lib() -> None:
    replace_once(
        "codex-rs/hepta-intelligence-eval/src/lib.rs",
        "mod closure;\nmod durable_holdout;",
        "mod attempt_journal;\nmod closure;\nmod durable_holdout;",
    )
    replace_once(
        "codex-rs/hepta-intelligence-eval/src/lib.rs",
        "mod product_runner;\nmod self_evolution_selection;",
        "mod product_runner;\nmod qualification_sink_file;\nmod self_evolution_selection;",
    )
    replace_once(
        "codex-rs/hepta-intelligence-eval/src/lib.rs",
        "pub use closure::CrossFoldPartitionV1;",
        "pub use attempt_journal::LockedFileAttemptJournalErrorV1;\npub use attempt_journal::LockedFileProductEvaluationAttemptJournalV1;\npub use attempt_journal::NoopProductEvaluationAttemptSinkV1;\npub use attempt_journal::ProductEvaluationAttemptEventV1;\npub use attempt_journal::ProductEvaluationAttemptSinkErrorV1;\npub use attempt_journal::ProductEvaluationAttemptSinkV1;\npub use attempt_journal::ProductEvaluationAttemptStageV1;\npub use closure::CrossFoldPartitionV1;",
    )
    replace_once(
        "codex-rs/hepta-intelligence-eval/src/lib.rs",
        "pub use product_runner::TemporalComparisonInputsV1;",
        "pub use product_runner::TemporalComparisonInputsV1;\npub use qualification_sink_file::LockedFileQualificationEvidenceSinkV1;\npub use qualification_sink_file::LockedFileQualificationSinkErrorV1;",
    )


def patch_product_runner() -> None:
    replace_once(
        "codex-rs/hepta-intelligence-eval/src/product_runner.rs",
        "use crate::MetricRoleV2;\nuse crate::OpeInterval;",
        "use crate::MetricRoleV2;\nuse crate::NoopProductEvaluationAttemptSinkV1;\nuse crate::OpeInterval;",
    )
    replace_once(
        "codex-rs/hepta-intelligence-eval/src/product_runner.rs",
        "use crate::OutcomeTrainingSample;\nuse crate::SignedEvaluationDecisionV1;",
        "use crate::OutcomeTrainingSample;\nuse crate::ProductEvaluationAttemptEventV1;\nuse crate::ProductEvaluationAttemptSinkErrorV1;\nuse crate::ProductEvaluationAttemptSinkV1;\nuse crate::ProductEvaluationAttemptStageV1;\nuse crate::SignedEvaluationDecisionV1;",
    )
    replace_once(
        "codex-rs/hepta-intelligence-eval/src/product_runner.rs",
        "pub trait ProductQualificationEvidenceSinkV1 {\n    /// Persist the terminal qualification evidence through the declared\n    /// evidence owner. Return a nonzero durable publication digest only after\n    /// the publication is committed.\n    fn persist(\n        &mut self,\n        execution_digest: Digest32,\n        decision: &SignedEvaluationDecisionV1,\n    ) -> Result<Digest32, ProductEvidenceSinkErrorV1>;\n}",
        "pub trait ProductQualificationEvidenceSinkV1 {\n    /// Persist the terminal qualification evidence through the declared\n    /// evidence owner. Return a nonzero durable publication digest only after\n    /// the publication is committed.\n    fn persist(\n        &mut self,\n        execution_digest: Digest32,\n        decision: &SignedEvaluationDecisionV1,\n    ) -> Result<Digest32, ProductEvidenceSinkErrorV1>;\n\n    /// Reconcile an accepted-or-unknown publication. Returning `Some` asserts\n    /// that the exact execution and decision are durably committed.\n    fn reconcile(\n        &mut self,\n        _execution_digest: Digest32,\n        _decision: &SignedEvaluationDecisionV1,\n    ) -> Result<Option<Digest32>, ProductEvidenceSinkErrorV1> {\n        Ok(None)\n    }\n}",
    )

    old_fn = '''    pub fn evaluate_temporal_comparison<P: FinalHoldoutProviderV1>(
        &mut self,
        product_plan: &ProductFrozenEvaluationPlanV1,
        candidate_plan: &TemporalEvaluationPlan,
        baseline_plan: &TemporalEvaluationPlan,
        provider: &mut P,
    ) -> Result<ProductTemporalEvaluationReceiptV1, ProductEvaluationError> {
        product_plan.validate_integrity()?;'''
    new_fn = '''    pub fn evaluate_temporal_comparison<P: FinalHoldoutProviderV1>(
        &mut self,
        product_plan: &ProductFrozenEvaluationPlanV1,
        candidate_plan: &TemporalEvaluationPlan,
        baseline_plan: &TemporalEvaluationPlan,
        provider: &mut P,
    ) -> Result<ProductTemporalEvaluationReceiptV1, ProductEvaluationError> {
        let mut attempts = NoopProductEvaluationAttemptSinkV1;
        self.evaluate_temporal_comparison_recorded(
            product_plan,
            candidate_plan,
            baseline_plan,
            provider,
            &mut attempts,
        )
    }

    pub fn evaluate_temporal_comparison_recorded<P: FinalHoldoutProviderV1>(
        &mut self,
        product_plan: &ProductFrozenEvaluationPlanV1,
        candidate_plan: &TemporalEvaluationPlan,
        baseline_plan: &TemporalEvaluationPlan,
        provider: &mut P,
        attempts: &mut dyn ProductEvaluationAttemptSinkV1,
    ) -> Result<ProductTemporalEvaluationReceiptV1, ProductEvaluationError> {
        product_plan.validate_integrity()?;'''
    replace_once("codex-rs/hepta-intelligence-eval/src/product_runner.rs", old_fn, new_fn)

    replace_once(
        "codex-rs/hepta-intelligence-eval/src/product_runner.rs",
        "        let holdout = self.holdout.consume(&product_plan.frozen_plan)?;\n        let mut inputs = provider.release_after_consumption(&holdout)?;",
        "        let attempt_id = product_plan.frozen_plan.plan_id.clone();\n        record_attempt(\n            attempts,\n            &attempt_id,\n            ProductEvaluationAttemptStageV1::Started,\n            product_plan.frozen_plan.plan_digest,\n            Digest32::ZERO,\n        )?;\n        let holdout = self.holdout.consume(&product_plan.frozen_plan)?;\n        record_attempt(\n            attempts,\n            &attempt_id,\n            ProductEvaluationAttemptStageV1::HoldoutConsumed,\n            holdout.record_digest,\n            Digest32::ZERO,\n        )?;\n        let result = (|| -> Result<ProductTemporalEvaluationReceiptV1, ProductEvaluationError> {\n        let mut inputs = provider.release_after_consumption(&holdout)?;\n        record_attempt(\n            attempts,\n            &attempt_id,\n            ProductEvaluationAttemptStageV1::HoldoutReleased,\n            holdout.use_receipt.use_digest,\n            Digest32::ZERO,\n        )?;",
    )
    replace_once(
        "codex-rs/hepta-intelligence-eval/src/product_runner.rs",
        "        let baseline = evaluate_temporal_holdout(\n            baseline_plan,",
        "        record_attempt(\n            attempts,\n            &attempt_id,\n            ProductEvaluationAttemptStageV1::CandidateEstimated,\n            candidate.evidence_digest,\n            Digest32::ZERO,\n        )?;\n        let baseline = evaluate_temporal_holdout(\n            baseline_plan,",
    )
    replace_once(
        "codex-rs/hepta-intelligence-eval/src/product_runner.rs",
        "        candidate.validate_integrity()?;\n        baseline.validate_integrity()?;",
        "        candidate.validate_integrity()?;\n        baseline.validate_integrity()?;\n        record_attempt(\n            attempts,\n            &attempt_id,\n            ProductEvaluationAttemptStageV1::BaselineEstimated,\n            baseline.evidence_digest,\n            Digest32::ZERO,\n        )?;",
    )
    replace_once(
        "codex-rs/hepta-intelligence-eval/src/product_runner.rs",
        "        receipt.receipt_seal = product_evaluation_seal(&receipt)?;\n        Ok(receipt)\n    }\n\n    pub fn qualification_bundle(",
        "        receipt.receipt_seal = product_evaluation_seal(&receipt)?;\n        record_attempt(\n            attempts,\n            &attempt_id,\n            ProductEvaluationAttemptStageV1::ComparisonSealed,\n            receipt.execution_digest,\n            Digest32::ZERO,\n        )?;\n        Ok(receipt)\n        })();\n        match result {\n            Ok(receipt) => Ok(receipt),\n            Err(error) => {\n                let error_digest = Digest32::of_bytes(format!(\"{error:?}\").as_bytes());\n                record_attempt(\n                    attempts,\n                    &attempt_id,\n                    ProductEvaluationAttemptStageV1::Failed,\n                    product_plan.frozen_plan.plan_digest,\n                    error_digest,\n                )?;\n                Err(error)\n            }\n        }\n    }\n\n    pub fn qualification_bundle(",
    )

    replace_once(
        "codex-rs/hepta-intelligence-eval/src/product_runner.rs",
        "        let publication_digest = sink.persist(temporal.execution_digest, &decision)?;",
        "        let publication_digest = match sink.persist(temporal.execution_digest, &decision) {\n            Ok(digest) => digest,\n            Err(ProductEvidenceSinkErrorV1::Indeterminate) => sink\n                .reconcile(temporal.execution_digest, &decision)?\n                .ok_or(ProductEvaluationError::Sink(\n                    ProductEvidenceSinkErrorV1::Indeterminate,\n                ))?,\n            Err(error) => return Err(error.into()),\n        };",
    )
    insert_before_once(
        "codex-rs/hepta-intelligence-eval/src/product_runner.rs",
        "fn product_qualification_evidence_digest(",
        '''fn record_attempt(
    attempts: &mut dyn ProductEvaluationAttemptSinkV1,
    attempt_id: &StableId,
    stage: ProductEvaluationAttemptStageV1,
    evidence_digest: Digest32,
    error_digest: Digest32,
) -> Result<Digest32, ProductEvaluationError> {
    attempts
        .record(&ProductEvaluationAttemptEventV1 {
            attempt_id: attempt_id.clone(),
            stage,
            evidence_digest,
            error_digest,
        })
        .map_err(ProductEvaluationError::Attempt)
}''',
    )
    replace_once(
        "codex-rs/hepta-intelligence-eval/src/product_runner.rs",
        "    Sink(ProductEvidenceSinkErrorV1),\n}",
        "    Sink(ProductEvidenceSinkErrorV1),\n    Attempt(ProductEvaluationAttemptSinkErrorV1),\n}",
    )
    replace_once(
        "codex-rs/hepta-intelligence-eval/src/product_runner.rs",
        "impl From<ProductEvidenceSinkErrorV1> for ProductEvaluationError {\n    fn from(value: ProductEvidenceSinkErrorV1) -> Self {\n        Self::Sink(value)\n    }\n}\n",
        "impl From<ProductEvidenceSinkErrorV1> for ProductEvaluationError {\n    fn from(value: ProductEvidenceSinkErrorV1) -> Self {\n        Self::Sink(value)\n    }\n}\nimpl From<ProductEvaluationAttemptSinkErrorV1> for ProductEvaluationError {\n    fn from(value: ProductEvaluationAttemptSinkErrorV1) -> Self {\n        Self::Attempt(value)\n    }\n}\n",
    )


def patch_checkpoint() -> None:
    insert_before_once(
        "codex-rs/hepta-intelligence-eval/src/fenced_holdout_file.rs",
        "    #[must_use]\n    pub fn anchor(&self)",
        '''    /// Rewrite the current semantic state into a fresh compact log.
    ///
    /// The checkpoint preserves the exact final state digest and journal while
    /// dropping superseded fence events. The caller atomically installs the new
    /// file only after independently retaining the returned anchor.
    pub fn checkpoint_to(
        &self,
        file: File,
    ) -> Result<Self, LockedFileCasErrorV1> {
        let mut compacted = Self::create(file, self.binding)?;
        let Some(current) = self.state.as_ref() else {
            return Ok(compacted);
        };
        let mut journal = FinalHoldoutJournalV1::with_record_limit(MAX_RECORDS)
            .map_err(|_| LockedFileCasErrorV1::Corrupt)?;
        let mut replay = FinalHoldoutCasRecordV1::new(
            self.binding,
            current.fence.clone(),
            journal.snapshot(),
        )
        .map_err(|_| LockedFileCasErrorV1::Corrupt)?;
        compacted
            .compare_and_swap(self.binding, None, &replay)
            .map_err(map_store_error)?;
        for entry in &current.journal.records {
            let receipt = journal
                .consume(journal.head_digest(), &entry.plan)
                .map_err(|_| LockedFileCasErrorV1::Corrupt)?;
            if receipt.disposition != crate::HoldoutUseDispositionV1::Recorded {
                return Err(LockedFileCasErrorV1::Corrupt);
            }
            let next = FinalHoldoutCasRecordV1::new(
                self.binding,
                current.fence.clone(),
                journal.snapshot(),
            )
            .map_err(|_| LockedFileCasErrorV1::Corrupt)?;
            compacted
                .compare_and_swap(self.binding, Some(replay.state_digest), &next)
                .map_err(map_store_error)?;
            replay = next;
        }
        if replay.state_digest != current.state_digest {
            return Err(LockedFileCasErrorV1::Corrupt);
        }
        Ok(compacted)
    }''',
    )
    insert_before_once(
        "codex-rs/hepta-intelligence-eval/src/fenced_holdout_file.rs",
        "fn io_error(error: io::Error)",
        '''fn map_store_error(error: FinalHoldoutCasStoreError) -> LockedFileCasErrorV1 {
    match error {
        FinalHoldoutCasStoreError::Conflict => LockedFileCasErrorV1::Corrupt,
        FinalHoldoutCasStoreError::Rejected => LockedFileCasErrorV1::Corrupt,
        FinalHoldoutCasStoreError::Indeterminate => LockedFileCasErrorV1::Indeterminate,
    }
}''',
    )
    append_once(
        "codex-rs/hepta-intelligence-eval/src/fenced_holdout_file_tests.rs",
        "fn checkpoint_compacts_fence_history_and_emits_capacity_measurement",
        r'''#[test]
fn checkpoint_compacts_fence_history_and_emits_capacity_measurement() {
    use std::time::Instant;

    let source = TempFile::new();
    let checkpoint = TempFile::new();
    let store = LockedFileFinalHoldoutCasStoreV1::create(source.create(), digest("binding"))
        .unwrap_or_else(|error| panic!("create source: {error}"));
    let mut current = owner(store, None);
    let mut anchor = current.anchor();
    for generation in 0..32 {
        let store = current.into_store();
        drop(store);
        let reopened = LockedFileFinalHoldoutCasStoreV1::recover(
            source.open(),
            digest("binding"),
            Some(anchor),
        )
        .unwrap_or_else(|error| panic!("recover generation {generation}: {error}"));
        current = owner(reopened, Some(anchor));
        anchor = current.anchor();
    }
    for index in 0..64 {
        current
            .consume(&plan(&format!("capacity-plan-{index}")))
            .unwrap_or_else(|error| panic!("consume {index}: {error}"));
    }
    anchor = current.anchor();
    let store = current.into_store();
    let source_bytes = fs::metadata(&source.path)
        .unwrap_or_else(|error| panic!("source metadata: {error}"))
        .len();
    let checkpoint_start = Instant::now();
    let compacted = store
        .checkpoint_to(checkpoint.create())
        .unwrap_or_else(|error| panic!("checkpoint: {error}"));
    let checkpoint_micros = checkpoint_start.elapsed().as_micros();
    assert_eq!(compacted.anchor(), Some(anchor));
    let checkpoint_bytes = fs::metadata(&checkpoint.path)
        .unwrap_or_else(|error| panic!("checkpoint metadata: {error}"))
        .len();
    assert!(checkpoint_bytes < source_bytes);
    drop(compacted);
    let recovery_start = Instant::now();
    let recovered = LockedFileFinalHoldoutCasStoreV1::recover(
        checkpoint.open(),
        digest("binding"),
        Some(anchor),
    )
    .unwrap_or_else(|error| panic!("recover checkpoint: {error}"));
    let recovery_micros = recovery_start.elapsed().as_micros();
    assert_eq!(recovered.anchor(), Some(anchor));

    if let Ok(path) = std::env::var("HEPTA_LEARNING_EVAL_CAPACITY_REPORT") {
        let report = format!(
            "{{\n  \"schema\": \"hepta.learning-eval.capacity.v1\",\n  \"fenceGenerations\": 33,\n  \"records\": 64,\n  \"sourceBytes\": {source_bytes},\n  \"checkpointBytes\": {checkpoint_bytes},\n  \"checkpointMicros\": {checkpoint_micros},\n  \"recoveryMicros\": {recovery_micros}\n}}\n"
        );
        fs::write(path, report)
            .unwrap_or_else(|error| panic!("write capacity report: {error}"));
    }
}''',
    )


def patch_tests() -> None:
    replace_once(
        "codex-rs/hepta-intelligence-eval/src/product_runner_tests.rs",
        "#[derive(Default)]\nstruct Sink {\n    persisted: Vec<Digest32>,\n}",
        "#[derive(Default)]\nstruct Sink {\n    persisted: Vec<Digest32>,\n    committed: Option<(Digest32, Digest32, Digest32)>,\n    indeterminate_once: bool,\n}",
    )
    replace_once(
        "codex-rs/hepta-intelligence-eval/src/product_runner_tests.rs",
        "        let digest = Digest32::of_bytes(&bytes);\n        self.persisted.push(digest);\n        Ok(digest)\n    }\n}",
        "        let digest = Digest32::of_bytes(&bytes);\n        self.persisted.push(digest);\n        self.committed = Some((\n            execution_digest,\n            decision.decision.evidence_digest,\n            digest,\n        ));\n        if self.indeterminate_once {\n            self.indeterminate_once = false;\n            return Err(ProductEvidenceSinkErrorV1::Indeterminate);\n        }\n        Ok(digest)\n    }\n\n    fn reconcile(\n        &mut self,\n        execution_digest: Digest32,\n        decision: &SignedEvaluationDecisionV1,\n    ) -> Result<Option<Digest32>, ProductEvidenceSinkErrorV1> {\n        Ok(self.committed.and_then(|(execution, evidence, publication)| {\n            (execution == execution_digest\n                && evidence == decision.decision.evidence_digest)\n                .then_some(publication)\n        }))\n    }\n}\n\n#[derive(Default)]\nstruct RecordingAttempts(Vec<ProductEvaluationAttemptStageV1>);\nimpl ProductEvaluationAttemptSinkV1 for RecordingAttempts {\n    fn record(\n        &mut self,\n        event: &ProductEvaluationAttemptEventV1,\n    ) -> Result<Digest32, ProductEvaluationAttemptSinkErrorV1> {\n        self.0.push(event.stage);\n        Ok(Digest32::of_bytes(format!(\"{:?}\", event).as_bytes()))\n    }\n}",
    )
    replace_once(
        "codex-rs/hepta-intelligence-eval/src/product_runner_tests.rs",
        "    let temporal = match runner.evaluate_temporal_comparison(\n        &frozen,\n        &fixture.candidate_plan,\n        &fixture.baseline_plan,\n        &mut fixture.provider,\n    ) {",
        "    let mut attempts = RecordingAttempts::default();\n    let temporal = match runner.evaluate_temporal_comparison_recorded(\n        &frozen,\n        &fixture.candidate_plan,\n        &fixture.baseline_plan,\n        &mut fixture.provider,\n        &mut attempts,\n    ) {",
    )
    replace_once(
        "codex-rs/hepta-intelligence-eval/src/product_runner_tests.rs",
        "    assert_eq!(fixture.provider.release_count, 1);",
        "    assert_eq!(fixture.provider.release_count, 1);\n    assert!(attempts\n        .0\n        .contains(&ProductEvaluationAttemptStageV1::HoldoutConsumed));\n    assert_eq!(\n        attempts.0.last(),\n        Some(&ProductEvaluationAttemptStageV1::ComparisonSealed)\n    );",
    )
    replace_once(
        "codex-rs/hepta-intelligence-eval/src/product_runner_tests.rs",
        "    assert!(!qualified.authority.grants_any());\n\n    let mut changed_generator = qualified;",
        "    assert!(!qualified.authority.grants_any());\n\n    let mut uncertain_sink = Sink {\n        indeterminate_once: true,\n        ..Sink::default()\n    };\n    let reconciled = runner\n        .qualify_and_persist(\n            &temporal,\n            &context,\n            &evidence,\n            ProductTimingEvidenceV1::Qualification,\n            &verifier,\n            50,\n            &mut uncertain_sink,\n        )\n        .unwrap_or_else(|error| panic!(\"reconciled qualification: {error}\"));\n    assert!(!reconciled.publication_digest.is_zero());\n\n    let mut changed_generator = qualified;",
    )


def patch_workflow() -> None:
    path = ".github/workflows/hepta-lane-e-gap-closure.yml"
    text = read(path)
    marker = "      - name: Evaluator line coverage threshold\n"
    step = r'''      - name: Fault-injected durability and capacity closure
        shell: bash
        run: |
          set -euo pipefail
          mkdir -p .hepta-evidence/learning-eval
          (
            cd codex-rs
            just test --locked -p codex-hepta-intelligence-eval qualification_sink_file --test-threads=1
            just test --locked -p codex-hepta-intelligence-eval attempt_journal --test-threads=1
            HEPTA_LEARNING_EVAL_CAPACITY_REPORT=../.hepta-evidence/learning-eval/capacity.json \
              just test --locked -p codex-hepta-intelligence-eval \
              checkpoint_compacts_fence_history_and_emits_capacity_measurement \
              --test-threads=1
          ) 2>&1 | tee -a .hepta-evidence/learning-eval/stress.log
          python3 - <<'PY'
          import json
          from pathlib import Path
          path = Path('.hepta-evidence/learning-eval/stress.json')
          value = json.loads(path.read_text(encoding='utf-8'))
          value['faultInjectionSuitesPassed'] = 3
          value['capacityReport'] = '.hepta-evidence/learning-eval/capacity.json'
          path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')
          PY

'''
    if "Fault-injected durability and capacity closure" not in text:
        count = text.count(marker)
        if count != 1:
            raise RuntimeError(f"{path}: expected one coverage marker, found {count}")
        text = text.replace(marker, step + marker, 1)
    verify_marker = "          python3 scripts/hepta-lane-e-closure.py verify\n"
    status_line = "          python3 scripts/hepta-learning-eval-status.py verify\n"
    if status_line.strip() not in text:
        text = text.replace(verify_marker, verify_marker + status_line)
    write(path, text)


def patch_evidence() -> None:
    path = "scripts/hepta-learning-eval-evidence.py"
    text = read(path)
    if '"capacity": output_digest(args.capacity),' not in text:
        text = text.replace(
            '            "runtime": output_digest(args.runtime_log),\n',
            '            "runtime": output_digest(args.runtime_log),\n            "capacity": output_digest(args.capacity),\n',
            1,
        )
        text = text.replace(
            '            ("runtime", args.runtime_log),\n',
            '            ("runtime", args.runtime_log),\n            ("capacity", args.capacity),\n',
            1,
        )
        text = text.replace(
            '    emit_parser.add_argument("--runtime-log")\n',
            '    emit_parser.add_argument("--runtime-log")\n    emit_parser.add_argument("--capacity")\n',
            1,
        )
    write(path, text)

    workflow = ".github/workflows/hepta-lane-e-gap-closure.yml"
    text = read(workflow)
    if "--capacity .hepta-evidence/learning-eval/capacity.json" not in text:
        text = text.replace(
            "            --runtime-log .hepta-evidence/learning-eval/runtime-e2e.log \\\n",
            "            --runtime-log .hepta-evidence/learning-eval/runtime-e2e.log \\\n            --capacity .hepta-evidence/learning-eval/capacity.json \\\n",
        )
    write(workflow, text)


def patch_status_and_docs() -> None:
    write("scripts/hepta-learning-eval-status.py", STATUS_SCRIPT)
    write(
        "docs/modules/learning.eval/TARGET_HOST_EVIDENCE_SCHEMA.json",
        json.dumps(TARGET_HOST_SCHEMA, indent=2, sort_keys=True) + "\n",
    )
    write("docs/modules/learning.eval/TARGET_HOST_QUALIFICATION.md", TARGET_HOST_DOC)
    append_once(
        "codex-rs/hepta-intelligence-eval/PRODUCTION_CONTRACT.md",
        "## Publication reconciliation and attempt journaling",
        r'''## Publication reconciliation and attempt journaling

A production qualification sink implements idempotent `persist` and exact
`reconcile`. If a commit may have succeeded but its acknowledgement was lost,
the runner accepts success only after reconciliation returns the publication
digest for the same execution and decision bindings. A missing or conflicting
record remains `Indeterminate` or rejected; blind retry is forbidden.

Production temporal evaluation uses
`evaluate_temporal_comparison_recorded` with a durable
`ProductEvaluationAttemptSinkV1`. Once the final holdout is consumed, every
release, estimator and sealing outcome is journaled. A failure becomes a terminal
attempt event and cannot be confused with an unused holdout. The compatibility
wrapper with the no-op sink is not a target-host production receipt.

`LockedFileFinalHoldoutCasStoreV1::checkpoint_to` rewrites current semantic
state into a compact fresh log while preserving the exact state digest and
anti-rollback anchor. Installation of the checkpoint remains a host-owned atomic
filesystem operation.
''',
    )
    append_once(
        "docs/modules/learning.eval/TECHNICAL.md",
        "### Durable publication, attempt state and compaction",
        r'''### Durable publication, attempt state and compaction

The repository supplies a locked-file idempotent qualification sink with exact
accepted-or-unknown reconciliation, plus a checksum-chained evaluation-attempt
journal. The production runner records final-holdout consumption before provider
release and records terminal failure after any downstream error. A checkpoint
operation preserves the exact final-holdout state digest while compacting
superseded fence history. CI runs injected unknown-commit, replay, rollback,
cross-process locking and checkpoint/recovery cases and emits a measured capacity
report for the exact candidate.

`CURRENT_STATUS.json` and `CURRENT_STATUS.md` are generated from source and the
implementation map. They deliberately leave exact-head qualification and every
external evidence gate unresolved until the corresponding signed artifact exists.
''',
    )
    append_once(
        "qualification/module-execution-dossiers/detail/learning.eval.md",
        "## 11. Durability convergence",
        r'''## 11. Durability convergence

The source candidate includes an idempotent locked-file qualification sink,
accepted-but-unknown reconciliation, a durable attempt journal beginning before
final-holdout consumption, and state-preserving CAS checkpoint compaction. The
Lane E workflow executes injected failure/recovery cases and emits the candidate's
capacity measurements. These source facts do not qualify an unnamed target host
or provide real future-calendar, privacy, independent acceptance or release
evidence.
''',
    )


def patch_map() -> None:
    path = ROOT / "docs/modules/learning.eval/IMPLEMENTATION_MAP.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    operations = data.setdefault("operations", [])
    additions = [
        {
            "operation": "LockedFileQualificationEvidenceSinkV1",
            "nativeSymbol": "LockedFileQualificationEvidenceSinkV1",
            "sourcePath": "codex-rs/hepta-intelligence-eval/src/qualification_sink_file.rs",
            "state": "source_idempotent_reconcilable_sink_implemented",
            "authority": "deny_all",
            "tests": ["codex-rs/hepta-intelligence-eval/src/qualification_sink_file.rs"],
            "sourcePathExists": True,
            "designOperation": "qualification_publication_reconciliation",
            "mappingClass": "owner_native",
            "delegatedCallees": [],
        },
        {
            "operation": "LockedFileProductEvaluationAttemptJournalV1",
            "nativeSymbol": "LockedFileProductEvaluationAttemptJournalV1",
            "sourcePath": "codex-rs/hepta-intelligence-eval/src/attempt_journal.rs",
            "state": "source_durable_attempt_journal_implemented",
            "authority": "deny_all",
            "tests": ["codex-rs/hepta-intelligence-eval/src/attempt_journal.rs"],
            "sourcePathExists": True,
            "designOperation": "evaluation_attempt_recovery",
            "mappingClass": "owner_native",
            "delegatedCallees": [],
        },
        {
            "operation": "LockedFileFinalHoldoutCasStoreV1::checkpoint_to",
            "nativeSymbol": "LockedFileFinalHoldoutCasStoreV1::checkpoint_to",
            "sourcePath": "codex-rs/hepta-intelligence-eval/src/fenced_holdout_file.rs",
            "state": "source_state_preserving_checkpoint_implemented",
            "authority": "deny_all",
            "tests": ["codex-rs/hepta-intelligence-eval/src/fenced_holdout_file_tests.rs"],
            "sourcePathExists": True,
            "designOperation": "final_holdout_checkpoint_compaction",
            "mappingClass": "owner_native",
            "delegatedCallees": [],
        },
    ]
    existing = {item.get("operation") for item in operations}
    for item in additions:
        if item["operation"] not in existing:
            operations.append(item)
    boundary = data.setdefault("claimBoundary", {})
    boundary["idempotentQualificationReconciliation"] = True
    boundary["durableEvaluationAttemptJournal"] = True
    boundary["statePreservingCheckpointCompaction"] = True
    boundary["generatedCurrentStatus"] = True
    data["generatedCurrentStatus"] = {
        "json": "docs/modules/learning.eval/CURRENT_STATUS.json",
        "markdown": "docs/modules/learning.eval/CURRENT_STATUS.md",
        "generator": "scripts/hepta-learning-eval-status.py",
    }
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def main() -> None:
    if not (ROOT / "codex-rs/hepta-intelligence-eval/src/signed_admission.rs").is_file():
        raise RuntimeError("apply P0 learning.eval patch before P1/P2")
    write("codex-rs/hepta-intelligence-eval/src/qualification_sink_file.rs", QUALIFICATION_SINK)
    write("codex-rs/hepta-intelligence-eval/src/attempt_journal.rs", ATTEMPT_JOURNAL)
    patch_lib()
    patch_product_runner()
    patch_checkpoint()
    patch_tests()
    patch_workflow()
    patch_evidence()
    patch_status_and_docs()
    patch_map()
    import subprocess
    subprocess.run(
        ["python3", "scripts/hepta-learning-eval-status.py", "write"],
        cwd=ROOT,
        check=True,
    )


if __name__ == "__main__":
    main()
