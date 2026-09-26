use std::collections::HashSet;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read as _;
use std::io::Write as _;

use atomic_write_file::AtomicWriteFile;
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

const JOURNAL_SCHEMA_V2: &str = "hepta.native-operation-journal.v2";
const JOURNAL_SCHEMA_V3: &str = "hepta.native-operation-journal.v3";
const MAX_JOURNAL_BYTES: u64 = 8 * 1024 * 1024;
const MAX_OPERATION_RECORDS: usize = 4096;
const MAX_RETIRED_OPERATION_DIGESTS: usize = 32 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OperationPhase {
    Prepared,
    Invoking,
    Indeterminate,
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
            OperationPhase::Prepared | OperationPhase::Invoking | OperationPhase::Indeterminate => {
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
}

#[derive(Debug)]
pub struct OperationJournal {
    path: PathBuf,
    operations: Vec<OperationRecord>,
    retired_operation_digests: Vec<String>,
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
        if lock_existed {
            ensure_private_state_file(&lock_path, true)?;
        }
        let lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(&lock_path)?;
        ensure_private_state_file(&lock_path, lock_existed)?;
        lock.try_lock().map_err(|_| {
            ShellError::State(format!(
                "operation journal is already owned by another native process: {}",
                lock_path.display()
            ))
        })?;
        if !path.exists() {
            return Ok(Self {
                path,
                operations: Vec::new(),
                retired_operation_digests: Vec::new(),
                failed: false,
                private_root,
                _lock: lock,
            });
        }
        ensure_private_state_file(&path, true)?;
        let metadata = std::fs::metadata(&path)?;
        if metadata.len() > MAX_JOURNAL_BYTES {
            return Err(ShellError::State(format!(
                "operation journal exceeds {MAX_JOURNAL_BYTES} bytes"
            )));
        }
        let mut bytes = Vec::new();
        File::open(&path)?
            .take(MAX_JOURNAL_BYTES + 1)
            .read_to_end(&mut bytes)?;
        if bytes.len() as u64 > MAX_JOURNAL_BYTES {
            return Err(ShellError::State(
                "operation journal read exceeded byte limit".to_owned(),
            ));
        }
        let mut state: JournalFile = serde_json::from_slice(&bytes)?;
        if state.schema != JOURNAL_SCHEMA_V2 && state.schema != JOURNAL_SCHEMA_V3 {
            return Err(ShellError::State(
                "operation journal schema is not supported".to_owned(),
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
        let mut keys = HashSet::with_capacity(state.operations.len());
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
        }
        Ok(Self {
            path,
            operations: state.operations,
            retired_operation_digests: state.retired_operation_digests,
            failed: false,
            private_root,
            _lock: lock,
        })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn find(&self, key: &OperationKey) -> Option<&OperationRecord> {
        self.operations.iter().find(|record| record.key == *key)
    }

    pub fn pending(&self) -> impl Iterator<Item = &OperationRecord> {
        self.operations
            .iter()
            .filter(|record| record.phase != OperationPhase::Terminal)
    }

    pub fn all(&self) -> &[OperationRecord] {
        &self.operations
    }

    pub fn retired_count(&self) -> usize {
        self.retired_operation_digests.len()
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
        let mut next = self.operations.clone();
        if let Some(index) = next.iter().position(|existing| existing.key == record.key) {
            let existing = &next[index];
            if existing.endpoint_id != record.endpoint_id
                || existing.subject_id != record.subject_id
                || existing.displayed_revision != record.displayed_revision
                || existing.action != record.action
                || existing.payload_digest != record.payload_digest
                || existing.binding_digest != record.binding_digest
                || existing.grant_digest != record.grant_digest
            {
                return Err(ShellError::State(
                    "operation identity was reused with changed semantics".to_owned(),
                ));
            }
            if existing.phase == OperationPhase::Terminal && existing != &record {
                return Err(ShellError::State(
                    "terminal operation observation is immutable".to_owned(),
                ));
            }
            if !phase_transition_allowed(existing.phase, record.phase) {
                return Err(ShellError::State(format!(
                    "operation phase cannot transition from {:?} to {:?}",
                    existing.phase, record.phase
                )));
            }
            next[index] = record;
        } else {
            if next.len() >= MAX_OPERATION_RECORDS {
                return Err(ShellError::State(format!(
                    "operation journal reached {MAX_OPERATION_RECORDS} records"
                )));
            }
            next.push(record);
        }
        if let Err(error) = self.persist(&next, &self.retired_operation_digests) {
            self.failed = true;
            return Err(error);
        }
        self.operations = next;
        Ok(())
    }

    pub fn compact_terminal(&mut self, keep_latest: usize) -> Result<(), ShellError> {
        self.ensure_healthy()?;
        let terminal_count = self
            .operations
            .iter()
            .filter(|record| record.phase == OperationPhase::Terminal)
            .count();
        let mut remaining_to_retire = terminal_count.saturating_sub(keep_latest);
        if remaining_to_retire == 0 {
            return Ok(());
        }

        let mut next_operations = Vec::with_capacity(self.operations.len() - remaining_to_retire);
        let mut next_retired = self.retired_operation_digests.clone();
        let mut retired_set: HashSet<String> = next_retired.iter().cloned().collect();
        for record in &self.operations {
            if remaining_to_retire > 0 && record.phase == OperationPhase::Terminal {
                let digest = retirement_digest(&record.endpoint_id, &record.key)?;
                if !retired_set.insert(digest.clone()) {
                    return Err(ShellError::State(
                        "active terminal operation already belongs to retirement frontier"
                            .to_owned(),
                    ));
                }
                next_retired.push(digest);
                remaining_to_retire -= 1;
            } else {
                next_operations.push(record.clone());
            }
        }
        next_retired.sort_unstable();
        next_retired.dedup();
        if next_retired.len() > MAX_RETIRED_OPERATION_DIGESTS {
            return Err(ShellError::State(format!(
                "operation retirement frontier reached {MAX_RETIRED_OPERATION_DIGESTS} entries"
            )));
        }
        if let Err(error) = self.persist(&next_operations, &next_retired) {
            self.failed = true;
            return Err(error);
        }
        self.operations = next_operations;
        self.retired_operation_digests = next_retired;
        Ok(())
    }

    fn persist(
        &self,
        operations: &[OperationRecord],
        retired_operation_digests: &[String],
    ) -> Result<(), ShellError> {
        self.private_root.verify()?;
        let state = JournalFile {
            schema: JOURNAL_SCHEMA_V3.to_owned(),
            operations: operations.to_vec(),
            retired_operation_digests: retired_operation_digests.to_vec(),
        };
        let bytes = serde_json::to_vec(&state)?;
        if bytes.len() as u64 > MAX_JOURNAL_BYTES {
            return Err(ShellError::State(format!(
                "operation journal would exceed {MAX_JOURNAL_BYTES} bytes"
            )));
        }
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let mut file = AtomicWriteFile::open(&self.path)?;
        file.write_all(&bytes)?;
        file.sync_all()?;
        file.commit()?;
        ensure_private_state_file(&self.path, false)?;
        sync_parent_directory(&self.path)?;
        Ok(())
    }
}

fn retirement_digest(endpoint_id: &str, key: &OperationKey) -> Result<String, ShellError> {
    validate_stable_id(endpoint_id, "retirement.endpoint_id")?;
    validate_stable_id(&key.session_id, "retirement.session_id")?;
    validate_stable_id(&key.operation_id, "retirement.operation_id")?;
    if key.session_generation == 0 {
        return Err(ShellError::State(
            "retired operation has zero session generation".to_owned(),
        ));
    }
    Ok(sha256_hex(serde_json::to_vec(&(
        "hepta.native-retired-operation.v1",
        endpoint_id,
        key,
    ))?))
}

fn phase_transition_allowed(from: OperationPhase, to: OperationPhase) -> bool {
    match from {
        OperationPhase::Prepared => matches!(
            to,
            OperationPhase::Prepared
                | OperationPhase::Invoking
                | OperationPhase::Indeterminate
                | OperationPhase::Terminal
        ),
        OperationPhase::Invoking => matches!(
            to,
            OperationPhase::Invoking | OperationPhase::Indeterminate | OperationPhase::Terminal
        ),
        OperationPhase::Indeterminate => {
            matches!(to, OperationPhase::Indeterminate | OperationPhase::Terminal)
        }
        OperationPhase::Terminal => to == OperationPhase::Terminal,
    }
}

#[cfg(unix)]
fn sync_parent_directory(path: &Path) -> Result<(), ShellError> {
    if let Some(parent) = path.parent() {
        File::open(parent)?.sync_all()?;
    }
    Ok(())
}

#[cfg(not(unix))]
fn sync_parent_directory(_path: &Path) -> Result<(), ShellError> {
    Ok(())
}

fn ensure_private_state_file(path: &Path, _preexisting: bool) -> Result<(), ShellError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(ShellError::Security(format!(
            "native operation journal state is not a regular local file: {}",
            path.display()
        )));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt as _;
        let mode = metadata.permissions().mode() & 0o777;
        if _preexisting && mode & 0o077 != 0 {
            return Err(ShellError::Security(format!(
                "native operation journal state is group/world accessible: {}",
                path.display()
            )));
        }
        if mode != 0o600 {
            std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
        }
    }
    Ok(())
}
