#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::{self};
use std::io::BufRead;
use std::io::BufReader;
use std::io::Read;
use std::io::Seek;
use std::io::Write;
#[cfg(unix)]
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Instant;

use codex_hepta_types::Digest32;
use codex_hepta_types::PhaseMetricEventV1;
use codex_hepta_types::PhaseMetricKindV1;
use codex_hepta_types::PhaseMetricSinkV1;

use serde::Deserialize;
use serde::Serialize;

#[path = "generation_control.rs"]
pub mod generation;
#[path = "native_control.rs"]
pub mod native;
#[cfg(target_os = "linux")]
#[path = "durable_control_file.rs"]
mod owned_file;

#[path = "journal_checkpoint_frame.rs"]
mod checkpoint_frame;
#[path = "journal_maintenance.rs"]
mod maintenance;
#[cfg(feature = "qualification-owned-file-read")]
#[path = "durable_control_observation.rs"]
mod observation;
use maintenance::compaction_path;
use maintenance::legacy_record_headroom;
use maintenance::push_image_line;
use maintenance::replace_headroom;
use maintenance::replay_legacy_checkpoint;
use maintenance::required_headroom;

const LEGACY_CHECKPOINT_PREFIX: &str = "legacy-checkpoint-v1|";
const LEGACY_TERMINAL_HEADROOM_BYTES: u64 = 16 * 1024;
const COMPACTION_TEMP_SUFFIX: &str = ".compact.tmp";

const MAX_RECORDS: usize = 16_384;
const MAX_JOURNAL_BYTES: u64 = 64 * 1024 * 1024;
const MAX_JOURNAL_LINE_BYTES: usize = 8 * 1024 * 1024;
const MAX_TOKENS: u32 = 1_000_000;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RequestState {
    Pending,
    Reserved,
    Assigned,
    Cancelling,
    Completed,
    Failed,
    Cancelled,
    Indeterminate,
}

