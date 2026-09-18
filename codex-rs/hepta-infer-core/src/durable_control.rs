#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::{self};
use std::io::BufRead;
use std::io::BufReader;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

#[path = "native_control.rs"]
pub mod native;

const MAX_RECORDS: usize = 16_384;
const MAX_JOURNAL_BYTES: u64 = 64 * 1024 * 1024;
const MAX_JOURNAL_LINE_BYTES: usize = 8 * 1024 * 1024;
const MAX_TOKENS: u32 = 1_000_000;
const LEGACY_CHECKPOINT_PREFIX: &str = "checkpoint-legacy-v1|";
const ARCHIVE_SUFFIX_PREFIX: &str = "archive-";
const COMPACTION_PREFIX: &str = "compaction-v1|";

#[derive(Deserialize, Serialize, Clone, Copy, Debug, Eq, PartialEq)]
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

#[derive(Deserialize, Serialize, Clone, Debug, Eq, PartialEq)]
pub struct InferenceRequest {
    pub request_id: String,
    pub principal_id: String,
    pub model_digest: String,
    pub payload_digest: String,
    pub maximum_tokens: u32,
    pub deadline_ms: u64,
    pub semantic_digest: String,
}

#[derive(Deserialize, Serialize, Clone, Debug, Eq, PartialEq)]
pub struct Reservation {
    pub reservation_id: String,
    pub quota_units: u64,
    pub maximum_tokens: u32,
    pub authority_epoch: u64,
    pub valid_until_ms: u64,
}

#[derive(Deserialize, Serialize, Clone, Debug, Eq, PartialEq)]
pub struct Assignment {
    pub worker_id: String,
    pub worker_generation: u64,
    pub assignment_digest: String,
}

#[derive(Deserialize, Serialize, Clone, Debug, Eq, PartialEq)]
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

#[derive(Deserialize, Serialize, Clone, Debug, Eq, PartialEq)]
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
    records: BTreeMap<String, RequestRecord>,
    native: native::NativeJournal,
    capacity: usize,
    journal_bytes: u64,
    poisoned: bool,
    cached_stamp: Option<FileStamp>,
    archive_digest: Option<String>,
    archive_stamp: Option<FileStamp>,
    replay_stats: JournalReplayStats,
}

/// Local work counters, not a throughput claim or a durable fact.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct JournalReplayStats {
    pub full_replays: u64,
    pub replayed_bytes: u64,
    pub unchanged_reuses: u64,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct NativeArchiveReceipt {
    pub archived: usize,
    pub remaining_native: usize,
    pub journal_bytes: u64,
    pub released_archive_bytes: u64,
}

/// A cache discriminator for cooperating writers in a host-owned directory.
/// This is not authentication against a privileged filesystem writer. Non-Unix
/// platforms deliberately take the full-replay path rather than trust mtimes.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct FileStamp {
    device: u64,
    inode: u64,
    length: u64,
    modified: (i64, i64),
    changed: (i64, i64),
    mode: u32,
}

