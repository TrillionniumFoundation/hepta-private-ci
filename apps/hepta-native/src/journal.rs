use crate::MAX_JSON_BYTES;
use crate::types::DecisionStatus;
use crate::types::OperationKey;
use crate::types::PlatformAction;
use crate::types::PlatformDecision;
use fs2::FileExt as _;
use serde::Deserialize;
use serde::Serialize;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read as _;
use std::io::Seek as _;
use std::io::SeekFrom;
use std::io::Write as _;
use std::path::Path;
use std::path::PathBuf;
use thiserror::Error;

const MAX_JOURNAL_BYTES: u64 = 8 * 1024 * 1024;
const MAX_RECORDS: usize = 16_384;

#[derive(Debug, Error)]
pub enum JournalError {
    #[error("journal I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("journal is malformed or exceeds a bound")]
    Invalid,
    #[error("operation identity was reused with changed payload or action")]
    IdentityReuse,
    #[error("terminal reconciliation must be an observed terminal result")]
    InvalidTerminal,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(tag = "phase", rename_all = "snake_case")]
enum RecordPhase {
    Dispatching,
    Terminal { decision: PlatformDecision },
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct OperationRecord {
    schema: String,
    key: OperationKey,
    action: PlatformAction,
    payload_digest: String,
    phase: RecordPhase,
}

#[derive(Clone, Debug)]
pub enum DispatchDisposition {
    Started,
    Indeterminate,
    Terminal(PlatformDecision),
}

#[derive(Clone, Debug)]
pub struct OperationJournal {
    path: PathBuf,
}

impl OperationJournal {
    pub fn open(path: PathBuf) -> Result<Self, JournalError> {
        if let Some(parent) = path.parent() {
            ensure_directory(parent)?;
        }
        let _ = open_rw(&path)?;
        Ok(Self { path })
    }

    pub fn begin_dispatch(
        &self,
        key: &OperationKey,
        action: PlatformAction,
        payload_digest: &str,
    ) -> Result<DispatchDisposition, JournalError> {
        self.with_locked_records(|file, records| {
            if let Some(record) = records.iter().rev().find(|record| record.key == *key) {
                if record.payload_digest != payload_digest || record.action != action {
                    return Err(JournalError::IdentityReuse);
                }
                return Ok(match &record.phase {
                    RecordPhase::Dispatching => DispatchDisposition::Indeterminate,
                    RecordPhase::Terminal { decision } => {
                        DispatchDisposition::Terminal(decision.clone())
                    }
                });
            }
            let record = OperationRecord {
                schema: "hepta.native.operation-journal.v1".to_string(),
                key: key.clone(),
                action,
                payload_digest: payload_digest.to_string(),
                phase: RecordPhase::Dispatching,
            };
            append_record(file, &record)?;
            Ok(DispatchDisposition::Started)
        })
    }

    pub fn finish(
        &self,
        key: &OperationKey,
        action: PlatformAction,
        payload_digest: &str,
        decision: PlatformDecision,
    ) -> Result<(), JournalError> {
        if !decision.terminal_observed
            || matches!(decision.status, DecisionStatus::Indeterminate)
            || decision.key != *key
            || decision.action != action
        {
            return Err(JournalError::InvalidTerminal);
        }
        self.with_locked_records(|file, records| {
            let prior = records
                .iter()
                .rev()
                .find(|record| record.key == *key)
                .ok_or(JournalError::Invalid)?;
            if prior.payload_digest != payload_digest || prior.action != action {
                return Err(JournalError::IdentityReuse);
            }
            if let RecordPhase::Terminal { decision: existing } = &prior.phase {
                if *existing == decision {
                    return Ok(());
                }
                return Err(JournalError::IdentityReuse);
            }
            let record = OperationRecord {
                schema: "hepta.native.operation-journal.v1".to_string(),
                key: key.clone(),
                action,
                payload_digest: payload_digest.to_string(),
                phase: RecordPhase::Terminal { decision },
            };
            append_record(file, &record)
        })
    }

    pub fn inspect(
        &self,
        key: &OperationKey,
        action: PlatformAction,
        payload_digest: &str,
    ) -> Result<Option<DispatchDisposition>, JournalError> {
        self.with_locked_records(|_, records| {
            let Some(record) = records.iter().rev().find(|record| record.key == *key) else {
                return Ok(None);
            };
            if record.payload_digest != payload_digest || record.action != action {
                return Err(JournalError::IdentityReuse);
            }
            Ok(Some(match &record.phase {
                RecordPhase::Dispatching => DispatchDisposition::Indeterminate,
                RecordPhase::Terminal { decision } => {
                    DispatchDisposition::Terminal(decision.clone())
                }
            }))
        })
    }