impl RequestState {
    fn as_str(self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Reserved => "reserved",
            Self::Assigned => "assigned",
            Self::Cancelling => "cancelling",
            Self::Completed => "completed",
            Self::Failed => "failed",
            Self::Cancelled => "cancelled",
            Self::Indeterminate => "indeterminate",
        }
    }

    fn parse(value: &str) -> Result<Self, Error> {
        match value {
            "pending" => Ok(Self::Pending),
            "reserved" => Ok(Self::Reserved),
            "assigned" => Ok(Self::Assigned),
            "cancelling" => Ok(Self::Cancelling),
            "completed" => Ok(Self::Completed),
            "failed" => Ok(Self::Failed),
            "cancelled" => Ok(Self::Cancelled),
            "indeterminate" => Ok(Self::Indeterminate),
            _ => Err(Error::CorruptJournal("request state")),
        }
    }

    fn terminal(self) -> bool {
        matches!(
            self,
            Self::Completed | Self::Failed | Self::Cancelled | Self::Indeterminate
        )
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct InferenceRequest {
    pub request_id: String,
    pub principal_id: String,
    pub model_digest: String,
    pub payload_digest: String,
    pub maximum_tokens: u32,
    pub deadline_ms: u64,
    pub semantic_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Reservation {
    pub reservation_id: String,
    pub quota_units: u64,
    pub maximum_tokens: u32,
    pub authority_epoch: u64,
    pub valid_until_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Assignment {
    pub worker_id: String,
    pub worker_generation: u64,
    pub assignment_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TerminalObservation {
    pub request_id: String,
    pub reservation_id: String,
    pub worker_id: String,
    pub worker_generation: u64,
    pub model_digest: String,
    pub payload_digest: String,
    pub terminal_observed: bool,
    pub terminal_status: Option<RequestState>,
    pub output_digest: Option<String>,
    pub consumed_tokens: u32,
    pub usage_units: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RequestRecord {
    pub request: InferenceRequest,
    pub revision: u64,
    pub state: RequestState,
    pub reservation: Option<Reservation>,
    pub assignment: Option<Assignment>,
    pub terminal_observation_digest: Option<String>,
    pub consumed_tokens: u32,
    pub usage_units: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ControlReceipt {
    pub request_id: String,
    pub revision: u64,
    pub state: RequestState,
    pub idempotent: bool,
    pub terminal_observed: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct JournalCompactionReceipt {
    pub before_bytes: u64,
    pub after_bytes: u64,
    pub legacy_records: usize,
    pub native_records: usize,
    pub generation_records: usize,
    pub reserved_headroom_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct JournalCapacityStatus {
    pub journal_bytes: u64,
    pub maximum_journal_bytes: u64,
    pub reserved_headroom_bytes: u64,
    pub admissible_bytes: u64,
    pub legacy_records: usize,
    pub native_records: usize,
    pub generation_records: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    InvalidIdentity(&'static str),
    InvalidDigest(&'static str),
    InvalidTime,
    InvalidTokens,
    CapacityExceeded,
    RequestNotFound,
    Conflict,
    InvalidTransition,
    StaleRevision,
    ReservationMismatch,
    AssignmentMismatch,
    UsageExceeded,
    TerminalObservationMissing,
    CorruptJournal(&'static str),
    Io(String),
    ArithmeticOverflow,
    WriterUnavailable,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

impl From<std::io::Error> for Error {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value.to_string())
    }
}

#[derive(Debug)]
pub struct DurableInferenceControl {
    path: PathBuf,
    file: File,
    // Only path constructors own directory-entry replacement capability.
    _writer_lock: Option<File>,
    records: BTreeMap<String, RequestRecord>,
    native: native::NativeJournal,
    generation: generation::GenerationJournal,
    capacity: usize,
    journal_bytes: u64,
    // Legacy/native liabilities; generation retains its independently derived reserve.
    reserved_headroom_bytes: u64,
    poisoned: bool,
    metrics: Option<Arc<dyn PhaseMetricSinkV1>>,
    failed_metrics: AtomicU64,
}

impl Drop for DurableInferenceControl {
    fn drop(&mut self) {
        // A concurrent fork can retain the open file description until exec.
        // Release this owner's lock even while such a descriptor is still open.
        let _ = self.file.unlock();
        if let Some(writer_lock) = &self._writer_lock {
            let _ = writer_lock.unlock();
        }
    }
}

impl DurableInferenceControl {
    /// Production serving entrance: the WAL must reside in a pre-provisioned,
    /// non-world-writable directory, with an owner-private, unaliased file.
    ///
    /// Callers must already control the complete directory namespace. These
    /// checks inspect only the immediate parent and final file; they do not
    /// verify ownership IDs or bind ancestors against concurrent replacement.
    /// Opening may create an empty WAL before the final identity comparison.
    ///
    /// This is stricter than `open`, which remains available for migration,
    /// repair and qualification. The read-only checks cannot authorize a
    /// dispatch: the existing single-writer lock and effect owner still apply.
    #[cfg(unix)]
    pub fn open_production(path: impl AsRef<Path>, capacity: usize) -> Result<Self, Error> {
        let path = path.as_ref();
        Self::check_production_path(path)?;
        let opened = Self::open(path, capacity)?;
        // Reject an observed final-path mismatch after open; callers retain
        // responsibility for preventing namespace changes throughout opening.
        Self::check_production_path(path)?;
        let actual = opened.file.metadata()?;
        let on_path = fs::symlink_metadata(path)?;
        if !actual.is_file() || !on_path.file_type().is_file() {
            return Err(Error::InvalidIdentity("unsafe production WAL file"));
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            use std::os::unix::fs::PermissionsExt;
            if actual.permissions().mode() & 0o077 != 0
                || on_path.permissions().mode() & 0o077 != 0
                || actual.nlink() != 1
                || actual.dev() != on_path.dev()
                || actual.ino() != on_path.ino()
            {
                return Err(Error::InvalidIdentity("unsafe production WAL inode"));
            }
        }
        Ok(opened)
    }

    /// The non-Unix implementation has no audited owner-only ACL and
    /// directory-entry durability guarantee. Even direct callers of the core
    /// API must not bypass the worker's fail-closed production startup.
    #[cfg(not(unix))]
    pub fn open_production(_path: impl AsRef<Path>, _capacity: usize) -> Result<Self, Error> {
        Err(Error::InvalidIdentity(
            "production WAL durability is unverified on this platform",
        ))
    }

    #[cfg(unix)]
    fn check_production_path(path: &Path) -> Result<(), Error> {
        if !path.is_absolute()
            || path.file_name().is_none()
            || path
                .components()
                .any(|component| component == Component::ParentDir)
        {
            return Err(Error::InvalidIdentity(
                "production WAL path must be absolute and free of parent traversal",
            ));
        }
        let directory = path
            .parent()
            .ok_or(Error::InvalidIdentity("production WAL parent missing"))?;
        let parent = fs::symlink_metadata(directory)?;
        if !parent.is_dir() || parent.file_type().is_symlink() {
            return Err(Error::InvalidIdentity("unsafe production WAL directory"));
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if parent.permissions().mode() & 0o022 != 0 {
                return Err(Error::InvalidIdentity(
                    "production WAL directory is writable by others",
                ));
            }
        }
        match fs::symlink_metadata(path) {
            Ok(metadata) => {
                if !metadata.file_type().is_file() {
                    return Err(Error::InvalidIdentity("unsafe production WAL path"));
                }
                #[cfg(unix)]
                {
                    use std::os::unix::fs::MetadataExt;
                    use std::os::unix::fs::PermissionsExt;
                    if metadata.permissions().mode() & 0o077 != 0 || metadata.nlink() != 1 {
                        return Err(Error::InvalidIdentity(
                            "production WAL file must be private",
                        ));
                    }
                }
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(Error::from(error)),
        }
        Ok(())
    }

    pub fn open(path: impl AsRef<Path>, capacity: usize) -> Result<Self, Error> {
        if capacity == 0 || capacity > MAX_RECORDS {
            return Err(Error::CapacityExceeded);
        }
        let path = path.as_ref().to_path_buf();
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        let mut options = OpenOptions::new();
        options.create(true).append(true).read(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        // A path owner must have an actual durable containing directory. This
        // preflight also keeps diagnostic procfs aliases from creating locks.
        #[cfg(unix)]
        {
            let parent = path
                .parent()
                .filter(|parent| !parent.as_os_str().is_empty())
                .unwrap_or_else(|| Path::new("."));
            File::open(parent)?.sync_all()?;
        }
        let mut lock_path = path.as_os_str().to_os_string();
        lock_path.push(".writer.lock");
        let writer_lock = options.open(PathBuf::from(lock_path))?;
        writer_lock
            .try_lock()
            .map_err(|_| Error::WriterUnavailable)?;
        // Open the data inode only after the stable ownership lock is held.
        let file = options.open(&path)?;
        let control = Self::replay_file(file, path, capacity, Some(writer_lock))?;
        // Preserve recovery evidence if replay failed. Descriptor-only owners
        // never enter this pathname cleanup or rename path.
        match fs::remove_file(compaction_path(&control.path)) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }
        #[cfg(unix)]
        {
            let parent = control
                .path
                .parent()
                .filter(|parent| !parent.as_os_str().is_empty())
                .unwrap_or_else(|| Path::new("."));
            File::open(parent)?.sync_all()?;
        }
        Ok(control)
    }

    /// Replay an already opened, host-selected Linux read/append file. This method
    /// never accesses the diagnostic pathname or its parent. The host chooses
    /// create-new versus reopen, retains responsibility for storage identity,
    /// and syncs the actual containing directory when creating an entry. Replay,
    /// locking and append-sync use only the supplied descriptor. Its flags must
    /// be readable and append-mode; the caller must not retain a writer or change
    /// the shared descriptor flags afterwards.
    #[cfg(target_os = "linux")]
    pub fn open_file(file: File, path: impl AsRef<Path>, capacity: usize) -> Result<Self, Error> {
        owned_file::validate_read_append(&file)?;
        Self::replay_file(file, path, capacity, /*writer_lock*/ None)
    }

    fn replay_file(
        mut file: File,
        path: impl AsRef<Path>,
        capacity: usize,
        writer_lock: Option<File>,
    ) -> Result<Self, Error> {
        if capacity == 0 || capacity > MAX_RECORDS {
            return Err(Error::CapacityExceeded);
        }
        if !file.metadata()?.is_file() {
            return Err(Error::CorruptJournal("journal is not a regular file"));
        }
        let path = path.as_ref().to_path_buf();
        // Lock before replay: two owners must never admit from the same stale cut.
        file.try_lock().map_err(|_| Error::WriterUnavailable)?;
        file.rewind()?;
        if file.metadata()?.len() > MAX_JOURNAL_BYTES {
            return Err(Error::CapacityExceeded);
        }
        let mut records = BTreeMap::new();
        let mut native = native::NativeJournal::default();
        let mut generation = generation::GenerationJournal::default();
        let mut reader = BufReader::new(file.try_clone()?);
        let mut journal_bytes = 0_u64;
        let mut line = Vec::new();
        let mut checkpoint_frame = checkpoint_frame::CheckpointFrame::default();
        loop {
            // Empty historical lines carry no state. Consume a whole buffered
            // run instead of entering the semantic parser once per byte.
            let blank_bytes = reader
                .fill_buf()?
                .iter()
                .take_while(|byte| **byte == b'\n')
                .count();
            if blank_bytes > 0 {
                journal_bytes += blank_bytes as u64;
                if journal_bytes > MAX_JOURNAL_BYTES {
                    return Err(Error::CapacityExceeded);
                }
                reader.consume(blank_bytes);
                continue;
            }
            line.clear();
            // Bound actual reads and allocation, including files whose metadata
            // races with open. One extra byte distinguishes EOF from overflow.
            let remaining = MAX_JOURNAL_BYTES.saturating_sub(journal_bytes) + 1;
            let limit = remaining.min(MAX_JOURNAL_LINE_BYTES as u64 + 1);
            let count = (&mut reader).take(limit).read_until(b'\n', &mut line)?;
            if count == 0 {
                break;
            }
            journal_bytes += count as u64;
            if count > MAX_JOURNAL_LINE_BYTES || journal_bytes > MAX_JOURNAL_BYTES {
                return Err(Error::CapacityExceeded);
            }
            if line.pop() != Some(b'\n') {
                return Err(Error::CorruptJournal("incomplete line"));
            }
            if line.last() == Some(&b'\r') {
                line.pop();
            }
            let line = std::str::from_utf8(&line).map_err(|_| Error::CorruptJournal("utf8"))?;
            if line.is_empty() {
                continue;
            }
            if checkpoint_frame.observe(line, capacity)? {
                continue;
            }
            // Each validated frame changes one identity. Previously accepted
            // frames are already disjoint, so inspect only this frame's ID.
            let collision = if let Some(json) = line.strip_prefix(native::CHECKPOINT_PREFIX) {
                let id = native.replay_checkpoint(json)?;
                records.contains_key(&id) || generation.records.contains_key(&id)
            } else if let Some(json) = line.strip_prefix(native::LEGACY_CHECKPOINT_PREFIX) {
                let id = native.replay_legacy_checkpoint(json)?;
                records.contains_key(&id) || generation.records.contains_key(&id)
            } else if let Some(json) = line.strip_prefix(LEGACY_CHECKPOINT_PREFIX) {
                let id = replay_legacy_checkpoint(&mut records, json)?;
                native.records.contains_key(&id) || generation.records.contains_key(&id)
            } else if let Some(json) = line.strip_prefix(generation::CHECKPOINT_PREFIX) {
                let id = generation.replay_checkpoint(json)?;
                records.contains_key(&id) || native.records.contains_key(&id)
            } else if let Some(json) = line.strip_prefix(native::JOURNAL_PREFIX) {
                let id = native.replay(json)?;
                records.contains_key(&id) || generation.records.contains_key(&id)
            } else if let Some(json) = line.strip_prefix(generation::JOURNAL_PREFIX) {
                let id = generation.replay(json)?;
                records.contains_key(&id) || native.records.contains_key(&id)
            } else {
                let event = decode_event(line)?;
                apply_event(&mut records, &event, /*replay*/ true)?;
                native.records.contains_key(event.request_id())
                    || generation.records.contains_key(event.request_id())
            };
            if records.len() + native.records.len() + generation.records.len() > capacity
                || collision
                || journal_bytes
                    .checked_add(generation.reserved_bytes()?)
                    .ok_or(Error::ArithmeticOverflow)?
                    > MAX_JOURNAL_BYTES
            {
                return Err(Error::CapacityExceeded);
            }
        }
        // Replay checks the three bounded namespaces once, after every
        // event has been validated. No owner is returned for a colliding ID.
        if records
            .keys()
            .any(|id| native.records.contains_key(id) || generation.records.contains_key(id))
            || native
                .records
                .keys()
                .any(|id| generation.records.contains_key(id))
        {
            return Err(Error::CapacityExceeded);
        }
        checkpoint_frame.finish()?;
        let reserved_headroom_bytes = required_headroom(&records, &native)?;
        if journal_bytes
            .checked_add(generation.reserved_bytes()?)
            .ok_or(Error::ArithmeticOverflow)?
            > MAX_JOURNAL_BYTES
        {
            return Err(Error::CapacityExceeded);
        }
        Ok(Self {
            path,
            file,
            _writer_lock: writer_lock,
            records,
            native,
            generation,
            capacity,
            journal_bytes,
            reserved_headroom_bytes,
            poisoned: false,
            metrics: None,
            failed_metrics: AtomicU64::new(0),
        })
    }

    /// Evidence owns WAL telemetry persistence; attaching a sink grants no authority.
    pub fn with_metrics_sink(mut self, sink: Arc<dyn PhaseMetricSinkV1>) -> Self {
        self.metrics = Some(sink);
        self
    }

    /// Strict qualification requires a healthy, non-lossy sink and a durable flush.
    pub fn production_metrics_ready(&self) -> bool {
        !self.poisoned
            && self.metrics.as_ref().is_some_and(|sink| sink.healthy())
            && self.failed_metrics.load(Ordering::Acquire) == 0
    }

    pub fn flush_production_metrics(&self) -> bool {
        let Some(sink) = &self.metrics else {
            return false;
        };
        if sink.flush().is_err() {
            self.failed_metrics.fetch_add(1, Ordering::Release);
            return false;
        }
        self.production_metrics_ready()
    }

    pub fn submit(
        &mut self,
        now_ms: u64,
        request: InferenceRequest,
    ) -> Result<ControlReceipt, Error> {
        validate_request(now_ms, &request)?;
        if let Some(current) = self.records.get(&request.request_id) {
            if current.request == request {
                return Ok(receipt(current, /*idempotent*/ true));
            }
            return Err(Error::Conflict);
        }
        if self.native.records.contains_key(&request.request_id)
            || self.generation.records.contains_key(&request.request_id)
        {
            return Err(Error::Conflict);
        }
        if self.records.len() + self.native.records.len() + self.generation.records.len()
            >= self.capacity
        {
            return Err(Error::CapacityExceeded);
        }
        let event = Event::Submit(request);
        self.commit(event)
    }

    pub fn reserve(
        &mut self,
        now_ms: u64,
        request_id: &str,
        expected_revision: u64,
        reservation: Reservation,
    ) -> Result<ControlReceipt, Error> {
        validate_identity(request_id, "request")?;
        validate_reservation(now_ms, &reservation)?;
        let record = self.records.get(request_id).ok_or(Error::RequestNotFound)?;
        if record.revision != expected_revision {
            return Err(Error::StaleRevision);
        }
        if record.state == RequestState::Reserved
            && record.reservation.as_ref() == Some(&reservation)
        {
            return Ok(receipt(record, /*idempotent*/ true));
        }
        if record.state != RequestState::Pending {
            return Err(Error::InvalidTransition);
        }
        if reservation.maximum_tokens < record.request.maximum_tokens {
            return Err(Error::UsageExceeded);
        }
        self.commit(Event::Reserve {
            request_id: request_id.to_string(),
            expected_revision,
            reservation,
        })
    }

    pub fn assign(
        &mut self,
        request_id: &str,
        expected_revision: u64,
        assignment: Assignment,
    ) -> Result<ControlReceipt, Error> {
        validate_identity(request_id, "request")?;
        validate_assignment(&assignment)?;
        let record = self.records.get(request_id).ok_or(Error::RequestNotFound)?;
        if record.revision != expected_revision {
            return Err(Error::StaleRevision);
        }
        if record.state == RequestState::Assigned && record.assignment.as_ref() == Some(&assignment)
        {
            return Ok(receipt(record, /*idempotent*/ true));
        }
        if record.state != RequestState::Reserved {
            return Err(Error::InvalidTransition);
        }
        self.commit(Event::Assign {
            request_id: request_id.to_string(),
            expected_revision,
            assignment,
        })
    }

    pub fn cancel(
        &mut self,
        request_id: &str,
        expected_revision: u64,
    ) -> Result<ControlReceipt, Error> {
        validate_identity(request_id, "request")?;
        let record = self.records.get(request_id).ok_or(Error::RequestNotFound)?;
        if record.revision != expected_revision {
            return Err(Error::StaleRevision);
        }
        if record.state == RequestState::Cancelled || record.state == RequestState::Cancelling {
            return Ok(receipt(record, /*idempotent*/ true));
        }
        if record.state.terminal() {
            return Err(Error::InvalidTransition);
        }
        self.commit(Event::Cancel {
            request_id: request_id.to_string(),
            expected_revision,
        })
    }

    pub fn settle(
        &mut self,
        request_id: &str,
        expected_revision: u64,
        observation_digest: String,
        observation: TerminalObservation,
    ) -> Result<ControlReceipt, Error> {
        validate_identity(request_id, "request")?;
        validate_digest(&observation_digest, "observation")?;
        validate_observation(&observation)?;
        let record = self.records.get(request_id).ok_or(Error::RequestNotFound)?;
        if record.revision != expected_revision {
            return Err(Error::StaleRevision);
        }
        if record.terminal_observation_digest.as_ref() == Some(&observation_digest) {
            return Ok(receipt(record, /*idempotent*/ true));
        }
        if record.state.terminal() {
            return Err(Error::Conflict);
        }
        let reservation = record
            .reservation
            .as_ref()
            .ok_or(Error::ReservationMismatch)?;
        let assignment = record
            .assignment
            .as_ref()
            .ok_or(Error::AssignmentMismatch)?;
        if observation.request_id != record.request.request_id
            || observation.reservation_id != reservation.reservation_id
            || observation.worker_id != assignment.worker_id
            || observation.worker_generation != assignment.worker_generation
            || observation.model_digest != record.request.model_digest
            || observation.payload_digest != record.request.payload_digest
        {
            return Err(Error::AssignmentMismatch);
        }
        if observation.consumed_tokens > reservation.maximum_tokens {
            return Err(Error::UsageExceeded);
        }
        if observation.terminal_observed {
            let status = observation
                .terminal_status
                .ok_or(Error::TerminalObservationMissing)?;
            if !matches!(
                status,
                RequestState::Completed | RequestState::Failed | RequestState::Cancelled
            ) {
                return Err(Error::InvalidTransition);
            }
            if matches!(status, RequestState::Completed) && observation.output_digest.is_none() {
                return Err(Error::TerminalObservationMissing);
            }
        } else if observation.terminal_status.is_some() || observation.output_digest.is_some() {
            return Err(Error::TerminalObservationMissing);
        }
        self.commit(Event::Settle {
            request_id: request_id.to_string(),
            expected_revision,
            observation_digest,
            observation,
        })
    }

    pub fn get(&self, request_id: &str) -> Option<&RequestRecord> {
        self.records.get(request_id)
    }

    pub fn journal_path(&self) -> &Path {
        &self.path
    }

    fn commit(&mut self, event: Event) -> Result<ControlReceipt, Error> {
        if self.poisoned {
            return Err(Error::WriterUnavailable);
        }
        // Validate only the affected immutable predecessor. Events have no
        // cross-record transitions; global capacity/namespace admission remains
        // with submit. A rejected event or uncertain append leaves every live
        // record untouched, without cloning unrelated historical payloads.
        let request_id = event.request_id().to_string();
        let mut staged = BTreeMap::new();
        if let Some(previous) = self.records.get(&request_id) {
            staged.insert(request_id.clone(), previous.clone());
        }
        apply_event(&mut staged, &event, /*replay*/ false)?;
        let prepared = staged.remove(&request_id).ok_or(Error::RequestNotFound)?;
        let result = receipt(&prepared, /*idempotent*/ false);
        let previous_headroom = self
            .records
            .get(&request_id)
            .map_or(0, legacy_record_headroom);
        let next_headroom = legacy_record_headroom(&prepared);
        let headroom_after = replace_headroom(
            self.reserved_headroom_bytes,
            previous_headroom,
            next_headroom,
        )?;
        let encoded = format!("{}\n", encode_event(&event));
        self.append_preserving_headroom(&encoded, headroom_after)?;
        self.records.insert(request_id, prepared);
        self.reserved_headroom_bytes = headroom_after;
        Ok(result)
    }

    #[cfg(test)]
    fn append(&mut self, encoded: &str) -> Result<(), Error> {
        self.append_with_generation_reserve(encoded, self.generation.reserved_bytes()?)
    }

    fn ensure_append_capacity(
        &self,
        encoded: &str,
        generation_reserved: u64,
    ) -> Result<u64, Error> {
        if self.poisoned {
            return Err(Error::WriterUnavailable);
        }
        let required = self
            .reserved_headroom_bytes
            .checked_add(generation_reserved)
            .ok_or(Error::ArithmeticOverflow)?;
        if encoded.len() > MAX_JOURNAL_LINE_BYTES
            || !self.append_fits(self.journal_bytes, encoded.len() as u64, required)?
        {
            return Err(Error::CapacityExceeded);
        }
        self.journal_bytes
            .checked_add(encoded.len() as u64)
            .ok_or(Error::ArithmeticOverflow)
    }

    fn append_with_generation_reserve(
        &mut self,
        encoded: &str,
        generation_reserved: u64,
    ) -> Result<(), Error> {
        self.append_with_reserves(encoded, self.reserved_headroom_bytes, generation_reserved)
    }

    pub(super) fn append_preserving_headroom(
        &mut self,
        encoded: &str,
        required_headroom_after: u64,
    ) -> Result<(), Error> {
        self.append_with_reserves(
            encoded,
            required_headroom_after,
            self.generation.reserved_bytes()?,
        )
    }

    fn append_with_reserves(
        &mut self,
        encoded: &str,
        required_headroom_after: u64,
        generation_reserved: u64,
    ) -> Result<(), Error> {
        if self.poisoned {
            return Err(Error::WriterUnavailable);
        }
        if encoded.len() > MAX_JOURNAL_LINE_BYTES {
            return Err(Error::CapacityExceeded);
        }
        let encoded_bytes = encoded.len() as u64;
        let required = required_headroom_after
            .checked_add(generation_reserved)
            .ok_or(Error::ArithmeticOverflow)?;
        if !self.append_fits(self.journal_bytes, encoded_bytes, required)? {
            // A diagnostic pathname is not a directory-entry capability.
            if self._writer_lock.is_none() {
                return Err(Error::CapacityExceeded);
            }
            let image = self.checkpoint_image()?;
            if !self.append_fits(image.len() as u64, encoded_bytes, required)? {
                return Err(Error::CapacityExceeded);
            }
            self.replace_with_checkpoint_image(&image)?;
        }
        let next_bytes = self
            .journal_bytes
            .checked_add(encoded_bytes)
            .ok_or(Error::ArithmeticOverflow)?;
        let started = Instant::now();
        // Unwinding from observational callbacks after an append must not
        // leave a live writer whose in-memory history missed durable bytes.
        self.poisoned = true;
        let persisted = self
            .file
            .write_all(encoded.as_bytes())
            .and_then(|()| self.file.flush())
            .and_then(|()| self.file.sync_all());
        // WAL telemetry is observational only. An Evidence outage never masks a
        // successfully fsynced event or makes the control owner retry its effect.
        if let Some(sink) = &self.metrics
            && sink
                .record(PhaseMetricEventV1 {
                    scope_digest: Digest32::of_bytes(self.path.to_string_lossy().as_bytes()),
                    operation_digest: Digest32::of_bytes(encoded.as_bytes()),
                    phase: PhaseMetricKindV1::Wal,
                    latency_micros: u64::try_from(started.elapsed().as_micros())
                        .unwrap_or(u64::MAX),
                    succeeded: persisted.is_ok(),
                })
                .is_err()
        {
            self.failed_metrics.fetch_add(1, Ordering::Release);
        }
        if let Err(error) = persisted {
            self.poisoned = true;
            return Err(error.into());
        }
        self.journal_bytes = next_bytes;
        self.poisoned = false;
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum Event {
    Submit(InferenceRequest),
    Reserve {
        request_id: String,
        expected_revision: u64,
        reservation: Reservation,
    },
    Assign {
        request_id: String,
        expected_revision: u64,
        assignment: Assignment,
    },
    Cancel {
        request_id: String,
        expected_revision: u64,
    },
    Settle {
        request_id: String,
        expected_revision: u64,
        observation_digest: String,
        observation: TerminalObservation,
    },
}

impl Event {
    fn request_id(&self) -> &str {
        match self {
            Self::Submit(request) => &request.request_id,
            Self::Reserve { request_id, .. }
            | Self::Assign { request_id, .. }
            | Self::Cancel { request_id, .. }
            | Self::Settle { request_id, .. } => request_id,
        }
    }
}

fn apply_event(
    records: &mut BTreeMap<String, RequestRecord>,
    event: &Event,
    replay: bool,
) -> Result<(), Error> {
    match event {
        Event::Submit(request) => {
            if let Some(current) = records.get(&request.request_id) {
                if replay && current.request == *request {
                    return Ok(());
                }
                return Err(Error::Conflict);
            }
            records.insert(
                request.request_id.clone(),
                RequestRecord {
                    request: request.clone(),
                    revision: 1,
                    state: RequestState::Pending,
                    reservation: None,
                    assignment: None,
                    terminal_observation_digest: None,
                    consumed_tokens: 0,
                    usage_units: 0,
                },
            );
        }
        Event::Reserve {
            request_id,
            expected_revision,
            reservation,
        } => {
            let record = records.get_mut(request_id).ok_or(Error::RequestNotFound)?;
            require_revision(record, *expected_revision, replay)?;
            if record.state != RequestState::Pending {
                return Err(Error::InvalidTransition);
            }
            record.reservation = Some(reservation.clone());
            record.state = RequestState::Reserved;
            record.revision = next_revision(record.revision)?;
        }
        Event::Assign {
            request_id,
            expected_revision,
            assignment,
        } => {
            let record = records.get_mut(request_id).ok_or(Error::RequestNotFound)?;
            require_revision(record, *expected_revision, replay)?;
            if record.state != RequestState::Reserved {
                return Err(Error::InvalidTransition);
            }
            record.assignment = Some(assignment.clone());
            record.state = RequestState::Assigned;
            record.revision = next_revision(record.revision)?;
        }
        Event::Cancel {
            request_id,
            expected_revision,
        } => {
            let record = records.get_mut(request_id).ok_or(Error::RequestNotFound)?;
            require_revision(record, *expected_revision, replay)?;
            record.state = match record.state {
                RequestState::Pending | RequestState::Reserved => RequestState::Cancelled,
                RequestState::Assigned => RequestState::Cancelling,
                _ => return Err(Error::InvalidTransition),
            };
            record.revision = next_revision(record.revision)?;
        }
        Event::Settle {
            request_id,
            expected_revision,
            observation_digest,
            observation,
        } => {
            let record = records.get_mut(request_id).ok_or(Error::RequestNotFound)?;
            require_revision(record, *expected_revision, replay)?;
            if !matches!(
                record.state,
                RequestState::Assigned | RequestState::Cancelling
            ) {
                return Err(Error::InvalidTransition);
            }
            record.state = if observation.terminal_observed {
                observation
                    .terminal_status
                    .ok_or(Error::TerminalObservationMissing)?
            } else {
                RequestState::Indeterminate
            };
            record.terminal_observation_digest = Some(observation_digest.clone());
            record.consumed_tokens = observation.consumed_tokens;
            record.usage_units = observation.usage_units;
            record.revision = next_revision(record.revision)?;
        }
    }
    Ok(())
}

fn require_revision(record: &RequestRecord, expected: u64, replay: bool) -> Result<(), Error> {
    if record.revision != expected {
        if replay {
            return Err(Error::CorruptJournal("event revision"));
        }
        return Err(Error::StaleRevision);
    }
    Ok(())
}

fn next_revision(value: u64) -> Result<u64, Error> {
    value.checked_add(1).ok_or(Error::ArithmeticOverflow)
}

fn validate_request(now_ms: u64, request: &InferenceRequest) -> Result<(), Error> {
    validate_identity(&request.request_id, "request")?;
    validate_identity(&request.principal_id, "principal")?;
    validate_digest(&request.model_digest, "model")?;
    validate_digest(&request.payload_digest, "payload")?;
    validate_digest(&request.semantic_digest, "semantic")?;
    if request.maximum_tokens == 0 || request.maximum_tokens > MAX_TOKENS {
        return Err(Error::InvalidTokens);
    }
    if request.deadline_ms <= now_ms {
        return Err(Error::InvalidTime);
    }
    Ok(())
}

fn validate_reservation(now_ms: u64, value: &Reservation) -> Result<(), Error> {
    validate_identity(&value.reservation_id, "reservation")?;
    if value.quota_units == 0
        || value.maximum_tokens == 0
        || value.maximum_tokens > MAX_TOKENS
        || value.authority_epoch == 0
        || value.valid_until_ms <= now_ms
    {
        return Err(Error::InvalidTime);
    }
    Ok(())
}

fn validate_assignment(value: &Assignment) -> Result<(), Error> {
    validate_identity(&value.worker_id, "worker")?;
    validate_digest(&value.assignment_digest, "assignment")?;
    if value.worker_generation == 0 {
        return Err(Error::InvalidTransition);
    }
    Ok(())
}

fn validate_observation(value: &TerminalObservation) -> Result<(), Error> {
    validate_identity(&value.request_id, "request")?;
    validate_identity(&value.reservation_id, "reservation")?;
    validate_identity(&value.worker_id, "worker")?;
    validate_digest(&value.model_digest, "model")?;
    validate_digest(&value.payload_digest, "payload")?;
    if value.worker_generation == 0 || value.consumed_tokens > MAX_TOKENS {
        return Err(Error::InvalidTransition);
    }
    if let Some(output) = &value.output_digest {
        validate_digest(output, "output")?;
    }
    Ok(())
}

fn validate_identity(value: &str, field: &'static str) -> Result<(), Error> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(Error::InvalidIdentity(field));
    }
    Ok(())
}

fn validate_digest(value: &str, field: &'static str) -> Result<(), Error> {
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(Error::InvalidDigest(field));
    }
    Ok(())
}

fn receipt(record: &RequestRecord, idempotent: bool) -> ControlReceipt {
    ControlReceipt {
        request_id: record.request.request_id.clone(),
        revision: record.revision,
        state: record.state,
        idempotent,
        terminal_observed: record.state.terminal() && record.state != RequestState::Indeterminate,
    }
}

fn encode_event(event: &Event) -> String {
    match event {
        Event::Submit(request) => format!(
            "submit|{}|{}|{}|{}|{}|{}|{}",
            request.request_id,
            request.principal_id,
            request.model_digest,
            request.payload_digest,
            request.maximum_tokens,
            request.deadline_ms,
            request.semantic_digest
        ),
        Event::Reserve {
            request_id,
            expected_revision,
            reservation,
        } => format!(
            "reserve|{request_id}|{expected_revision}|{}|{}|{}|{}|{}",
            reservation.reservation_id,
            reservation.quota_units,
            reservation.maximum_tokens,
            reservation.authority_epoch,
            reservation.valid_until_ms
        ),
        Event::Assign {
            request_id,
            expected_revision,
            assignment,
        } => format!(
            "assign|{request_id}|{expected_revision}|{}|{}|{}",
            assignment.worker_id, assignment.worker_generation, assignment.assignment_digest
        ),
        Event::Cancel {
            request_id,
            expected_revision,
        } => format!("cancel|{request_id}|{expected_revision}"),
        Event::Settle {
            request_id,
            expected_revision,
            observation_digest,
            observation,
        } => format!(
            "settle|{request_id}|{expected_revision}|{observation_digest}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}",
            observation.reservation_id,
            observation.worker_id,
            observation.worker_generation,
            observation.model_digest,
            observation.payload_digest,
            u8::from(observation.terminal_observed),
            observation
                .terminal_status
                .map_or("none", RequestState::as_str),
            observation.output_digest.as_deref().unwrap_or("none"),
            observation.consumed_tokens,
            observation.usage_units,
            observation.request_id
        ),
    }
}

fn decode_event(line: &str) -> Result<Event, Error> {
    let fields: Vec<_> = line.split('|').collect();
    match fields.as_slice() {
        [
            "submit",
            request_id,
            principal_id,
            model,
            payload,
            tokens,
            deadline,
            semantic,
        ] => Ok(Event::Submit(InferenceRequest {
            request_id: (*request_id).to_string(),
            principal_id: (*principal_id).to_string(),
            model_digest: (*model).to_string(),
            payload_digest: (*payload).to_string(),
            maximum_tokens: parse_u32(tokens)?,
            deadline_ms: parse_u64(deadline)?,
            semantic_digest: (*semantic).to_string(),
        })),
        [
            "reserve",
            request_id,
            revision,
            reservation_id,
            quota,
            tokens,
            epoch,
            valid_until,
        ] => Ok(Event::Reserve {
            request_id: (*request_id).to_string(),
            expected_revision: parse_u64(revision)?,
            reservation: Reservation {
                reservation_id: (*reservation_id).to_string(),
                quota_units: parse_u64(quota)?,
                maximum_tokens: parse_u32(tokens)?,
                authority_epoch: parse_u64(epoch)?,
                valid_until_ms: parse_u64(valid_until)?,
            },
        }),
        [
            "assign",
            request_id,
            revision,
            worker_id,
            generation,
            assignment_digest,
        ] => Ok(Event::Assign {
            request_id: (*request_id).to_string(),
            expected_revision: parse_u64(revision)?,
            assignment: Assignment {
                worker_id: (*worker_id).to_string(),
                worker_generation: parse_u64(generation)?,
                assignment_digest: (*assignment_digest).to_string(),
            },
        }),
        ["cancel", request_id, revision] => Ok(Event::Cancel {
            request_id: (*request_id).to_string(),
            expected_revision: parse_u64(revision)?,
        }),
        [
            "settle",
            request_id,
            revision,
            observation_digest,
            reservation_id,
            worker_id,
            worker_generation,
            model,
            payload,
            terminal,
            status,
            output,
            tokens,
            usage,
            observed_request_id,
        ] => Ok(Event::Settle {
            request_id: (*request_id).to_string(),
            expected_revision: parse_u64(revision)?,
            observation_digest: (*observation_digest).to_string(),
            observation: TerminalObservation {
                request_id: (*observed_request_id).to_string(),
                reservation_id: (*reservation_id).to_string(),
                worker_id: (*worker_id).to_string(),
                worker_generation: parse_u64(worker_generation)?,
                model_digest: (*model).to_string(),
                payload_digest: (*payload).to_string(),
                terminal_observed: match *terminal {
                    "1" => true,
                    "0" => false,
                    _ => return Err(Error::CorruptJournal("terminal boolean")),
                },
                terminal_status: if *status == "none" {
                    None
                } else {
                    Some(RequestState::parse(status)?)
                },
                output_digest: (*output != "none").then(|| (*output).to_string()),
                consumed_tokens: parse_u32(tokens)?,
                usage_units: parse_u64(usage)?,
            },
        }),
        _ => Err(Error::CorruptJournal("event shape")),
    }
}

fn parse_u64(value: &str) -> Result<u64, Error> {
    value.parse().map_err(|_| Error::CorruptJournal("u64"))
}

fn parse_u32(value: &str) -> Result<u32, Error> {
    value.parse().map_err(|_| Error::CorruptJournal("u32"))
}

#[cfg(test)]
#[path = "durable_control_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "durable_history_tests.rs"]
mod history_tests;

#[cfg(all(test, target_os = "linux"))]
#[path = "durable_control_file_tests.rs"]
mod file_tests;

#[cfg(test)]
#[path = "durable_scaling_tests.rs"]
mod scaling_tests;

#[cfg(test)]
#[path = "durable_metrics_panic_tests.rs"]
mod metrics_panic_tests;