impl DurableInferenceControl {
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
        // Lock BEFORE resolving the journal inode: a peer may publish a
        // compacted generation between open and lock acquisition otherwise.
        let lock_file = acquire_writer_lock(&path)?;
        let file = options.open(&path)?;
        validate_regular_file(&file)?;
        let mut records = BTreeMap::new();
        let mut native = native::NativeJournal::default();
        let mut reader = BufReader::new(file.try_clone()?);
        let mut journal_bytes = 0_u64;
        let mut compaction_archive_digest: Option<String> = None;
        let mut line = Vec::new();
        loop {
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
            if let Some(digest) = line.strip_prefix(COMPACTION_PREFIX) {
                validate_digest(digest, "compaction archive")?;
                if compaction_archive_digest
                    .replace(digest.to_string())
                    .is_some()
                {
                    return Err(Error::CorruptJournal("duplicate compaction header"));
                }
            } else if let Some(json) = line.strip_prefix(LEGACY_CHECKPOINT_PREFIX) {
                let record: RequestRecord = serde_json::from_str(json)
                    .map_err(|_| Error::CorruptJournal("legacy checkpoint decode"))?;
                validate_checkpoint_record(&record)?;
                if records
                    .insert(record.request.request_id.clone(), record)
                    .is_some()
                {
                    return Err(Error::CorruptJournal("duplicate legacy checkpoint"));
                }
            } else if let Some(json) = line.strip_prefix(native::CHECKPOINT_PREFIX) {
                native.replay_checkpoint(json)?;
            } else if let Some(json) = line.strip_prefix(native::JOURNAL_PREFIX) {
                native.replay(json)?;
            } else {
                apply_event(&mut records, &decode_event(line)?, /*replay*/ true)?;
            }
            if records.len() + native.records.len() > capacity {
                return Err(Error::CapacityExceeded);
            }
        }
        if records.keys().any(|id| native.records.contains_key(id)) {
            return Err(Error::Conflict);
        }
        let archive_stamp = verify_compaction_archive(&path, compaction_archive_digest.as_deref())?;
        let cached_stamp = file_stamp(&file)?;
        #[cfg(unix)]
        {
            let parent = path
                .parent()
                .filter(|parent| !parent.as_os_str().is_empty())
                .unwrap_or_else(|| Path::new("."));
            File::open(parent)?.sync_all()?;
        }
        drop(lock_file);
        Ok(Self {
            path,
            file,
            records,
            native,
            capacity,
            journal_bytes,
            poisoned: false,
            cached_stamp,
            archive_digest: compaction_archive_digest,
            archive_stamp,
            replay_stats: JournalReplayStats {
                full_replays: 1,
                replayed_bytes: journal_bytes,
                unchanged_reuses: 0,
            },
        })
    }

    pub fn submit(
        &mut self,
        now_ms: u64,
        request: InferenceRequest,
    ) -> Result<ControlReceipt, Error> {
        validate_request(now_ms, &request)?;
        self.commit(Event::Submit(request))
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

    pub fn replay_stats(&self) -> JournalReplayStats {
        self.replay_stats
    }

    /// The active journal reserves enough headroom for dispatch/cancel metadata
    /// plus one maximal terminal observation. Callers may compact before new
    /// admission when this returns true; compaction preserves the full previous
    /// event stream in a content-addressed sibling archive.
    pub fn needs_compaction(&self) -> bool {
        self.journal_bytes > MAX_JOURNAL_BYTES - 2 * MAX_JOURNAL_LINE_BYTES as u64
    }

    /// Acquire the journal writer fence for one short mutation and refresh
    /// this handle from the latest durable cut. The returned lock must remain
    /// alive through append + fsync; dropping it releases other workers.
    fn reload_locked(&mut self) -> Result<File, Error> {
        if self.poisoned {
            return Err(Error::WriterUnavailable);
        }
        let lock_file = acquire_writer_lock(&self.path)?;
        // Another process may have compacted by atomically replacing the active
        // journal since this handle was opened. Reopen the pathname while the
        // stable sidecar fence is held so replay and the next append target the
        // same current inode.
        let mut options = OpenOptions::new();
        options.append(true).read(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let current_file = options.open(&self.path)?;
        validate_regular_file(&current_file)?;
        let current_stamp = file_stamp(&current_file)?;
        if let (Some(cached), Some(current)) = (self.cached_stamp, current_stamp)
            && cached == current
        {
            // Only reuse a cut whose inode, length, mtime AND ctime are
            // unchanged. Peer appends, same-size edits and generation changes
            // all take full replay. Archive disappearance still fails closed.
            if let Some(digest) = &self.archive_digest {
                let archive = File::open(archive_path(&self.path, digest)?)?;
                validate_private_file(&archive)?;
                let stamp = file_stamp(&archive)?;
                if stamp.is_none() || stamp != self.archive_stamp {
                    self.archive_stamp = verify_compaction_archive(&self.path, Some(digest))?;
                }
            }
            self.file = current_file;
            self.replay_stats.unchanged_reuses =
                self.replay_stats.unchanged_reuses.saturating_add(1);
            return Ok(lock_file);
        }

        let mut records = BTreeMap::new();
        let mut native = native::NativeJournal::default();
        let mut reader = BufReader::new(current_file.try_clone()?);
        let mut journal_bytes = 0_u64;
        let mut compaction_archive_digest: Option<String> = None;
        let mut line = Vec::new();
        loop {
            line.clear();
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
            if let Some(digest) = line.strip_prefix(COMPACTION_PREFIX) {
                validate_digest(digest, "compaction archive")?;
                if compaction_archive_digest
                    .replace(digest.to_string())
                    .is_some()
                {
                    return Err(Error::CorruptJournal("duplicate compaction header"));
                }
            } else if let Some(json) = line.strip_prefix(LEGACY_CHECKPOINT_PREFIX) {
                let record: RequestRecord = serde_json::from_str(json)
                    .map_err(|_| Error::CorruptJournal("legacy checkpoint decode"))?;
                validate_checkpoint_record(&record)?;
                if records
                    .insert(record.request.request_id.clone(), record)
                    .is_some()
                {
                    return Err(Error::CorruptJournal("duplicate legacy checkpoint"));
                }
            } else if let Some(json) = line.strip_prefix(native::CHECKPOINT_PREFIX) {
                native.replay_checkpoint(json)?;
            } else if let Some(json) = line.strip_prefix(native::JOURNAL_PREFIX) {
                native.replay(json)?;
            } else {
                apply_event(&mut records, &decode_event(line)?, /*replay*/ true)?;
            }
            if records.len() + native.records.len() > self.capacity {
                return Err(Error::CapacityExceeded);
            }
        }
        if records.keys().any(|id| native.records.contains_key(id)) {
            return Err(Error::Conflict);
        }
        let archive_stamp =
            verify_compaction_archive(&self.path, compaction_archive_digest.as_deref())?;
        self.records = records;
        self.native = native;
        self.journal_bytes = journal_bytes;
        self.file = current_file;
        self.cached_stamp = current_stamp;
        self.archive_digest = compaction_archive_digest;
        self.archive_stamp = archive_stamp;
        self.replay_stats.full_replays = self.replay_stats.full_replays.saturating_add(1);
        self.replay_stats.replayed_bytes = self
            .replay_stats
            .replayed_bytes
            .saturating_add(journal_bytes);
        Ok(lock_file)
    }

    /// Rewrite the active journal to one canonical checkpoint per current
    /// request while preserving the complete pre-compaction event stream in a
    /// content-addressed sibling archive. Indeterminate/in-flight records stay
    /// in the compacted active journal, so compaction never makes them
    /// replayable or releases their capacity.
    /// Move released native runs out of the hot replay set while preserving
    /// exact idempotence identity in owner-only per-request archives. The full
    /// pre-compaction event stream is still retained by the content-addressed
    /// compaction archive, so this is a hot-state optimization rather than
    /// history deletion.
    pub fn archive_released_native(&mut self) -> Result<NativeArchiveReceipt, Error> {
        let _writer_fence = self.reload_locked()?;
        let released = self
            .native
            .records
            .iter()
            .filter_map(|(id, record)| {
                (record.state == native::NativeReservationState::Released).then(|| id.clone())
            })
            .collect::<BTreeSet<_>>();

        if released.is_empty() {
            if self.needs_compaction() {
                let native_state = self.native.clone();
                self.compact_current_with_archive(&native_state)?;
            }
            return Ok(NativeArchiveReceipt {
                archived: 0,
                remaining_native: self.native.records.len(),
                journal_bytes: self.journal_bytes,
                released_archive_bytes: released_archive_bytes(&self.path)?,
            });
        }

        ensure_released_archive_dir(&self.path)?;
        for request_id in &released {
            let record = self
                .native
                .records
                .get(request_id)
                .ok_or(Error::RequestNotFound)?;
            self.persist_released_native_record(record)?;
        }
        sync_released_archive_dir(&self.path)?;

        // Stage hot-state removal separately. Publication of the compacted
        // journal happens before the in-memory cut changes, so a failed rename
        // never lets this handle forget a command identity while still usable.
        let mut staged_native = self.native.clone();
        for request_id in &released {
            staged_native.records.remove(request_id);
        }
        self.compact_current_with_archive(&staged_native)?;
        self.native = staged_native;

        Ok(NativeArchiveReceipt {
            archived: released.len(),
            remaining_native: self.native.records.len(),
            journal_bytes: self.journal_bytes,
            released_archive_bytes: released_archive_bytes(&self.path)?,
        })
    }

    pub(super) fn archived_native_record(
        &self,
        request_id: &str,
    ) -> Result<Option<native::NativeRunRecord>, Error> {
        validate_identity(request_id, "native archived request")?;
        let path = released_record_path(&self.path, request_id)?;
        let mut file = match File::open(&path) {
            Ok(file) => file,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error.into()),
        };
        validate_private_file(&file)?;
        if file.metadata()?.len() > MAX_JOURNAL_LINE_BYTES as u64 {
            return Err(Error::CorruptJournal("native released archive size"));
        }
        let mut bytes = Vec::new();
        file.read_to_end(&mut bytes)?;
        let record: native::NativeRunRecord = serde_json::from_slice(&bytes)
            .map_err(|_| Error::CorruptJournal("native released archive decode"))?;
        native::validate_checkpoint(&record)?;
        if record.request.request_id != request_id
            || record.state != native::NativeReservationState::Released
        {
            return Err(Error::CorruptJournal("native released archive identity"));
        }
        Ok(Some(record))
    }

    fn persist_released_native_record(
        &self,
        record: &native::NativeRunRecord,
    ) -> Result<(), Error> {
        if record.state != native::NativeReservationState::Released {
            return Err(Error::InvalidTransition);
        }
        native::validate_checkpoint(record)?;
        let path = released_record_path(&self.path, &record.request.request_id)?;
        let encoded = serde_json::to_vec(record)
            .map_err(|_| Error::CorruptJournal("native released archive encode"))?;
        if encoded.len() > MAX_JOURNAL_LINE_BYTES {
            return Err(Error::CapacityExceeded);
        }

        match File::open(&path) {
            Ok(mut existing) => {
                validate_private_file(&existing)?;
                if existing.metadata()?.len() > MAX_JOURNAL_LINE_BYTES as u64 {
                    return Err(Error::CorruptJournal("native released archive size"));
                }
                let mut bytes = Vec::new();
                existing.read_to_end(&mut bytes)?;
                if bytes != encoded {
                    return Err(Error::Conflict);
                }
                return Ok(());
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }

        let mut options = OpenOptions::new();
        options.create_new(true).write(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut archive = options.open(path)?;
        archive.write_all(&encoded)?;
        archive.flush()?;
        archive.sync_all()?;
        Ok(())
    }

    pub fn compact_with_archive(&mut self) -> Result<PathBuf, Error> {
        let _writer_fence = self.reload_locked()?;
        let native_state = self.native.clone();
        self.compact_current_with_archive(&native_state)
    }

    fn compact_current_with_archive(
        &mut self,
        native_state: &native::NativeJournal,
    ) -> Result<PathBuf, Error> {
        let mut source = File::open(&self.path)?;
        let archive_digest = digest_hex(Digest32::of_reader(&mut source, MAX_JOURNAL_BYTES)?);
        let archive = archive_path(&self.path, &archive_digest)?;
        if archive.exists() {
            verify_archive_file(&archive, &archive_digest)?;
        } else {
            let archive_tmp = sibling_temp_path(&archive, "tmp");
            let mut archived = fresh_private_temporary(&archive_tmp)?;
            source.seek(SeekFrom::Start(0))?;
            let copied = std::io::copy(&mut source.take(MAX_JOURNAL_BYTES + 1), &mut archived)?;
            if copied > MAX_JOURNAL_BYTES {
                return Err(Error::CapacityExceeded);
            }
            archived.flush()?;
            archived.sync_all()?;
            verify_archive_file(&archive_tmp, &archive_digest)?;
            fs::rename(&archive_tmp, &archive)?;
            sync_parent(&self.path)?;
        }

        // Emit one bounded record at a time. Do not hold both the complete
        // source stream and the complete checkpoint image in memory.
        let tmp = sibling_temp_path(&self.path, "compact");
        let mut compact_file = fresh_private_temporary(&tmp)?;
        let mut compacted_bytes = 0;
        write_checkpoint_line(
            &mut compact_file,
            &mut compacted_bytes,
            &format!("{COMPACTION_PREFIX}{archive_digest}\n"),
        )?;
        for record in self.records.values() {
            let json = serde_json::to_string(record)
                .map_err(|_| Error::CorruptJournal("legacy checkpoint encode"))?;
            write_checkpoint_line(
                &mut compact_file,
                &mut compacted_bytes,
                &format!("{LEGACY_CHECKPOINT_PREFIX}{json}\n"),
            )?;
        }
        for line in native_state.checkpoint_lines() {
            write_checkpoint_line(&mut compact_file, &mut compacted_bytes, &line?)?;
        }
        compact_file.flush()?;
        compact_file.sync_all()?;

        // Once publication is attempted, any I/O error requires reopen. Never
        // continue through an old inode after an uncertain rename/dir fsync.
        self.poisoned = true;
        fs::rename(&tmp, &self.path)?;
        sync_parent(&self.path)?;
        self.file = OpenOptions::new()
            .append(true)
            .read(true)
            .open(&self.path)?;
        validate_private_file(&self.file)?;
        self.cached_stamp = file_stamp(&self.file)?;
        self.archive_stamp = verify_compaction_archive(&self.path, Some(&archive_digest))?;
        self.archive_digest = Some(archive_digest);
        self.journal_bytes = compacted_bytes;
        self.poisoned = false;
        Ok(archive)
    }

    fn commit(&mut self, event: Event) -> Result<ControlReceipt, Error> {
        let _writer_fence = self.reload_locked()?;
        // Idempotence, capacity and record-bound validation are evaluated under
        // the same writer fence as the append. A stale handle can therefore
        // never return a receipt from its pre-refresh cache.
        if let Some(existing) = self.validate_latest_event(&event)? {
            return Ok(existing);
        }
        let request_id = event.request_id().to_string();
        // Preparation copies only the affected record; the durable append
        // still precedes publication and validation failures leave state alone.
        let mut prepared = BTreeMap::new();
        if let Some(record) = self.records.get(&request_id) {
            prepared.insert(request_id.clone(), record.clone());
        }
        apply_event(&mut prepared, &event, /*replay*/ false)?;
        let next = prepared.remove(&request_id).ok_or(Error::RequestNotFound)?;
        let encoded = format!("{}\n", encode_event(&event));
        self.append(&encoded)?;
        self.records.insert(request_id.clone(), next);
        let record = self
            .records
            .get(&request_id)
            .ok_or(Error::RequestNotFound)?;
        Ok(receipt(record, /*idempotent*/ false))
    }

    fn validate_latest_event(&self, event: &Event) -> Result<Option<ControlReceipt>, Error> {
        match event {
            Event::Submit(request) => {
                if self.native.records.contains_key(&request.request_id) {
                    return Err(Error::Conflict);
                }
                if let Some(current) = self.records.get(&request.request_id) {
                    if current.request == *request {
                        return Ok(Some(receipt(current, /*idempotent*/ true)));
                    }
                    return Err(Error::Conflict);
                }
                if self.records.len() + self.native.records.len() >= self.capacity {
                    return Err(Error::CapacityExceeded);
                }
            }
            Event::Reserve {
                request_id,
                expected_revision,
                reservation,
            } => {
                let record = self.records.get(request_id).ok_or(Error::RequestNotFound)?;
                require_revision(record, *expected_revision, /*replay*/ false)?;
                if record.state == RequestState::Reserved
                    && record.reservation.as_ref() == Some(reservation)
                {
                    return Ok(Some(receipt(record, /*idempotent*/ true)));
                }
                if record.state != RequestState::Pending {
                    return Err(Error::InvalidTransition);
                }
                if reservation.maximum_tokens < record.request.maximum_tokens {
                    return Err(Error::UsageExceeded);
                }
            }
            Event::Assign {
                request_id,
                expected_revision,
                assignment,
            } => {
                let record = self.records.get(request_id).ok_or(Error::RequestNotFound)?;
                require_revision(record, *expected_revision, /*replay*/ false)?;
                if record.state == RequestState::Assigned
                    && record.assignment.as_ref() == Some(assignment)
                {
                    return Ok(Some(receipt(record, /*idempotent*/ true)));
                }
                if record.state != RequestState::Reserved {
                    return Err(Error::InvalidTransition);
                }
            }
            Event::Cancel {
                request_id,
                expected_revision,
            } => {
                let record = self.records.get(request_id).ok_or(Error::RequestNotFound)?;
                require_revision(record, *expected_revision, /*replay*/ false)?;
                if matches!(
                    record.state,
                    RequestState::Cancelled | RequestState::Cancelling
                ) {
                    return Ok(Some(receipt(record, /*idempotent*/ true)));
                }
                if record.state.terminal() {
                    return Err(Error::InvalidTransition);
                }
            }
            Event::Settle {
                request_id,
                expected_revision,
                observation_digest,
                observation,
            } => {
                let record = self.records.get(request_id).ok_or(Error::RequestNotFound)?;
                require_revision(record, *expected_revision, /*replay*/ false)?;
                if record.terminal_observation_digest.as_ref() == Some(observation_digest) {
                    return Ok(Some(receipt(record, /*idempotent*/ true)));
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
            }
        }
        Ok(None)
    }

    fn append(&mut self, encoded: &str) -> Result<(), Error> {
        if self.poisoned {
            return Err(Error::WriterUnavailable);
        }
        let next_bytes = self
            .journal_bytes
            .checked_add(encoded.len() as u64)
            .ok_or(Error::ArithmeticOverflow)?;
        if encoded.len() > MAX_JOURNAL_LINE_BYTES || next_bytes > MAX_JOURNAL_BYTES {
            return Err(Error::CapacityExceeded);
        }
        let persisted = self
            .file
            .write_all(encoded.as_bytes())
            .and_then(|()| self.file.flush())
            .and_then(|()| self.file.sync_all());
        if let Err(error) = persisted {
            // A partial write or failed sync has an unknown durable outcome.
            // Keep this owner fenced until explicit inspection and reopen.
            self.poisoned = true;
            return Err(error.into());
        }
        self.journal_bytes = next_bytes;
        match file_stamp(&self.file) {
            Ok(stamp) => self.cached_stamp = stamp,
            Err(error) => {
                self.poisoned = true;
                return Err(error);
            }
        }
        Ok(())
    }
}

fn released_archive_dir(path: &Path) -> PathBuf {
    sibling_temp_path(path, "released")
}

fn ensure_released_archive_dir(path: &Path) -> Result<(), Error> {
    let directory = released_archive_dir(path);
    match fs::symlink_metadata(&directory) {
        Ok(metadata) if !metadata.is_dir() => {
            return Err(Error::InvalidIdentity("native released archive must be a directory"));
        }
        Ok(metadata) => {
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                if metadata.permissions().mode() & 0o077 != 0 {
                    return Err(Error::InvalidIdentity("native released archive must be owner-only"));
                }
            }
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            fs::create_dir(&directory)?;
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                fs::set_permissions(&directory, fs::Permissions::from_mode(0o700))?;
            }
            sync_parent(path)?;
        }
        Err(error) => return Err(error.into()),
    }
    Ok(())
}

fn released_record_path(path: &Path, request_id: &str) -> Result<PathBuf, Error> {
    validate_identity(request_id, "native archived request")?;
    let name = digest_hex(Digest32::of_bytes(request_id.as_bytes()));
    Ok(released_archive_dir(path).join(format!("{name}.json")))
}

fn sync_released_archive_dir(path: &Path) -> Result<(), Error> {
    File::open(released_archive_dir(path))?.sync_all()?;
    Ok(())
}

fn released_archive_bytes(path: &Path) -> Result<u64, Error> {
    let directory = released_archive_dir(path);
    let entries = match fs::read_dir(&directory) {
        Ok(entries) => entries,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(0),
        Err(error) => return Err(error.into()),
    };
    let mut total = 0_u64;
    for entry in entries {
        let entry = entry?;
        let metadata = entry.metadata()?;
        if !metadata.is_file() {
            return Err(Error::InvalidIdentity("native released archive entry"));
        }
        total = total
            .checked_add(metadata.len())
            .ok_or(Error::ArithmeticOverflow)?;
    }
    Ok(total)
}

fn acquire_writer_lock(path: &Path) -> Result<File, Error> {
    let lock_path = sibling_temp_path(path, "writer.lock");
    let mut options = OpenOptions::new();
    options.create(true).read(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let lock = options.open(lock_path)?;
    lock.try_lock().map_err(|_| Error::WriterUnavailable)?;
    Ok(lock)
}

fn sibling_temp_path(path: &Path, suffix: &str) -> PathBuf {
    let file_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("inference.journal");
    path.with_file_name(format!("{file_name}.{suffix}"))
}

fn digest_hex(digest: Digest32) -> String {
    let mut hex = String::with_capacity(64);
    const HEX: &[u8; 16] = b"0123456789abcdef";
    for &byte in digest.as_array() {
        hex.push(HEX[(byte >> 4) as usize] as char);
        hex.push(HEX[(byte & 0x0f) as usize] as char);
    }
    hex
}

fn archive_path(path: &Path, digest: &str) -> Result<PathBuf, Error> {
    validate_digest(digest, "compaction archive")?;
    let file_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or(Error::InvalidIdentity("journal path"))?;
    Ok(path.with_file_name(format!("{file_name}.{ARCHIVE_SUFFIX_PREFIX}{digest}")))
}

fn validate_regular_file(file: &File) -> Result<(), Error> {
    if !file.metadata()?.is_file() {
        return Err(Error::InvalidIdentity("journal must be a regular file"));
    }
    Ok(())
}

fn validate_private_file(file: &File) -> Result<(), Error> {
    validate_regular_file(file)?;
    let metadata = file.metadata()?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(Error::InvalidIdentity("journal must be owner-only"));
        }
    }
    Ok(())
}

