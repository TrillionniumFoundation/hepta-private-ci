use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::BufRead;
use std::io::BufReader;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::platform::PlatformAction;
use crate::shell::OperationRecord;
use crate::shell::PlatformDecision;
use crate::shell::PlatformDecisionStatus;
use crate::shell::SessionOperationKey;

const JOURNAL_SCHEMA: &str = "hepta.ui.native.operation-journal.v1";
const MAX_JOURNAL_BYTES: u64 = 16 * 1024 * 1024;
const MAX_JOURNAL_LINE_BYTES: usize = 16 * 1024;
const MAX_JOURNAL_LINES: usize = 16_384;
const MAX_UNIQUE_OPERATIONS: usize = 4_096;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct JournalRecordV1 {
    schema: String,
    session_id: String,
    session_generation: u64,
    operation_id: String,
    action: String,
    payload_digest: String,
    grant_receipt_digest: String,
    status: String,
    terminal_observed: bool,
    outcome_digest: Option<String>,
}

#[derive(Debug)]
pub enum JournalError {
    PathNotAbsolute,
    ParentMissing,
    InsecurePermissions,
    TooLarge,
    TooManyRecords,
    LineTooLarge,
    TruncatedRecord,
    InvalidRecord,
    ConflictingRecord,
    WriterUnavailable,
    Io(String),
    Serialization(String),
}

impl fmt::Display for JournalError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for JournalError {}

/// Append-only, sync-before-return operation journal.
///
/// The journal records an indeterminate dispatch intent before an OS effect is
/// invoked. A crash can therefore lose a terminal observation, but it cannot
/// make an uncertain operation safe to replay. Reopen reconstructs the latest
/// state per session-fenced operation and requires reconciliation for every
/// non-terminal record.
#[derive(Debug)]
pub(crate) struct DurableShellJournal {
    path: PathBuf,
    file: File,
    bytes_written: u64,
    lines_written: usize,
    poisoned: bool,
}

impl DurableShellJournal {
    pub(crate) fn open(
        path: impl Into<PathBuf>,
    ) -> Result<(Self, BTreeMap<SessionOperationKey, OperationRecord>), JournalError> {
        let path = path.into();
        if !path.is_absolute() {
            return Err(JournalError::PathNotAbsolute);
        }
        let parent = path.parent().ok_or(JournalError::ParentMissing)?;
        if !parent.is_dir() {
            return Err(JournalError::ParentMissing);
        }

        let existing = path.exists();
        let file = open_journal_file(&path)?;
        if existing {
            validate_private_permissions(&file)?;
        }
        file.try_lock()
            .map_err(|_| JournalError::WriterUnavailable)?;
        let metadata = file
            .metadata()
            .map_err(|error| JournalError::Io(error.to_string()))?;
        if metadata.len() > MAX_JOURNAL_BYTES {
            return Err(JournalError::TooLarge);
        }

        let (records, lines_written) = load_records(&file)?;
        #[cfg(unix)]
        File::open(parent)
            .and_then(|directory| directory.sync_all())
            .map_err(|error| JournalError::Io(error.to_string()))?;
        let journal = Self {
            path,
            file,
            bytes_written: metadata.len(),
            lines_written,
            poisoned: false,
        };
        Ok((journal, records))
    }

    pub(crate) fn append(&mut self, record: &OperationRecord) -> Result<(), JournalError> {
        if self.poisoned {
            return Err(JournalError::WriterUnavailable);
        }
        if self.lines_written >= MAX_JOURNAL_LINES {
            return Err(JournalError::TooManyRecords);
        }
        let wire = JournalRecordV1::from_operation(record);
        let mut bytes = serde_json::to_vec(&wire)
            .map_err(|error| JournalError::Serialization(error.to_string()))?;
        if bytes.len() > MAX_JOURNAL_LINE_BYTES {
            return Err(JournalError::LineTooLarge);
        }
        bytes.push(b'\n');
        let next_size = self
            .bytes_written
            .checked_add(u64::try_from(bytes.len()).map_err(|_| JournalError::TooLarge)?)
            .ok_or(JournalError::TooLarge)?;
        if next_size > MAX_JOURNAL_BYTES {
            return Err(JournalError::TooLarge);
        }
        let persisted = self
            .file
            .write_all(&bytes)
            .and_then(|()| self.file.flush())
            .and_then(|()| self.file.sync_all());
        if let Err(error) = persisted {
            self.poisoned = true;
            return Err(JournalError::Io(error.to_string()));
        }
        self.bytes_written = next_size;
        self.lines_written += 1;
        Ok(())
    }

