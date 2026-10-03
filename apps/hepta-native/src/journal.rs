use std::collections::HashMap;
use std::collections::HashSet;
use std::fs::File;
use std::io::Read as _;
use std::path::Path;
use std::path::PathBuf;

use serde::Deserialize;
use serde::Serialize;

use crate::error::ShellError;
use crate::model::OperationKey;
use crate::model::PlatformAction;
use crate::model::PlatformReceipt;
use crate::model::TerminalStatus;
use crate::model::sha256_hex;
use crate::model::validate_digest;
use crate::model::validate_stable_id;
use crate::private_state::PrivateStateRoot;
use crate::retirement::Checkpoint;
use crate::retirement::RetirementMembership;
use crate::retirement::RetirementStore;

#[path = "journal_replay.rs"]
mod replay;
use replay::JournalWalEntry;
use replay::build_operation_index;
use replay::read_snapshot;
use replay::replay_wal;
pub(crate) use replay::retirement_digest;
use replay::validate_transition;

const JOURNAL_SCHEMA_V2: &str = "hepta.native-operation-journal.v2";
const JOURNAL_SCHEMA_V3: &str = "hepta.native-operation-journal.v3";
const JOURNAL_SCHEMA_V4: &str = "hepta.native-operation-journal.v4";
const JOURNAL_SCHEMA_V5: &str = "hepta.native-operation-journal.v5";
const JOURNAL_SCHEMA_V6: &str = "hepta.native-operation-journal.v6";
const JOURNAL_SCHEMA_V7: &str = "hepta.native-operation-journal.v7";
const WAL_SCHEMA: &str = "hepta.native-operation-wal.v1";
const MAX_JOURNAL_BYTES: u64 = 8 * 1024 * 1024;
const MAX_WAL_BYTES: u64 = 4 * 1024 * 1024;
const MAX_WAL_FRAME_BYTES: u64 = 128 * 1024;
const WAL_CHECKPOINT_ENTRIES: usize = 128;
const MAX_OPERATION_RECORDS: usize = 4096;
const MAX_RETIRED_OPERATION_DIGESTS: usize = 32 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OperationPhase {
    Prepared,
    Invoking,
    Indeterminate,
    ObservationClosed,
    Terminal,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OperationRecord {
    pub endpoint_id: String,
    pub key: OperationKey,
    pub subject_id: String,
    pub displayed_revision: u64,
    pub action: PlatformAction,
    pub payload_digest: String,
    pub binding_digest: String,
    pub grant_digest: String,
    pub phase: OperationPhase,
    pub terminal_status: Option<TerminalStatus>,
    pub outcome_digest: Option<String>,
}

impl OperationRecord {
    pub fn validate(&self) -> Result<(), ShellError> {
        validate_stable_id(&self.endpoint_id, "journal.endpoint_id")?;
        validate_stable_id(&self.key.session_id, "journal.session_id")?;
        validate_stable_id(&self.key.operation_id, "journal.operation_id")?;
        validate_stable_id(&self.subject_id, "journal.subject_id")?;
        if self.key.session_generation == 0 || self.displayed_revision == 0 {
            return Err(ShellError::State(
                "journal operation has zero session generation or displayed revision".to_owned(),
            ));
        }
        validate_digest(&self.payload_digest, "journal.payload_digest")?;
        validate_digest(&self.binding_digest, "journal.binding_digest")?;
        validate_digest(&self.grant_digest, "journal.grant_digest")?;
        if let Some(outcome_digest) = &self.outcome_digest {
            validate_digest(outcome_digest, "journal.outcome_digest")?;
        }
        match self.phase {
            OperationPhase::Terminal => {
                if self.terminal_status.is_none() || self.outcome_digest.is_none() {
                    return Err(ShellError::State(
                        "terminal journal operation is missing terminal evidence".to_owned(),
                    ));
                }
            }
            OperationPhase::Prepared
            | OperationPhase::Invoking
            | OperationPhase::Indeterminate
            | OperationPhase::ObservationClosed => {
                if self.terminal_status.is_some() || self.outcome_digest.is_some() {
                    return Err(ShellError::State(
                        "non-terminal journal operation contains terminal evidence".to_owned(),
                    ));
                }
            }
        }
        Ok(())
    }

    pub fn receipt(&self) -> PlatformReceipt {
        PlatformReceipt {
            key: self.key.clone(),
            action: self.action,
            payload_digest: self.payload_digest.clone(),
            terminal_status: self.terminal_status,
            outcome_digest: self.outcome_digest.clone(),
            terminal_observed: self.phase == OperationPhase::Terminal,
            observation_closed: self.phase == OperationPhase::ObservationClosed,
            can_close_observation: self.phase == OperationPhase::Indeterminate,
            may_have_executed: self.phase != OperationPhase::Prepared
                && !matches!(
                    self.terminal_status,
                    Some(TerminalStatus::Rejected | TerminalStatus::Quarantined)
                ),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct JournalFile {
    schema: String,
    operations: Vec<OperationRecord>,
    #[serde(default)]
    retired_operation_digests: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    retirement_checkpoint: Option<Checkpoint>,
    #[serde(default)]
    wal_sequence: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    wal_frontier: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    checksum: Option<String>,
}

impl JournalFile {
    fn checksum(&self) -> Result<String, ShellError> {
        // Detect accidental corruption, NOT a MAC or rollback-prevention authority.
        if self.schema == JOURNAL_SCHEMA_V7 {
            return Ok(sha256_hex(serde_json::to_vec(&(
                &self.schema,
                &self.operations,
                &self.retired_operation_digests,
                &self.retirement_checkpoint,
                self.wal_sequence,
                &self.wal_frontier,
            ))?));
        }
        if self.schema == JOURNAL_SCHEMA_V6 {
            return Ok(sha256_hex(serde_json::to_vec(&(
                &self.schema,
                &self.operations,
                &self.retired_operation_digests,
                &self.retirement_checkpoint,
            ))?));
        }
        Ok(sha256_hex(serde_json::to_vec(&(
            &self.schema,
            &self.operations,
            &self.retired_operation_digests,
        ))?))
    }

    fn verify_integrity(&self) -> Result<(), ShellError> {
        if !matches!(self.schema.as_str(), JOURNAL_SCHEMA_V6 | JOURNAL_SCHEMA_V7)
            && self.retirement_checkpoint.is_some()
        {
            return Err(ShellError::State(
                "legacy journal contains a v6 retirement checkpoint".to_owned(),
            ));
        }
        if self.schema != JOURNAL_SCHEMA_V7
            && (self.wal_sequence != 0 || self.wal_frontier.is_some())
        {
            return Err(ShellError::State(
                "legacy journal contains a v7 WAL frontier".to_owned(),
            ));
        }
        if self.wal_sequence == 0 && self.wal_frontier.is_some()
            || self.wal_sequence != 0 && self.wal_frontier.is_none()
        {
            return Err(ShellError::State(
                "journal WAL sequence/frontier is inconsistent".to_owned(),
            ));
        }
        if let Some(frontier) = &self.wal_frontier {
            validate_digest(frontier, "journal.wal_frontier")?;
        }
        match self.schema.as_str() {
            JOURNAL_SCHEMA_V4 | JOURNAL_SCHEMA_V5 | JOURNAL_SCHEMA_V6 | JOURNAL_SCHEMA_V7
                if self.checksum.as_ref() == Some(&self.checksum()?) => Ok(()),
            JOURNAL_SCHEMA_V2 | JOURNAL_SCHEMA_V3 if self.checksum.is_none() => Ok(()),
            _ => Err(ShellError::State(
                "journal checksum/schema failed; preserve evidence and reconcile, never restore an older snapshot automatically".to_owned(),
            )),
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct JournalCapacity {
    pub active_records: usize,
    pub active_limit: usize,
    pub pending_records: usize,
    pub closed_observations: usize,
    pub retired_identities: usize,
    pub retirement_limit: Option<usize>,
    pub retirement_segments: usize,
    pub wal_entries: usize,
    pub wal_bytes: u64,
}

#[derive(Debug)]
pub struct OperationJournal {
    path: PathBuf,
    operations: Vec<OperationRecord>,
    operation_index: HashMap<OperationKey, usize>,
    retired_operation_digests: Vec<String>,
    retirement: Option<RetirementStore>,
    wal_sequence: u64,
    wal_frontier: Option<String>,
    wal_entries: usize,
    wal_bytes: u64,
    failed: bool,
    private_root: PrivateStateRoot,
    _lock: File,
}

impl Drop for OperationJournal {
    fn drop(&mut self) {
        let _ = self._lock.unlock();
    }
}

impl OperationJournal {
    pub fn open(path: impl Into<PathBuf>) -> Result<Self, ShellError> {
        let path = path.into();
        if !path.is_absolute() {
            return Err(ShellError::InvalidInput(
                "operation journal path must be absolute".to_owned(),
            ));
        }
        let parent = path.parent().ok_or_else(|| {
            ShellError::InvalidInput("operation journal path has no private parent".to_owned())
        })?;
        let private_root = PrivateStateRoot::open(parent.to_path_buf())?;
        let lock_path = path.with_extension("lock");
        let lock_existed = lock_path.exists();
        let lock = crate::journal_storage::open_private_file_in(
            &private_root,
            &lock_path,
            crate::journal_storage::FileAccess::Lock,
            lock_existed,
        )?;
        lock.try_lock().map_err(|_| {
            ShellError::State(format!(
                "operation journal is already owned by another native process: {}",
                lock_path.display()
            ))
        })?;

        let wal_path = crate::journal_storage::wal_path(&path);
        let mut state = if path.exists() {
            read_snapshot(&private_root, &path)?
        } else {
            let has_previous =
                std::fs::symlink_metadata(crate::journal_storage::previous_path(&path)).is_ok();
            let has_retirement =
                std::fs::symlink_metadata(crate::retirement::directory(&path)).is_ok();
            let has_wal = std::fs::symlink_metadata(&wal_path).is_ok();
            if has_previous || has_retirement && !has_wal {
                return Err(ShellError::State(
                    "journal is missing but durable history exists; recovery requires the WAL or authority reconciliation, never replay".to_owned(),
                ));
            }
            let mut empty = JournalFile {
                schema: JOURNAL_SCHEMA_V7.to_owned(),
                operations: Vec::new(),
                retired_operation_digests: Vec::new(),
                retirement_checkpoint: None,
                wal_sequence: 0,
                wal_frontier: None,
                checksum: None,
            };
            empty.checksum = Some(empty.checksum()?);
            empty
        };
        state.verify_integrity()?;
        if !matches!(
            state.schema.as_str(),
            JOURNAL_SCHEMA_V5 | JOURNAL_SCHEMA_V6 | JOURNAL_SCHEMA_V7
        ) && state
            .operations
            .iter()
            .any(|record| record.phase == OperationPhase::ObservationClosed)
        {
            return Err(ShellError::State(
                "legacy journal contains v5 observation closure".to_owned(),
            ));
        }
        if state.schema == JOURNAL_SCHEMA_V2 && !state.retired_operation_digests.is_empty() {
            return Err(ShellError::State(
                "legacy journal cannot contain a retirement frontier".to_owned(),
            ));
        }
        if state.operations.len() > MAX_OPERATION_RECORDS {
            return Err(ShellError::State(format!(
                "operation journal exceeds {MAX_OPERATION_RECORDS} records"
            )));
        }
        if state.retired_operation_digests.len() > MAX_RETIRED_OPERATION_DIGESTS {
            return Err(ShellError::State(format!(
                "operation retirement frontier exceeds {MAX_RETIRED_OPERATION_DIGESTS} entries"
            )));
        }

        let replay = replay_wal(
            &private_root,
            &path,
            &mut state.operations,
            state.wal_sequence,
            state.wal_frontier.clone(),
        )?;
        state.wal_sequence = replay.sequence;
        state.wal_frontier = replay.frontier.clone();
        if replay.partial_tail {
            crate::journal_storage::truncate_wal(&private_root, &path, replay.valid_bytes)?;
        }
        if replay.applied_entries == 0 && replay.total_bytes != 0 {
            // A durable checkpoint already includes every complete frame. The
            // stale WAL may be cleared only after its chain was fully verified.
            crate::journal_storage::truncate_wal(&private_root, &path, 0)?;
        }

        let mut retired = HashSet::with_capacity(state.retired_operation_digests.len());
        for digest in &state.retired_operation_digests {
            validate_digest(digest, "journal.retired_operation_digest")?;
            if !retired.insert(digest.clone()) {
                return Err(ShellError::State(
                    "duplicate operation identity in retirement frontier".to_owned(),
                ));
            }
        }
        state.retired_operation_digests.sort_unstable();
        let retirement = RetirementStore::open(&path, state.retirement_checkpoint.as_ref())?;
        let mut keys = HashSet::with_capacity(state.operations.len());
        let mut identities = Vec::with_capacity(state.operations.len());
        for operation in &state.operations {
            operation.validate()?;
            if !keys.insert(operation.key.clone()) {
                return Err(ShellError::State(
                    "duplicate operation identity in journal".to_owned(),
                ));
            }
            let digest = retirement_digest(&operation.endpoint_id, &operation.key)?;
            if retired.contains(&digest) {
                return Err(ShellError::State(
                    "active operation also appears in retirement frontier".to_owned(),
                ));
            }
            identities.push(digest);
        }
        let memberships = match retirement.as_ref() {
            Some(store) => store.memberships(&identities)?,
            None => identities
                .iter()
                .map(|_| RetirementMembership::Absent)
                .collect(),
        };
        // Retirement publication precedes journal checkpoint replacement. Reuse
        // one validated membership result for rollback and immutable-archive
        // checks instead of traversing random index prefixes a second time.
        let mut operations = Vec::with_capacity(state.operations.len());
        for (record, membership) in state.operations.into_iter().zip(memberships) {
            match membership {
                RetirementMembership::Absent => operations.push(record),
                RetirementMembership::Legacy | RetirementMembership::Archived(_)
                    if !matches!(
                        record.phase,
                        OperationPhase::Terminal | OperationPhase::ObservationClosed
                    ) =>
                {
                    return Err(ShellError::State(
                        "live operation overlaps a durable retirement; possible journal rollback"
                            .to_owned(),
                    ));
                }
                RetirementMembership::Archived(archived) if *archived != record => {
                    return Err(ShellError::State(
                        "active closed record differs from its durable archive".to_owned(),
                    ));
                }
                RetirementMembership::Legacy | RetirementMembership::Archived(_) => {}
            }
        }
        let operation_index = build_operation_index(&operations)?;
        Ok(Self {
            path,
            operations,
            operation_index,
            retired_operation_digests: state.retired_operation_digests,
            retirement,
            wal_sequence: replay.sequence,
            wal_frontier: replay.frontier,
            wal_entries: replay.applied_entries,
            wal_bytes: if replay.applied_entries == 0 {
                0
            } else {
                replay.valid_bytes
            },
            failed: false,
            private_root,
            _lock: lock,
        })
    }

    /// Read-only historical lookup. Legacy identity-only tombstones return None;
    /// callers must still enforce ensure_not_retired before starting any effect.
    pub fn archived_record(
        &self,
        endpoint_id: &str,
        key: &OperationKey,
    ) -> Result<Option<OperationRecord>, ShellError> {
        self.ensure_healthy()?;
        let digest = retirement_digest(endpoint_id, key)?;
        match &self.retirement {
            Some(store) => store.read_record(&digest),
            None => Ok(None),
        }
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn find(&self, key: &OperationKey) -> Option<&OperationRecord> {
        self.operation_index
            .get(key)
            .and_then(|index| self.operations.get(*index))
    }

    pub fn pending(&self) -> impl Iterator<Item = &OperationRecord> {
        self.operations.iter().filter(|record| {
            !matches!(
                record.phase,
                OperationPhase::Terminal | OperationPhase::ObservationClosed
            )
        })
    }

    pub fn all(&self) -> &[OperationRecord] {
        &self.operations
    }

    pub fn retired_count(&self) -> usize {
        self.retirement.as_ref().map_or(0, RetirementStore::len)
            + self
                .retired_operation_digests
                .iter()
                .filter(|digest| {
                    !self
                        .retirement
                        .as_ref()
                        .is_some_and(|store| store.contains(digest))
                })
                .count()
    }

    pub fn ensure_not_retired(
        &self,
        endpoint_id: &str,
        key: &OperationKey,
    ) -> Result<(), ShellError> {
        let digest = retirement_digest(endpoint_id, key)?;
        if self
            .retired_operation_digests
            .binary_search(&digest)
            .is_ok()
            || self
                .retirement
                .as_ref()
                .is_some_and(|store| store.contains(&digest))
        {
            return Err(ShellError::State(
                "operation identity belongs to the durable retirement frontier".to_owned(),
            ));
        }
        Ok(())
    }

    /// Failed persistence requires reopen and reconciliation, never replay.
    pub fn ensure_healthy(&self) -> Result<(), ShellError> {
        self.private_root.verify()?;
        if self.failed {
            return Err(ShellError::State(
                "journal persistence is indeterminate; reopen and reconcile".to_owned(),
            ));
        }
        Ok(())
    }

    pub fn upsert(&mut self, record: OperationRecord) -> Result<(), ShellError> {
        self.ensure_healthy()?;
        record.validate()?;
        self.ensure_not_retired(&record.endpoint_id, &record.key)?;
        if !self.operation_index.contains_key(&record.key)
            && self.operations.len() >= MAX_OPERATION_RECORDS
        {
            self.compact_closed_history(MAX_OPERATION_RECORDS / 2)?;
        }
        let existing_index = self.operation_index.get(&record.key).copied();
        if let Some(index) = existing_index {
            validate_transition(&self.operations[index], &record)?;
            if self.operations[index] == record {
                return Ok(());
            }
        } else if self.operations.len() >= MAX_OPERATION_RECORDS {
            return Err(ShellError::State(format!(
                "operation journal reached {MAX_OPERATION_RECORDS} records"
            )));
        }

        if let Err(error) = self.append_wal(record.clone()) {
            self.failed = true;
            return Err(error);
        }
        match existing_index {
            Some(index) => self.operations[index] = record,
            None => {
                let index = self.operations.len();
                self.operation_index.insert(record.key.clone(), index);
                self.operations.push(record);
            }
        }
        if let Err(error) = self.checkpoint_if_needed() {
            self.failed = true;
            return Err(error);
        }
        Ok(())
    }

    fn append_wal(&mut self, record: OperationRecord) -> Result<(), ShellError> {
        let sequence = self
            .wal_sequence
            .checked_add(1)
            .ok_or_else(|| ShellError::State("native journal WAL sequence overflow".to_owned()))?;
        let entry = JournalWalEntry::new(sequence, self.wal_frontier.clone(), record)?;
        let bytes = serde_json::to_vec(&entry)?;
        self.wal_bytes = crate::journal_storage::append_wal_frame(
            &self.private_root,
            &self.path,
            &bytes,
            MAX_WAL_BYTES,
            MAX_WAL_FRAME_BYTES,
        )?;
        self.wal_sequence = sequence;
        self.wal_frontier = Some(entry.checksum);
        self.wal_entries = self.wal_entries.checked_add(1).ok_or_else(|| {
            ShellError::State("native journal WAL entry count overflow".to_owned())
        })?;
        Ok(())
    }

    fn checkpoint_if_needed(&mut self) -> Result<(), ShellError> {
        if self.wal_entries < WAL_CHECKPOINT_ENTRIES && self.wal_bytes < MAX_WAL_BYTES * 3 / 4 {
            return Ok(());
        }
        self.persist(&self.operations, &self.retired_operation_digests)?;
        self.wal_entries = 0;
        self.wal_bytes = 0;
        Ok(())
    }

    /// End automatic observation, not the external operation. Never authorizes
    /// replay and never manufactures terminal evidence. Repeating is harmless.
    pub fn close_observation(&mut self, key: &OperationKey) -> Result<PlatformReceipt, ShellError> {
        self.ensure_healthy()?;
        let record = self.find(key).cloned().ok_or_else(|| {
            ShellError::State("operation is missing or already retired".to_owned())
        })?;
        if record.phase == OperationPhase::ObservationClosed {
            return Ok(record.receipt());
        }
        if record.phase != OperationPhase::Indeterminate {
            return Err(ShellError::State(
                "only an indeterminate observation can be archived".to_owned(),
            ));
        }
        let closed = OperationRecord {
            phase: OperationPhase::ObservationClosed,
            ..record
        };
        let receipt = closed.receipt();
        self.upsert(closed)?;
        Ok(receipt)
    }

    pub fn capacity(&self) -> JournalCapacity {
        JournalCapacity {
            active_records: self.operations.len(),
            active_limit: MAX_OPERATION_RECORDS,
            pending_records: self.pending().count(),
            closed_observations: self
                .operations
                .iter()
                .filter(|record| record.phase == OperationPhase::ObservationClosed)
                .count(),
            retired_identities: self.retired_count(),
            retirement_limit: None,
            retirement_segments: self
                .retirement
                .as_ref()
                .map_or(0, RetirementStore::segments),
            wal_entries: self.wal_entries,
            wal_bytes: self.wal_bytes,
        }
    }

    pub fn compact_terminal(&mut self, keep_latest: usize) -> Result<(), ShellError> {
        self.compact_completed(keep_latest, false)
    }

    /// Includes unknown observations only after explicit durable closure.
    pub fn compact_closed_history(&mut self, keep_latest: usize) -> Result<(), ShellError> {
        self.compact_completed(keep_latest, true)
    }

    fn compact_completed(
        &mut self,
        keep_latest: usize,
        include_closed: bool,
    ) -> Result<(), ShellError> {
        self.ensure_healthy()?;
        let terminal_count = self
            .operations
            .iter()
            .filter(|record| {
                record.phase == OperationPhase::Terminal
                    || (include_closed && record.phase == OperationPhase::ObservationClosed)
            })
            .count();
        let mut remaining_to_retire = terminal_count.saturating_sub(keep_latest);
        if remaining_to_retire == 0 {
            return Ok(());
        }

        let mut next_operations = Vec::with_capacity(self.operations.len() - remaining_to_retire);
        let mut next_retired = self.retired_operation_digests.clone();
        let mut retiring_records = Vec::new();
        let mut retired_set: HashSet<String> = next_retired.iter().cloned().collect();
        for record in &self.operations {
            if remaining_to_retire > 0
                && (record.phase == OperationPhase::Terminal
                    || (include_closed && record.phase == OperationPhase::ObservationClosed))
            {
                let digest = retirement_digest(&record.endpoint_id, &record.key)?;
                if !retired_set.insert(digest.clone()) {
                    return Err(ShellError::State(
                        "active terminal operation already belongs to retirement frontier"
                            .to_owned(),
                    ));
                }
                next_retired.push(digest);
                retiring_records.push(record.clone());
                remaining_to_retire -= 1;
            } else {
                next_operations.push(record.clone());
            }
        }
        next_retired.sort_unstable();
        next_retired.dedup();
        let publication = (|| {
            if self.retirement.is_none() {
                self.retirement = Some(RetirementStore::create(&self.path)?);
            }
            self.retirement
                .as_mut()
                .ok_or_else(|| ShellError::State("retirement store unavailable".to_owned()))?
                .append_records(&next_retired, &retiring_records)?;
            self.persist(&next_operations, &[])
        })();
        if let Err(error) = publication {
            self.failed = true;
            return Err(error);
        }
        self.operations = next_operations;
        self.operation_index = build_operation_index(&self.operations)?;
        self.retired_operation_digests.clear();
        self.wal_entries = 0;
        self.wal_bytes = 0;
        Ok(())
    }

    fn persist(
        &self,
        operations: &[OperationRecord],
        retired_operation_digests: &[String],
    ) -> Result<(), ShellError> {
        self.private_root.verify()?;
        let mut state = JournalFile {
            schema: JOURNAL_SCHEMA_V7.to_owned(),
            operations: operations.to_vec(),
            retired_operation_digests: retired_operation_digests.to_vec(),
            retirement_checkpoint: self.retirement.as_ref().map(RetirementStore::checkpoint),
            wal_sequence: self.wal_sequence,
            wal_frontier: self.wal_frontier.clone(),
            checksum: None,
        };
        state.checksum = Some(state.checksum()?);
        let bytes = serde_json::to_vec(&state)?;
        if bytes.len() as u64 > MAX_JOURNAL_BYTES {
            return Err(ShellError::State(format!(
                "operation journal would exceed {MAX_JOURNAL_BYTES} bytes"
            )));
        }
        if self.path.exists() {
            let mut previous = Vec::new();
            crate::journal_storage::open_private_file_in(
                &self.private_root,
                &self.path,
                crate::journal_storage::FileAccess::Read,
                /*preexisting*/ true,
            )?
            .take(MAX_JOURNAL_BYTES + 1)
            .read_to_end(&mut previous)?;
            if previous.len() as u64 > MAX_JOURNAL_BYTES {
                return Err(ShellError::State(
                    "prior journal exceeded byte limit".to_owned(),
                ));
            }
            let prior: JournalFile = serde_json::from_slice(&previous)?;
            prior.verify_integrity()?;
            let backup = crate::journal_storage::previous_path(&self.path);
            // A forensic checkpoint only: automatic fallback can resurrect an effect.
            crate::journal_storage::write_private(&self.private_root, &backup, &previous)?;
        }
        crate::journal_storage::write_private(&self.private_root, &self.path, &bytes)?;
        crate::journal_storage::truncate_wal(&self.private_root, &self.path, 0)?;
        Ok(())
    }
}
