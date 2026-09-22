use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Write;
use std::path::Path;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::ReleaseId;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use crate::SupervisorError;
use crate::restart_policy::RESTART_ATTEMPT_BUDGET;
use crate::restart_policy::RESTART_RECOVERY_WINDOW;

pub(crate) const RESTART_JOURNAL_SCHEMA_VERSION: u32 = 1;
pub(crate) const RESTART_JOURNAL_FILE: &str = "supervisor-restart-budget.json";
const MAX_RESTART_JOURNAL_BYTES: u64 = 4_096;
const RESTART_JOURNAL_DOMAIN: &[u8] = b"hepta-supervisor:restart-budget:v1";
static RESTART_JOURNAL_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct DurableRestartWindow {
    pub attempts: u32,
    pub window_started_unix_millis: Option<u64>,
}

impl DurableRestartWindow {
    pub(crate) fn empty() -> Self {
        Self {
            attempts: 0,
            window_started_unix_millis: None,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RestartBudgetJournal {
    pub schema_version: u32,
    pub agent_id: AgentId,
    pub release_id: ReleaseId,
    pub main: DurableRestartWindow,
    pub matrix: DurableRestartWindow,
    pub journal_sha256: Sha256Digest,
}

impl RestartBudgetJournal {
    pub(crate) fn new(
        agent_id: AgentId,
        release_id: ReleaseId,
        main: DurableRestartWindow,
        matrix: DurableRestartWindow,
    ) -> Result<Self, SupervisorError> {
        let mut journal = Self {
            schema_version: RESTART_JOURNAL_SCHEMA_VERSION,
            agent_id,
            release_id,
            main,
            matrix,
            journal_sha256: Sha256Digest::for_bytes(b"pending"),
        };
        journal.journal_sha256 = journal.compute_digest()?;
        journal.validate()?;
        Ok(journal)
    }

    fn validate(&self) -> Result<(), SupervisorError> {
        if self.schema_version != RESTART_JOURNAL_SCHEMA_VERSION
            || !valid_window(&self.main)
            || !valid_window(&self.matrix)
            || self.journal_sha256 != self.compute_digest()?
        {
            return Err(SupervisorError::CorruptLease(
                "restart budget journal is malformed or has a digest mismatch".to_string(),
            ));
        }
        Ok(())
    }

    fn compute_digest(&self) -> Result<Sha256Digest, SupervisorError> {
        let payload = serde_json::to_vec(&(
            self.schema_version,
            &self.agent_id,
            &self.release_id,
            &self.main,
            &self.matrix,
        ))
        .map_err(|error| SupervisorError::CorruptLease(error.to_string()))?;
        Ok(Sha256Digest::from_sha256_output(Sha256::digest(
            [RESTART_JOURNAL_DOMAIN, payload.as_slice()].concat(),
        )))
    }
}

pub(crate) fn read_restart_journal(
    run_root: &Path,
) -> Result<Option<RestartBudgetJournal>, SupervisorError> {
    let path = run_root.join(RESTART_JOURNAL_FILE);
    let metadata = match std::fs::symlink_metadata(&path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    if !metadata.file_type().is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() > MAX_RESTART_JOURNAL_BYTES
    {
        return Err(SupervisorError::CorruptLease(
            "restart budget journal is not a bounded regular file".to_string(),
        ));
    }
    let journal: RestartBudgetJournal = serde_json::from_slice(&std::fs::read(path)?)
        .map_err(|error| SupervisorError::CorruptLease(error.to_string()))?;
    journal.validate()?;
    Ok(Some(journal))
}

pub(crate) fn write_restart_journal(
    run_root: &Path,
    journal: &RestartBudgetJournal,
) -> Result<(), SupervisorError> {
    journal.validate()?;
    std::fs::create_dir_all(run_root)?;
    let sequence = RESTART_JOURNAL_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let temp_path = run_root.join(format!(
        ".supervisor-restart-budget-{}-{sequence}.tmp",
        std::process::id()
    ));
    let final_path = run_root.join(RESTART_JOURNAL_FILE);
    let mut bytes = serde_json::to_vec(journal)
        .map_err(|error| SupervisorError::CorruptLease(error.to_string()))?;
    bytes.push(b'\n');
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp_path)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    drop(file);
    if let Err(error) = crate::durable_publish::publish(&temp_path, &final_path) {
        let _ = std::fs::remove_file(&temp_path);
        return Err(error.into());
    }
    Ok(())
}

pub(crate) fn unix_millis_now() -> Result<u64, SupervisorError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        .as_millis();
    u64::try_from(millis).map_err(|_| {
        SupervisorError::Invalid("system time exceeds restart journal range".to_string())
    })
}

pub(crate) fn restore_window(
    durable: &DurableRestartWindow,
    now: Instant,
    now_unix_millis: u64,
) -> (u32, Option<Instant>, Option<u64>, bool) {
    if durable.attempts == 0 {
        return (0, None, None, false);
    }
    let Some(started_unix_millis) = durable.window_started_unix_millis else {
        return (
            RESTART_ATTEMPT_BUDGET,
            Some(now),
            Some(now_unix_millis),
            true,
        );
    };
    let recovery_window_millis = u64::try_from(RESTART_RECOVERY_WINDOW.as_millis())
        .expect("bounded recovery window milliseconds");
    let Some(elapsed_millis) = now_unix_millis.checked_sub(started_unix_millis) else {
        // Wall-clock rollback is not allowed to buy extra restart attempts.
        return (
            RESTART_ATTEMPT_BUDGET,
            Some(now),
            Some(now_unix_millis),
            true,
        );
    };
    if elapsed_millis >= recovery_window_millis {
        return (0, None, None, false);
    }
    let elapsed = Duration::from_millis(elapsed_millis);
    let started = now.checked_sub(elapsed).unwrap_or(now);
    (
        durable.attempts,
        Some(started),
        Some(started_unix_millis),
        durable.attempts >= RESTART_ATTEMPT_BUDGET,
    )
}

fn valid_window(window: &DurableRestartWindow) -> bool {
    window.attempts <= RESTART_ATTEMPT_BUDGET
        && ((window.attempts == 0 && window.window_started_unix_millis.is_none())
            || (window.attempts > 0 && window.window_started_unix_millis.is_some()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn restart_journal_round_trips_and_rejects_clock_rollback_with_full_budget() {
        let dir = tempfile::tempdir().expect("temp");
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent");
        let release = ReleaseId::parse("release-a").expect("release");
        let journal = RestartBudgetJournal::new(
            agent,
            release,
            DurableRestartWindow {
                attempts: 2,
                window_started_unix_millis: Some(2_000),
            },
            DurableRestartWindow::empty(),
        )
        .expect("journal");
        write_restart_journal(dir.path(), &journal).expect("write");
        assert_eq!(
            read_restart_journal(dir.path()).expect("read"),
            Some(journal)
        );

        let now = Instant::now();
        let (attempts, started, wall, exhausted) = restore_window(
            &DurableRestartWindow {
                attempts: 2,
                window_started_unix_millis: Some(2_000),
            },
            now,
            1_000,
        );
        assert_eq!(attempts, RESTART_ATTEMPT_BUDGET);
        assert_eq!(started, Some(now));
        assert_eq!(wall, Some(1_000));
        assert!(exhausted);
    }
}