fn file_stamp(file: &File) -> Result<Option<FileStamp>, Error> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let metadata = file.metadata()?;
        // Legacy journals may be readable with broader modes. They never
        // earn a cached cut; native writes still require owner-only access.
        if metadata.mode() & 0o077 != 0 {
            return Ok(None);
        }
        Ok(Some(FileStamp {
            device: metadata.dev(),
            inode: metadata.ino(),
            length: metadata.len(),
            modified: (metadata.mtime(), metadata.mtime_nsec()),
            changed: (metadata.ctime(), metadata.ctime_nsec()),
            mode: metadata.mode(),
        }))
    }
    #[cfg(not(unix))]
    {
        file.metadata()?;
        Ok(None)
    }
}

fn sync_parent(path: &Path) -> Result<(), Error> {
    let parent = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    File::open(parent)?.sync_all()?;
    Ok(())
}

fn fresh_private_temporary(path: &Path) -> Result<File, Error> {
    // The caller holds the stable owner fence. A regular temporary left by a
    // killed compactor is not authoritative history; never follow a symlink.
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.is_file() => fs::remove_file(path)?,
        Ok(_) => return Err(Error::InvalidIdentity("non-regular compaction temporary")),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => return Err(error.into()),
    }
    let mut options = OpenOptions::new();
    options.create_new(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    Ok(options.open(path)?)
}

