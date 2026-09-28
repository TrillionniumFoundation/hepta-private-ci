//! Bounded epoch compaction, lossless archive chaining and retention planning
//! for the NDU projection journal.
//!
//! This module is deliberately separate from `NduProjectionStoreV1`. It supplies
//! a versioned semantic transition candidate without silently changing the V1
//! on-disk format or activating history deletion. Local archive deletion remains
//! an operator action and is admitted only after explicit external-copy, object-
//! version, restore-drill and monotonic-frontier acknowledgements.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;

use crate::projection_journal::NduProjectionEntryV1;
use crate::projection_journal::NduProjectionJournalV1;
use crate::projection_journal::NduProjectionKindV1;

const CHECKPOINT_MAGIC: &[u8; 8] = b"HNDUCP01";
const ARCHIVE_MAGIC: &[u8; 8] = b"HNDUAR01";
const CHECKPOINT_DIGEST_DOMAIN: &[u8] = b"hepta.ndu.projection-checkpoint.v1\0";
const OPERATION_DIGEST_DOMAIN: &[u8] = b"hepta.ndu.projection-operation.v1\0";
const ARCHIVE_TRANSITION_DOMAIN: &[u8] = b"hepta.ndu.projection-archive-transition.v1\0";
const ARCHIVE_CHECKSUM_DOMAIN: &[u8] = b"hepta.ndu.projection-archive-checksum.v1\0";
const ENTRY_DIGEST_DOMAIN: &[u8] = b"hepta.ndu.projection-journal-entry.v1";

const ACTIVE_RECORD_LIMIT: usize = 4096;
const COMPACT_IDENTITY_LIMIT: usize = 65_536;
const STATE_KEY_LIMIT: usize = 65_536;
const MAX_LOCAL_ARCHIVES: u16 = 1024;
const ENTRY_BYTES: usize = 8 + 1 + 32 + 32 + 32 + 32 + 32 + 32;
const REPLAY_RECORD_BYTES: usize = 32 + 8 + 1 + 32 + 32 + 32;
const STATE_KEY_BYTES: usize = 32 + 32 + 32;
const CHECKPOINT_HEADER_BYTES: usize = 8 + 8 + 8 + 32 + 32 + 4 + 4 + 4 + 4;
const CHECKPOINT_TRAILER_BYTES: usize = 32;
const ARCHIVE_HEADER_BYTES: usize = 8 + 8 + 32 + 4 + 4 + 32 + 32;
const ARCHIVE_TRAILER_BYTES: usize = 32;
const MAX_CHECKPOINT_BYTES: usize = CHECKPOINT_HEADER_BYTES
    + COMPACT_IDENTITY_LIMIT * REPLAY_RECORD_BYTES
    + STATE_KEY_LIMIT * STATE_KEY_BYTES * 3
    + CHECKPOINT_TRAILER_BYTES;
const MAX_ARCHIVE_BYTES: usize = ARCHIVE_HEADER_BYTES
    + MAX_CHECKPOINT_BYTES
    + ACTIVE_RECORD_LIMIT * ENTRY_BYTES
    + ARCHIVE_TRAILER_BYTES;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduProjectionEpochError {
    ZeroEpoch,
    EmptyDigest,
    ActiveRecordLimitExceeded,
    IdentityLimitExceeded,
    StateLimitExceeded,
    RevocationCapacityExhausted,
    IdentityConflict,
    DuplicateIdentity,
    ProjectionNotRecorded,
    RevokedProjection,
    SelectionPredecessorMismatch,
    EmptyArchive,
    ArchiveTooLarge,
    CorruptHeader,
    Truncated,
    CorruptSequence,
    CorruptPredecessor,
    CorruptEntryDigest,
    CorruptCheckpoint,
    CorruptArchive,
    ArchiveChainMismatch,
    InvalidRetentionPolicy,
    RetentionNotAcknowledged,
    FrontierRegression,
    UnknownKind(u8),
}

impl fmt::Display for NduProjectionEpochError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduProjectionEpochError {}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct ProjectionKeyV1 {
    objective_digest: Digest32,
    subject_digest: Digest32,
    payload_digest: Digest32,
}

impl ProjectionKeyV1 {
    const fn new(
        objective_digest: Digest32,
        subject_digest: Digest32,
        payload_digest: Digest32,
    ) -> Self {
        Self {
            objective_digest,
            subject_digest,
            payload_digest,
        }
    }

