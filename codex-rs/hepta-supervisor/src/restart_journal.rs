use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Write;
use std::path::Path;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
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
            && (main.schema_version != 1
                || main.window_started_unix_ms == 0
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

fn valid_window(window: &DurableRestartWindow) -> bool {
    window.attempts <= RESTART_ATTEMPT_BUDGET
        && ((window.attempts == 0 && window.window_started_unix_millis.is_none())
            || (window.attempts > 0 && window.window_started_unix_millis.is_some()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;

    #[test]
    fn restart_journal_writer_migrates_legacy_main_window() {
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
            read_record(dir.path())
                .expect("read")
                .and_then(|record| record.companion),
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
    }

    #[test]
    fn main_and_companion_writes_preserve_both_domains_and_wire_bytes() {
        let dir = tempfile::tempdir().expect("temp");
        let mut main = RestartBudgetState {
            schema_version: 1,
            window_started_unix_ms: 2_000,
            attempts: 2,
            pending: true,
            next_eligible_unix_ms: 2_500,
        };
        std::fs::write(
            dir.path().join(RESTART_JOURNAL_FILE),
            serde_json::to_vec(&main).expect("legacy main bytes"),
        )
        .expect("legacy main write");
        let companion = RestartBudgetJournal::new(
            AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent"),
            ReleaseId::parse("release-a").expect("release"),
            DurableRestartWindow::empty(),
            DurableRestartWindow {
                attempts: 1,
                window_started_unix_millis: Some(2_000),
            },
        )
        .expect("companion");
        write_restart_journal(dir.path(), &companion).expect("companion write");
        assert_eq!(
            read_main_restart_budget(dir.path()).expect("main after companion write"),
            Some(main.clone())
        );

        main.attempts = 3;
        main.pending = false;
        main.next_eligible_unix_ms = 3_000;
        write_main_restart_budget(dir.path(), &main).expect("next main write");
        let record = read_record(dir.path()).expect("record").expect("present");
        assert_eq!(
            (record.main, record.companion),
            (Some(main), Some(companion))
        );
        let expected = concat!(
            r#"{"schema_version":2,"main":{"schema_version":1,"window_started_unix_ms":2000,"#,
            r#""attempts":3,"pending":false,"next_eligible_unix_ms":3000},"#,
            r#""companion":{"schema_version":1,"#,
            r#""agent_id":"018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12","release_id":"release-a","#,
            r#""main":{"attempts":0,"window_started_unix_millis":null},"#,
            r#""matrix":{"attempts":1,"window_started_unix_millis":2000},"#,
            r#""journal_sha256":"ff05e9b0fd44bb99494c4ee38bd6752a10b32350c60dd4a4f66a5a68951b52ca"},"#,
            r#""record_sha256":"217bdeb3c67532e532ec754442f5ee5838fee911d1bf62bffc000b4a252e6af7"}"#,
            "\n",
        );
        assert_eq!(
            std::fs::read(dir.path().join(RESTART_JOURNAL_FILE)).expect("wire bytes"),
            expected.as_bytes()
        );
    }

    #[test]
    fn legacy_companion_read_preserves_attempts_without_rewriting_input() {
        let dir = tempfile::tempdir().expect("temp");
        let legacy = RestartBudgetJournal::new(
            AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent"),
            ReleaseId::parse("release-a").expect("release"),
            DurableRestartWindow {
                attempts: 2,
                window_started_unix_millis: Some(2_000),
            },
            DurableRestartWindow {
                attempts: 1,
                window_started_unix_millis: Some(2_000),
            },
        )
        .expect("legacy journal");
        let path = dir.path().join(RESTART_JOURNAL_FILE);
        let original = serde_json::to_vec(&legacy).expect("legacy bytes");
        std::fs::write(&path, &original).expect("legacy write");
        let expected_main = RestartBudgetState {
            schema_version: 1,
            window_started_unix_ms: 2_000,
            attempts: 2,
            pending: false,
            next_eligible_unix_ms: 2_000,
        };
        let expected_companion = RestartBudgetJournal::new(
            legacy.agent_id,
            legacy.release_id,
            DurableRestartWindow::empty(),
            legacy.matrix,
        )
        .expect("normalized companion");
        let record = read_record(dir.path()).expect("migrate").expect("present");
        assert_eq!(
            (record.main, record.companion),
            (
                Some(expected_main.clone()),
                Some(expected_companion.clone())
            )
        );
        assert_eq!(std::fs::read(&path).expect("original bytes"), original);

        write_main_restart_budget(dir.path(), &expected_main).expect("canonical write");
        let record = read_record(dir.path())
            .expect("canonical read")
            .expect("present");
        assert_eq!(
            (record.main, record.companion),
            (Some(expected_main), Some(expected_companion))
        );
    }

    #[test]
    fn stale_projection_and_corrupt_record_cannot_replace_current_budget() {
        let dir = tempfile::tempdir().expect("temp");
        let main = RestartBudgetState {
            schema_version: 1,
            window_started_unix_ms: 2_000,
            attempts: 2,
            pending: true,
            next_eligible_unix_ms: 2_500,
        };
        write_main_restart_budget(dir.path(), &main).expect("main write");
        let path = dir.path().join(RESTART_JOURNAL_FILE);
        let original = std::fs::read(&path).expect("original bytes");
        let stale = RestartBudgetJournal::new(
            AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent"),
            ReleaseId::parse("release-a").expect("release"),
            DurableRestartWindow {
                attempts: 1,
                window_started_unix_millis: Some(2_000),
            },
            DurableRestartWindow::empty(),
        )
        .expect("stale projection");
        assert!(matches!(
            write_restart_journal(dir.path(), &stale),
            Err(SupervisorError::CorruptLease(_))
        ));
        assert_eq!(std::fs::read(&path).expect("unchanged bytes"), original);

        let mut corrupt: serde_json::Value = serde_json::from_slice(&original).expect("record");
        corrupt["main"]["attempts"] = serde_json::json!(0);
        let corrupt = serde_json::to_vec(&corrupt).expect("corrupt bytes");
        std::fs::write(&path, &corrupt).expect("corrupt write");
        assert!(matches!(
            read_main_restart_budget(dir.path()),
            Err(SupervisorError::CorruptLease(_))
        ));
        assert!(matches!(
            write_main_restart_budget(dir.path(), &main),
            Err(SupervisorError::CorruptLease(_))
        ));
        assert_eq!(
            std::fs::read(&path).expect("corrupt bytes retained"),
            corrupt
        );
    }

    #[test]
    fn active_main_budget_rejects_clock_rollback_without_replenishing_attempts() {
        let dir = tempfile::tempdir().expect("temp");
        let main = RestartBudgetState {
            schema_version: 1,
            window_started_unix_ms: u64::MAX - 1,
            attempts: 2,
            pending: false,
            next_eligible_unix_ms: u64::MAX - 1,
        };
        write_main_restart_budget(dir.path(), &main).expect("future main write");
        let path = dir.path().join(RESTART_JOURNAL_FILE);
        let original = std::fs::read(&path).expect("original bytes");
        assert!(matches!(
            crate::restart_budget::claim_restart(
                dir.path(),
                /*maximum_attempts*/ 3,
                std::time::Duration::from_secs(/*secs*/ 300),
                std::time::Duration::from_millis(/*millis*/ 250),
            ),
            Err(crate::restart_budget::RestartBudgetError::Invalid(_))
        ));
        assert_eq!(
            read_main_restart_budget(dir.path()).expect("read"),
            Some(main)
        );
        assert_eq!(std::fs::read(&path).expect("unchanged bytes"), original);
    }
}