    pub(crate) fn path(&self) -> &Path {
        &self.path
    }
}

fn load_records(
    file: &File,
) -> Result<(BTreeMap<SessionOperationKey, OperationRecord>, usize), JournalError> {
    let clone = file
        .try_clone()
        .map_err(|error| JournalError::Io(error.to_string()))?;
    let mut reader = BufReader::new(clone);
    let mut operations = BTreeMap::new();
    let mut lines = 0_usize;
    let mut journal_bytes = 0_u64;
    let mut line = Vec::new();
    loop {
        line.clear();
        let remaining = MAX_JOURNAL_BYTES.saturating_sub(journal_bytes) + 1;
        let limit = remaining.min(MAX_JOURNAL_LINE_BYTES as u64 + 2);
        let count = (&mut reader)
            .take(limit)
            .read_until(b'\n', &mut line)
            .map_err(|error| JournalError::Io(error.to_string()))?;
        if count == 0 {
            break;
        }
        journal_bytes = journal_bytes
            .checked_add(count as u64)
            .ok_or(JournalError::TooLarge)?;
        if count > MAX_JOURNAL_LINE_BYTES + 1 || journal_bytes > MAX_JOURNAL_BYTES {
            return Err(JournalError::TooLarge);
        }
        if line.pop() != Some(b'\n') {
            return Err(JournalError::TruncatedRecord);
        }
        if line.last() == Some(&b'\r') {
            line.pop();
        }
        if line.is_empty() {
            continue;
        }
        lines = lines.checked_add(1).ok_or(JournalError::TooManyRecords)?;
        if lines > MAX_JOURNAL_LINES || line.len() > MAX_JOURNAL_LINE_BYTES {
            return Err(JournalError::TooManyRecords);
        }
        let wire: JournalRecordV1 =
            serde_json::from_slice(&line).map_err(|_| JournalError::InvalidRecord)?;
        let record = wire.into_operation()?;
        if let Some(previous) = operations.get(&record.key) {
            validate_transition(previous, &record)?;
        } else if operations.len() >= MAX_UNIQUE_OPERATIONS {
            return Err(JournalError::TooManyRecords);
        }
        operations.insert(record.key.clone(), record);
    }
    Ok((operations, lines))
}

fn validate_transition(
    previous: &OperationRecord,
    next: &OperationRecord,
) -> Result<(), JournalError> {
    if previous.key != next.key
        || previous.action != next.action
        || previous.payload_digest != next.payload_digest
        || previous.grant_receipt_digest != next.grant_receipt_digest
    {
        return Err(JournalError::ConflictingRecord);
    }
    if previous.decision.terminal_observed && previous.decision != next.decision {
        return Err(JournalError::ConflictingRecord);
    }
    Ok(())
}

impl JournalRecordV1 {
    fn from_operation(record: &OperationRecord) -> Self {
        Self {
            schema: JOURNAL_SCHEMA.to_string(),
            session_id: record.key.session_id.to_string(),
            session_generation: record.key.session_generation.get(),
            operation_id: record.key.operation_id.to_string(),
            action: record.action.as_str().to_string(),
            payload_digest: record.payload_digest.to_string(),
            grant_receipt_digest: record.grant_receipt_digest.to_string(),
            status: status_label(&record.decision.status).to_string(),
            terminal_observed: record.decision.terminal_observed,
            outcome_digest: record.decision.outcome_digest.map(|value| value.to_string()),
        }
    }

