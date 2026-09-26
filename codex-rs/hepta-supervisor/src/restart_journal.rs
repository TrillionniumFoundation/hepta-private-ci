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
use crate::restart_budget::RestartBudgetState;
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

// One physical writer/codec owns both independent restart domains. The main
// Agent budget includes a pending intent; Matrix has a separate release-bound
// fault window. They may not overwrite each other's record at this path.
const RESTART_RECORD_SCHEMA: u32 = 2;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct RestartRecord {
    schema_version: u32,
    main: Option<RestartBudgetState>,
    companion: Option<RestartBudgetJournal>,
    record_sha256: Sha256Digest,
}

impl RestartRecord {
    fn empty() -> Self {
        Self {
            schema_version: RESTART_RECORD_SCHEMA,
            main: None,
            companion: None,
            record_sha256: Sha256Digest::for_bytes(b"pending"),
        }
    }

    fn digest(&self) -> Result<Sha256Digest, SupervisorError> {
        let payload = serde_json::to_vec(&(self.schema_version, &self.main, &self.companion))
            .map_err(|error| SupervisorError::CorruptLease(error.to_string()))?;
        Ok(Sha256Digest::from_sha256_output(Sha256::digest(
            [
                b"hepta-supervisor:restart-record:v2".as_slice(),
                payload.as_slice(),
            ]
            .concat(),
        )))
    }

    fn validate(&self) -> Result<(), SupervisorError> {
        if self.schema_version != RESTART_RECORD_SCHEMA
            || self.record_sha256 != self.digest()?
            || (self.main.is_none() && self.companion.is_none())
        {
            return Err(SupervisorError::CorruptLease(
                "invalid canonical restart record".to_string(),
            ));
        }
        if let Some(main) = &self.main
            && (!matches!(
                main.schema_version,
                1 | crate::restart_budget::RESTART_BUDGET_SCHEMA_VERSION
            ) || (main.schema_version == 1 && main.release_binding.is_some())
                || (main.schema_version == crate::restart_budget::RESTART_BUDGET_SCHEMA_VERSION
                    && main.pending
                    && main.release_binding.is_none())
                || main.window_started_unix_ms == 0
                || (main.operator_stopped && main.pending)
                || (main.pending_requires_spawn && !main.pending)
                || (main.pending
                    && (main.attempts == 0
                        || main.next_eligible_unix_ms < main.window_started_unix_ms)))
        {
            return Err(SupervisorError::CorruptLease(
                "invalid pending restart state".to_string(),
            ));
        }
        if let Some(companion) = &self.companion {
            companion.validate()?;
            if companion.main != DurableRestartWindow::empty() {
                return Err(SupervisorError::CorruptLease(
                    "duplicate main restart authority".to_string(),
                ));
            }
        }
        Ok(())
    }
}

fn legacy_main(
    window: &DurableRestartWindow,
) -> Result<Option<RestartBudgetState>, SupervisorError> {
    if window.attempts == 0 {
        return Ok(None);
    }
    let started = window
        .window_started_unix_millis
        .filter(|value| *value > 0)
        .ok_or_else(|| {
            SupervisorError::CorruptLease("legacy restart window has no valid origin".to_string())
        })?;
    Ok(Some(RestartBudgetState {
        schema_version: 1,
        window_started_unix_ms: started,
        attempts: window.attempts,
        pending: false,
        release_binding: None,
        operator_stopped: false,
        pending_requires_spawn: false,
        next_eligible_unix_ms: started,
    }))
}

