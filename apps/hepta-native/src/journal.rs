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
use crate::model::validate_digest;
use crate::model::validate_stable_id;

const JOURNAL_SCHEMA: &str = "hepta.native-operation-journal.v1";
const MAX_JOURNAL_BYTES: u64 = 8 * 1024 * 1024;
const MAX_OPERATION_RECORDS: usize = 4096;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OperationPhase {
    Prepared,
    Invoking,
    Indeterminate,
    Terminal,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct OperationRecord {
    pub endpoint_id: String,
    pub key: OperationKey,
    pub action: PlatformAction,
    pub payload_digest: String,
    pub phase: OperationPhase,
    pub terminal_status: Option<TerminalStatus>,
    pub outcome_digest: Option<String>,
}

impl OperationRecord {
    pub fn validate(&self) -> Result<(), ShellError> {
        validate_stable_id(&self.endpoint_id, "journal.endpoint_id")?;
        validate_stable_id(&self.key.session_id, "journal.session_id")?;
        validate_stable_id(&self.key.operation_id, "journal.operation_id")?;
        if self.key.session_generation == 0 {
            return Err(ShellError::State(
                "journal operation has zero session generation".to_owned(),
            ));
        }
        validate_digest(&self.payload_digest, "journal.payload_digest")?;
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
            | OperationPhase::Indeterminate => {
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
struct JournalFile {
    schema: String,
    operations: Vec<OperationRecord>,
}

#[derive(Debug, Clone)]
pub struct OperationJournal {
    path: PathBuf,
    operations: Vec<OperationRecord>,
}

impl OperationJournal {
    pub fn open(path: impl Into<PathBuf>) -> Result<Self, ShellError> {
        let path = path.into();
        if !path.is_absolute() {
            return Err(ShellError::InvalidInput(
                "operation journal path must be absolute".to_owned(),
            ));
        }
        if !path.exists() {
            return Ok(Self {
                path,
                operations: Vec::new(),
            });
        }
        let metadata = std::fs::metadata(&path)?;
        if metadata.len() > MAX_JOURNAL_BYTES {
            return Err(ShellError::State(format!(
                "operation journal exceeds {MAX_JOURNAL_BYTES} bytes"
            )));
        }
        let bytes = std::fs::read(&path)?;
        let state: JournalFile = serde_json::from_slice(&bytes)?;
        if state.schema != JOURNAL_SCHEMA {
            return Err(ShellError::State(
                "operation journal schema is not supported".to_owned(),
            ));
        }
        if state.operations.len() > MAX_OPERATION_RECORDS {
            return Err(ShellError::State(format!(
                "operation journal exceeds {MAX_OPERATION_RECORDS} records"
            )));
        }
        for operation in &state.operations {
            operation.validate()?;
        }
        Ok(Self {
            path,
            operations: state.operations,
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

    pub fn upsert(&mut self, record: OperationRecord) -> Result<(), ShellError> {
        record.validate()?;
        if let Some(index) = self
            .operations
            .iter()
            .position(|existing| existing.key == record.key)
        {
            let existing = &self.operations[index];
            if existing.payload_digest != record.payload_digest || existing.action != record.action {
                return Err(ShellError::State(
                    "operation identity was reused with changed semantics".to_owned(),
                ));
            }
            if !phase_transition_allowed(existing.phase, record.phase) {
                return Err(ShellError::State(format!(
                    "operation phase cannot transition from {:?} to {:?}",
                    existing.phase, record.phase
                )));
            }
            self.operations[index] = record;
        } else {
            if self.operations.len() >= MAX_OPERATION_RECORDS {
                return Err(ShellError::State(format!(
                    "operation journal reached {MAX_OPERATION_RECORDS} records"
                )));
            }
            self.operations.push(record);
        }
        self.persist()
    }

    pub fn compact_terminal(&mut self, keep_latest: usize) -> Result<(), ShellError> {
        let terminal_count = self
            .operations
            .iter()
            .filter(|record| record.phase == OperationPhase::Terminal)
            .count();
        if terminal_count <= keep_latest {
            return Ok(());
        }
        let mut remove = terminal_count - keep_latest;
        self.operations.retain(|record| {
            if remove > 0 && record.phase == OperationPhase::Terminal {
                remove -= 1;
                false
            } else {
                true
            }
        });
        self.persist()
    }

    fn persist(&self) -> Result<(), ShellError> {
        let state = JournalFile {
            schema: JOURNAL_SCHEMA.to_owned(),
            operations: self.operations.clone(),
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
        Ok(())
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
