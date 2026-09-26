use std::fs;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use super::*;

const CHECKPOINT_PREFIX: &str = "checkpoint-v1|";
const CHECKPOINT_META_PREFIX: &str = "checkpoint-v1|meta|";
const CHECKPOINT_LEGACY_PREFIX: &str = "checkpoint-v1|legacy|";
const CHECKPOINT_NATIVE_PREFIX: &str = "checkpoint-v1|native|";
const CHECKPOINT_SCHEMA_VERSION: u32 = 1;
const ARCHIVED_FILTER_BYTES: usize = 1024 * 1024;
const ARCHIVED_FILTER_HASHES: u8 = 7;
const RETAIN_CHECKPOINTS: usize = 3;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct ArchivedRequestFilter {
    bits: Vec<u8>,
    insertions: u64,
}

impl Default for ArchivedRequestFilter {
    fn default() -> Self {
        Self {
            bits: vec![0; ARCHIVED_FILTER_BYTES],
            insertions: 0,
        }
    }
}

impl ArchivedRequestFilter {
    pub(super) fn might_contain(&self, request_id: &str) -> bool {
        self.positions(request_id)
            .all(|position| self.bits[position / 8] & (1 << (position % 8)) != 0)
    }

    fn insert(&mut self, request_id: &str) -> Result<(), Error> {
        validate_identity(request_id, "archived request")?;
        let positions: Vec<usize> = self.positions(request_id).collect();
        for position in positions {
            self.bits[position / 8] |= 1 << (position % 8);
        }
        self.insertions = self
            .insertions
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;
        Ok(())
    }