    fn into_operation(self) -> Result<OperationRecord, JournalError> {
        if self.schema != JOURNAL_SCHEMA {
            return Err(JournalError::InvalidRecord);
        }
        let session_id = StableId::new(self.session_id).map_err(|_| JournalError::InvalidRecord)?;
        let session_generation =
            Generation::new(self.session_generation).map_err(|_| JournalError::InvalidRecord)?;
        let operation_id =
            StableId::new(self.operation_id).map_err(|_| JournalError::InvalidRecord)?;
        let action = PlatformAction::parse(&self.action).ok_or(JournalError::InvalidRecord)?;
        let payload_digest =
            Digest32::from_str(&self.payload_digest).map_err(|_| JournalError::InvalidRecord)?;
        let grant_receipt_digest = Digest32::from_str(&self.grant_receipt_digest)
            .map_err(|_| JournalError::InvalidRecord)?;
        if payload_digest.is_zero() || grant_receipt_digest.is_zero() {
            return Err(JournalError::InvalidRecord);
        }
        let status = parse_status(&self.status).ok_or(JournalError::InvalidRecord)?;
        let outcome_digest = self
            .outcome_digest
            .map(|value| Digest32::from_str(&value).map_err(|_| JournalError::InvalidRecord))
            .transpose()?;
        if outcome_digest.is_some_and(Digest32::is_zero) {
            return Err(JournalError::InvalidRecord);
        }
        if self.terminal_observed != is_terminal_status(&status) {
            return Err(JournalError::InvalidRecord);
        }
        if self.terminal_observed != outcome_digest.is_some() {
            return Err(JournalError::InvalidRecord);
        }
        let key = SessionOperationKey {
            session_id,
            session_generation,
            operation_id,
        };
        let decision = PlatformDecision {
            key: key.clone(),
            action,
            payload_digest,
            status,
            terminal_observed: self.terminal_observed,
            outcome_digest,
        };
        Ok(OperationRecord {
            key,
            action,
            payload_digest,
            grant_receipt_digest,
            decision,
        })
    }
}

fn status_label(status: &PlatformDecisionStatus) -> &'static str {
    match status {
        PlatformDecisionStatus::Rejected => "rejected",
        PlatformDecisionStatus::Indeterminate => "indeterminate",
        PlatformDecisionStatus::Succeeded => "succeeded",
        PlatformDecisionStatus::Failed => "failed",
    }
}

fn parse_status(value: &str) -> Option<PlatformDecisionStatus> {
    match value {
        "rejected" => Some(PlatformDecisionStatus::Rejected),
        "indeterminate" => Some(PlatformDecisionStatus::Indeterminate),
        "succeeded" => Some(PlatformDecisionStatus::Succeeded),
        "failed" => Some(PlatformDecisionStatus::Failed),
        _ => None,
    }
}

fn is_terminal_status(status: &PlatformDecisionStatus) -> bool {
    !matches!(status, PlatformDecisionStatus::Indeterminate)
}

fn open_journal_file(path: &Path) -> Result<File, JournalError> {
    let mut options = OpenOptions::new();
    options.create(true).read(true).append(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    options
        .open(path)
        .map_err(|error| JournalError::Io(error.to_string()))
}

#[cfg(unix)]
fn validate_private_permissions(file: &File) -> Result<(), JournalError> {
    use std::os::unix::fs::PermissionsExt;

    let mode = file
        .metadata()
        .map_err(|error| JournalError::Io(error.to_string()))?
        .permissions()
        .mode();
    if mode & 0o077 != 0 {
        return Err(JournalError::InsecurePermissions);
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_private_permissions(_file: &File) -> Result<(), JournalError> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::fs;

    use super::*;

    fn unique_path(name: &str) -> PathBuf {
        let mut path = std::env::temp_dir();
        path.push(format!(
            "hepta-native-{name}-{}-{}.journal",
            std::process::id(),
            crate::shell::now_unix_ms().unwrap_or(1)
        ));
        path
    }

    #[test]
    fn truncated_record_fails_closed_on_reopen() {
        let path = unique_path("truncated");
        fs::write(&path, b"{\"schema\":\"hepta.ui.native.operation-journal.v1\"")
            .unwrap_or_else(|error| panic!("write fixture: {error}"));
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;

            let permissions = fs::Permissions::from_mode(0o600);
            fs::set_permissions(&path, permissions)
                .unwrap_or_else(|error| panic!("set fixture permissions: {error}"));
        }
        let result = DurableShellJournal::open(&path);
        assert!(matches!(result, Err(JournalError::TruncatedRecord)));
        let _ = fs::remove_file(path);
    }
}