fn read_record(run_root: &Path) -> Result<Option<RestartRecord>, SupervisorError> {
    use std::io::Read;
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
            "restart record is not a bounded regular file".to_string(),
        ));
    }
    let mut bytes = Vec::new();
    std::fs::File::open(path)?
        .take(MAX_RESTART_JOURNAL_BYTES + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_RESTART_JOURNAL_BYTES {
        return Err(SupervisorError::CorruptLease(
            "restart record grew beyond its bound".to_string(),
        ));
    }
    let value: serde_json::Value = serde_json::from_slice(&bytes)
        .map_err(|error| SupervisorError::CorruptLease(error.to_string()))?;
    let mut record = if value
        .get("schema_version")
        .and_then(serde_json::Value::as_u64)
        == Some(2)
    {
        let record: RestartRecord = serde_json::from_value(value)
            .map_err(|error| SupervisorError::CorruptLease(error.to_string()))?;
        record.validate()?;
        return Ok(Some(record));
    } else if value.get("agent_id").is_some() {
        // The historical companion writer also carried a main-window
        // projection. Migrate its acknowledged attempts, never erase them.
        let old: RestartBudgetJournal = serde_json::from_value(value)
            .map_err(|error| SupervisorError::CorruptLease(error.to_string()))?;
        old.validate()?;
        let main = legacy_main(&old.main)?;
        let companion = RestartBudgetJournal::new(
            old.agent_id,
            old.release_id,
            DurableRestartWindow::empty(),
            old.matrix,
        )?;
        RestartRecord {
            main,
            companion: Some(companion),
            ..RestartRecord::empty()
        }
    } else {
        let main: RestartBudgetState = serde_json::from_value(value)
            .map_err(|error| SupervisorError::CorruptLease(error.to_string()))?;
        RestartRecord {
            main: Some(main),
            ..RestartRecord::empty()
        }
    };
    record.record_sha256 = record.digest()?;
    record.validate()?;
    Ok(Some(record))
}

fn write_record(run_root: &Path, mut record: RestartRecord) -> Result<(), SupervisorError> {
    record.record_sha256 = record.digest()?;
    record.validate()?;
    std::fs::create_dir_all(run_root)?;
    let sequence = RESTART_JOURNAL_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let temp_path = run_root.join(format!(
        ".supervisor-restart-budget-{}-{sequence}.tmp",
        std::process::id()
    ));
    let final_path = run_root.join(RESTART_JOURNAL_FILE);
    let mut bytes = serde_json::to_vec(&record)
        .map_err(|error| SupervisorError::CorruptLease(error.to_string()))?;
    bytes.push(b'\n');
    if bytes.len() as u64 > MAX_RESTART_JOURNAL_BYTES {
        return Err(SupervisorError::CorruptLease(
            "restart record exceeds bound".to_string(),
        ));
    }
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(&temp_path)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    drop(file);
    if let Err(error) = crate::durable_publish::publish(&temp_path, &final_path) {
        let _ = std::fs::remove_file(&temp_path);
        return Err(error.into());
    }
    Ok(())
}

pub(crate) fn read_main_restart_budget(
    run_root: &Path,
) -> Result<Option<RestartBudgetState>, SupervisorError> {
    Ok(read_record(run_root)?.and_then(|record| record.main))
}

pub(crate) fn write_main_restart_budget(
    run_root: &Path,
    state: &RestartBudgetState,
) -> Result<(), SupervisorError> {
    let mut record = read_record(run_root)?.unwrap_or_else(RestartRecord::empty);
    record.main = Some(state.clone());
    write_record(run_root, record)
}

pub(crate) fn read_restart_journal(
    run_root: &Path,
) -> Result<Option<RestartBudgetJournal>, SupervisorError> {
    let Some(record) = read_record(run_root)? else {
        return Ok(None);
    };
    Ok(record.companion)
}

pub(crate) fn write_restart_journal(
    run_root: &Path,
    journal: &RestartBudgetJournal,
) -> Result<(), SupervisorError> {
    journal.validate()?;
    let mut record = read_record(run_root)?.unwrap_or_else(RestartRecord::empty);
    if journal.main != DurableRestartWindow::empty() {
        let legacy = legacy_main(&journal.main)?;
        if record.main.is_some() && record.main != legacy {
            return Err(SupervisorError::CorruptLease(
                "stale main-window projection cannot overwrite current restart state".to_string(),
            ));
        }
        record.main = legacy;
    }
    record.companion = Some(RestartBudgetJournal::new(
        journal.agent_id.clone(),
        journal.release_id.clone(),
        DurableRestartWindow::empty(),
        journal.matrix.clone(),
    )?);
    write_record(run_root, record)
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
    let Ok(recovery_window_millis) = u64::try_from(RESTART_RECOVERY_WINDOW.as_millis()) else {
        return (
            RESTART_ATTEMPT_BUDGET,
            Some(now),
            Some(now_unix_millis),
            true,
        );
    };
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
            Some(
                RestartBudgetJournal::new(
                    journal.agent_id,
                    journal.release_id,
                    DurableRestartWindow::empty(),
                    journal.matrix
                )
                .expect("companion projection")
            )
        );
        assert_eq!(
            read_main_restart_budget(dir.path())
                .expect("main projection")
                .expect("main budget")
                .attempts,
            2
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
