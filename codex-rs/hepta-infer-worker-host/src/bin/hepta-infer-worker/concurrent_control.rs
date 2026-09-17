use std::collections::BTreeMap;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::thread;
use std::time::Duration;

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::Error as ControlError;
use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;
use codex_hepta_infer_core::durable_control::native::NativeRunStatus;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

const STATE_SCHEMA: &str = "hepta.inference.concurrent-budget.v1";
const ARCHIVE_SCHEMA: &str = "hepta.inference.concurrent-archive.v1";
const MAXIMUM_IN_FLIGHT: usize = 256;
const PER_REQUEST_JOURNAL_CAPACITY: usize = 8;
const LOCK_RETRY: Duration = Duration::from_millis(5);

#[derive(Debug)]
pub enum ConcurrentControlError {
    Invalid(&'static str),
    Busy,
    CapacityExceeded,
    Corrupt(&'static str),
    Io(String),
    Control(ControlError),
}

impl std::fmt::Display for ConcurrentControlError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl std::error::Error for ConcurrentControlError {}
impl From<std::io::Error> for ConcurrentControlError {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value.to_string())
    }
}
impl From<ControlError> for ConcurrentControlError {
    fn from(value: ControlError) -> Self {
        Self::Control(value)
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ActiveEntry {
    request_id: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct BudgetBody {
    schema: String,
    revision: u64,
    maximum_in_flight: usize,
    active: BTreeMap<String, ActiveEntry>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct BudgetEnvelope {
    body: BudgetBody,
    sha256: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum ArchiveDisposition {
    Terminal,
    PreDispatchStopped,
    QuarantinedIndeterminate,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ArchiveBody {
    schema: String,
    disposition: ArchiveDisposition,
    record: NativeRunRecord,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ArchiveEnvelope {
    body: ArchiveBody,
    sha256: String,
}

#[derive(Debug)]
pub struct ConcurrentBudgetOwner {
    root: PathBuf,
    state_path: PathBuf,
    lock_path: PathBuf,
    active_dir: PathBuf,
    archive_dir: PathBuf,
    lease_dir: PathBuf,
    maximum_in_flight: usize,
}

#[derive(Debug)]
pub struct BudgetReservation {
    request_id: String,
    request_key: String,
    journal_path: PathBuf,
    _lease: File,
}

impl BudgetReservation {
    pub fn journal_path(&self) -> &Path {
        &self.journal_path
    }
    pub fn request_id(&self) -> &str {
        &self.request_id
    }
}

#[derive(Debug)]
pub enum BudgetAdmission {
    Execute(BudgetReservation),
    Archived(NativeRunRecord),
}

impl ConcurrentBudgetOwner {
    pub fn open(
        base_journal: impl AsRef<Path>,
        maximum_in_flight: usize,
    ) -> Result<Self, ConcurrentControlError> {
        if !(1..=MAXIMUM_IN_FLIGHT).contains(&maximum_in_flight) {
            return Err(ConcurrentControlError::CapacityExceeded);
        }
        let base = base_journal.as_ref();
        if !base.is_absolute() {
            return Err(ConcurrentControlError::Invalid("journal path must be absolute"));
        }
        let mut root_name = base.as_os_str().to_os_string();
        root_name.push(".concurrent");
        let root = PathBuf::from(root_name);
        let owner = Self {
            state_path: root.join("budget-state.json"),
            lock_path: root.join("budget.lock"),
            active_dir: root.join("active"),
            archive_dir: root.join("archive"),
            lease_dir: root.join("leases"),
            root,
            maximum_in_flight,
        };
        owner.prepare_directories()?;
        Ok(owner)
    }

    pub fn admit(&self, request_id: &str) -> Result<BudgetAdmission, ConcurrentControlError> {
        validate_request_id(request_id)?;
        let _budget_lock = self.lock_budget()?;
        let mut state = self.load_state()?;
        self.reconcile_locked(&mut state)?;
        let key = request_key(request_id);
        if let Some(record) = self.load_archive(&key)? {
            if record.request.request_id != request_id {
                return Err(ConcurrentControlError::Corrupt("archive request identity"));
            }
            return Ok(BudgetAdmission::Archived(record));
        }
        let lease = self.try_lock_request(&key)?;
        if state.active.contains_key(&key) {
            return Err(ConcurrentControlError::Busy);
        }
        if state.active.len() >= self.maximum_in_flight {
            return Err(ConcurrentControlError::CapacityExceeded);
        }
        state.active.insert(
            key.clone(),
            ActiveEntry {
                request_id: request_id.to_string(),
            },
        );
        advance_revision(&mut state)?;
        self.persist_state(&state)?;
        Ok(BudgetAdmission::Execute(BudgetReservation {
            request_id: request_id.to_string(),
            request_key: key.clone(),
            journal_path: self.active_dir.join(format!("{key}.journal")),
            _lease: lease,
        }))
    }

    pub fn finalize(
        &self,
        reservation: &BudgetReservation,
    ) -> Result<NativeRunRecord, ConcurrentControlError> {
        let _budget_lock = self.lock_budget()?;
        let mut state = self.load_state()?;
        let entry = state
            .active
            .get(&reservation.request_key)
            .ok_or(ConcurrentControlError::Corrupt("missing active budget entry"))?;
        if entry.request_id != reservation.request_id {
            return Err(ConcurrentControlError::Corrupt("active budget identity drift"));
        }
        let record = self.reconcile_request_journal(
            &reservation.request_id,
            &reservation.journal_path,
        )?;
        self.write_archive(&reservation.request_key, &record)?;
        state.active.remove(&reservation.request_key);
        advance_revision(&mut state)?;
        self.persist_state(&state)?;
        self.archive_journal(&reservation.request_key, &reservation.journal_path)?;
        Ok(record)
    }

    fn prepare_directories(&self) -> Result<(), ConcurrentControlError> {
        for path in [
            self.root.as_path(),
            self.active_dir.as_path(),
            self.archive_dir.as_path(),
            self.lease_dir.as_path(),
        ] {
            fs::create_dir_all(path)?;
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                fs::set_permissions(path, fs::Permissions::from_mode(0o700))?;
            }
        }
        Ok(())
    }

    fn lock_budget(&self) -> Result<File, ConcurrentControlError> {
        let file = open_owner_file(&self.lock_path)?;
        loop {
            match file.try_lock() {
                Ok(()) => return Ok(file),
                Err(TryLockError::WouldBlock) => thread::sleep(LOCK_RETRY),
                Err(TryLockError::Error(error)) => return Err(error.into()),
            }
        }
    }

    fn try_lock_request(&self, key: &str) -> Result<File, ConcurrentControlError> {
        let file = open_owner_file(&self.lease_dir.join(format!("{key}.lock")))?;
        match file.try_lock() {
            Ok(()) => Ok(file),
            Err(TryLockError::WouldBlock) => Err(ConcurrentControlError::Busy),
            Err(TryLockError::Error(error)) => Err(error.into()),
        }
    }

    fn load_state(&self) -> Result<BudgetBody, ConcurrentControlError> {
        if !self.state_path.exists() {
            return Ok(BudgetBody {
                schema: STATE_SCHEMA.to_string(),
                revision: 1,
                maximum_in_flight: self.maximum_in_flight,
                active: BTreeMap::new(),
            });
        }
        let envelope: BudgetEnvelope = serde_json::from_slice(&fs::read(&self.state_path)?)
            .map_err(|_| ConcurrentControlError::Corrupt("budget json"))?;
        if envelope.body.schema != STATE_SCHEMA
            || envelope.body.revision == 0
            || envelope.body.maximum_in_flight != self.maximum_in_flight
            || envelope.sha256 != digest_json(&envelope.body)?
        {
            return Err(ConcurrentControlError::Corrupt("budget envelope"));
        }
        Ok(envelope.body)
    }

    fn persist_state(&self, state: &BudgetBody) -> Result<(), ConcurrentControlError> {
        if state.schema != STATE_SCHEMA
            || state.maximum_in_flight != self.maximum_in_flight
            || state.active.len() > self.maximum_in_flight
        {
            return Err(ConcurrentControlError::Corrupt("budget state invariant"));
        }
        durable_replace_json(
            &self.state_path,
            &BudgetEnvelope {
                body: state.clone(),
                sha256: digest_json(state)?,
            },
        )
    }

    fn reconcile_locked(&self, state: &mut BudgetBody) -> Result<(), ConcurrentControlError> {
        let entries = state
            .active
            .iter()
            .map(|(key, entry)| (key.clone(), entry.clone()))
            .collect::<Vec<_>>();
        let mut changed = false;
        let mut journal_moves = Vec::new();
        for (key, entry) in entries {
            if self.load_archive(&key)?.is_some() {
                state.active.remove(&key);
                changed = true;
                continue;
            }
            let lease = match self.try_lock_request(&key) {
                Ok(value) => value,
                Err(ConcurrentControlError::Busy) => continue,
                Err(error) => return Err(error),
            };
            let journal = self.active_dir.join(format!("{key}.journal"));
            if !journal.exists() {
                state.active.remove(&key);
                changed = true;
                drop(lease);
                continue;
            }
            let record = self.reconcile_request_journal(&entry.request_id, &journal)?;
            self.write_archive(&key, &record)?;
            state.active.remove(&key);
            journal_moves.push((key, journal));
            changed = true;
            drop(lease);
        }
        if changed {
            advance_revision(state)?;
            self.persist_state(state)?;
            for (key, journal) in journal_moves {
                self.archive_journal(&key, &journal)?;
            }
        }
        Ok(())
    }

    fn reconcile_request_journal(
        &self,
        request_id: &str,
        journal: &Path,
    ) -> Result<NativeRunRecord, ConcurrentControlError> {
        let mut control = DurableInferenceControl::open(journal, PER_REQUEST_JOURNAL_CAPACITY)?;
        let record = control
            .native_record(request_id)
            .cloned()
            .ok_or(ConcurrentControlError::Corrupt("request journal missing record"))?;
        match record.state {
            NativeReservationState::Reserved => {
                control.stop_native_before_dispatch(
                    request_id,
                    "request owner absent before durable dispatch; slot safely reclaimed".to_string(),
                )?;
            }
            NativeReservationState::Dispatching
            | NativeReservationState::Running
            | NativeReservationState::Cancelling => {
                let dispatch = record
                    .dispatch
                    .as_ref()
                    .ok_or(ConcurrentControlError::Corrupt("possible dispatch missing binding"))?;
                control.settle_native(
                    request_id,
                    NativeRunOutput {
                        thread_id: dispatch.thread_id.clone(),
                        turn_id: record.turn_id.clone().unwrap_or_default(),
                        model: record.request.model.clone(),
                        model_provider: dispatch.model_provider.clone(),
                        status: NativeRunStatus::Indeterminate,
                        output: String::new(),
                        observed_output_tokens: None,
                        terminal_observed: false,
                        owner_authority: NativeOwnerAuthority::Unverified,
                        stop_reason: Some(
                            "request owner absent after possible dispatch; quarantined without replay"
                                .to_string(),
                        ),
                    },
                )?;
            }
            NativeReservationState::Indeterminate | NativeReservationState::Released => {}
        }
        control
            .native_record(request_id)
            .cloned()
            .ok_or(ConcurrentControlError::Corrupt("reconciled request missing"))
    }

    fn write_archive(
        &self,
        key: &str,
        record: &NativeRunRecord,
    ) -> Result<(), ConcurrentControlError> {
        let disposition = if record.state == NativeReservationState::Indeterminate {
            ArchiveDisposition::QuarantinedIndeterminate
        } else if record.pre_dispatch_stop.is_some() && record.observation.is_none() {
            ArchiveDisposition::PreDispatchStopped
        } else if record.state == NativeReservationState::Released {
            ArchiveDisposition::Terminal
        } else {
            return Err(ConcurrentControlError::Corrupt("non-archivable request state"));
        };
        let body = ArchiveBody {
            schema: ARCHIVE_SCHEMA.to_string(),
            disposition,
            record: record.clone(),
        };
        let path = self.archive_dir.join(format!("{key}.json"));
        if path.exists() {
            if self.load_archive(key)?.as_ref() != Some(record) {
                return Err(ConcurrentControlError::Corrupt("archive semantic conflict"));
            }
            return Ok(());
        }
        durable_replace_json(
            &path,
            &ArchiveEnvelope {
                sha256: digest_json(&body)?,
                body,
            },
        )
    }

    fn load_archive(&self, key: &str) -> Result<Option<NativeRunRecord>, ConcurrentControlError> {
        let path = self.archive_dir.join(format!("{key}.json"));
        if !path.exists() {
            return Ok(None);
        }
        let envelope: ArchiveEnvelope = serde_json::from_slice(&fs::read(path)?)
            .map_err(|_| ConcurrentControlError::Corrupt("archive json"))?;
        if envelope.body.schema != ARCHIVE_SCHEMA || envelope.sha256 != digest_json(&envelope.body)? {
            return Err(ConcurrentControlError::Corrupt("archive envelope"));
        }
        Ok(Some(envelope.body.record))
    }

    fn archive_journal(&self, key: &str, journal: &Path) -> Result<(), ConcurrentControlError> {
        if !journal.exists() {
            return Ok(());
        }
        let destination = self.archive_dir.join(format!("{key}.journal"));
        if destination.exists() {
            fs::remove_file(journal)?;
        } else {
            fs::rename(journal, destination)?;
        }
        sync_dir(&self.active_dir)?;
        sync_dir(&self.archive_dir)
    }
}

fn advance_revision(state: &mut BudgetBody) -> Result<(), ConcurrentControlError> {
    state.revision = state
        .revision
        .checked_add(1)
        .ok_or(ConcurrentControlError::Corrupt("budget revision overflow"))?;
    Ok(())
}

fn validate_request_id(value: &str) -> Result<(), ConcurrentControlError> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(ConcurrentControlError::Invalid("invalid request id"));
    }
    Ok(())
}

fn request_key(request_id: &str) -> String {
    format!("{:x}", Sha256::digest(request_id.as_bytes()))
}

fn digest_json<T: Serialize>(value: &T) -> Result<String, ConcurrentControlError> {
    let bytes = serde_json::to_vec(value)
        .map_err(|_| ConcurrentControlError::Corrupt("json encode"))?;
    Ok(format!("{:x}", Sha256::digest(bytes)))
}

fn open_owner_file(path: &Path) -> Result<File, ConcurrentControlError> {
    let mut options = OpenOptions::new();
    options.create(true).read(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let file = options.open(path)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if file.metadata()?.permissions().mode() & 0o077 != 0 {
            return Err(ConcurrentControlError::Invalid("control file must be owner-only"));
        }
    }
    Ok(file)
}

fn durable_replace_json<T: Serialize>(path: &Path, value: &T) -> Result<(), ConcurrentControlError> {
    let parent = path
        .parent()
        .ok_or(ConcurrentControlError::Invalid("state path has no parent"))?;
    let bytes = serde_json::to_vec(value)
        .map_err(|_| ConcurrentControlError::Corrupt("json encode"))?;
    let temp = path.with_extension("tmp");
    let mut file = open_owner_file(&temp)?;
    file.set_len(0)?;
    file.write_all(&bytes)?;
    file.flush()?;
    file.sync_all()?;
    drop(file);
    fs::rename(&temp, path)?;
    sync_dir(parent)
}

fn sync_dir(path: &Path) -> Result<(), ConcurrentControlError> {
    #[cfg(unix)]
    File::open(path)?.sync_all()?;
    Ok(())
}
