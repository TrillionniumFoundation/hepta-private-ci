// Crash-safe segmented storage for the external evidence frontier journal.
//
// The predecessor adapter stores one bounded JSONL file. This successor keeps
// that file as the active tail for wire compatibility, but automatically seals
// bounded immutable segments and links them through self-authenticating metadata.
// A small atomic latest index makes startup and CAS independent of lifetime
// history size. The index is a cache/pointer, never a replacement for the
// segment/record digest chains; stale indexes are reconstructed from the active
// tail and the latest sealed segment.

use std::collections::BTreeSet;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use super::EvidenceFrontierAuditRecordV1;
use super::LockedFileEvidenceFrontierBackend as LegacyLockedFileEvidenceFrontierBackend;
use super::audit_record_sha256;
use super::open_existing_journal;
use super::open_pinned_directory;
use super::open_writable_journal;
use super::read_private_regular_file;
use super::unavailable;
use super::validate_journal_metadata;
use crate::EvidenceFrontierBackend;
use crate::EvidenceFrontierBackendError;
use crate::EvidenceFrontierBackendIdentityV1;
use crate::EvidenceFrontierDurableAckV1;
use crate::EvidenceFrontierHistoryRangeV1;
use crate::EvidenceRecoveryFrontierV2;
use crate::evidence_recovery_frontier_v2_sha256;
use crate::frontier_backend::EVIDENCE_FRONTIER_AUDIT_RECORD_SCHEMA_VERSION;
use crate::frontier_backend::EVIDENCE_FRONTIER_MAX_AUDIT_RECORD_BYTES;
use crate::frontier_backend::EVIDENCE_FRONTIER_MAX_AUDIT_RECORDS;
use crate::frontier_backend::EVIDENCE_FRONTIER_MAX_JOURNAL_BYTES;

const SEGMENT_METADATA_SCHEMA_VERSION: u32 = 1;
const LATEST_INDEX_SCHEMA_VERSION: u32 = 1;
const MAX_INDEX_BYTES: u64 = 1024 * 1024;
const MAX_SEGMENT_METADATA_BYTES: u64 = 512 * 1024;
const MAX_SEGMENT_ANCESTORS: usize = 64;
const MAX_SEGMENT_COUNT_ALERT: u64 = 1_000_000;

#[cfg(not(test))]
const ACTIVE_SEGMENT_MAX_RECORDS: usize = 1024;
#[cfg(test)]
const ACTIVE_SEGMENT_MAX_RECORDS: usize = 4;