    fn with_locked_records<T>(
        &self,
        operation: impl FnOnce(&mut File, &[OperationRecord]) -> Result<T, JournalError>,
    ) -> Result<T, JournalError> {
        let mut file = open_rw(&self.path)?;
        FileExt::lock_exclusive(&file)?;
        let result = (|| {
            let records = read_records(&mut file)?;
            operation(&mut file, &records)
        })();
        let unlock = FileExt::unlock(&file);
        match (result, unlock) {
            (Ok(value), Ok(())) => Ok(value),
            (Err(error), _) => Err(error),
            (Ok(_), Err(error)) => Err(JournalError::Io(error)),
        }
    }
}

#[derive(Clone, Debug)]
pub struct NonceJournal {
    path: PathBuf,
}

impl NonceJournal {
    pub fn open(path: PathBuf) -> Result<Self, JournalError> {
        if let Some(parent) = path.parent() {
            ensure_directory(parent)?;
        }
        let _ = open_rw(&path)?;
        Ok(Self { path })
    }

    pub fn claim(&self, nonce: &str) -> Result<bool, JournalError> {
        let mut file = open_rw(&self.path)?;
        FileExt::lock_exclusive(&file)?;
        let result = (|| {
            let size = file.metadata()?.len();
            if size > MAX_JOURNAL_BYTES {
                return Err(JournalError::Invalid);
            }
            file.seek(SeekFrom::Start(0))?;
            let mut text = String::new();
            file.take(MAX_JOURNAL_BYTES + 1).read_to_string(&mut text)?;
            let mut count = 0usize;
            for line in text.lines() {
                count += 1;
                if count > MAX_RECORDS || line.len() > 256 {
                    return Err(JournalError::Invalid);
                }
                if line == nonce {
                    return Ok(false);
                }
            }
            if count >= MAX_RECORDS {
                return Err(JournalError::Invalid);
            }
            file.seek(SeekFrom::End(0))?;
            writeln!(file, "{nonce}")?;
            file.sync_all()?;
            Ok(true)
        })();
        let unlock = FileExt::unlock(&file);
        match (result, unlock) {
            (Ok(value), Ok(())) => Ok(value),
            (Err(error), _) => Err(error),
            (Ok(_), Err(error)) => Err(JournalError::Io(error)),
        }
    }
}

fn read_records(file: &mut File) -> Result<Vec<OperationRecord>, JournalError> {
    let size = file.metadata()?.len();
    if size > MAX_JOURNAL_BYTES {
        return Err(JournalError::Invalid);
    }
    file.seek(SeekFrom::Start(0))?;
    let mut bytes = Vec::new();
    file.take(MAX_JOURNAL_BYTES + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_JOURNAL_BYTES {
        return Err(JournalError::Invalid);
    }
    let mut records = Vec::new();
    for line in bytes
        .split(|byte| *byte == b'\n')
        .filter(|line| !line.is_empty())
    {
        if line.len() > MAX_JSON_BYTES {
            return Err(JournalError::Invalid);
        }
        records.push(serde_json::from_slice(line).map_err(|_| JournalError::Invalid)?);
        if records.len() > MAX_RECORDS {
            return Err(JournalError::Invalid);
        }
    }
    Ok(records)
}

fn append_record(file: &mut File, record: &OperationRecord) -> Result<(), JournalError> {
    let encoded = serde_json::to_vec(record).map_err(|_| JournalError::Invalid)?;
    if encoded.len() > MAX_JSON_BYTES {
        return Err(JournalError::Invalid);
    }
    let current = file.metadata()?.len();
    let next = current
        .checked_add(u64::try_from(encoded.len() + 1).map_err(|_| JournalError::Invalid)?)
        .ok_or(JournalError::Invalid)?;
    if next > MAX_JOURNAL_BYTES {
        return Err(JournalError::Invalid);
    }
    file.seek(SeekFrom::End(0))?;
    file.write_all(&encoded)?;
    file.write_all(b"\n")?;
    file.sync_all()?;
    Ok(())
}

fn ensure_directory(path: &Path) -> Result<(), JournalError> {
    std::fs::create_dir_all(path)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt as _;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))?;
    }
    Ok(())
}

fn open_rw(path: &Path) -> Result<File, JournalError> {
    let mut options = OpenOptions::new();
    options.create(true).read(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt as _;
        options.mode(0o600);
    }
    Ok(options.open(path)?)
}
