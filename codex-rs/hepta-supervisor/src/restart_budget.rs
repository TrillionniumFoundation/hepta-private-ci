//! Durable bounded automatic-restart budget for one supervised Agent.

use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Write;
use std::path::Path;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::SystemTime;

use codex_hepta_contracts::AgentId;
use serde::Deserialize;
use serde::Serialize;

use crate::SupervisorError;

pub(crate) const RESTART_BUDGET_SCHEMA_VERSION: u32 = 1;
const RESTART_BUDGET_FILE: &str = "supervisor-restart-budget.json";
static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RestartBudgetRecord {
    pub schema_version: u32,
    pub agent_id: AgentId,
    pub window_started_unix_ms: u64,
    pub attempts: u8,
    pub not_before_unix_ms: u64,
}

impl RestartBudgetRecord {
    pub(crate) fn validate(&self) -> Result<(), SupervisorError> {
        if self.schema_version != RESTART_BUDGET_SCHEMA_VERSION
            || self.window_started_unix_ms == 0
            || self.attempts == 0
            || self.attempts > 64
            || self.not_before_unix_ms < self.window_started_unix_ms
        {
            return Err(SupervisorError::Invalid(
                "restart budget record is malformed".to_string(),
            ));
        }
        Ok(())
    }
}

pub(crate) fn unix_millis_now() -> Result<u64, SupervisorError> {
    let millis = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .map_err(|_| SupervisorError::Invalid("system clock before epoch".to_string()))?
        .as_millis();
    u64::try_from(millis)
        .map_err(|_| SupervisorError::Invalid("system clock exceeds u64 milliseconds".to_string()))
}

pub(crate) fn read_restart_budget(
    run_root: &Path,
    agent_id: &AgentId,
) -> Result<Option<RestartBudgetRecord>, SupervisorError> {
    let path = run_root.join(RESTART_BUDGET_FILE);
    let bytes = match std::fs::read(&path) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    if bytes.len() > 4 * 1024 {
        return Err(SupervisorError::Invalid(
            "restart budget record exceeds bounded size".to_string(),
        ));
    }
    let record: RestartBudgetRecord = serde_json::from_slice(&bytes)
        .map_err(|error| SupervisorError::Invalid(format!("decode restart budget: {error}")))?;
    record.validate()?;
    if &record.agent_id != agent_id {
        return Err(SupervisorError::Invalid(
            "restart budget Agent binding mismatch".to_string(),
        ));
    }
    Ok(Some(record))
}

pub(crate) fn write_restart_budget(
    run_root: &Path,
    record: &RestartBudgetRecord,
) -> Result<(), SupervisorError> {
    record.validate()?;
    std::fs::create_dir_all(run_root)?;
    let final_path = run_root.join(RESTART_BUDGET_FILE);
    let sequence = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let temp = run_root.join(format!(
        ".{RESTART_BUDGET_FILE}.{}.{sequence}.tmp",
        std::process::id()
    ));
    let mut bytes = serde_json::to_vec(record)
        .map_err(|error| SupervisorError::Invalid(format!("encode restart budget: {error}")))?;
    bytes.push(b'\n');
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    drop(file);
    std::fs::rename(&temp, &final_path)?;
    sync_directory(run_root)
}

pub(crate) fn clear_restart_budget(run_root: &Path) -> Result<(), SupervisorError> {
    let path = run_root.join(RESTART_BUDGET_FILE);
    match std::fs::remove_file(&path) {
        Ok(()) => sync_directory(run_root),
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error.into()),
    }
}

#[cfg(unix)]
fn sync_directory(path: &Path) -> Result<(), SupervisorError> {
    std::fs::File::open(path)?.sync_all()?;
    Ok(())
}

#[cfg(not(unix))]
fn sync_directory(_path: &Path) -> Result<(), SupervisorError> {
    Ok(())
}