    fn is_valid(self) -> bool {
        !self.objective_digest.is_zero()
            && !self.subject_digest.is_zero()
            && !self.payload_digest.is_zero()
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct ScopeKeyV1 {
    objective_digest: Digest32,
    subject_digest: Digest32,
}

impl ScopeKeyV1 {
    const fn new(objective_digest: Digest32, subject_digest: Digest32) -> Self {
        Self {
            objective_digest,
            subject_digest,
        }
    }

    fn is_valid(self) -> bool {
        !self.objective_digest.is_zero() && !self.subject_digest.is_zero()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct ReplayRecordV1 {
    sequence: u64,
    kind: NduProjectionKindV1,
    operation_digest: Digest32,
    predecessor_entry_digest: Digest32,
    entry_digest: Digest32,
}

/// A bounded semantic checkpoint. It retains every historical operation
/// identity as a compact semantic digest, while current projection, revocation
/// and selection state remain explicit. Full transition bytes live in chained
/// archives and can independently reconstruct this checkpoint from epoch zero.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduProjectionCheckpointV1 {
    epoch: u64,
    record_count: u64,
    head_digest: Digest32,
    previous_archive_digest: Digest32,
    identities: BTreeMap<Digest32, ReplayRecordV1>,
    recorded: BTreeSet<ProjectionKeyV1>,
    revoked: BTreeSet<ProjectionKeyV1>,
    selected: BTreeMap<ScopeKeyV1, Digest32>,
    checkpoint_digest: Digest32,
}

impl NduProjectionCheckpointV1 {
    #[must_use]
    pub fn initial() -> Self {
        let mut value = Self {
            epoch: 0,
            record_count: 0,
            head_digest: Digest32::ZERO,
            previous_archive_digest: Digest32::ZERO,
            identities: BTreeMap::new(),
            recorded: BTreeSet::new(),
            revoked: BTreeSet::new(),
            selected: BTreeMap::new(),
            checkpoint_digest: Digest32::ZERO,
        };
        value.refresh_digest();
        value
    }

    #[must_use]
    pub const fn epoch(&self) -> u64 {
        self.epoch
    }

    #[must_use]
    pub const fn record_count(&self) -> u64 {
        self.record_count
    }

    #[must_use]
    pub const fn head_digest(&self) -> Digest32 {
        self.head_digest
    }

    #[must_use]
    pub const fn previous_archive_digest(&self) -> Digest32 {
        self.previous_archive_digest
    }

    #[must_use]
    pub const fn checkpoint_digest(&self) -> Digest32 {
        self.checkpoint_digest
    }

    #[must_use]
    pub fn identity_count(&self) -> usize {
        self.identities.len()
    }

    #[must_use]
    pub fn selected_projection_digest(
        &self,
        objective_digest: Digest32,
        subject_digest: Digest32,
    ) -> Option<Digest32> {
        self.selected
            .get(&ScopeKeyV1::new(objective_digest, subject_digest))
            .copied()
    }

    #[must_use]
    pub fn is_projection_revoked(
        &self,
        objective_digest: Digest32,
        subject_digest: Digest32,
        payload_digest: Digest32,
    ) -> bool {
        self.revoked.contains(&ProjectionKeyV1::new(
            objective_digest,
            subject_digest,
            payload_digest,
        ))
    }

    pub fn export_bytes(&self) -> Vec<u8> {
        let mut bytes = self.bytes_without_digest();
        bytes.extend_from_slice(self.checkpoint_digest.as_array());
        bytes
    }

    /// Decode a checkpoint and verify its canonical digest and local invariants.
    /// Complete semantic provenance is established by `verify_archive_chain`,
    /// which reconstructs checkpoints from epoch zero using lossless archives.
    pub fn reopen(bytes: &[u8]) -> Result<Self, NduProjectionEpochError> {
        if bytes.len() < CHECKPOINT_HEADER_BYTES + CHECKPOINT_TRAILER_BYTES {
            return Err(NduProjectionEpochError::Truncated);
        }
        if bytes.len() > MAX_CHECKPOINT_BYTES {
            return Err(NduProjectionEpochError::ArchiveTooLarge);
        }
        if &bytes[..8] != CHECKPOINT_MAGIC {
            return Err(NduProjectionEpochError::CorruptHeader);
        }
        let mut offset = 8;
        let epoch = read_u64(bytes, &mut offset)?;
        let record_count = read_u64(bytes, &mut offset)?;
        let head_digest = read_digest(bytes, &mut offset)?;
        let previous_archive_digest = read_digest(bytes, &mut offset)?;
        let identity_count = read_count(bytes, &mut offset, COMPACT_IDENTITY_LIMIT)?;
        let recorded_count = read_count(bytes, &mut offset, STATE_KEY_LIMIT)?;
        let revoked_count = read_count(bytes, &mut offset, STATE_KEY_LIMIT)?;
        let selected_count = read_count(bytes, &mut offset, STATE_KEY_LIMIT)?;

        let expected = CHECKPOINT_HEADER_BYTES
            .checked_add(
                identity_count
                    .checked_mul(REPLAY_RECORD_BYTES)
                    .ok_or(NduProjectionEpochError::Truncated)?,
            )
            .and_then(|value| value.checked_add(recorded_count.checked_mul(STATE_KEY_BYTES)?))
            .and_then(|value| value.checked_add(revoked_count.checked_mul(STATE_KEY_BYTES)?))
            .and_then(|value| value.checked_add(selected_count.checked_mul(STATE_KEY_BYTES)?))
            .and_then(|value| value.checked_add(CHECKPOINT_TRAILER_BYTES))
            .ok_or(NduProjectionEpochError::Truncated)?;
        if bytes.len() != expected {
            return Err(NduProjectionEpochError::Truncated);
        }

        let mut identities = BTreeMap::new();
        let mut sequences = BTreeSet::new();
        for _ in 0..identity_count {
            let identity_digest = read_digest(bytes, &mut offset)?;
            let record = ReplayRecordV1 {
                sequence: read_u64(bytes, &mut offset)?,
                kind: kind_from_tag(read_u8(bytes, &mut offset)?)?,
                operation_digest: read_digest(bytes, &mut offset)?,
                predecessor_entry_digest: read_digest(bytes, &mut offset)?,
                entry_digest: read_digest(bytes, &mut offset)?,
            };
            if identity_digest.is_zero()
                || record.operation_digest.is_zero()
                || record.entry_digest.is_zero()
                || record.sequence == 0
                || record.sequence > record_count
                || !sequences.insert(record.sequence)
                || identities.insert(identity_digest, record).is_some()
            {
                return Err(NduProjectionEpochError::CorruptCheckpoint);
            }
        }

        let mut recorded = BTreeSet::new();
        for _ in 0..recorded_count {
            let key = read_projection_key(bytes, &mut offset)?;
            if !key.is_valid() || !recorded.insert(key) {
                return Err(NduProjectionEpochError::CorruptCheckpoint);
            }
        }
        let mut revoked = BTreeSet::new();
        for _ in 0..revoked_count {
            let key = read_projection_key(bytes, &mut offset)?;
            if !key.is_valid() || !revoked.insert(key) {
                return Err(NduProjectionEpochError::CorruptCheckpoint);
            }
        }
        let mut selected = BTreeMap::new();
        for _ in 0..selected_count {
            let scope = ScopeKeyV1::new(
                read_digest(bytes, &mut offset)?,
                read_digest(bytes, &mut offset)?,
            );
            let payload_digest = read_digest(bytes, &mut offset)?;
            if !scope.is_valid()
                || payload_digest.is_zero()
                || selected.insert(scope, payload_digest).is_some()
            {
                return Err(NduProjectionEpochError::CorruptCheckpoint);
            }
        }
        let checkpoint_digest = read_digest(bytes, &mut offset)?;
        if offset != bytes.len() {
            return Err(NduProjectionEpochError::Truncated);
        }

        let value = Self {
            epoch,
            record_count,
            head_digest,
            previous_archive_digest,
            identities,
            recorded,
            revoked,
            selected,
            checkpoint_digest,
        };
        value.validate_local_invariants()?;
        let expected_digest = digest_checkpoint(&value.bytes_without_digest());
        if value.checkpoint_digest != expected_digest {
            return Err(NduProjectionEpochError::CorruptCheckpoint);
        }
        Ok(value)
    }

    fn bytes_without_digest(&self) -> Vec<u8> {
        let capacity = CHECKPOINT_HEADER_BYTES
            + self.identities.len() * REPLAY_RECORD_BYTES
            + (self.recorded.len() + self.revoked.len() + self.selected.len()) * STATE_KEY_BYTES;
        let mut bytes = Vec::with_capacity(capacity);
        bytes.extend_from_slice(CHECKPOINT_MAGIC);
        bytes.extend_from_slice(&self.epoch.to_be_bytes());
        bytes.extend_from_slice(&self.record_count.to_be_bytes());
        bytes.extend_from_slice(self.head_digest.as_array());
        bytes.extend_from_slice(self.previous_archive_digest.as_array());
        push_count(&mut bytes, self.identities.len());
        push_count(&mut bytes, self.recorded.len());
        push_count(&mut bytes, self.revoked.len());
        push_count(&mut bytes, self.selected.len());
        for (identity_digest, record) in &self.identities {
            bytes.extend_from_slice(identity_digest.as_array());
            bytes.extend_from_slice(&record.sequence.to_be_bytes());
            bytes.push(kind_tag(record.kind));
            bytes.extend_from_slice(record.operation_digest.as_array());
            bytes.extend_from_slice(record.predecessor_entry_digest.as_array());
            bytes.extend_from_slice(record.entry_digest.as_array());
        }
        for key in &self.recorded {
            push_projection_key(&mut bytes, *key);
        }
        for key in &self.revoked {
            push_projection_key(&mut bytes, *key);
        }
        for (scope, payload_digest) in &self.selected {
            bytes.extend_from_slice(scope.objective_digest.as_array());
            bytes.extend_from_slice(scope.subject_digest.as_array());
            bytes.extend_from_slice(payload_digest.as_array());
        }
        bytes
    }

    fn refresh_digest(&mut self) {
        self.checkpoint_digest = digest_checkpoint(&self.bytes_without_digest());
    }

    fn validate_local_invariants(&self) -> Result<(), NduProjectionEpochError> {
        let count = usize::try_from(self.record_count)
            .map_err(|_| NduProjectionEpochError::IdentityLimitExceeded)?;
        if count != self.identities.len() || count > COMPACT_IDENTITY_LIMIT {
            return Err(NduProjectionEpochError::CorruptCheckpoint);
        }
        if self.recorded.len() > STATE_KEY_LIMIT
            || self.revoked.len() > STATE_KEY_LIMIT
            || self.selected.len() > STATE_KEY_LIMIT
            || !self.revoked.is_subset(&self.recorded)
        {
            return Err(NduProjectionEpochError::CorruptCheckpoint);
        }
        if self.record_count == 0 {
            if self.epoch != 0
                || !self.head_digest.is_zero()
                || !self.previous_archive_digest.is_zero()
                || !self.recorded.is_empty()
                || !self.revoked.is_empty()
                || !self.selected.is_empty()
            {
                return Err(NduProjectionEpochError::CorruptCheckpoint);
            }
        } else if self.epoch == 0 || self.head_digest.is_zero() {
            return Err(NduProjectionEpochError::CorruptCheckpoint);
        }
        let sequences: BTreeSet<u64> = self
            .identities
            .values()
            .map(|record| record.sequence)
            .collect();
        if sequences.len() != count || sequences.iter().copied().ne(1..=self.record_count) {
            return Err(NduProjectionEpochError::CorruptCheckpoint);
        }
        for (scope, payload_digest) in &self.selected {
            let key = ProjectionKeyV1::new(
                scope.objective_digest,
                scope.subject_digest,
                *payload_digest,
            );
            if !self.recorded.contains(&key) || self.revoked.contains(&key) {
                return Err(NduProjectionEpochError::CorruptCheckpoint);
            }
        }
        Ok(())
    }

    fn apply_entry(&mut self, entry: &NduProjectionEntryV1) -> Result<(), NduProjectionEpochError> {
        if entry.identity_digest.is_zero()
            || entry.objective_digest.is_zero()
            || entry.subject_digest.is_zero()
            || entry.payload_digest.is_zero()
        {
            return Err(NduProjectionEpochError::EmptyDigest);
        }
        if self.identities.len() >= COMPACT_IDENTITY_LIMIT {
            return Err(NduProjectionEpochError::IdentityLimitExceeded);
        }
        let expected_sequence = self
            .record_count
            .checked_add(1)
            .ok_or(NduProjectionEpochError::IdentityLimitExceeded)?;
        if entry.sequence != expected_sequence {
            return Err(NduProjectionEpochError::CorruptSequence);
        }
        if entry.predecessor_entry_digest != self.head_digest {
            return Err(NduProjectionEpochError::CorruptPredecessor);
        }
        if entry.entry_digest
            != digest_entry(
                entry.sequence,
                entry.kind,
                entry.identity_digest,
                entry.objective_digest,
                entry.subject_digest,
                entry.payload_digest,
                entry.predecessor_entry_digest,
            )
        {
            return Err(NduProjectionEpochError::CorruptEntryDigest);
        }
        if self.identities.contains_key(&entry.identity_digest) {
            return Err(NduProjectionEpochError::DuplicateIdentity);
        }

        let key = ProjectionKeyV1::new(
            entry.objective_digest,
            entry.subject_digest,
            entry.payload_digest,
        );
        let scope = ScopeKeyV1::new(entry.objective_digest, entry.subject_digest);
        match entry.kind {
            NduProjectionKindV1::Preference | NduProjectionKindV1::Utility => {
                if self.revoked.contains(&key) {
                    return Err(NduProjectionEpochError::RevokedProjection);
                }
                if !self.recorded.contains(&key) && self.recorded.len() >= STATE_KEY_LIMIT {
                    return Err(NduProjectionEpochError::StateLimitExceeded);
                }
                self.recorded.insert(key);
            }
            NduProjectionKindV1::SelectedProjection => {
                if !self.recorded.contains(&key) {
                    return Err(NduProjectionEpochError::ProjectionNotRecorded);
                }
                if self.revoked.contains(&key) {
                    return Err(NduProjectionEpochError::RevokedProjection);
                }
                if !self.selected.contains_key(&scope) && self.selected.len() >= STATE_KEY_LIMIT {
                    return Err(NduProjectionEpochError::StateLimitExceeded);
                }
                self.selected.insert(scope, entry.payload_digest);
            }
            NduProjectionKindV1::Revocation => {
                if !self.recorded.contains(&key) {
                    return Err(NduProjectionEpochError::ProjectionNotRecorded);
                }
                if self.revoked.contains(&key) {
                    return Err(NduProjectionEpochError::RevokedProjection);
                }
                if self.revoked.len() >= STATE_KEY_LIMIT {
                    return Err(NduProjectionEpochError::StateLimitExceeded);
                }
                self.revoked.insert(key);
                if self.selected.get(&scope) == Some(&entry.payload_digest) {
                    self.selected.remove(&scope);
                }
            }
        }

        self.identities.insert(
            entry.identity_digest,
            ReplayRecordV1 {
                sequence: entry.sequence,
                kind: entry.kind,
                operation_digest: operation_digest(
                    entry.kind,
                    entry.objective_digest,
                    entry.subject_digest,
                    entry.payload_digest,
                ),
                predecessor_entry_digest: entry.predecessor_entry_digest,
                entry_digest: entry.entry_digest,
            },
        );
        self.record_count = entry.sequence;
        self.head_digest = entry.entry_digest;
        self.refresh_digest();
        Ok(())
    }

    fn replay_identity(
        &self,
        kind: NduProjectionKindV1,
        identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        payload_digest: Digest32,
    ) -> Result<Option<NduProjectionEntryV1>, NduProjectionEpochError> {
        let Some(record) = self.identities.get(&identity_digest) else {
            return Ok(None);
        };
        if record.kind != kind
            || record.operation_digest
                != operation_digest(kind, objective_digest, subject_digest, payload_digest)
        {
            return Err(NduProjectionEpochError::IdentityConflict);
        }
        Ok(Some(NduProjectionEntryV1 {
            sequence: record.sequence,
            kind,
            identity_digest,
            objective_digest,
            subject_digest,
            payload_digest,
            predecessor_entry_digest: record.predecessor_entry_digest,
            entry_digest: record.entry_digest,
        }))
    }

    fn projection_recorded(&self, key: ProjectionKeyV1) -> bool {
        self.recorded.contains(&key)
    }

    fn projection_revoked(&self, key: ProjectionKeyV1) -> bool {
        self.revoked.contains(&key)
    }

    fn live_projection_count(&self) -> usize {
        self.recorded.difference(&self.revoked).count()
    }

    fn same_semantic_state(&self, other: &Self) -> bool {
        self.record_count == other.record_count
            && self.head_digest == other.head_digest
            && self.identities == other.identities
            && self.recorded == other.recorded
            && self.revoked == other.revoked
            && self.selected == other.selected
    }
}

/// An in-memory epoch journal whose active suffix is bounded independently of
/// cumulative history. Rotation folds the suffix into a compact checkpoint and
/// emits a lossless, self-validating transition archive. It grants no file or
/// deletion authority; durable integration must use the same commit/unknown-
/// outcome discipline as `NduProjectionStoreV1`.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduProjectionEpochJournalV1 {
    base: NduProjectionCheckpointV1,
    working: NduProjectionCheckpointV1,
    active_entries: Vec<NduProjectionEntryV1>,
}

impl Default for NduProjectionEpochJournalV1 {
    fn default() -> Self {
        Self::new()
    }
}

impl NduProjectionEpochJournalV1 {
    #[must_use]
    pub fn new() -> Self {
        let checkpoint = NduProjectionCheckpointV1::initial();
        Self {
            base: checkpoint.clone(),
            working: checkpoint,
            active_entries: Vec::new(),
        }
    }

    pub fn from_v1(journal: &NduProjectionJournalV1) -> Result<Self, NduProjectionEpochError> {
        let mut value = Self::new();
        for entry in journal.entries() {
            value.working.apply_entry(entry)?;
            value.active_entries.push(entry.clone());
        }
        Ok(value)
    }

    /// Reconstruct a compact journal only from an archive chain anchored at
    /// the canonical empty checkpoint. A detached final archive is insufficient
    /// because its embedded predecessor checkpoint is not an external frontier.
    pub fn from_archive_chain(archives: &[Vec<u8>]) -> Result<Self, NduProjectionEpochError> {
        let checkpoint = reconstruct_projection_archive_chain_v1(archives)?;
        Ok(Self {
            base: checkpoint.clone(),
            working: checkpoint,
            active_entries: Vec::new(),
        })
    }

    #[must_use]
    pub fn checkpoint(&self) -> &NduProjectionCheckpointV1 {
        &self.base
    }

    #[must_use]
    pub fn active_entries(&self) -> &[NduProjectionEntryV1] {
        &self.active_entries
    }

    #[must_use]
    pub fn total_record_count(&self) -> u64 {
        self.working.record_count()
    }

    #[must_use]
    pub fn selected_projection_digest(
        &self,
        objective_digest: Digest32,
        subject_digest: Digest32,
    ) -> Option<Digest32> {
        self.working
            .selected_projection_digest(objective_digest, subject_digest)
    }

    pub fn append_projection(
        &mut self,
        kind: NduProjectionKindV1,
        identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        payload_digest: Digest32,
    ) -> Result<NduProjectionEntryV1, NduProjectionEpochError> {
        if !is_projection(kind) {
            return Err(NduProjectionEpochError::IdentityConflict);
        }
        if let Some(entry) = self.working.replay_identity(
            kind,
            identity_digest,
            objective_digest,
            subject_digest,
            payload_digest,
        )? {
            return Ok(entry);
        }
        let key = ProjectionKeyV1::new(objective_digest, subject_digest, payload_digest);
        if self.working.projection_revoked(key) {
            return Err(NduProjectionEpochError::RevokedProjection);
        }
        let additional = usize::from(!self.working.projection_recorded(key));
        self.ensure_non_revocation_capacity(additional)?;
        self.append_new(
            kind,
            identity_digest,
            objective_digest,
            subject_digest,
            payload_digest,
        )
    }

    pub fn select_projection_if_current(
        &mut self,
        identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        expected_predecessor: Option<Digest32>,
        payload_digest: Digest32,
    ) -> Result<NduProjectionEntryV1, NduProjectionEpochError> {
        if let Some(entry) = self.working.replay_identity(
            NduProjectionKindV1::SelectedProjection,
            identity_digest,
            objective_digest,
            subject_digest,
            payload_digest,
        )? {
            return Ok(entry);
        }
        let key = ProjectionKeyV1::new(objective_digest, subject_digest, payload_digest);
        if !self.working.projection_recorded(key) {
            return Err(NduProjectionEpochError::ProjectionNotRecorded);
        }
        if self.working.projection_revoked(key) {
            return Err(NduProjectionEpochError::RevokedProjection);
        }
        if self
            .working
            .selected_projection_digest(objective_digest, subject_digest)
            != expected_predecessor
        {
            return Err(NduProjectionEpochError::SelectionPredecessorMismatch);
        }
        self.ensure_non_revocation_capacity(0)?;
        self.append_new(
            NduProjectionKindV1::SelectedProjection,
            identity_digest,
            objective_digest,
            subject_digest,
            payload_digest,
        )
    }

    pub fn revoke_projection(
        &mut self,
        identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        payload_digest: Digest32,
    ) -> Result<NduProjectionEntryV1, NduProjectionEpochError> {
        if let Some(entry) = self.working.replay_identity(
            NduProjectionKindV1::Revocation,
            identity_digest,
            objective_digest,
            subject_digest,
            payload_digest,
        )? {
            return Ok(entry);
        }
        let key = ProjectionKeyV1::new(objective_digest, subject_digest, payload_digest);
        if !self.working.projection_recorded(key) {
            return Err(NduProjectionEpochError::ProjectionNotRecorded);
        }
        if self.working.projection_revoked(key) {
            return Err(NduProjectionEpochError::RevokedProjection);
        }
        if self.active_entries.len() >= ACTIVE_RECORD_LIMIT {
            return Err(NduProjectionEpochError::ActiveRecordLimitExceeded);
        }
        self.append_new(
            NduProjectionKindV1::Revocation,
            identity_digest,
            objective_digest,
            subject_digest,
            payload_digest,
        )
    }

    /// Close the active suffix, emit one lossless archive transition, and
    /// continue from a compact checkpoint with a fresh bounded active budget.
    pub fn rotate(self) -> Result<(NduProjectionEpochArchiveV1, Self), NduProjectionEpochError> {
        if self.active_entries.is_empty() {
            return Err(NduProjectionEpochError::EmptyArchive);
        }
        let (archive, checkpoint) =
            NduProjectionEpochArchiveV1::build(&self.base, &self.active_entries)?;
        if !checkpoint.same_semantic_state(&self.working) {
            return Err(NduProjectionEpochError::CorruptArchive);
        }
        let next = Self {
            base: checkpoint.clone(),
            working: checkpoint,
            active_entries: Vec::new(),
        };
        Ok((archive, next))
    }

    fn ensure_non_revocation_capacity(
        &self,
        additional_revocation_reservation: usize,
    ) -> Result<(), NduProjectionEpochError> {
        let active_after = self
            .active_entries
            .len()
            .checked_add(1)
            .ok_or(NduProjectionEpochError::ActiveRecordLimitExceeded)?;
        let reserved = self
            .working
            .live_projection_count()
            .checked_add(additional_revocation_reservation)
            .ok_or(NduProjectionEpochError::RevocationCapacityExhausted)?;
        if active_after
            .checked_add(reserved)
            .ok_or(NduProjectionEpochError::RevocationCapacityExhausted)?
            > ACTIVE_RECORD_LIMIT
        {
            return Err(NduProjectionEpochError::RevocationCapacityExhausted);
        }
        Ok(())
    }

    fn append_new(
        &mut self,
        kind: NduProjectionKindV1,
        identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        payload_digest: Digest32,
    ) -> Result<NduProjectionEntryV1, NduProjectionEpochError> {
        if identity_digest.is_zero()
            || objective_digest.is_zero()
            || subject_digest.is_zero()
            || payload_digest.is_zero()
        {
            return Err(NduProjectionEpochError::EmptyDigest);
        }
        if self.active_entries.len() >= ACTIVE_RECORD_LIMIT {
            return Err(NduProjectionEpochError::ActiveRecordLimitExceeded);
        }
        let sequence = self
            .working
            .record_count
            .checked_add(1)
            .ok_or(NduProjectionEpochError::IdentityLimitExceeded)?;
        let predecessor_entry_digest = self.working.head_digest;
        let entry_digest = digest_entry(
            sequence,
            kind,
            identity_digest,
            objective_digest,
            subject_digest,
            payload_digest,
            predecessor_entry_digest,
        );
        let entry = NduProjectionEntryV1 {
            sequence,
            kind,
            identity_digest,
            objective_digest,
            subject_digest,
            payload_digest,
            predecessor_entry_digest,
            entry_digest,
        };
        self.working.apply_entry(&entry)?;
        self.active_entries.push(entry.clone());
        Ok(entry)
    }
}

/// A lossless transition archive. The transition digest is the epoch-chain
/// identity and is intentionally computed before the after-checkpoint digest,
/// avoiding a circular hash dependency. A separate archive checksum binds the
/// complete encoded object including that after-checkpoint digest.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduProjectionEpochArchiveV1 {
    epoch: u64,
    previous_archive_digest: Digest32,
    checkpoint_before: NduProjectionCheckpointV1,
    entries: Vec<NduProjectionEntryV1>,
    transition_digest: Digest32,
    checkpoint_after_digest: Digest32,
    archive_checksum: Digest32,
}

impl NduProjectionEpochArchiveV1 {
    fn build(
        before: &NduProjectionCheckpointV1,
        entries: &[NduProjectionEntryV1],
    ) -> Result<(Self, NduProjectionCheckpointV1), NduProjectionEpochError> {
        if entries.is_empty() {
            return Err(NduProjectionEpochError::EmptyArchive);
        }
        if entries.len() > ACTIVE_RECORD_LIMIT {
            return Err(NduProjectionEpochError::ActiveRecordLimitExceeded);
        }
        let epoch = before
            .epoch
            .checked_add(1)
            .ok_or(NduProjectionEpochError::ZeroEpoch)?;
        let transition_digest = digest_transition(epoch, before, entries);
        let mut after = before.clone();
        for entry in entries {
            after.apply_entry(entry)?;
        }
        after.epoch = epoch;
        after.previous_archive_digest = transition_digest;
        after.refresh_digest();
        let mut archive = Self {
            epoch,
            previous_archive_digest: before.previous_archive_digest,
            checkpoint_before: before.clone(),
            entries: entries.to_vec(),
            transition_digest,
            checkpoint_after_digest: after.checkpoint_digest,
            archive_checksum: Digest32::ZERO,
        };
        archive.archive_checksum = digest_archive_checksum(&archive.bytes_without_checksum());
        Ok((archive, after))
    }

