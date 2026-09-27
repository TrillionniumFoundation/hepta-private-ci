//! Owner-local durable planning decisions. Publication requires both file
//! durability and a pinned, external signed checkpoint. This store owns planner
//! decisions and observed receipt projections, never another owner's effects.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use ed25519_dalek::VerifyingKey;

use crate::PlannerCheckpointAnchorV1;
use crate::PlannerCheckpointV1;
use crate::PlannerDecisionEnvelopeV1;
use crate::PlannerJournalKindV1;
use crate::PlannerJournalV1;
use crate::SignedPlannerCheckpointV1;

#[path = "planner_store_codec.rs"]
mod codec;
#[path = "planner_store_fs.rs"]
mod disk;

#[derive(Clone, Debug)]
pub struct PlannerStoreOptionsV1 {
    pub maximum_records: usize,
    pub maximum_bytes: u64,
    pub maximum_segments: usize,
    pub rotate_after_bytes: u64,
}

impl Default for PlannerStoreOptionsV1 {
    fn default() -> Self {
        Self {
            maximum_records: 4096,
            maximum_bytes: 128 * 1024 * 1024,
            maximum_segments: 32,
            rotate_after_bytes: 4 * 1024 * 1024,
        }
    }
}

impl PlannerStoreOptionsV1 {
    fn validate(&self) -> Result<(), PlannerStoreError> {
        if !(1..=4096).contains(&self.maximum_records)
            || !(1024..=128 * 1024 * 1024).contains(&self.maximum_bytes)
            || !(1..=32).contains(&self.maximum_segments)
            || !(1024..=8 * 1024 * 1024).contains(&self.rotate_after_bytes)
            || self.rotate_after_bytes > self.maximum_bytes
        {
            return Err(PlannerStoreError::LimitExceeded);
        }
        Ok(())
    }
}

#[derive(Debug)]
pub enum PlannerStoreError {
    Io(std::io::Error),
    Locked,
    UnsafePermissions,
    Corrupt,
    UnsupportedSchema,
    LimitExceeded,
    IdentityConflict,
    InvalidTransition,
    MissingDecisionBody,
    AnchorUnavailable,
    InvalidAnchorSignature,
    StaleAnchor,
    Rollback,
    Retired,
    Poisoned,
    #[cfg(test)]
    InjectedFailure,
}

impl fmt::Display for PlannerStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for PlannerStoreError {}

