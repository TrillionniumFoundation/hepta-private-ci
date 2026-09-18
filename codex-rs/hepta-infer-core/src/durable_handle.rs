//! Reopen-per-transaction handle for the inference control journal.
//!
//! The journal remains the single durable owner. Each mutation acquires one
//! sidecar coordination lock, opens/replays the current journal, commits one
//! bounded state transition, fsyncs it and releases both locks before model or
//! network work. A full journal may roll over only when every native request is
//! released. Immutable old segments and compact request tombstones preserve
//! auditability and prevent semantic resurrection across capacity cycles.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::BufRead;
use std::io::BufReader;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;

use crate::durable_control::DurableInferenceControl;
use crate::durable_control::Error;
use crate::durable_control::native::NativeDispatch;
use crate::durable_control::native::NativeRequest;
use crate::durable_control::native::NativeRunOutput;
use crate::durable_control::native::NativeRunRecord;

const WRITER_RETRY_ATTEMPTS: usize = 200;
const WRITER_RETRY_DELAY: Duration = Duration::from_millis(10);
const MAX_TOMBSTONE_SEGMENT_BYTES: u64 = 64 * 1024 * 1024;
const MAX_TOMBSTONE_LINE_BYTES: usize = 4096;
const NATIVE_PREFIX: &str = "native-v1|";