const ACTIVE_SEGMENT_MAX_BYTES: u64 = 16 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceFrontierCapacityAlertV1 {
    Healthy,
    ActiveNearRollover,
    SegmentCountElevated,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceFrontierCapacityV1 {
    pub schema_version: u32,
    pub store_id: String,
    pub latest_generation: Option<u64>,
    pub segment_count: u64,
    pub archived_records: u64,
    pub archived_bytes: u64,
    pub active_records: u64,
    pub active_bytes: u64,
    pub active_record_limit: u64,
    pub active_byte_limit: u64,
    pub active_record_headroom: u64,
    pub active_byte_headroom: u64,
    pub alert: EvidenceFrontierCapacityAlertV1,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidenceFrontierSegmentPointerV1 {
    metadata_file_name: String,
    metadata_file_sha256: Sha256Digest,
    first_audit_sequence: u64,
    last_audit_sequence: u64,
    first_generation: u64,
    last_generation: u64,
    last_record_sha256: Sha256Digest,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidenceFrontierSegmentMetadataV1 {
    schema_version: u32,
    backend_id: String,
    backend_identity_sha256: Sha256Digest,
    store_id: String,
    segment_file_name: String,
    segment_file_sha256: Sha256Digest,
    segment_bytes: u64,
    first_audit_sequence: u64,
    last_audit_sequence: u64,
    first_generation: u64,
    last_generation: u64,
    previous_record_sha256: Option<Sha256Digest>,
    last_record_sha256: Sha256Digest,
    previous_segment: Option<EvidenceFrontierSegmentPointerV1>,
    ancestors: Vec<EvidenceFrontierSegmentPointerV1>,
    metadata_sha256: Sha256Digest,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct EvidenceFrontierSegmentMetadataPayloadV1<'a> {
    schema_version: u32,
    backend_id: &'a str,
    backend_identity_sha256: &'a Sha256Digest,
    store_id: &'a str,
    segment_file_name: &'a str,
    segment_file_sha256: &'a Sha256Digest,
    segment_bytes: u64,
    first_audit_sequence: u64,
    last_audit_sequence: u64,
    first_generation: u64,
    last_generation: u64,
    previous_record_sha256: Option<&'a Sha256Digest>,
    last_record_sha256: &'a Sha256Digest,
    previous_segment: Option<&'a EvidenceFrontierSegmentPointerV1>,
    ancestors: &'a [EvidenceFrontierSegmentPointerV1],
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidenceFrontierLatestIndexV1 {
    schema_version: u32,
    backend_id: String,
    backend_identity_sha256: Sha256Digest,
    store_id: String,
    segment_count: u64,
    archived_records: u64,
    archived_bytes: u64,
    latest_segment: Option<EvidenceFrontierSegmentPointerV1>,
    active_journal_bytes: u64,
    active_journal_sha256: Sha256Digest,
    audit_sequence: u64,
    frontier_generation: u64,
    frontier_sha256: Sha256Digest,
    record_sha256: Sha256Digest,
    frontier: EvidenceRecoveryFrontierV2,
    index_sha256: Sha256Digest,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct EvidenceFrontierLatestIndexPayloadV1<'a> {
    schema_version: u32,
    backend_id: &'a str,
    backend_identity_sha256: &'a Sha256Digest,
    store_id: &'a str,
    segment_count: u64,
    archived_records: u64,
    archived_bytes: u64,
    latest_segment: Option<&'a EvidenceFrontierSegmentPointerV1>,
    active_journal_bytes: u64,
    active_journal_sha256: &'a Sha256Digest,
    audit_sequence: u64,
    frontier_generation: u64,
    frontier_sha256: &'a Sha256Digest,
    record_sha256: &'a Sha256Digest,
    frontier: &'a EvidenceRecoveryFrontierV2,
}

#[derive(Clone, Debug)]
struct ChainCursor {
    next_audit_sequence: u64,
    previous_generation: Option<u64>,
    previous_record_sha256: Option<Sha256Digest>,
    previous_frontier: Option<EvidenceRecoveryFrontierV2>,
}

impl ChainCursor {
    fn initial() -> Self {
        Self {
            next_audit_sequence: 1,
            previous_generation: None,
            previous_record_sha256: None,
            previous_frontier: None,
        }
    }

    fn after_record(
        record: &EvidenceFrontierAuditRecordV1,
    ) -> Result<Self, EvidenceFrontierBackendError> {
        Ok(Self {
            next_audit_sequence: record
                .audit_sequence
                .checked_add(1)
                .ok_or_else(|| invalid("frontier audit sequence exhausted"))?,
            previous_generation: Some(record.frontier.frontier_generation),
            previous_record_sha256: Some(record.record_sha256.clone()),
            previous_frontier: Some(record.frontier.clone()),
        })
    }

    fn advance(
        &mut self,
        record: &EvidenceFrontierAuditRecordV1,
    ) -> Result<(), EvidenceFrontierBackendError> {
        self.next_audit_sequence = self
            .next_audit_sequence
            .checked_add(1)
            .ok_or_else(|| corrupt("frontier audit sequence overflow"))?;
        self.previous_generation = Some(record.frontier.frontier_generation);
        self.previous_record_sha256 = Some(record.record_sha256.clone());
        self.previous_frontier = Some(record.frontier.clone());
        Ok(())
    }
}

struct StorePaths {
    token: String,
    active: PathBuf,
    lock: PathBuf,
    index: PathBuf,
}

struct RecoveredPublication {
    frontier_sha256: Sha256Digest,
    audit_sequence: u64,
    durable_path: PathBuf,
}

struct VerifiedArchivedHistory {
    latest_metadata: EvidenceFrontierSegmentMetadataV1,
    latest_record: EvidenceFrontierAuditRecordV1,
    segment_count: u64,
    archived_records: u64,
    archived_bytes: u64,
}

struct SegmentedState {
    index: Option<EvidenceFrontierLatestIndexV1>,
    latest_segment_metadata: Option<EvidenceFrontierSegmentMetadataV1>,
    active_records: Vec<EvidenceFrontierAuditRecordV1>,
    active_bytes: u64,
    active_sha256: Sha256Digest,
}

impl SegmentedState {
    fn latest_record(&self) -> Option<&EvidenceFrontierAuditRecordV1> {
        self.active_records.last()
    }

    fn latest_generation(&self) -> Option<u64> {
        self.latest_record()
            .map(|record| record.frontier.frontier_generation)
            .or_else(|| self.index.as_ref().map(|index| index.frontier_generation))
    }

    fn latest_audit_sequence(&self) -> u64 {
        self.latest_record()
            .map(|record| record.audit_sequence)
            .or_else(|| self.index.as_ref().map(|index| index.audit_sequence))
            .unwrap_or(0)
    }

    fn latest_record_sha256(&self) -> Option<Sha256Digest> {
        self.latest_record()
            .map(|record| record.record_sha256.clone())
            .or_else(|| self.index.as_ref().map(|index| index.record_sha256.clone()))
    }

    fn latest_frontier(&self) -> Option<EvidenceRecoveryFrontierV2> {
        self.latest_record()
            .map(|record| record.frontier.clone())
            .or_else(|| self.index.as_ref().map(|index| index.frontier.clone()))
    }

    fn segment_count(&self) -> u64 {
        self.index.as_ref().map_or(0, |index| index.segment_count)
    }

    fn archived_records(&self) -> u64 {
        self.index.as_ref().map_or(0, |index| index.archived_records)
    }

    fn archived_bytes(&self) -> u64 {
        self.index.as_ref().map_or(0, |index| index.archived_bytes)
    }

    fn latest_segment(&self) -> Option<&EvidenceFrontierSegmentPointerV1> {
        self.index
            .as_ref()
            .and_then(|index| index.latest_segment.as_ref())
    }
}

/// Production successor for the original single-file backend.
///
/// Existing `<store>.jsonl` journals remain the active tail and are migrated in
/// place on the first automatic rollover. New writes use one dedicated lock,
/// immutable linked segment files and an atomic latest index. No history is
/// deleted and no operator has to clear a full journal to continue publishing.
pub struct SegmentedFileEvidenceFrontierBackend {
    legacy: LegacyLockedFileEvidenceFrontierBackend,
}