impl From<std::io::Error> for PlannerStoreError {
    fn from(error: std::io::Error) -> Self {
        Self::Io(error)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlannerStoredRecordKindV1 {
    Decision,
    SelectedPlan,
    Revocation,
    OwnerObservation,
    LegacySourceArchive,
}

type RecordKind = PlannerStoredRecordKindV1;

impl RecordKind {
    fn tag(self) -> u8 {
        match self {
            Self::Decision => 0,
            Self::SelectedPlan => 1,
            Self::Revocation => 2,
            Self::OwnerObservation => 3,
            Self::LegacySourceArchive => 4,
        }
    }

    fn from_tag(value: u8) -> Result<Self, PlannerStoreError> {
        match value {
            0 => Ok(Self::Decision),
            1 => Ok(Self::SelectedPlan),
            2 => Ok(Self::Revocation),
            3 => Ok(Self::OwnerObservation),
            4 => Ok(Self::LegacySourceArchive),
            _ => Err(PlannerStoreError::UnsupportedSchema),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerStoredRecordV1 {
    sequence: u64,
    kind: RecordKind,
    identity: Digest32,
    target: Digest32,
    predecessor: Digest32,
    body: Vec<u8>,
    digest: Digest32,
}

type Entry = PlannerStoredRecordV1;

impl PlannerStoredRecordV1 {
    #[must_use]
    pub const fn sequence(&self) -> u64 { self.sequence }
    #[must_use]
    pub const fn kind(&self) -> PlannerStoredRecordKindV1 { self.kind }
    #[must_use]
    pub const fn identity(&self) -> Digest32 { self.identity }
    #[must_use]
    pub const fn target(&self) -> Digest32 { self.target }
    #[must_use]
    pub const fn digest(&self) -> Digest32 { self.digest }
    #[must_use]
    pub fn body(&self) -> &[u8] { &self.body }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerAppendReceiptV1 {
    pub record_sequence: u64,
    pub record_digest: Digest32,
    pub checkpoint: SignedPlannerCheckpointV1,
    pub idempotent: bool,
}

pub struct PlannerStoreV1 {
    files: disk::StoreFiles,
    entries: Vec<Entry>,
    checkpoint: SignedPlannerCheckpointV1,
    pinned_key: VerifyingKey,
    anchor: Box<dyn PlannerCheckpointAnchorV1>,
    options: PlannerStoreOptionsV1,
    poisoned: bool,
    recovered_tail_digest: Option<Digest32>,
    #[cfg(test)]
    fault: Option<TestFault>,
}

impl fmt::Debug for PlannerStoreV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.debug_struct("PlannerStoreV1")
            .field("checkpoint", &self.checkpoint.checkpoint)
            .field("record_count", &self.entries.len())
            .field("poisoned", &self.poisoned)
            .finish_non_exhaustive()
    }
}

impl PlannerStoreV1 {
    pub fn open(
        root: &Path,
        store_id: Digest32,
        pinned_key: VerifyingKey,
        mut anchor: Box<dyn PlannerCheckpointAnchorV1>,
        options: PlannerStoreOptionsV1,
    ) -> Result<Self, PlannerStoreError> {
        options.validate()?;
        if store_id.is_zero() || !root.is_absolute() {
            return Err(PlannerStoreError::Corrupt);
        }
        let current = anchor.load(store_id).map_err(|_| PlannerStoreError::AnchorUnavailable)?;
        if let Some(current) = &current {
            validate_signed(current, &pinned_key, store_id)?;
        }
        let initialize = current.as_ref().is_none_or(|value| value.checkpoint.sequence == 0);
        let mut files = disk::StoreFiles::open(root, store_id, initialize)?;
        let mut loaded = files.load(&options)?;
        let genesis = codec::Header::genesis(store_id);
        let current = match current {
            Some(current) => current,
            None => {
                if !loaded.entries.is_empty() || files.header.base_sequence != 0 {
                    return Err(PlannerStoreError::Rollback);
                }
                let next = PlannerCheckpointV1 {
                    store_id, sequence: 0, head_digest: genesis.base_head, retired: false,
                };
                let signed = anchor.compare_exchange(None, next)
                    .map_err(|_| PlannerStoreError::AnchorUnavailable)?;
                validate_signed(&signed, &pinned_key, store_id)?;
                if signed.checkpoint != next {
                    return Err(PlannerStoreError::StaleAnchor);
                }
                signed
            }
        };
        let target = current.checkpoint;
        let available = loaded.entries.last().map_or(0, |entry| entry.sequence);
        if target.sequence > available || target.sequence < files.header.base_sequence {
            return Err(PlannerStoreError::Rollback);
        }
        let target_index = usize::try_from(target.sequence).map_err(|_| PlannerStoreError::LimitExceeded)?;
        let head = if target_index == 0 {
            genesis.base_head
        } else {
            loaded.entries.get(target_index - 1).ok_or(PlannerStoreError::Rollback)?.digest
        };
        if head != target.head_digest {
            return Err(PlannerStoreError::Rollback);
        }
        loaded.entries.truncate(target_index);
        replay(&loaded.entries)?;
        let cut = if target.sequence == files.header.base_sequence {
            codec::HEADER_BYTES
        } else {
            loaded.active_frame_ends.iter()
                .find(|(sequence, _)| *sequence == target.sequence)
                .map(|(_, end)| *end)
                .ok_or(PlannerStoreError::Rollback)?
        };
        if cut > loaded.complete_active_bytes || cut > loaded.active_bytes {
            return Err(PlannerStoreError::Corrupt);
        }
        let recovered_tail_digest = files.recover_prefix(cut, &options)?;
        Ok(Self {
            files,
            entries: loaded.entries,
            checkpoint: current,
            pinned_key,
            anchor,
            options,
            poisoned: false,
            recovered_tail_digest,
            #[cfg(test)]
            fault: None,
        })
    }

    /// Archival projections only. Callers must not interpret cached records as
    /// fresh authority or a successful external effect.
    #[must_use]
    pub fn records(&self) -> &[PlannerStoredRecordV1] { &self.entries }

    #[must_use]
    pub fn checkpoint(&self) -> &SignedPlannerCheckpointV1 { &self.checkpoint }

    #[must_use]
    pub const fn recovered_tail_digest(&self) -> Option<Digest32> { self.recovered_tail_digest }

    pub fn selected_plan_digest(&mut self) -> Result<Option<Digest32>, PlannerStoreError> {
        self.ensure_current()?;
        Ok(replay(&self.entries)?.selected)
    }

    pub fn record_decision(
        &mut self,
        identity: Digest32,
        envelope: &PlannerDecisionEnvelopeV1,
    ) -> Result<PlannerAppendReceiptV1, PlannerStoreError> {
        self.append(RecordKind::Decision, identity, envelope.receipt_digest(), envelope.canonical_bytes().to_vec())
    }

    pub fn select_plan(
        &mut self,
        identity: Digest32,
        decision: Digest32,
    ) -> Result<PlannerAppendReceiptV1, PlannerStoreError> {
        self.append(RecordKind::SelectedPlan, identity, decision, Vec::new())
    }

    pub fn revoke_plan(
        &mut self,
        identity: Digest32,
        decision: Digest32,
    ) -> Result<PlannerAppendReceiptV1, PlannerStoreError> {
        self.append(RecordKind::Revocation, identity, decision, Vec::new())
    }

    /// Preserve a downstream owner's receipt bytes without adopting authority
    /// over their truth. A product consumer separately verifies that owner.
    pub fn record_owner_observation(
        &mut self,
        identity: Digest32,
        decision: Digest32,
        canonical_receipt: &[u8],
    ) -> Result<PlannerAppendReceiptV1, PlannerStoreError> {
        if canonical_receipt.is_empty() || canonical_receipt.len() > crate::MAX_PLANNER_ENVELOPE_BYTES {
            return Err(PlannerStoreError::LimitExceeded);
        }
        self.append(RecordKind::OwnerObservation, identity, decision, canonical_receipt.to_vec())
    }

    fn append(
        &mut self,
        kind: RecordKind,
        identity: Digest32,
        target: Digest32,
        body: Vec<u8>,
    ) -> Result<PlannerAppendReceiptV1, PlannerStoreError> {
        self.ensure_current()?;
        if let Some(existing) = self.entries.iter().find(|entry| entry.identity == identity) {
            return if existing.kind == kind && existing.target == target && existing.body == body {
                Ok(PlannerAppendReceiptV1 {
                    record_sequence: existing.sequence,
                    record_digest: existing.digest,
                    checkpoint: self.checkpoint.clone(),
                    idempotent: true,
                })
            } else {
                Err(PlannerStoreError::IdentityConflict)
            };
        }
        if self.entries.len() >= self.options.maximum_records {
            return Err(PlannerStoreError::LimitExceeded);
        }
        let sequence = self.checkpoint.checkpoint.sequence.checked_add(1)
            .ok_or(PlannerStoreError::LimitExceeded)?;
        let entry = codec::make_entry(
            self.checkpoint.checkpoint.store_id, sequence, kind, identity, target,
            self.checkpoint.checkpoint.head_digest, body,
        )?;
        let mut prospective = self.entries.clone();
        prospective.push(entry.clone());
        replay(&prospective)?;
        let frame = codec::encode_entry(self.checkpoint.checkpoint.store_id, &entry)?;
        if self.files.active.metadata()?.len() + frame.len() as u64 > self.options.rotate_after_bytes {
            self.compact()?;
        }
        self.files.check_capacity(&self.options, frame.len(), false)?;
        #[cfg(test)]
        if self.fault == Some(TestFault::PartialAppend) {
            use std::io::Seek;
            use std::io::SeekFrom;
            use std::io::Write;
            self.files.active.seek(SeekFrom::End(0))?;
            self.files.active.write_all(&frame[..frame.len() / 2])?;
            self.files.active.sync_all()?;
            self.poisoned = true;
            return Err(PlannerStoreError::InjectedFailure);
        }
        if let Err(error) = self.files.append_and_sync(&frame) {
            self.poisoned = true;
            return Err(error);
        }
        #[cfg(test)]
        if self.fault == Some(TestFault::AfterFileSync) {
            self.poisoned = true;
            return Err(PlannerStoreError::InjectedFailure);
        }
        let next = PlannerCheckpointV1 {
            store_id: self.checkpoint.checkpoint.store_id,
            sequence,
            head_digest: entry.digest,
            retired: false,
        };
        let signed = self.publish_checkpoint(next)?;
        #[cfg(test)]
        if self.fault == Some(TestFault::AfterAnchor) {
            self.poisoned = true;
            return Err(PlannerStoreError::InjectedFailure);
        }
        self.entries = prospective;
        self.checkpoint = signed.clone();
        Ok(PlannerAppendReceiptV1 {
            record_sequence: sequence, record_digest: entry.digest,
            checkpoint: signed, idempotent: false,
        })
    }

    fn ensure_current(&mut self) -> Result<(), PlannerStoreError> {
        if self.poisoned {
            return Err(PlannerStoreError::Poisoned);
        }
        let current = self.anchor.load(self.checkpoint.checkpoint.store_id)
            .map_err(|_| PlannerStoreError::AnchorUnavailable)?
            .ok_or(PlannerStoreError::StaleAnchor)?;
        validate_signed(&current, &self.pinned_key, self.checkpoint.checkpoint.store_id)?;
        if current.checkpoint != self.checkpoint.checkpoint {
            self.poisoned = true;
            return Err(PlannerStoreError::StaleAnchor);
        }
        Ok(())
    }

    fn publish_checkpoint(
        &mut self,
        next: PlannerCheckpointV1,
    ) -> Result<SignedPlannerCheckpointV1, PlannerStoreError> {
        let result = self.anchor.compare_exchange(Some(self.checkpoint.checkpoint), next)
            .map_err(|_| PlannerStoreError::AnchorUnavailable)
            .and_then(|signed| {
                validate_signed(&signed, &self.pinned_key, next.store_id)?;
                if signed.checkpoint != next {
                    return Err(PlannerStoreError::StaleAnchor);
                }
                Ok(signed)
            });
        if result.is_err() {
            self.poisoned = true;
        }
        result
    }

    /// Rotate the active log into a content-addressed immutable segment. No
    /// identities or revocations are discarded. Quotas enforce retention and
    /// backpressure instead of silently deleting evidence to regain capacity.
    pub fn compact(&mut self) -> Result<(), PlannerStoreError> {
        self.ensure_current()?;
        let loaded = self.files.load(&self.options)?;
        if loaded.entries != self.entries || loaded.complete_active_bytes != loaded.active_bytes {
            self.poisoned = true;
            return Err(PlannerStoreError::Corrupt);
        }
        let result = self.files.compact(
            self.checkpoint.checkpoint.sequence,
            self.checkpoint.checkpoint.head_digest,
            &self.options,
        );
        if result.is_err() {
            self.poisoned = true;
        }
        result
    }

    /// Export a flat, self-contained backup without copying the external anchor
    /// or its signing key. Old backups remain inspectable, never automatically
    /// eligible for restoration over a newer checkpoint.
    pub fn backup_to(&mut self, directory: &Path) -> Result<PathBuf, PlannerStoreError> {
        self.ensure_current()?;
        disk::private_dir(directory)?;
        let bytes = self.flat_bytes(&self.entries)?;
        let current = self.checkpoint.checkpoint;
        let path = directory.join(format!("{}-{}-{}.hcp", current.store_id, current.sequence, current.head_digest));
        disk::atomic_create(&path, &bytes)?;
        Ok(path)
    }

    pub fn restore_to_empty(
        root: &Path,
        backup: &Path,
        store_id: Digest32,
        pinned_key: VerifyingKey,
        mut anchor: Box<dyn PlannerCheckpointAnchorV1>,
        options: PlannerStoreOptionsV1,
    ) -> Result<Self, PlannerStoreError> {
        options.validate()?;
        let signed = anchor.load(store_id).map_err(|_| PlannerStoreError::AnchorUnavailable)?
            .ok_or(PlannerStoreError::Rollback)?;
        validate_signed(&signed, &pinned_key, store_id)?;
        let bytes = disk::read_bounded(backup, options.maximum_bytes)?;
        let decoded = codec::decode_segment(&bytes)?;
        if decoded.header.store_id != store_id || decoded.header.base_sequence != 0
            || decoded.complete_bytes != bytes.len() || decoded.entries.len() > options.maximum_records
        {
            return Err(PlannerStoreError::Corrupt);
        }
        replay(&decoded.entries)?;
        let head = decoded.entries.last().map_or(decoded.header.base_head, |entry| entry.digest);
        if signed.checkpoint.sequence != decoded.entries.len() as u64 || signed.checkpoint.head_digest != head {
            return Err(PlannerStoreError::Rollback);
        }
        if root.join("active.hcp").exists() {
            return Err(PlannerStoreError::IdentityConflict);
        }
        let mut files = disk::StoreFiles::open(root, store_id, true)?;
        if files.active.metadata()?.len() != codec::HEADER_BYTES as u64 {
            return Err(PlannerStoreError::IdentityConflict);
        }
        files.replace_active(&bytes)?;
        drop(files);
        Self::open(root, store_id, pinned_key, anchor, options)
    }

    /// Import the old digest-only reference without fabricating missing bodies.
    /// Its original bytes are retained verbatim; every decision requires a
    /// supplied, previously validated complete envelope. Publication is one CAS.
    pub fn migrate_reference_journal(
        &mut self,
        journal: &PlannerJournalV1,
        bodies: &BTreeMap<Digest32, PlannerDecisionEnvelopeV1>,
    ) -> Result<SignedPlannerCheckpointV1, PlannerStoreError> {
        self.ensure_current()?;
        if !self.entries.is_empty() {
            return Err(PlannerStoreError::InvalidTransition);
        }
        let source = journal.export_bytes();
        PlannerJournalV1::reopen(&source).map_err(|_| PlannerStoreError::Corrupt)?;
        let source_digest = Digest32::of_bytes(&source);
        let mut records = vec![(RecordKind::LegacySourceArchive, source_digest, source_digest, source)];
        for record in journal.entries() {
            match record.kind {
                PlannerJournalKindV1::Snapshot => (), // Retained inside the complete source archive.
                PlannerJournalKindV1::Decision => {
                    let body = bodies.get(&record.payload_digest).ok_or(PlannerStoreError::MissingDecisionBody)?;
                    if body.receipt_digest() != record.payload_digest {
                        return Err(PlannerStoreError::IdentityConflict);
                    }
                    records.push((RecordKind::Decision, record.identity_digest, record.payload_digest, body.canonical_bytes().to_vec()));
                }
                PlannerJournalKindV1::SelectedPlan => records.push((RecordKind::SelectedPlan, record.identity_digest, record.payload_digest, Vec::new())),
                PlannerJournalKindV1::Revocation => records.push((RecordKind::Revocation, record.identity_digest, record.payload_digest, Vec::new())),
            }
        }
        if records.len() > self.options.maximum_records {
            return Err(PlannerStoreError::LimitExceeded);
        }
        let mut entries = Vec::new();
        let mut predecessor = self.checkpoint.checkpoint.head_digest;
        for (kind, identity, target, body) in records {
            let sequence = entries.len() as u64 + 1;
            let entry = codec::make_entry(self.checkpoint.checkpoint.store_id, sequence, kind, identity, target, predecessor, body)?;
            predecessor = entry.digest;
            entries.push(entry);
        }
        if replay(&entries)?.selected != journal.selected_plan_digest() {
            return Err(PlannerStoreError::InvalidTransition);
        }
        let bytes = self.flat_bytes(&entries)?;
        self.files.check_capacity(&self.options, bytes.len(), false)?;
        if let Err(error) = self.files.replace_active(&bytes) {
            self.poisoned = true;
            return Err(error);
        }
        let next = PlannerCheckpointV1 {
            store_id: self.checkpoint.checkpoint.store_id,
            sequence: entries.len() as u64,
            head_digest: predecessor,
            retired: false,
        };
        let signed = self.publish_checkpoint(next)?;
        self.entries = entries;
        self.checkpoint = signed.clone();
        Ok(signed)
    }

    fn flat_bytes(&self, entries: &[Entry]) -> Result<Vec<u8>, PlannerStoreError> {
        let store_id = self.checkpoint.checkpoint.store_id;
        let mut bytes = codec::Header::genesis(store_id).encode();
        for entry in entries {
            let frame = codec::encode_entry(store_id, entry)?;
            if bytes.len() as u64 + frame.len() as u64 > self.options.maximum_bytes {
                return Err(PlannerStoreError::LimitExceeded);
            }
            bytes.extend_from_slice(&frame);
        }
        Ok(bytes)
    }
}

fn validate_signed(
    signed: &SignedPlannerCheckpointV1,
    key: &VerifyingKey,
    store_id: Digest32,
) -> Result<(), PlannerStoreError> {
    if signed.checkpoint.store_id != store_id || !signed.verify(key) {
        return Err(PlannerStoreError::InvalidAnchorSignature);
    }
    if signed.checkpoint.retired {
        return Err(PlannerStoreError::Retired);
    }
    Ok(())
}

struct Projection {
    selected: Option<Digest32>,
}

fn replay(entries: &[Entry]) -> Result<Projection, PlannerStoreError> {
    let mut identities = BTreeSet::new();
    let mut decisions = BTreeSet::new();
    let mut revoked = BTreeSet::new();
    let mut selected = None;
    for entry in entries {
        if !identities.insert(entry.identity) {
            return Err(PlannerStoreError::IdentityConflict);
        }
        match entry.kind {
            RecordKind::Decision => {
                if !PlannerDecisionEnvelopeV1::validate_archive(&entry.body, entry.target) {
                    return Err(PlannerStoreError::Corrupt);
                }
                decisions.insert(entry.target);
            }
            RecordKind::SelectedPlan => {
                if !entry.body.is_empty() || !decisions.contains(&entry.target) || revoked.contains(&entry.target) {
                    return Err(PlannerStoreError::InvalidTransition);
                }
                selected = Some(entry.target);
            }
            RecordKind::Revocation => {
                if !entry.body.is_empty() {
                    return Err(PlannerStoreError::Corrupt);
                }
                revoked.insert(entry.target);
                if selected == Some(entry.target) { selected = None; }
            }
            RecordKind::OwnerObservation => {
                if entry.body.is_empty() || !decisions.contains(&entry.target) {
                    return Err(PlannerStoreError::InvalidTransition);
                }
            }
            RecordKind::LegacySourceArchive => {
                if Digest32::of_bytes(&entry.body) != entry.target {
                    return Err(PlannerStoreError::Corrupt);
                }
                PlannerJournalV1::reopen(&entry.body).map_err(|_| PlannerStoreError::Corrupt)?;
            }
        }
    }
    Ok(Projection { selected })
}

#[cfg(test)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum TestFault { PartialAppend, AfterFileSync, AfterAnchor }

#[cfg(test)]
#[path = "planner_store_tests.rs"]
mod tests;