#[derive(Clone, Debug)]
pub struct DurableInferenceControlHandle {
    path: PathBuf,
    capacity: usize,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct ArchivedRequestTombstone {
    request_id: String,
    request_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct ArchiveReceipt {
    archive_file: String,
    original_bytes: u64,
    released_requests: usize,
    rolled_at_unix_nanos: u128,
}

#[derive(Clone, Debug)]
struct ScannedRequest {
    request: NativeRequest,
    released: bool,
}

impl DurableInferenceControlHandle {
    pub fn new(path: impl AsRef<Path>, capacity: usize) -> Result<Self, Error> {
        let handle = Self {
            path: path.as_ref().to_path_buf(),
            capacity,
        };
        handle.with_coordination(|this| {
            drop(this.open_current_with_retry()?);
            Ok(())
        })?;
        Ok(handle)
    }

    pub fn journal_path(&self) -> &Path {
        &self.path
    }

    fn coordination_path(&self) -> PathBuf {
        PathBuf::from(format!("{}.owner.lock", self.path.display()))
    }

    fn legacy_tombstone_path(&self) -> PathBuf {
        PathBuf::from(format!("{}.tombstones.jsonl", self.path.display()))
    }

    fn tombstone_segment_path(&self, index: u64) -> PathBuf {
        PathBuf::from(format!(
            "{}.tombstones.{index:08}.jsonl",
            self.path.display()
        ))
    }

    fn tombstone_paths(&self) -> Result<Vec<(u64, PathBuf)>, Error> {
        let parent = self
            .path
            .parent()
            .filter(|path| !path.as_os_str().is_empty())
            .unwrap_or_else(|| Path::new("."));
        let base = self
            .path
            .file_name()
            .and_then(|name| name.to_str())
            .ok_or(Error::InvalidIdentity("journal path"))?;
        let legacy_name = format!("{base}.tombstones.jsonl");
        let prefix = format!("{base}.tombstones.");
        let mut paths = Vec::new();
        for entry in fs::read_dir(parent)? {
            let entry = entry?;
            let name = entry.file_name();
            let Some(name) = name.to_str() else { continue };
            if name == legacy_name {
                paths.push((0, entry.path()));
                continue;
            }
            let Some(rest) = name.strip_prefix(&prefix) else { continue };
            let Some(number) = rest.strip_suffix(".jsonl") else { continue };
            if number.len() != 8 || !number.bytes().all(|byte| byte.is_ascii_digit()) {
                continue;
            }
            let index = number
                .parse::<u64>()
                .map_err(|_| Error::CorruptJournal("tombstone segment name"))?;
            if index == 0 {
                return Err(Error::CorruptJournal("zero tombstone segment"));
            }
            paths.push((index, entry.path()));
        }
        paths.sort_by_key(|(index, _)| *index);
        for pair in paths.windows(2) {
            if pair[0].0 == pair[1].0 {
                return Err(Error::CorruptJournal("duplicate tombstone segment"));
            }
        }
        Ok(paths)
    }

    fn archive_receipt_path(&self) -> PathBuf {
        PathBuf::from(format!("{}.archives.jsonl", self.path.display()))
    }

    fn with_coordination<T>(
        &self,
        operation: impl FnOnce(&Self) -> Result<T, Error>,
    ) -> Result<T, Error> {
        if let Some(parent) = self.path.parent() {
            fs::create_dir_all(parent)?;
        }
        let lock_path = self.coordination_path();
        let mut options = OpenOptions::new();
        options.create(true).read(true).write(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let lock = options.open(&lock_path)?;
        for attempt in 0..=WRITER_RETRY_ATTEMPTS {
            match lock.try_lock() {
                Ok(()) => return operation(self),
                Err(_) if attempt < WRITER_RETRY_ATTEMPTS => {
                    std::thread::sleep(WRITER_RETRY_DELAY);
                }
                Err(_) => return Err(Error::WriterUnavailable),
            }
        }
        Err(Error::WriterUnavailable)
    }

    fn open_current_with_retry(&self) -> Result<DurableInferenceControl, Error> {
        for attempt in 0..=WRITER_RETRY_ATTEMPTS {
            match DurableInferenceControl::open(&self.path, self.capacity) {
                Ok(control) => return Ok(control),
                Err(Error::WriterUnavailable) if attempt < WRITER_RETRY_ATTEMPTS => {
                    std::thread::sleep(WRITER_RETRY_DELAY);
                }
                Err(error) => return Err(error),
            }
        }
        Err(Error::WriterUnavailable)
    }

    fn transaction_unlocked<T>(
        &self,
        operation: impl FnOnce(&mut DurableInferenceControl) -> Result<T, Error>,
    ) -> Result<T, Error> {
        let mut control = self.open_current_with_retry()?;
        operation(&mut control)
    }

    fn transaction<T>(
        &self,
        operation: impl FnOnce(&mut DurableInferenceControl) -> Result<T, Error>,
    ) -> Result<T, Error> {
        self.with_coordination(|this| this.transaction_unlocked(operation))
    }

    pub fn reserve_native(
        &self,
        request: NativeRequest,
        maximum_in_flight: usize,
    ) -> Result<NativeRunRecord, Error> {
        self.with_coordination(|this| {
            this.reject_archived_request(&request)?;
            match this.transaction_unlocked(|control| {
                control.reserve_native(request.clone(), maximum_in_flight)
            }) {
                Ok(record) => Ok(record),
                Err(Error::CapacityExceeded) => {
                    if !this.rollover_quiescent_unlocked()? {
                        return Err(Error::CapacityExceeded);
                    }
                    this.reject_archived_request(&request)?;
                    this.transaction_unlocked(|control| {
                        control.reserve_native(request, maximum_in_flight)
                    })
                }
                Err(error) => Err(error),
            }
        })
    }

    pub fn dispatch_native(
        &self,
        request_id: &str,
        dispatch: NativeDispatch,
    ) -> Result<NativeRunRecord, Error> {
        self.transaction(|control| control.dispatch_native(request_id, dispatch))
    }

    pub fn native_started(
        &self,
        request_id: &str,
        turn_id: String,
    ) -> Result<NativeRunRecord, Error> {
        self.transaction(|control| control.native_started(request_id, turn_id))
    }

    pub fn cancel_native(&self, request_id: &str) -> Result<NativeRunRecord, Error> {
        self.transaction(|control| control.cancel_native(request_id))
    }

    pub fn stop_native_before_dispatch(
        &self,
        request_id: &str,
        reason: String,
    ) -> Result<NativeRunRecord, Error> {
        self.transaction(|control| control.stop_native_before_dispatch(request_id, reason))
    }

    pub fn stop_native_before_turn_start(
        &self,
        request_id: &str,
        reason: String,
    ) -> Result<NativeRunRecord, Error> {
        self.transaction(|control| control.stop_native_before_turn_start(request_id, reason))
    }

    pub fn settle_native(
        &self,
        request_id: &str,
        output: NativeRunOutput,
    ) -> Result<NativeRunRecord, Error> {
        self.transaction(|control| control.settle_native(request_id, output))
    }

    pub fn native_record(&self, request_id: &str) -> Result<Option<NativeRunRecord>, Error> {
        self.transaction(|control| Ok(control.native_record(request_id).cloned()))
    }

    /// Explicit maintenance hook. Returns true only after a complete quiescent
    /// rollover. Any unresolved external effect keeps the current segment live.
    pub fn rollover_if_quiescent(&self) -> Result<bool, Error> {
        self.with_coordination(|this| this.rollover_quiescent_unlocked())
    }

    fn reject_archived_request(&self, request: &NativeRequest) -> Result<(), Error> {
        let wanted = BTreeSet::from([request.request_id.clone()]);
        let tombstones = self.read_tombstones_for(&wanted)?;
        if tombstones.contains_key(&request.request_id) {
            return Err(Error::Conflict);
        }
        Ok(())
    }

    /// Stream every bounded segment but retain only identities needed by the
    /// current operation. Historical growth therefore affects disk scan work,
    /// not peak memory. Conflicting duplicate identities fail closed.
    fn read_tombstones_for(
        &self,
        wanted: &BTreeSet<String>,
    ) -> Result<BTreeMap<String, String>, Error> {
        let mut result = BTreeMap::new();
        for (_, path) in self.tombstone_paths()? {
            let file = File::open(&path)?;
            if file.metadata()?.len() > MAX_TOMBSTONE_SEGMENT_BYTES {
                return Err(Error::CapacityExceeded);
            }
            for line in BufReader::new(file).lines() {
                let line = line?;
                if line.len() > MAX_TOMBSTONE_LINE_BYTES {
                    return Err(Error::CorruptJournal("archived tombstone line"));
                }
                if line.is_empty() {
                    continue;
                }
                let tombstone: ArchivedRequestTombstone = serde_json::from_str(&line)
                    .map_err(|_| Error::CorruptJournal("archived tombstone"))?;
                if !wanted.contains(&tombstone.request_id) {
                    continue;
                }
                match result.insert(
                    tombstone.request_id,
                    tombstone.request_digest.clone(),
                ) {
                    Some(previous) if previous != tombstone.request_digest => {
                        return Err(Error::CorruptJournal("archived tombstone conflict"));
                    }
                    _ => {}
                }
            }
        }
        Ok(result)
    }

    fn rollover_quiescent_unlocked(&self) -> Result<bool, Error> {
        let current = self.open_current_with_retry()?;
        let scanned = scan_native_journal(&self.path)?;
        if scanned.is_empty() || scanned.values().any(|record| !record.released) {
            return Ok(false);
        }
        let current_bytes = current.journal_path().metadata()?.len();
        drop(current);

        let wanted = scanned.keys().cloned().collect::<BTreeSet<_>>();
        let existing = self.read_tombstones_for(&wanted)?;
        let mut additions = Vec::new();
        for record in scanned.values() {
            let digest = native_request_digest(&record.request)?;
            if let Some(previous) = existing.get(&record.request.request_id) {
                if previous != &digest {
                    return Err(Error::CorruptJournal("archived request identity drift"));
                }
                continue;
            }
            additions.push(ArchivedRequestTombstone {
                request_id: record.request.request_id.clone(),
                request_digest: digest,
            });
        }
        self.append_tombstones(&additions)?;

        let rolled_at_unix_nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| Error::InvalidTime)?
            .as_nanos();
        let archive_path = PathBuf::from(format!(
            "{}.archive.{rolled_at_unix_nanos}.journal",
            self.path.display()
        ));
        if archive_path.exists() {
            return Err(Error::Conflict);
        }
        fs::rename(&self.path, &archive_path)?;
        sync_parent(&self.path)?;
        drop(self.open_current_with_retry()?);
        let receipt = ArchiveReceipt {
            archive_file: archive_path
                .file_name()
                .and_then(|name| name.to_str())
                .ok_or(Error::InvalidIdentity("archive file"))?
                .to_string(),
            original_bytes: current_bytes,
            released_requests: scanned.len(),
            rolled_at_unix_nanos,
        };
        self.append_archive_receipt(&receipt)?;
        Ok(true)
    }

    fn append_tombstones(&self, additions: &[ArchivedRequestTombstone]) -> Result<(), Error> {
        if additions.is_empty() {
            return Ok(());
        }
        let paths = self.tombstone_paths()?;
        let mut segment = paths
            .iter()
            .filter(|(index, _)| *index > 0)
            .map(|(index, _)| *index)
            .max()
            .unwrap_or(1);
        let mut path = self.tombstone_segment_path(segment);
        let mut existing = path.metadata().map(|meta| meta.len()).unwrap_or(0);

        for tombstone in additions {
            let mut encoded = serde_json::to_vec(tombstone)
                .map_err(|_| Error::CorruptJournal("archived tombstone encode"))?;
            if encoded.len() > MAX_TOMBSTONE_LINE_BYTES {
                return Err(Error::CapacityExceeded);
            }
            encoded.push(b'\n');
            if existing.saturating_add(encoded.len() as u64) > MAX_TOMBSTONE_SEGMENT_BYTES {
                segment = segment.checked_add(1).ok_or(Error::CapacityExceeded)?;
                path = self.tombstone_segment_path(segment);
                if path.exists() {
                    return Err(Error::CorruptJournal("tombstone segment collision"));
                }
                existing = 0;
            }

            let mut options = OpenOptions::new();
            options.create(true).append(true).read(true);
            #[cfg(unix)]
            {
                use std::os::unix::fs::OpenOptionsExt;
                options.mode(0o600);
            }
            let mut file = options.open(&path)?;
            let on_disk = file.metadata()?.len();
            if on_disk != existing
                || on_disk.saturating_add(encoded.len() as u64) > MAX_TOMBSTONE_SEGMENT_BYTES
            {
                return Err(Error::CorruptJournal("tombstone segment size drift"));
            }
            file.write_all(&encoded)?;
            file.flush()?;
            file.sync_all()?;
            sync_parent(&path)?;
            existing = existing.saturating_add(encoded.len() as u64);
        }
        Ok(())
    }

    fn append_archive_receipt(&self, receipt: &ArchiveReceipt) -> Result<(), Error> {
        let path = self.archive_receipt_path();
        let mut options = OpenOptions::new();
        options.create(true).append(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut file = options.open(&path)?;
        let encoded = serde_json::to_vec(receipt)
            .map_err(|_| Error::CorruptJournal("archive receipt encode"))?;
        if encoded.len() > MAX_TOMBSTONE_LINE_BYTES {
            return Err(Error::CapacityExceeded);
        }
        file.write_all(&encoded)?;
        file.write_all(b"\n")?;
        file.flush()?;
        file.sync_all()?;
        sync_parent(&path)
    }
}

fn scan_native_journal(path: &Path) -> Result<BTreeMap<String, ScannedRequest>, Error> {
    let file = File::open(path)?;
    let mut records: BTreeMap<String, ScannedRequest> = BTreeMap::new();
    for line in BufReader::new(file).lines() {
        let line = line?;
        if line.is_empty() {
            continue;
        }
        let json = line
            .strip_prefix(NATIVE_PREFIX)
            .ok_or(Error::InvalidTransition)?;
        let value: Value =
            serde_json::from_str(json).map_err(|_| Error::CorruptJournal("native archive scan"))?;
        let object = value
            .as_object()
            .filter(|object| object.len() == 1)
            .ok_or(Error::CorruptJournal("native archive event"))?;
        let (kind, payload) = object.iter().next().expect("single event field");
        let payload = payload
            .as_object()
            .ok_or(Error::CorruptJournal("native archive payload"))?;
        match kind.as_str() {
            "Reserve" => {
                let request: NativeRequest = serde_json::from_value(
                    payload
                        .get("request")
                        .cloned()
                        .ok_or(Error::CorruptJournal("native archive reserve"))?,
                )
                .map_err(|_| Error::CorruptJournal("native archive request"))?;
                if records
                    .insert(
                        request.request_id.clone(),
                        ScannedRequest {
                            request,
                            released: false,
                        },
                    )
                    .is_some()
                {
                    return Err(Error::CorruptJournal("native archive duplicate reserve"));
                }
            }
            "Dispatch" | "Started" | "Cancel" => {
                let id = event_request_id(payload)?;
                let record = records
                    .get_mut(id)
                    .ok_or(Error::CorruptJournal("native archive missing reserve"))?;
                record.released = false;
            }
            "Stop" => {
                let id = event_request_id(payload)?;
                let record = records
                    .get_mut(id)
                    .ok_or(Error::CorruptJournal("native archive missing reserve"))?;
                record.released = true;
            }
            "Observe" => {
                let id = event_request_id(payload)?.to_string();
                let output: NativeRunOutput = serde_json::from_value(
                    payload
                        .get("output")
                        .cloned()
                        .ok_or(Error::CorruptJournal("native archive observe"))?,
                )
                .map_err(|_| Error::CorruptJournal("native archive output"))?;
                let record = records
                    .get_mut(&id)
                    .ok_or(Error::CorruptJournal("native archive missing reserve"))?;
                record.released = output.terminal_observed;
            }
            _ => return Err(Error::CorruptJournal("native archive event kind")),
        }
    }
    Ok(records)
}

fn event_request_id(payload: &serde_json::Map<String, Value>) -> Result<&str, Error> {
    payload
        .get("request_id")
        .and_then(Value::as_str)
        .ok_or(Error::CorruptJournal("native archive request id"))
}

fn native_request_digest(request: &NativeRequest) -> Result<String, Error> {
    let bytes = serde_json::to_vec(request)
        .map_err(|_| Error::CorruptJournal("native request tombstone encode"))?;
    Ok(hex_lower(Digest32::of_bytes(&bytes).as_array()))
}

fn hex_lower(bytes: &[u8; 32]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(64);
    for byte in bytes {
        output.push(HEX[(byte >> 4) as usize] as char);
        output.push(HEX[(byte & 0x0f) as usize] as char);
    }
    output
}

fn sync_parent(path: &Path) -> Result<(), Error> {
    #[cfg(unix)]
    {
        let parent = path
            .parent()
            .filter(|parent| !parent.as_os_str().is_empty())
            .unwrap_or_else(|| Path::new("."));
        File::open(parent)?.sync_all()?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;
    use std::sync::Barrier;

    use super::*;

    fn request(id: &str) -> NativeRequest {
        NativeRequest {
            request_id: id.to_string(),
            principal_id: "agent-one".to_string(),
            worker_generation: 1,
            model: "model-one".to_string(),
            payload_digest: "1".repeat(64),
        }
    }

    #[test]
    fn handle_does_not_retain_writer_lock_between_transactions() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("inference.journal");
        let handle = DurableInferenceControlHandle::new(&path, 16).unwrap();

        let second_writer = DurableInferenceControl::open(&path, 16)
            .expect("handle lifetime must not retain the journal writer lock");
        drop(second_writer);

        handle.reserve_native(request("r1"), 2).unwrap();
        assert!(handle.native_record("r1").unwrap().is_some());
    }

    #[test]
    fn concurrent_handles_share_one_budget_without_holding_model_length_lock() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("inference.journal");
        let handle = DurableInferenceControlHandle::new(&path, 16).unwrap();
        let barrier = Arc::new(Barrier::new(3));

        let mut threads = Vec::new();
        for id in ["r1", "r2"] {
            let handle = handle.clone();
            let barrier = Arc::clone(&barrier);
            threads.push(std::thread::spawn(move || {
                barrier.wait();
                handle.reserve_native(request(id), 2)
            }));
        }
        barrier.wait();
        for thread in threads {
            thread.join().unwrap().unwrap();
        }

        assert!(handle.native_record("r1").unwrap().is_some());
        assert!(handle.native_record("r2").unwrap().is_some());
        let third = handle.reserve_native(request("r3"), 2);
        assert_eq!(third.unwrap_err(), Error::CapacityExceeded);
    }

    #[test]
    fn released_history_rolls_over_and_cannot_be_replayed() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("inference.journal");
        let handle = DurableInferenceControlHandle::new(&path, 1).unwrap();
        handle.reserve_native(request("old"), 1).unwrap();
        handle
            .stop_native_before_dispatch("old", "local stop".to_string())
            .unwrap();

        handle.reserve_native(request("new"), 1).unwrap();
        assert!(handle.native_record("new").unwrap().is_some());
        assert_eq!(
            handle.reserve_native(request("old"), 1).unwrap_err(),
            Error::Conflict
        );
        assert!(handle.tombstone_path().is_file());
        assert!(handle.archive_receipt_path().is_file());
    }

    #[test]
    fn unresolved_dispatch_blocks_rollover() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("inference.journal");
        let handle = DurableInferenceControlHandle::new(&path, 1).unwrap();
        handle.reserve_native(request("r1"), 1).unwrap();
        handle
            .dispatch_native(
                "r1",
                NativeDispatch {
                    thread_id: "thread-one".to_string(),
                    model_provider: "provider-one".to_string(),
                    context_digest: "2".repeat(64),
                },
            )
            .unwrap();

        assert_eq!(
            handle.reserve_native(request("r2"), 1).unwrap_err(),
            Error::CapacityExceeded
        );
        assert!(!handle.rollover_if_quiescent().unwrap());
    }

    #[test]
    fn proven_pre_turn_stop_releases_slot_and_allows_rollover() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("inference.journal");
        let handle = DurableInferenceControlHandle::new(&path, 1).unwrap();
        handle.reserve_native(request("r1"), 1).unwrap();
        handle
            .dispatch_native(
                "r1",
                NativeDispatch {
                    thread_id: "thread-one".to_string(),
                    model_provider: "provider-one".to_string(),
                    context_digest: "2".repeat(64),
                },
            )
            .unwrap();
        handle
            .stop_native_before_turn_start("r1", "freshness rejected".to_string())
            .unwrap();
        handle.reserve_native(request("r2"), 1).unwrap();
        assert!(handle.native_record("r2").unwrap().is_some());
    }
}
