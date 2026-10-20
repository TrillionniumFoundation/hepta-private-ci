//! Bounded, generation-fenced metrics WAL for the neuron worker.
//!
//! The host owns the file, and every append is fsynced before its receipt is
//! returned. A group shares one sync. Torn final frames are removed on reopen;
//! complete corrupt frames fail closed. Metrics never grant effect authority.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const MAGIC: &[u8; 8] = b"HNMETW01";
const HEADER_BYTES: u64 = 8 + 32 + 8;
const MAX_EVENTS: usize = 65_536;
const MAX_BODY_BYTES: usize = 512;
const MAX_ID_BYTES: usize = 128;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronMetricEventV1 {
    pub event_id: StableId,
    pub generation: Generation,
    pub plan_digest: Digest32,
    pub execution_digest: Digest32,
    pub request_count: u32,
    pub elapsed_micros: u64,
    pub cpu_micros: u64,
    pub rss_bytes: u64,
    pub p95_micros: u64,
    pub p99_micros: u64,
    pub lock_wait_micros: u64,
    pub recovered: bool,
}

impl NeuronMetricEventV1 {
    fn validate(&self, generation: Generation) -> Result<(), MetricsError> {
        if self.generation != generation {
            return Err(MetricsError::StaleGeneration);
        }
        if self.event_id.as_str().is_empty() || self.event_id.as_str().len() > MAX_ID_BYTES {
            return Err(MetricsError::InvalidEvent("event id"));
        }
        if self.plan_digest.is_zero() || self.execution_digest.is_zero() {
            return Err(MetricsError::InvalidEvent("event digest"));
        }
        if self.request_count == 0 || self.request_count > 256 {
            return Err(MetricsError::InvalidEvent("request count"));
        }
        if self.p95_micros > self.p99_micros {
            return Err(MetricsError::InvalidEvent("latency quantiles"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MetricsCommitReceiptV1 {
    pub event_id: StableId,
    pub sequence: u64,
    pub scope_digest: Digest32,
    pub generation: Generation,
    pub event_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MetricsError {
    InvalidScope,
    InvalidEvent(&'static str),
    StaleGeneration,
    DuplicateConflict,
    Capacity,
    CorruptHeader,
    CorruptFrame,
    Busy,
    NotRegular,
    Poisoned,
    Io(std::io::ErrorKind),
}

impl fmt::Display for MetricsError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl StdError for MetricsError {}
impl From<std::io::Error> for MetricsError {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value.kind())
    }
}

struct LockedMetricFile(File);
impl LockedMetricFile {
    fn acquire(file: File) -> Result<Self, MetricsError> {
        if !file.metadata()?.is_file() {
            return Err(MetricsError::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(MetricsError::Busy),
            Err(TryLockError::Error(error)) => Err(error.into()),
        }
    }
}
impl Drop for LockedMetricFile {
    fn drop(&mut self) {
        let _ = self.0.unlock();
    }
}

fn open_host_owned_metrics_file(path: &Path) -> Result<File, MetricsError> {
    // File enrollment is still the host's responsibility. A metrics writer
    // must nevertheless never follow an untrusted final-component symlink
    // or append to an aliased inode.
    let previous = match path.symlink_metadata() {
        Ok(metadata) => {
            if !metadata.file_type().is_file() {
                return Err(MetricsError::NotRegular);
            }
            #[cfg(unix)]
            {
                use std::os::unix::fs::MetadataExt;
                if metadata.nlink() != 1 {
                    return Err(MetricsError::NotRegular);
                }
            }
            Some(metadata)
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
        Err(error) => return Err(error.into()),
    };

    // Exclusive create never follows a pre-existing symlink, even when its
    // destination does not exist. Existing files are only opened without
    // O_CREAT, and nothing is written before identity checks complete.
    let mut create = OpenOptions::new();
    create.read(true).write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        create.mode(0o600);
    }
    let file = match create.open(path) {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            OpenOptions::new().read(true).write(true).open(path)?
        }
        Err(error) => return Err(error.into()),
    };
    let opened = file.metadata()?;
    let current = path.symlink_metadata()?;
    if !opened.is_file() || !current.file_type().is_file() {
        return Err(MetricsError::NotRegular);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        // Before/after inode binding fences path replacement between the
        // enrollment check and open. The owner must still trust its parent
        // directory and prevent hostile mutation after enrollment.
        if opened.nlink() != 1
            || current.nlink() != 1
            || opened.dev() != current.dev()
            || opened.ino() != current.ino()
            || previous
                .as_ref()
                .is_some_and(|before| before.dev() != opened.dev() || before.ino() != opened.ino())
        {
            return Err(MetricsError::NotRegular);
        }
    }
    #[cfg(not(unix))]
    let _ = previous;
    Ok(file)
}

/// A single scope/generation owner. Each append_group call performs at most
/// one sync for its new records and returns non-authorizing receipts.
pub struct NeuronMetricsGroupCommitWriterV1 {
    file: LockedMetricFile,
    scope_digest: Digest32,
    generation: Generation,
    entries: BTreeMap<StableId, (Digest32, u64)>,
    poisoned: bool,
}

impl NeuronMetricsGroupCommitWriterV1 {
    pub fn open(
        path: impl AsRef<Path>,
        scope_digest: Digest32,
        generation: Generation,
    ) -> Result<Self, MetricsError> {
        if scope_digest.is_zero() {
            return Err(MetricsError::InvalidScope);
        }
        let path = path.as_ref();
        let file = open_host_owned_metrics_file(path)?;
        let mut locked = LockedMetricFile::acquire(file)?;
        let header = header(scope_digest, generation);
        let file_len = locked.0.metadata()?.len();
        if file_len == 0 {
            locked.0.write_all(&header)?;
            locked.0.sync_all()?;
            #[cfg(unix)]
            if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
                File::open(parent)?.sync_all()?;
            }
        } else {
            if file_len < HEADER_BYTES {
                return Err(MetricsError::CorruptHeader);
            }
            let mut actual = [0_u8; HEADER_BYTES as usize];
            locked.0.seek(SeekFrom::Start(0))?;
            locked.0.read_exact(&mut actual)?;
            if actual != header {
                return Err(MetricsError::CorruptHeader);
            }
        }

        let mut entries = BTreeMap::new();
        let length = locked.0.metadata()?.len();
        let mut offset = HEADER_BYTES;
        while offset < length {
            let remaining = length - offset;
            if remaining < 4 {
                truncate_tail(&mut locked.0, offset)?;
                break;
            }
            let mut len_bytes = [0; 4];
            locked.0.seek(SeekFrom::Start(offset))?;
            locked.0.read_exact(&mut len_bytes)?;
            let body_len = u32::from_be_bytes(len_bytes) as usize;
            if !(1..=MAX_BODY_BYTES).contains(&body_len) {
                return Err(MetricsError::CorruptFrame);
            }
            let frame_len = 4 + body_len as u64 + 32;
            if remaining < frame_len {
                truncate_tail(&mut locked.0, offset)?;
                break;
            }
            let mut body = vec![0_u8; body_len];
            let mut checksum = [0_u8; 32];
            locked.0.read_exact(&mut body)?;
            locked.0.read_exact(&mut checksum)?;
            if Digest32::of_bytes(&body) != Digest32::from_array(checksum) {
                return Err(MetricsError::CorruptFrame);
            }
            let event = decode_event(&body)?;
            event
                .validate(generation)
                .map_err(|_| MetricsError::CorruptFrame)?;
            let event_digest = Digest32::of_bytes(&body);
            let sequence = u64::try_from(entries.len() + 1).map_err(|_| MetricsError::Capacity)?;
            if entries
                .insert(event.event_id, (event_digest, sequence))
                .is_some()
                || entries.len() > MAX_EVENTS
            {
                return Err(MetricsError::CorruptFrame);
            }
            offset += frame_len;
        }
        locked.0.seek(SeekFrom::End(0))?;
        Ok(Self {
            file: locked,
            scope_digest,
            generation,
            entries,
            poisoned: false,
        })
    }

    #[must_use]
    pub fn event_count(&self) -> usize {
        self.entries.len()
    }

    pub fn append(
        &mut self,
        event: NeuronMetricEventV1,
    ) -> Result<MetricsCommitReceiptV1, MetricsError> {
        self.append_group(vec![event])?
            .pop()
            .ok_or(MetricsError::InvalidEvent("empty group"))
    }

    /// Only new records are written. An exact duplicate receives its original
    /// receipt; the same event ID with changed metrics is rejected.
    pub fn append_group(
        &mut self,
        events: Vec<NeuronMetricEventV1>,
    ) -> Result<Vec<MetricsCommitReceiptV1>, MetricsError> {
        if self.poisoned {
            return Err(MetricsError::Poisoned);
        }
        if events.is_empty() || events.len() > MAX_EVENTS {
            return Err(MetricsError::Capacity);
        }
        let mut pending = BTreeMap::<StableId, (Digest32, u64)>::new();
        let mut frames = Vec::new();
        let mut receipts = Vec::with_capacity(events.len());
        for event in events {
            event.validate(self.generation)?;
            let body = encode_event(&event);
            if body.len() > MAX_BODY_BYTES {
                return Err(MetricsError::InvalidEvent("frame too large"));
            }
            let event_digest = Digest32::of_bytes(&body);
            let old = pending
                .get(&event.event_id)
                .or_else(|| self.entries.get(&event.event_id));
            let sequence = if let Some((recorded_digest, sequence)) = old {
                if *recorded_digest != event_digest {
                    return Err(MetricsError::DuplicateConflict);
                }
                *sequence
            } else {
                if self.entries.len() + pending.len() >= MAX_EVENTS {
                    return Err(MetricsError::Capacity);
                }
                let sequence = u64::try_from(self.entries.len() + pending.len() + 1)
                    .map_err(|_| MetricsError::Capacity)?;
                frames.extend_from_slice(&(body.len() as u32).to_be_bytes());
                frames.extend_from_slice(&body);
                frames.extend_from_slice(event_digest.as_array());
                pending.insert(event.event_id.clone(), (event_digest, sequence));
                sequence
            };
            receipts.push(MetricsCommitReceiptV1 {
                event_id: event.event_id,
                sequence,
                scope_digest: self.scope_digest,
                generation: self.generation,
                event_digest,
                authority: AuthorityPosture::DENY_ALL,
            });
        }
        if !frames.is_empty() {
            self.poisoned = true;
            self.file.0.seek(SeekFrom::End(0))?;
            self.file.0.write_all(&frames)?;
            self.file.0.sync_all()?;
            self.entries.extend(pending);
            self.poisoned = false;
        }
        Ok(receipts)
    }
}

fn header(scope_digest: Digest32, generation: Generation) -> [u8; HEADER_BYTES as usize] {
    let mut bytes = [0_u8; HEADER_BYTES as usize];
    bytes[..8].copy_from_slice(MAGIC);
    bytes[8..40].copy_from_slice(scope_digest.as_array());
    bytes[40..48].copy_from_slice(&generation.get().to_be_bytes());
    bytes
}

fn truncate_tail(file: &mut File, length: u64) -> Result<(), MetricsError> {
    file.set_len(length)?;
    file.sync_all()?;
    Ok(())
}

fn encode_event(event: &NeuronMetricEventV1) -> Vec<u8> {
    let name = event.event_id.as_str().as_bytes();
    let mut bytes = Vec::with_capacity(2 + name.len() + 8 + 64 + 4 + 48 + 1);
    bytes.extend_from_slice(&(name.len() as u16).to_be_bytes());
    bytes.extend_from_slice(name);
    bytes.extend_from_slice(&event.generation.get().to_be_bytes());
    bytes.extend_from_slice(event.plan_digest.as_array());
    bytes.extend_from_slice(event.execution_digest.as_array());
    bytes.extend_from_slice(&event.request_count.to_be_bytes());
    for value in [
        event.elapsed_micros,
        event.cpu_micros,
        event.rss_bytes,
        event.p95_micros,
        event.p99_micros,
        event.lock_wait_micros,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    bytes.push(u8::from(event.recovered));
    bytes
}

fn decode_event(bytes: &[u8]) -> Result<NeuronMetricEventV1, MetricsError> {
    let mut position = 0;
    let id_len = read_u16(bytes, &mut position)? as usize;
    if id_len == 0 || id_len > MAX_ID_BYTES {
        return Err(MetricsError::CorruptFrame);
    }
    let id_bytes = read_slice(bytes, &mut position, id_len)?;
    let event_id = std::str::from_utf8(id_bytes)
        .ok()
        .and_then(|name| StableId::new(name).ok())
        .ok_or(MetricsError::CorruptFrame)?;
    let generation =
        Generation::new(read_u64(bytes, &mut position)?).map_err(|_| MetricsError::CorruptFrame)?;
    let plan_digest = read_digest(bytes, &mut position)?;
    let execution_digest = read_digest(bytes, &mut position)?;
    let request_count = read_u32(bytes, &mut position)?;
    let elapsed_micros = read_u64(bytes, &mut position)?;
    let cpu_micros = read_u64(bytes, &mut position)?;
    let rss_bytes = read_u64(bytes, &mut position)?;
    let p95_micros = read_u64(bytes, &mut position)?;
    let p99_micros = read_u64(bytes, &mut position)?;
    let lock_wait_micros = read_u64(bytes, &mut position)?;
    let recovered = match read_slice(bytes, &mut position, 1)?[0] {
        0 => false,
        1 => true,
        _ => return Err(MetricsError::CorruptFrame),
    };
    if position != bytes.len() {
        return Err(MetricsError::CorruptFrame);
    }
    Ok(NeuronMetricEventV1 {
        event_id,
        generation,
        plan_digest,
        execution_digest,
        request_count,
        elapsed_micros,
        cpu_micros,
        rss_bytes,
        p95_micros,
        p99_micros,
        lock_wait_micros,
        recovered,
    })
}

fn read_slice<'a>(
    data: &'a [u8],
    position: &mut usize,
    count: usize,
) -> Result<&'a [u8], MetricsError> {
    let end = position
        .checked_add(count)
        .ok_or(MetricsError::CorruptFrame)?;
    let result = data.get(*position..end).ok_or(MetricsError::CorruptFrame)?;
    *position = end;
    Ok(result)
}

fn read_u16(data: &[u8], pos: &mut usize) -> Result<u16, MetricsError> {
    let bytes: [u8; 2] = read_slice(data, pos, 2)?
        .try_into()
        .map_err(|_| MetricsError::CorruptFrame)?;
    Ok(u16::from_be_bytes(bytes))
}
fn read_u32(data: &[u8], pos: &mut usize) -> Result<u32, MetricsError> {
    let bytes: [u8; 4] = read_slice(data, pos, 4)?
        .try_into()
        .map_err(|_| MetricsError::CorruptFrame)?;
    Ok(u32::from_be_bytes(bytes))
}
fn read_u64(data: &[u8], pos: &mut usize) -> Result<u64, MetricsError> {
    let bytes: [u8; 8] = read_slice(data, pos, 8)?
        .try_into()
        .map_err(|_| MetricsError::CorruptFrame)?;
    Ok(u64::from_be_bytes(bytes))
}
fn read_digest(data: &[u8], pos: &mut usize) -> Result<Digest32, MetricsError> {
    let bytes: [u8; 32] = read_slice(data, pos, 32)?
        .try_into()
        .map_err(|_| MetricsError::CorruptFrame)?;
    Ok(Digest32::from_array(bytes))
}

#[cfg(test)]
#[path = "metrics_tests.rs"]
mod tests;