    #[must_use]
    pub const fn epoch(&self) -> u64 {
        self.epoch
    }

    #[must_use]
    pub const fn archive_digest(&self) -> Digest32 {
        self.transition_digest
    }

    #[must_use]
    pub const fn checkpoint_after_digest(&self) -> Digest32 {
        self.checkpoint_after_digest
    }

    #[must_use]
    pub const fn archive_checksum(&self) -> Digest32 {
        self.archive_checksum
    }

    #[must_use]
    pub const fn previous_archive_digest(&self) -> Digest32 {
        self.previous_archive_digest
    }

    #[must_use]
    pub fn entry_count(&self) -> usize {
        self.entries.len()
    }

    #[must_use]
    pub fn encoded_len(&self) -> usize {
        ARCHIVE_HEADER_BYTES
            + self.checkpoint_before.export_bytes().len()
            + self.entries.len() * ENTRY_BYTES
            + ARCHIVE_TRAILER_BYTES
    }

    pub fn export_bytes(&self) -> Vec<u8> {
        let mut bytes = self.bytes_without_checksum();
        bytes.extend_from_slice(self.archive_checksum.as_array());
        bytes
    }

    pub fn reopen(
        bytes: &[u8],
    ) -> Result<(Self, NduProjectionCheckpointV1), NduProjectionEpochError> {
        if bytes.len() < ARCHIVE_HEADER_BYTES + ARCHIVE_TRAILER_BYTES {
            return Err(NduProjectionEpochError::Truncated);
        }
        if bytes.len() > MAX_ARCHIVE_BYTES {
            return Err(NduProjectionEpochError::ArchiveTooLarge);
        }
        if &bytes[..8] != ARCHIVE_MAGIC {
            return Err(NduProjectionEpochError::CorruptHeader);
        }
        let mut offset = 8;
        let epoch = read_u64(bytes, &mut offset)?;
        if epoch == 0 {
            return Err(NduProjectionEpochError::ZeroEpoch);
        }
        let previous_archive_digest = read_digest(bytes, &mut offset)?;
        let checkpoint_len = read_count(bytes, &mut offset, MAX_CHECKPOINT_BYTES)?;
        let entry_count = read_count(bytes, &mut offset, ACTIVE_RECORD_LIMIT)?;
        if entry_count == 0 {
            return Err(NduProjectionEpochError::EmptyArchive);
        }
        let transition_digest = read_digest(bytes, &mut offset)?;
        let checkpoint_after_digest = read_digest(bytes, &mut offset)?;
        let expected = ARCHIVE_HEADER_BYTES
            .checked_add(checkpoint_len)
            .and_then(|value| value.checked_add(entry_count.checked_mul(ENTRY_BYTES)?))
            .and_then(|value| value.checked_add(ARCHIVE_TRAILER_BYTES))
            .ok_or(NduProjectionEpochError::Truncated)?;
        if bytes.len() != expected {
            return Err(NduProjectionEpochError::Truncated);
        }
        let checkpoint_end = offset
            .checked_add(checkpoint_len)
            .ok_or(NduProjectionEpochError::Truncated)?;
        let checkpoint_before = NduProjectionCheckpointV1::reopen(
            bytes
                .get(offset..checkpoint_end)
                .ok_or(NduProjectionEpochError::Truncated)?,
        )?;
        offset = checkpoint_end;
        if checkpoint_before.epoch.checked_add(1) != Some(epoch)
            || checkpoint_before.previous_archive_digest != previous_archive_digest
        {
            return Err(NduProjectionEpochError::ArchiveChainMismatch);
        }
        let mut entries = Vec::with_capacity(entry_count);
        for _ in 0..entry_count {
            entries.push(read_entry(bytes, &mut offset)?);
        }
        let archive_checksum = read_digest(bytes, &mut offset)?;
        if offset != bytes.len() {
            return Err(NduProjectionEpochError::Truncated);
        }
        let expected_transition = digest_transition(epoch, &checkpoint_before, &entries);
        if transition_digest != expected_transition {
            return Err(NduProjectionEpochError::CorruptArchive);
        }
        let mut after = checkpoint_before.clone();
        for entry in &entries {
            after.apply_entry(entry)?;
        }
        after.epoch = epoch;
        after.previous_archive_digest = transition_digest;
        after.refresh_digest();
        if after.checkpoint_digest != checkpoint_after_digest {
            return Err(NduProjectionEpochError::CorruptArchive);
        }
        let archive = Self {
            epoch,
            previous_archive_digest,
            checkpoint_before,
            entries,
            transition_digest,
            checkpoint_after_digest,
            archive_checksum,
        };
        if archive.archive_checksum != digest_archive_checksum(&archive.bytes_without_checksum()) {
            return Err(NduProjectionEpochError::CorruptArchive);
        }
        Ok((archive, after))
    }