    fn positions<'a>(&'a self, request_id: &'a str) -> impl Iterator<Item = usize> + 'a {
        (0..ARCHIVED_FILTER_HASHES).map(move |salt| {
            let mut hasher = Sha256::new();
            hasher.update(b"hepta.inference.control.archived-request-filter.v1\0");
            hasher.update([salt]);
            hasher.update(request_id.as_bytes());
            let digest = hasher.finalize();
            let mut value = [0_u8; 8];
            value.copy_from_slice(&digest[..8]);
            (u64::from_be_bytes(value) % (self.bits.len() as u64 * 8)) as usize
        })
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct CheckpointMetaV1 {
    schema_version: u32,
    native_maximum_in_flight: Option<usize>,
    archived_filter_insertions: u64,
    archived_filter_hex: String,
}

#[derive(Default)]
pub(super) struct CheckpointReplay {
    seen_meta: bool,
    closed: bool,
    legacy_records: usize,
    native_records: usize,
}

impl CheckpointReplay {
    pub(super) fn apply(
        &mut self,
        line: &str,
        records: &mut BTreeMap<String, RequestRecord>,
        native: &mut native::NativeJournal,
        archived: &mut ArchivedRequestFilter,
    ) -> Result<(), Error> {
        if self.closed {
            return Err(Error::CorruptJournal("checkpoint after journal event"));
        }
        if let Some(json) = line.strip_prefix(CHECKPOINT_META_PREFIX) {
            if self.seen_meta || !records.is_empty() || !native.records.is_empty() {
                return Err(Error::CorruptJournal("duplicate checkpoint metadata"));
            }
            let meta: CheckpointMetaV1 = serde_json::from_str(json)
                .map_err(|_| Error::CorruptJournal("checkpoint metadata"))?;
            if meta.schema_version != CHECKPOINT_SCHEMA_VERSION
                || meta
                    .native_maximum_in_flight
                    .is_some_and(|value| !(1..=256).contains(&value))
            {
                return Err(Error::CorruptJournal("checkpoint metadata"));
            }
            let bits = decode_hex(&meta.archived_filter_hex)?;
            if bits.len() != ARCHIVED_FILTER_BYTES {
                return Err(Error::CorruptJournal("checkpoint archived filter"));
            }
            *archived = ArchivedRequestFilter {
                bits,
                insertions: meta.archived_filter_insertions,
            };
            native.maximum_in_flight = meta.native_maximum_in_flight;
            self.seen_meta = true;
            return Ok(());
        }
        if !self.seen_meta {
            return Err(Error::CorruptJournal("checkpoint record before metadata"));
        }
        if let Some(json) = line.strip_prefix(CHECKPOINT_LEGACY_PREFIX) {
            let record: RequestRecord = serde_json::from_str(json)
                .map_err(|_| Error::CorruptJournal("legacy checkpoint record"))?;
            validate_legacy_checkpoint_record(&record)?;
            let request_id = record.request.request_id.clone();
            if archived.might_contain(&request_id)
                || native.records.contains_key(&request_id)
                || records.insert(request_id, record).is_some()
            {
                return Err(Error::CorruptJournal("checkpoint identity conflict"));
            }
            self.legacy_records += 1;
            return Ok(());
        }
        if let Some(json) = line.strip_prefix(CHECKPOINT_NATIVE_PREFIX) {
            let record: native::NativeRunRecord = serde_json::from_str(json)
                .map_err(|_| Error::CorruptJournal("native checkpoint record"))?;
            native::validate_checkpoint_record(&record, native.maximum_in_flight)?;
            let request_id = record.request.request_id.clone();
            if archived.might_contain(&request_id)
                || records.contains_key(&request_id)
                || native.records.insert(request_id, record).is_some()
            {
                return Err(Error::CorruptJournal("checkpoint identity conflict"));
            }
            if let Some(limit) = native.maximum_in_flight
                && native
                    .records
                    .values()
                    .filter(|record| record.state != native::NativeReservationState::Released)
                    .count()
                    > limit
            {
                return Err(Error::CapacityExceeded);
            }
            self.native_records += 1;
            return Ok(());
        }
        Err(Error::CorruptJournal("checkpoint line"))
    }

    pub(super) fn close(&mut self) {
        self.closed = true;
    }

    pub(super) fn finish(&self) -> Result<(), Error> {
        if (self.legacy_records != 0 || self.native_records != 0) && !self.seen_meta {
            return Err(Error::CorruptJournal("checkpoint metadata missing"));
        }
        Ok(())
    }
}

pub(super) fn is_checkpoint_line(line: &str) -> bool {
    line.starts_with(CHECKPOINT_PREFIX)
}

pub(super) struct RecoveredActiveJournal {
    pub(super) file: File,
    pub(super) active_bytes: Vec<u8>,
    pub(super) generation: u64,
    pub(super) manifest_sha256: Option<JournalDigest32>,
}

pub(super) fn generation_store_for(path: &Path) -> Result<JournalGenerationStore, Error> {
    let parent = path
        .parent()
        .filter(|value| !value.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    let file_name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or(Error::InvalidIdentity("journal file name"))?;
    if file_name.is_empty() || file_name.as_bytes().contains(&0) {
        return Err(Error::InvalidIdentity("journal file name"));
    }
    let directory = parent.join(format!(".{file_name}.generations"));
    Ok(JournalGenerationStore::open(directory, "inference-control")?)
}

pub(super) fn recover_active_journal(
    path: &Path,
    file: File,
    store: &JournalGenerationStore,
) -> Result<RecoveredActiveJournal, Error> {
    let active_bytes = read_locked_file(&file)?;
    match store.recover() {
        Ok(recovered) => {
            let snapshot = recovered.snapshot;
            let active_is_current = active_bytes == snapshot
                || (active_bytes.len() > snapshot.len()
                    && active_bytes.starts_with(&snapshot)
                    && snapshot.last() == Some(&b'\n'));
            if active_is_current {
                return Ok(RecoveredActiveJournal {
                    file,
                    active_bytes,
                    generation: recovered.manifest.generation,
                    manifest_sha256: Some(recovered.manifest_sha256),
                });
            }
            let active_is_predecessor = active_bytes.len() as u64
                == recovered.manifest.archive_bytes
                && digest_bytes(&active_bytes) == recovered.manifest.archive_sha256;
            if !active_is_predecessor {
                return Err(Error::CorruptJournal("journal generation divergence"));
            }
            let mut failpoints = NoJournalFailpoints;
            let replacement = replace_locked_journal(path, file, &snapshot, &mut failpoints)?;
            Ok(RecoveredActiveJournal {
                file: replacement,
                active_bytes: snapshot,
                generation: recovered.manifest.generation,
                manifest_sha256: Some(recovered.manifest_sha256),
            })
        }
        Err(JournalGenerationError::NotFound) => Ok(RecoveredActiveJournal {
            file,
            active_bytes,
            generation: 0,
            manifest_sha256: None,
        }),
        Err(error) => Err(error.into()),
    }
}

pub(super) fn compact_owner(
    owner: &mut DurableInferenceControl,
    now_unix_ms: u64,
    prune_terminal: bool,
    failpoints: &mut dyn JournalFailpointController,
) -> Result<CompactionReceipt, Error> {
    if owner.poisoned {
        return Err(Error::WriterUnavailable);
    }
    if now_unix_ms == 0 {
        return Err(Error::InvalidTime);
    }
    let snapshot = build_snapshot(owner, prune_terminal)?;
    if snapshot.bytes.len() as u64 > MAX_JOURNAL_BYTES {
        return Err(Error::CapacityExceeded);
    }
    let predecessor = read_locked_file(&owner.file)?;
    let generation = owner
        .generation
        .checked_add(1)
        .ok_or(Error::ArithmeticOverflow)?;
    let committed = match owner.generation_store.commit_generation(
        generation,
        owner.generation_manifest_sha256,
        &snapshot.bytes,
        &predecessor,
        now_unix_ms,
        RETAIN_CHECKPOINTS,
        failpoints,
    ) {
        Ok(value) => value,
        Err(error) => {
            owner.poisoned = true;
            return Err(error.into());
        }
    };
    let previous_file = owner.file.try_clone()?;
    let replacement = match replace_locked_journal(
        &owner.path,
        previous_file,
        &snapshot.bytes,
        failpoints,
    ) {
        Ok(value) => value,
        Err(error) => {
            owner.poisoned = true;
            return Err(error);
        }
    };
    owner.file = replacement;
    owner.records = snapshot.records;
    owner.native = snapshot.native;
    owner.archived_request_filter = snapshot.archived;
    owner.journal_bytes = snapshot.bytes.len() as u64;
    owner.generation = committed.manifest.generation;
    owner.generation_manifest_sha256 = Some(committed.manifest_sha256);
    Ok(CompactionReceipt {
        generation: committed.manifest.generation,
        manifest_sha256: committed.manifest_sha256,
        predecessor_bytes: predecessor.len() as u64,
        snapshot_bytes: snapshot.bytes.len() as u64,
        pruned_legacy_records: snapshot.pruned_legacy_records,
        pruned_native_records: snapshot.pruned_native_records,
    })
}

pub(super) fn metrics(owner: &DurableInferenceControl) -> InferenceControlMetrics {
    use native::NativeReservationState;
    let count = |state| {
        owner
            .native
            .records
            .values()
            .filter(|record| record.state == state)
            .count()
    };
    InferenceControlMetrics {
        journal_bytes: owner.journal_bytes,
        journal_generation: owner.generation,
        capacity: owner.capacity,
        legacy_active_records: owner.records.len(),
        native_active_records: owner.native.records.len(),
        native_reserved: count(NativeReservationState::Reserved),
        native_dispatching: count(NativeReservationState::Dispatching),
        native_running: count(NativeReservationState::Running),
        native_cancelling: count(NativeReservationState::Cancelling),
        native_indeterminate: count(NativeReservationState::Indeterminate),
        native_released: count(NativeReservationState::Released),
        archived_request_insertions: owner.archived_request_filter.insertions,
        writer_poisoned: owner.poisoned,
    }
}

pub(super) fn unix_time_ms() -> Result<u64, Error> {
    let duration = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| Error::InvalidTime)?;
    u64::try_from(duration.as_millis()).map_err(|_| Error::ArithmeticOverflow)
}

struct SnapshotState {
    bytes: Vec<u8>,
    records: BTreeMap<String, RequestRecord>,
    native: native::NativeJournal,
    archived: ArchivedRequestFilter,
    pruned_legacy_records: usize,
    pruned_native_records: usize,
}

fn build_snapshot(
    owner: &DurableInferenceControl,
    prune_terminal: bool,
) -> Result<SnapshotState, Error> {
    let mut records = owner.records.clone();
    let mut native = owner.native.clone();
    let mut archived = owner.archived_request_filter.clone();
    let mut pruned_legacy_records = 0;
    let mut pruned_native_records = 0;
    if prune_terminal {
        let ids: Vec<String> = records
            .iter()
            .filter_map(|(id, record)| {
                matches!(
                    record.state,
                    RequestState::Completed | RequestState::Failed | RequestState::Cancelled
                )
                .then(|| id.clone())
            })
            .collect();
        for id in ids {
            archived.insert(&id)?;
            records.remove(&id);
            pruned_legacy_records += 1;
        }
        let ids: Vec<String> = native
            .records
            .iter()
            .filter_map(|(id, record)| {
                (record.state == native::NativeReservationState::Released).then(|| id.clone())
            })
            .collect();
        for id in ids {
            archived.insert(&id)?;
            native.records.remove(&id);
            pruned_native_records += 1;
        }
    }

    let meta = CheckpointMetaV1 {
        schema_version: CHECKPOINT_SCHEMA_VERSION,
        native_maximum_in_flight: native.maximum_in_flight,
        archived_filter_insertions: archived.insertions,
        archived_filter_hex: encode_hex(&archived.bits),
    };
    let mut bytes = Vec::new();
    push_json_line(&mut bytes, CHECKPOINT_META_PREFIX, &meta)?;
    for record in records.values() {
        validate_legacy_checkpoint_record(record)?;
        push_json_line(&mut bytes, CHECKPOINT_LEGACY_PREFIX, record)?;
    }
    for record in native.records.values() {
        native::validate_checkpoint_record(record, native.maximum_in_flight)?;
        push_json_line(&mut bytes, CHECKPOINT_NATIVE_PREFIX, record)?;
    }
    if bytes.len() as u64 > MAX_JOURNAL_BYTES {
        return Err(Error::CapacityExceeded);
    }
    Ok(SnapshotState {
        bytes,
        records,
        native,
        archived,
        pruned_legacy_records,
        pruned_native_records,
    })
}

fn push_json_line<T: Serialize>(
    bytes: &mut Vec<u8>,
    prefix: &str,
    value: &T,
) -> Result<(), Error> {
    let json = serde_json::to_vec(value).map_err(|_| Error::CorruptJournal("checkpoint encode"))?;
    let line_bytes = prefix
        .len()
        .checked_add(json.len())
        .and_then(|value| value.checked_add(1))
        .ok_or(Error::ArithmeticOverflow)?;
    if line_bytes > MAX_JOURNAL_LINE_BYTES {
        return Err(Error::CapacityExceeded);
    }
    bytes.extend_from_slice(prefix.as_bytes());
    bytes.extend_from_slice(&json);
    bytes.push(b'\n');
    Ok(())
}

fn validate_legacy_checkpoint_record(record: &RequestRecord) -> Result<(), Error> {
    validate_identity(&record.request.request_id, "request")?;
    validate_identity(&record.request.principal_id, "principal")?;
    validate_digest(&record.request.model_digest, "model")?;
    validate_digest(&record.request.payload_digest, "payload")?;
    validate_digest(&record.request.semantic_digest, "semantic")?;
    if record.request.maximum_tokens == 0
        || record.request.maximum_tokens > MAX_TOKENS
        || record.request.deadline_ms == 0
        || record.revision == 0
    {
        return Err(Error::CorruptJournal("legacy checkpoint request"));
    }
    if let Some(reservation) = &record.reservation {
        validate_identity(&reservation.reservation_id, "reservation")?;
        if reservation.quota_units == 0
            || reservation.maximum_tokens == 0
            || reservation.maximum_tokens > MAX_TOKENS
            || reservation.authority_epoch == 0
            || reservation.valid_until_ms == 0
            || reservation.maximum_tokens < record.request.maximum_tokens
        {
            return Err(Error::CorruptJournal("legacy checkpoint reservation"));
        }
    }
    if let Some(assignment) = &record.assignment {
        validate_assignment(assignment)?;
    }
    if let Some(digest) = &record.terminal_observation_digest {
        validate_digest(digest, "terminal observation")?;
    }
    let valid_shape = match record.state {
        RequestState::Pending => {
            record.revision == 1
                && record.reservation.is_none()
                && record.assignment.is_none()
                && record.terminal_observation_digest.is_none()
                && record.consumed_tokens == 0
                && record.usage_units == 0
        }
        RequestState::Reserved => {
            record.revision == 2
                && record.reservation.is_some()
                && record.assignment.is_none()
                && record.terminal_observation_digest.is_none()
                && record.consumed_tokens == 0
                && record.usage_units == 0
        }
        RequestState::Assigned => {
            record.revision == 3
                && record.reservation.is_some()
                && record.assignment.is_some()
                && record.terminal_observation_digest.is_none()
                && record.consumed_tokens == 0
                && record.usage_units == 0
        }
        RequestState::Cancelling => {
            record.revision == 4
                && record.reservation.is_some()
                && record.assignment.is_some()
                && record.terminal_observation_digest.is_none()
        }
        RequestState::Completed | RequestState::Failed | RequestState::Indeterminate => {
            matches!(record.revision, 4 | 5)
                && record.reservation.is_some()
                && record.assignment.is_some()
                && record.terminal_observation_digest.is_some()
        }
        RequestState::Cancelled => {
            (record.terminal_observation_digest.is_none()
                && record.assignment.is_none()
                && matches!(record.revision, 2 | 3))
                || (record.terminal_observation_digest.is_some()
                    && record.reservation.is_some()
                    && record.assignment.is_some()
                    && matches!(record.revision, 4 | 5))
        }
    };
    if !valid_shape {
        return Err(Error::CorruptJournal("legacy checkpoint state"));
    }
    if record.consumed_tokens > record.request.maximum_tokens {
        return Err(Error::UsageExceeded);
    }
    Ok(())
}

fn replace_locked_journal(
    path: &Path,
    _current_file: File,
    snapshot: &[u8],
    failpoints: &mut dyn JournalFailpointController,
) -> Result<File, Error> {
    failpoints.hit(crate::journal_generation::JournalFailpoint::BeforeActiveWrite)?;
    let parent = path
        .parent()
        .filter(|value| !value.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    let file_name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or(Error::InvalidIdentity("journal file name"))?;
    let temp_path = parent.join(format!(
        ".{file_name}.compact.{}.tmp",
        std::process::id()
    ));
    let _ = fs::remove_file(&temp_path);
    let mut options = OpenOptions::new();
    options.create_new(true).append(true).read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut replacement = options.open(&temp_path)?;
    let mut renamed = false;
    let result = (|| {
        replacement.write_all(snapshot)?;
        replacement.flush()?;
        replacement.sync_all()?;
        failpoints.hit(crate::journal_generation::JournalFailpoint::AfterActiveFsync)?;
        replacement
            .try_lock()
            .map_err(|_| Error::WriterUnavailable)?;
        failpoints.hit(crate::journal_generation::JournalFailpoint::BeforeActiveRename)?;
        fs::rename(&temp_path, path)?;
        renamed = true;
        failpoints.hit(crate::journal_generation::JournalFailpoint::AfterActiveRename)?;
        File::open(parent)?.sync_all()?;
        failpoints.hit(crate::journal_generation::JournalFailpoint::AfterActiveDirectoryFsync)?;
        Ok(())
    })();
    if let Err(error) = result {
        if !renamed {
            let _ = fs::remove_file(&temp_path);
        }
        return Err(error);
    }
    Ok(replacement)
}

fn read_locked_file(file: &File) -> Result<Vec<u8>, Error> {
    let mut reader = file.try_clone()?;
    reader.seek(SeekFrom::Start(0))?;
    let mut bytes = Vec::new();
    reader
        .take(MAX_JOURNAL_BYTES.saturating_add(1))
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_JOURNAL_BYTES {
        return Err(Error::CapacityExceeded);
    }
    Ok(bytes)
}

fn digest_bytes(bytes: &[u8]) -> JournalDigest32 {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    hasher.finalize().into()
}

fn encode_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push(HEX[(byte >> 4) as usize] as char);
        output.push(HEX[(byte & 0x0f) as usize] as char);
    }
    output
}

fn decode_hex(value: &str) -> Result<Vec<u8>, Error> {
    if value.len() % 2 != 0 || value.len() > ARCHIVED_FILTER_BYTES * 2 {
        return Err(Error::CorruptJournal("checkpoint archived filter"));
    }
    let mut bytes = Vec::with_capacity(value.len() / 2);
    for pair in value.as_bytes().chunks_exact(2) {
        let high = hex_nibble(pair[0])?;
        let low = hex_nibble(pair[1])?;
        bytes.push((high << 4) | low);
    }
    Ok(bytes)
}

fn hex_nibble(value: u8) -> Result<u8, Error> {
    match value {
        b'0'..=b'9' => Ok(value - b'0'),
        b'a'..=b'f' => Ok(value - b'a' + 10),
        _ => Err(Error::CorruptJournal("checkpoint archived filter")),
    }
}