fn write_checkpoint_line(file: &mut File, total: &mut u64, line: &str) -> Result<(), Error> {
    let next = total
        .checked_add(line.len() as u64)
        .ok_or(Error::ArithmeticOverflow)?;
    if line.len() > MAX_JOURNAL_LINE_BYTES || next > MAX_JOURNAL_BYTES {
        return Err(Error::CapacityExceeded);
    }
    file.write_all(line.as_bytes())?;
    *total = next;
    Ok(())
}

fn verify_archive_file(path: &Path, expected_digest: &str) -> Result<Option<FileStamp>, Error> {
    let mut file = File::open(path)?;
    validate_private_file(&file)?;
    if digest_hex(Digest32::of_reader(&mut file, MAX_JOURNAL_BYTES)?) != expected_digest {
        return Err(Error::CorruptJournal("compaction archive digest"));
    }
    file_stamp(&file)
}

fn verify_compaction_archive(
    path: &Path,
    expected_digest: Option<&str>,
) -> Result<Option<FileStamp>, Error> {
    let Some(expected_digest) = expected_digest else {
        return Ok(None);
    };
    let archive = archive_path(path, expected_digest)?;
    verify_archive_file(&archive, expected_digest)
}

fn validate_checkpoint_record(record: &RequestRecord) -> Result<(), Error> {
    validate_request(0, &record.request)?;
    if record.revision == 0 {
        return Err(Error::CorruptJournal("checkpoint revision"));
    }
    if let Some(reservation) = &record.reservation {
        validate_identity(&reservation.reservation_id, "reservation")?;
        if reservation.quota_units == 0
            || reservation.maximum_tokens == 0
            || reservation.maximum_tokens > MAX_TOKENS
            || reservation.authority_epoch == 0
        {
            return Err(Error::CorruptJournal("checkpoint reservation"));
        }
    }
    if let Some(assignment) = &record.assignment {
        validate_assignment(assignment)?;
    }
    if let Some(digest) = &record.terminal_observation_digest {
        validate_digest(digest, "observation")?;
    }
    if record.consumed_tokens > MAX_TOKENS {
        return Err(Error::UsageExceeded);
    }
    Ok(())
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

#[cfg(all(test, unix))]
#[path = "durable_scalability_tests.rs"]
mod scalability_tests;