    fn bytes_without_checksum(&self) -> Vec<u8> {
        let checkpoint = self.checkpoint_before.export_bytes();
        let mut bytes = Vec::with_capacity(
            ARCHIVE_HEADER_BYTES + checkpoint.len() + self.entries.len() * ENTRY_BYTES,
        );
        bytes.extend_from_slice(ARCHIVE_MAGIC);
        bytes.extend_from_slice(&self.epoch.to_be_bytes());
        bytes.extend_from_slice(self.previous_archive_digest.as_array());
        push_count(&mut bytes, checkpoint.len());
        push_count(&mut bytes, self.entries.len());
        bytes.extend_from_slice(self.transition_digest.as_array());
        bytes.extend_from_slice(self.checkpoint_after_digest.as_array());
        bytes.extend_from_slice(&checkpoint);
        for entry in &self.entries {
            push_entry(&mut bytes, entry);
        }
        bytes
    }
}

/// Reconstruct an archive chain from the canonical empty checkpoint. This is the
/// semantic proof needed before treating a detached checkpoint as authoritative.
fn reconstruct_projection_archive_chain_v1(
    archives: &[Vec<u8>],
) -> Result<NduProjectionCheckpointV1, NduProjectionEpochError> {
    let mut current = NduProjectionCheckpointV1::initial();
    for bytes in archives {
        let (archive, after) = NduProjectionEpochArchiveV1::reopen(bytes)?;
        if archive.checkpoint_before != current
            || archive.previous_archive_digest != current.previous_archive_digest
        {
            return Err(NduProjectionEpochError::ArchiveChainMismatch);
        }
        current = after;
    }
    Ok(current)
}

pub fn verify_projection_archive_chain_v1(
    archives: &[Vec<u8>],
    expected_checkpoint: &NduProjectionCheckpointV1,
) -> Result<Digest32, NduProjectionEpochError> {
    let current = reconstruct_projection_archive_chain_v1(archives)?;
    if &current != expected_checkpoint {
        return Err(NduProjectionEpochError::ArchiveChainMismatch);
    }
    Ok(current.checkpoint_digest)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NduProjectionRetentionPolicyV1 {
    pub local_archive_count: u16,
    pub minimum_external_copies: u16,
    pub max_local_archive_bytes: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NduProjectionArchiveAcknowledgementV1 {
    pub epoch: u64,
    pub archive_digest: Digest32,
    pub archive_checksum: Digest32,
    pub external_copy_count: u16,
    pub object_version_digest: Digest32,
    pub restore_drill_receipt_digest: Digest32,
    pub monotonic_frontier_epoch: u64,
    pub monotonic_frontier_digest: Digest32,
}

/// Return oldest-first archive digests that may be removed from the local host.
/// The function never deletes bytes and never grants external deletion authority.
pub fn plan_projection_archive_retention_v1(
    policy: NduProjectionRetentionPolicyV1,
    local_archives: &[NduProjectionEpochArchiveV1],
    acknowledgements: &[NduProjectionArchiveAcknowledgementV1],
    current_checkpoint: &NduProjectionCheckpointV1,
) -> Result<Vec<Digest32>, NduProjectionEpochError> {
    validate_retention_policy(policy)?;
    if local_archives.is_empty() {
        return Ok(Vec::new());
    }
    let mut expected_epoch = local_archives[0].epoch;
    let mut expected_previous = local_archives[0].previous_archive_digest;
    let mut total_bytes = 0_u64;
    for archive in local_archives {
        if archive.epoch != expected_epoch || archive.previous_archive_digest != expected_previous {
            return Err(NduProjectionEpochError::ArchiveChainMismatch);
        }
        expected_epoch = expected_epoch
            .checked_add(1)
            .ok_or(NduProjectionEpochError::ArchiveChainMismatch)?;
        expected_previous = archive.transition_digest;
        total_bytes = total_bytes
            .checked_add(u64::try_from(archive.encoded_len()).unwrap_or(u64::MAX))
            .ok_or(NduProjectionEpochError::ArchiveTooLarge)?;
    }
    let latest = local_archives
        .last()
        .ok_or(NduProjectionEpochError::ArchiveChainMismatch)?;
    if latest.transition_digest != current_checkpoint.previous_archive_digest
        || latest.checkpoint_after_digest != current_checkpoint.checkpoint_digest
        || latest.epoch != current_checkpoint.epoch
    {
        return Err(NduProjectionEpochError::FrontierRegression);
    }

    let keep_count = usize::from(policy.local_archive_count);
    let mut remaining_count = local_archives.len();
    let mut remaining_bytes = total_bytes;
    let mut prune = Vec::new();
    for archive in local_archives {
        if remaining_count <= keep_count && remaining_bytes <= policy.max_local_archive_bytes {
            break;
        }
        if remaining_count <= 1 {
            break;
        }
        let acknowledged = acknowledgements.iter().any(|ack| {
            ack.epoch == archive.epoch
                && ack.archive_digest == archive.transition_digest
                && ack.archive_checksum == archive.archive_checksum
                && ack.external_copy_count >= policy.minimum_external_copies
                && !ack.object_version_digest.is_zero()
                && !ack.restore_drill_receipt_digest.is_zero()
                && ack.monotonic_frontier_epoch == current_checkpoint.epoch
                && ack.monotonic_frontier_digest == current_checkpoint.checkpoint_digest
        });
        if !acknowledged {
            return Err(NduProjectionEpochError::RetentionNotAcknowledged);
        }
        prune.push(archive.transition_digest);
        remaining_count -= 1;
        remaining_bytes = remaining_bytes
            .saturating_sub(u64::try_from(archive.encoded_len()).unwrap_or(u64::MAX));
    }
    if remaining_count > keep_count || remaining_bytes > policy.max_local_archive_bytes {
        return Err(NduProjectionEpochError::RetentionNotAcknowledged);
    }
    Ok(prune)
}

fn validate_retention_policy(
    policy: NduProjectionRetentionPolicyV1,
) -> Result<(), NduProjectionEpochError> {
    if policy.local_archive_count == 0
        || policy.local_archive_count > MAX_LOCAL_ARCHIVES
        || policy.minimum_external_copies < 2
        || policy.max_local_archive_bytes == 0
    {
        return Err(NduProjectionEpochError::InvalidRetentionPolicy);
    }
    Ok(())
}

fn digest_checkpoint(bytes: &[u8]) -> Digest32 {
    Digest32::of_parts(&[CHECKPOINT_DIGEST_DOMAIN, bytes])
}

fn operation_digest(
    kind: NduProjectionKindV1,
    objective_digest: Digest32,
    subject_digest: Digest32,
    payload_digest: Digest32,
) -> Digest32 {
    let tag = [kind_tag(kind)];
    Digest32::of_parts(&[
        OPERATION_DIGEST_DOMAIN,
        &tag,
        objective_digest.as_array(),
        subject_digest.as_array(),
        payload_digest.as_array(),
    ])
}

fn digest_transition(
    epoch: u64,
    before: &NduProjectionCheckpointV1,
    entries: &[NduProjectionEntryV1],
) -> Digest32 {
    let epoch_bytes = epoch.to_be_bytes();
    let count_bytes = u32::try_from(entries.len())
        .unwrap_or(u32::MAX)
        .to_be_bytes();
    let mut entry_bytes = Vec::with_capacity(entries.len() * ENTRY_BYTES);
    for entry in entries {
        push_entry(&mut entry_bytes, entry);
    }
    Digest32::of_parts(&[
        ARCHIVE_TRANSITION_DOMAIN,
        &epoch_bytes,
        before.previous_archive_digest.as_array(),
        before.checkpoint_digest.as_array(),
        &count_bytes,
        &entry_bytes,
    ])
}

fn digest_archive_checksum(bytes: &[u8]) -> Digest32 {
    Digest32::of_parts(&[ARCHIVE_CHECKSUM_DOMAIN, bytes])
}

fn digest_entry(
    sequence: u64,
    kind: NduProjectionKindV1,
    identity_digest: Digest32,
    objective_digest: Digest32,
    subject_digest: Digest32,
    payload_digest: Digest32,
    predecessor_entry_digest: Digest32,
) -> Digest32 {
    let sequence_bytes = sequence.to_be_bytes();
    let tag = [kind_tag(kind)];
    Digest32::of_parts(&[
        ENTRY_DIGEST_DOMAIN,
        &sequence_bytes,
        &tag,
        identity_digest.as_array(),
        objective_digest.as_array(),
        subject_digest.as_array(),
        payload_digest.as_array(),
        predecessor_entry_digest.as_array(),
    ])
}

const fn is_projection(kind: NduProjectionKindV1) -> bool {
    matches!(
        kind,
        NduProjectionKindV1::Preference | NduProjectionKindV1::Utility
    )
}

const fn kind_tag(kind: NduProjectionKindV1) -> u8 {
    match kind {
        NduProjectionKindV1::Preference => 0,
        NduProjectionKindV1::Utility => 1,
        NduProjectionKindV1::SelectedProjection => 2,
        NduProjectionKindV1::Revocation => 3,
    }
}

fn kind_from_tag(value: u8) -> Result<NduProjectionKindV1, NduProjectionEpochError> {
    match value {
        0 => Ok(NduProjectionKindV1::Preference),
        1 => Ok(NduProjectionKindV1::Utility),
        2 => Ok(NduProjectionKindV1::SelectedProjection),
        3 => Ok(NduProjectionKindV1::Revocation),
        _ => Err(NduProjectionEpochError::UnknownKind(value)),
    }
}

fn push_count(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&u32::try_from(value).unwrap_or(u32::MAX).to_be_bytes());
}

fn push_projection_key(bytes: &mut Vec<u8>, key: ProjectionKeyV1) {
    bytes.extend_from_slice(key.objective_digest.as_array());
    bytes.extend_from_slice(key.subject_digest.as_array());
    bytes.extend_from_slice(key.payload_digest.as_array());
}

fn push_entry(bytes: &mut Vec<u8>, entry: &NduProjectionEntryV1) {
    bytes.extend_from_slice(&entry.sequence.to_be_bytes());
    bytes.push(kind_tag(entry.kind));
    bytes.extend_from_slice(entry.identity_digest.as_array());
    bytes.extend_from_slice(entry.objective_digest.as_array());
    bytes.extend_from_slice(entry.subject_digest.as_array());
    bytes.extend_from_slice(entry.payload_digest.as_array());
    bytes.extend_from_slice(entry.predecessor_entry_digest.as_array());
    bytes.extend_from_slice(entry.entry_digest.as_array());
}

fn read_count(
    bytes: &[u8],
    offset: &mut usize,
    maximum: usize,
) -> Result<usize, NduProjectionEpochError> {
    let value = usize::try_from(read_u32(bytes, offset)?)
        .map_err(|_| NduProjectionEpochError::Truncated)?;
    if value > maximum {
        return Err(NduProjectionEpochError::ArchiveTooLarge);
    }
    Ok(value)
}

fn read_u8(bytes: &[u8], offset: &mut usize) -> Result<u8, NduProjectionEpochError> {
    let value = *bytes
        .get(*offset)
        .ok_or(NduProjectionEpochError::Truncated)?;
    *offset += 1;
    Ok(value)
}

fn read_u32(bytes: &[u8], offset: &mut usize) -> Result<u32, NduProjectionEpochError> {
    let end = (*offset)
        .checked_add(4)
        .ok_or(NduProjectionEpochError::Truncated)?;
    let value = u32::from_be_bytes(
        bytes
            .get(*offset..end)
            .ok_or(NduProjectionEpochError::Truncated)?
            .try_into()
            .map_err(|_| NduProjectionEpochError::Truncated)?,
    );
    *offset = end;
    Ok(value)
}

fn read_u64(bytes: &[u8], offset: &mut usize) -> Result<u64, NduProjectionEpochError> {
    let end = (*offset)
        .checked_add(8)
        .ok_or(NduProjectionEpochError::Truncated)?;
    let value = u64::from_be_bytes(
        bytes
            .get(*offset..end)
            .ok_or(NduProjectionEpochError::Truncated)?
            .try_into()
            .map_err(|_| NduProjectionEpochError::Truncated)?,
    );
    *offset = end;
    Ok(value)
}

fn read_digest(bytes: &[u8], offset: &mut usize) -> Result<Digest32, NduProjectionEpochError> {
    let end = (*offset)
        .checked_add(32)
        .ok_or(NduProjectionEpochError::Truncated)?;
    let array: [u8; 32] = bytes
        .get(*offset..end)
        .ok_or(NduProjectionEpochError::Truncated)?
        .try_into()
        .map_err(|_| NduProjectionEpochError::Truncated)?;
    *offset = end;
    Ok(Digest32::from_array(array))
}

fn read_projection_key(
    bytes: &[u8],
    offset: &mut usize,
) -> Result<ProjectionKeyV1, NduProjectionEpochError> {
    Ok(ProjectionKeyV1::new(
        read_digest(bytes, offset)?,
        read_digest(bytes, offset)?,
        read_digest(bytes, offset)?,
    ))
}

fn read_entry(
    bytes: &[u8],
    offset: &mut usize,
) -> Result<NduProjectionEntryV1, NduProjectionEpochError> {
    Ok(NduProjectionEntryV1 {
        sequence: read_u64(bytes, offset)?,
        kind: kind_from_tag(read_u8(bytes, offset)?)?,
        identity_digest: read_digest(bytes, offset)?,
        objective_digest: read_digest(bytes, offset)?,
        subject_digest: read_digest(bytes, offset)?,
        payload_digest: read_digest(bytes, offset)?,
        predecessor_entry_digest: read_digest(bytes, offset)?,
        entry_digest: read_digest(bytes, offset)?,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn sample_v1() -> NduProjectionJournalV1 {
        let objective = digest("objective");
        let subject = digest("subject");
        let projection_a = digest("projection-a");
        let projection_b = digest("projection-b");
        let mut journal = NduProjectionJournalV1::new();
        journal
            .append_projection(
                NduProjectionKindV1::Preference,
                digest("append-a"),
                objective,
                subject,
                projection_a,
            )
            .expect("append a");
        journal
            .append_projection(
                NduProjectionKindV1::Utility,
                digest("append-b"),
                objective,
                subject,
                projection_b,
            )
            .expect("append b");
        journal
            .select_projection_if_current(
                digest("select-a"),
                objective,
                subject,
                None,
                projection_a,
            )
            .expect("select a");
        journal
            .revoke_projection(digest("revoke-a"), objective, subject, projection_a)
            .expect("revoke a");
        journal
            .select_projection_if_current(
                digest("select-b"),
                objective,
                subject,
                None,
                projection_b,
            )
            .expect("select b");
        journal
    }

    #[test]
    fn rotation_preserves_replay_selection_revocation_and_sequence() {
        let original = sample_v1();
        let objective = digest("objective");
        let subject = digest("subject");
        let projection_a = digest("projection-a");
        let projection_b = digest("projection-b");
        let epoch = NduProjectionEpochJournalV1::from_v1(&original).expect("import v1");
        let (archive, mut next) = epoch.rotate().expect("rotate");
        let bytes = archive.export_bytes();
        let (reopened, checkpoint) =
            NduProjectionEpochArchiveV1::reopen(&bytes).expect("reopen archive");
        assert_eq!(reopened, archive);
        assert_eq!(checkpoint, *next.checkpoint());
        assert_eq!(
            next.selected_projection_digest(objective, subject),
            Some(projection_b)
        );
        assert!(checkpoint.is_projection_revoked(objective, subject, projection_a));

        let historical = next
            .select_projection_if_current(
                digest("select-b"),
                objective,
                subject,
                Some(projection_a),
                projection_b,
            )
            .expect("exact replay");
        assert_eq!(historical, original.entries()[4]);
        assert!(next.active_entries().is_empty());
        assert_eq!(
            next.select_projection_if_current(
                digest("select-b"),
                objective,
                subject,
                Some(projection_b),
                projection_a,
            ),
            Err(NduProjectionEpochError::IdentityConflict)
        );

        let projection_c = digest("projection-c");
        let appended = next
            .append_projection(
                NduProjectionKindV1::Preference,
                digest("append-c"),
                objective,
                subject,
                projection_c,
            )
            .expect("append c");
        assert_eq!(appended.sequence, 6);
        assert_eq!(
            appended.predecessor_entry_digest,
            original.entries()[4].entry_digest
        );
        next.select_projection_if_current(
            digest("select-c"),
            objective,
            subject,
            Some(projection_b),
            projection_c,
        )
        .expect("select c");
        assert_eq!(
            next.selected_projection_digest(objective, subject),
            Some(projection_c)
        );
    }

    #[test]
    fn archive_chain_reconstructs_checkpoint_and_tampering_fails_closed() {
        let first = NduProjectionEpochJournalV1::from_v1(&sample_v1()).expect("import");
        let (archive_one, mut second) = first.rotate().expect("first rotation");
        second
            .append_projection(
                NduProjectionKindV1::Preference,
                digest("append-next"),
                digest("objective-next"),
                digest("subject-next"),
                digest("projection-next"),
            )
            .expect("append next");
        let (archive_two, third) = second.rotate().expect("second rotation");
        let chain = vec![archive_one.export_bytes(), archive_two.export_bytes()];
        assert_eq!(
            verify_projection_archive_chain_v1(&chain, third.checkpoint()),
            Ok(third.checkpoint().checkpoint_digest())
        );
        assert_eq!(
            NduProjectionEpochJournalV1::from_archive_chain(&chain)
                .expect("reconstruct chain")
                .checkpoint(),
            third.checkpoint()
        );

        let mut tampered = chain.clone();
        let index = tampered[1].len() / 2;
        tampered[1][index] ^= 1;
        assert!(verify_projection_archive_chain_v1(&tampered, third.checkpoint()).is_err());

        let reordered = vec![chain[1].clone(), chain[0].clone()];
        assert_eq!(
            verify_projection_archive_chain_v1(&reordered, third.checkpoint()),
            Err(NduProjectionEpochError::ArchiveChainMismatch)
        );
    }

    #[test]
    fn retention_requires_external_versions_restore_drills_and_frontier() {
        let first = NduProjectionEpochJournalV1::from_v1(&sample_v1()).expect("import");
        let (archive_one, mut second) = first.rotate().expect("first rotation");
        second
            .append_projection(
                NduProjectionKindV1::Preference,
                digest("append-two"),
                digest("objective-two"),
                digest("subject-two"),
                digest("projection-two"),
            )
            .expect("append two");
        let (archive_two, mut third) = second.rotate().expect("second rotation");
        third
            .append_projection(
                NduProjectionKindV1::Preference,
                digest("append-three"),
                digest("objective-three"),
                digest("subject-three"),
                digest("projection-three"),
            )
            .expect("append three");
        let (archive_three, fourth) = third.rotate().expect("third rotation");
        let archives = [archive_one, archive_two, archive_three];
        let policy = NduProjectionRetentionPolicyV1 {
            local_archive_count: 2,
            minimum_external_copies: 2,
            max_local_archive_bytes: u64::MAX,
        };
        assert_eq!(
            plan_projection_archive_retention_v1(policy, &archives, &[], fourth.checkpoint()),
            Err(NduProjectionEpochError::RetentionNotAcknowledged)
        );
        let acknowledgement = NduProjectionArchiveAcknowledgementV1 {
            epoch: archives[0].epoch(),
            archive_digest: archives[0].archive_digest(),
            archive_checksum: archives[0].archive_checksum(),
            external_copy_count: 2,
            object_version_digest: digest("object-version"),
            restore_drill_receipt_digest: digest("restore-drill"),
            monotonic_frontier_epoch: fourth.checkpoint().epoch(),
            monotonic_frontier_digest: fourth.checkpoint().checkpoint_digest(),
        };
        let mut wrong_checksum = acknowledgement;
        wrong_checksum.archive_checksum = digest("wrong-archive-checksum");
        assert_eq!(
            plan_projection_archive_retention_v1(
                policy,
                &archives,
                &[wrong_checksum],
                fourth.checkpoint(),
            ),
            Err(NduProjectionEpochError::RetentionNotAcknowledged)
        );
        let mut wrong_frontier = acknowledgement;
        wrong_frontier.monotonic_frontier_digest = digest("unbound-frontier");
        assert_eq!(
            plan_projection_archive_retention_v1(
                policy,
                &archives,
                &[wrong_frontier],
                fourth.checkpoint(),
            ),
            Err(NduProjectionEpochError::RetentionNotAcknowledged)
        );
        assert_eq!(
            plan_projection_archive_retention_v1(
                policy,
                &archives,
                &[acknowledgement],
                fourth.checkpoint(),
            ),
            Ok(vec![archives[0].archive_digest()])
        );
    }

    #[test]
    fn checkpoint_round_trip_and_archive_checksum_are_canonical() {
        let journal = NduProjectionEpochJournalV1::from_v1(&sample_v1()).expect("import");
        let (archive, next) = journal.rotate().expect("rotate");
        let checkpoint = next.checkpoint();
        assert_eq!(
            NduProjectionCheckpointV1::reopen(&checkpoint.export_bytes()),
            Ok(checkpoint.clone())
        );
        let exported = archive.export_bytes();
        let (reopened, reopened_checkpoint) =
            NduProjectionEpochArchiveV1::reopen(&exported).expect("reopen");
        assert_eq!(reopened.export_bytes(), exported);
        assert_eq!(reopened_checkpoint, checkpoint.clone());
    }
}
