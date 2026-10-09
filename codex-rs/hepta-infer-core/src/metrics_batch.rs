//! Bounded, batched telemetry journal. Metrics are observations only, never
//! acceptance receipts, authority or evidence of a host operation's success.

use std::error::Error as StdError;
use std::fmt;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::Path;

use codex_hepta_types::Digest32;

const MAGIC: &[u8; 4] = b"HMB1";
const ENTRY_BYTES: usize = 32 + 1 + 8 + 8;
const HEADER_BYTES: usize = 4 + 8 + 2 + 4 + 32;
const CHECKSUM_BYTES: usize = 32;
const MAX_BATCH_SAMPLES: usize = 4_096;
const MAX_JOURNAL_BYTES: u64 = 256 * 1024 * 1024;

#[repr(u8)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MetricKindV1 {
    QueueAgeMicros = 1,
    IntentLatencyMicros = 2,
    ModelLatencyMicros = 3,
    JournalFsyncMicros = 4,
    WitnessFsyncMicros = 5,
    CasLatencyMicros = 6,
    SignatureLatencyMicros = 7,
    CnsLatencyMicros = 8,
    ReplayMicros = 9,
    LockWaitMicros = 10,
    WriteBytes = 11,
    CommunicationBytes = 12,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct MetricObservationV1 {
    pub lane_digest: Digest32,
    pub kind: MetricKindV1,
    pub monotonic_micros: u64,
    pub value: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MetricsErrorV1 {
    InvalidCapacity,
    MissingLane,
    BufferFull,
    WriterUnavailable,
    Poisoned,
    CorruptFrame,
    JournalFull,
    Io,
}

impl fmt::Display for MetricsErrorV1 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl StdError for MetricsErrorV1 {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct MetricsFlushReceiptV1 {
    pub sequence: u64,
    pub sample_count: usize,
    pub frame_bytes: usize,
    pub frame_digest: Digest32,
}

/// Writer-lock-protected metric batch. record() is not durable; flush() writes
/// an entire checksummed batch and syncs exactly once. On an unknown write or
/// fsync outcome the writer poisons itself, so callers must reopen/reconcile.
#[derive(Debug)]
pub struct BatchedMetricJournalV1 {
    file: File,
    sequence: u64,
    previous: Digest32,
    pending: Vec<MetricObservationV1>,
    maximum_pending: usize,
    journal_bytes: u64,
    poisoned: bool,
}

impl BatchedMetricJournalV1 {
    pub fn open(path: impl AsRef<Path>, maximum_pending: usize) -> Result<Self, MetricsErrorV1> {
        if maximum_pending == 0 || maximum_pending > MAX_BATCH_SAMPLES {
            return Err(MetricsErrorV1::InvalidCapacity);
        }
        let path = path.as_ref();
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(|_| MetricsErrorV1::Io)?;
        }
        let mut options = OpenOptions::new();
        options.read(true).write(true).create(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut file = options.open(path).map_err(|_| MetricsErrorV1::Io)?;
        file.try_lock().map_err(|_| MetricsErrorV1::WriterUnavailable)?;
        let (sequence, previous, journal_bytes) = replay(&mut file)?;
        file.seek(SeekFrom::End(0)).map_err(|_| MetricsErrorV1::Io)?;
        if let Some(parent) = path.parent() {
            File::open(parent)
                .and_then(|dir| dir.sync_all())
                .map_err(|_| MetricsErrorV1::Io)?;
        }
        Ok(Self {
            file,
            sequence,
            previous,
            pending: Vec::new(),
            maximum_pending,
            journal_bytes,
            poisoned: false,
        })
    }

    pub fn record(&mut self, sample: MetricObservationV1) -> Result<(), MetricsErrorV1> {
        if self.poisoned {
            return Err(MetricsErrorV1::Poisoned);
        }
        if sample.lane_digest.is_zero() {
            return Err(MetricsErrorV1::MissingLane);
        }
        if self.pending.len() >= self.maximum_pending {
            return Err(MetricsErrorV1::BufferFull);
        }
        self.pending.push(sample);
        Ok(())
    }

    pub fn pending_count(&self) -> usize {
        self.pending.len()
    }

    pub fn flush(&mut self) -> Result<Option<MetricsFlushReceiptV1>, MetricsErrorV1> {
        if self.poisoned {
            return Err(MetricsErrorV1::Poisoned);
        }
        if self.pending.is_empty() {
            return Ok(None);
        }
        let sequence = self.sequence.checked_add(1).ok_or(MetricsErrorV1::JournalFull)?;
        let mut frame = Vec::with_capacity(
            HEADER_BYTES + self.pending.len() * ENTRY_BYTES + CHECKSUM_BYTES,
        );
        frame.extend_from_slice(MAGIC);
        frame.extend_from_slice(&sequence.to_be_bytes());
        frame.extend_from_slice(&(self.pending.len() as u16).to_be_bytes());
        frame.extend_from_slice(&((self.pending.len() * ENTRY_BYTES) as u32).to_be_bytes());
        frame.extend_from_slice(self.previous.as_array());
        for sample in &self.pending {
            frame.extend_from_slice(sample.lane_digest.as_array());
            frame.push(sample.kind as u8);
            frame.extend_from_slice(&sample.monotonic_micros.to_be_bytes());
            frame.extend_from_slice(&sample.value.to_be_bytes());
        }
        let frame_digest = Digest32::of_bytes(&frame);
        frame.extend_from_slice(frame_digest.as_array());
        let new_bytes = self
            .journal_bytes
            .checked_add(frame.len() as u64)
            .ok_or(MetricsErrorV1::JournalFull)?;
        if new_bytes > MAX_JOURNAL_BYTES {
            return Err(MetricsErrorV1::JournalFull);
        }
        let persisted = self.file.write_all(&frame).and_then(|()| self.file.sync_data());
        if persisted.is_err() {
            self.poisoned = true;
            return Err(MetricsErrorV1::Io);
        }
        let receipt = MetricsFlushReceiptV1 {
            sequence,
            sample_count: self.pending.len(),
            frame_bytes: frame.len(),
            frame_digest,
        };
        self.sequence = sequence;
        self.previous = frame_digest;
        self.journal_bytes = new_bytes;
        self.pending.clear();
        Ok(Some(receipt))
    }

    /// Times a synchronous CAS/signature/CNS/etc operation at the actual call
    /// boundary. The operation result and telemetry result are returned
    /// separately so a missing metric can never fabricate operation success.
    pub fn measure<T, E>(
        &mut self,
        lane_digest: Digest32,
        kind: MetricKindV1,
        monotonic_micros: u64,
        operation: impl FnOnce() -> Result<T, E>,
    ) -> (Result<T, E>, Result<(), MetricsErrorV1>) {
        let started = std::time::Instant::now();
        let result = operation();
        let value = started.elapsed().as_micros().min(u128::from(u64::MAX)) as u64;
        let metric = self.record(MetricObservationV1 {
            lane_digest,
            kind,
            monotonic_micros,
            value,
        });
        (result, metric)
    }
}

fn replay(file: &mut File) -> Result<(u64, Digest32, u64), MetricsErrorV1> {
    file.seek(SeekFrom::Start(0)).map_err(|_| MetricsErrorV1::Io)?;
    let length = file.metadata().map_err(|_| MetricsErrorV1::Io)?.len();
    if length > MAX_JOURNAL_BYTES {
        return Err(MetricsErrorV1::JournalFull);
    }
    let mut offset = 0_u64;
    let mut sequence = 0_u64;
    let mut previous = Digest32::ZERO;
    while offset < length {
        if length - offset < HEADER_BYTES as u64 + CHECKSUM_BYTES as u64 {
            return Err(MetricsErrorV1::CorruptFrame);
        }
        let mut header = [0_u8; HEADER_BYTES];
        file.read_exact(&mut header).map_err(|_| MetricsErrorV1::CorruptFrame)?;
        if &header[..4] != MAGIC {
            return Err(MetricsErrorV1::CorruptFrame);
        }
        let actual_seq = u64::from_be_bytes(header[4..12].try_into().map_err(|_| MetricsErrorV1::CorruptFrame)?);
        let count = u16::from_be_bytes(header[12..14].try_into().map_err(|_| MetricsErrorV1::CorruptFrame)?) as usize;
        let body_len = u32::from_be_bytes(header[14..18].try_into().map_err(|_| MetricsErrorV1::CorruptFrame)?) as usize;
        if count == 0
            || count > MAX_BATCH_SAMPLES
            || body_len != count * ENTRY_BYTES
            || &header[18..50] != previous.as_array()
            || actual_seq != sequence.checked_add(1).ok_or(MetricsErrorV1::CorruptFrame)?
            || length - offset < (HEADER_BYTES + body_len + CHECKSUM_BYTES) as u64
        {
            return Err(MetricsErrorV1::CorruptFrame);
        }
        let mut frame = Vec::with_capacity(HEADER_BYTES + body_len);
        frame.extend_from_slice(&header);
        let mut body = vec![0_u8; body_len];
        file.read_exact(&mut body).map_err(|_| MetricsErrorV1::CorruptFrame)?;
        frame.extend_from_slice(&body);
        let mut checksum = [0_u8; CHECKSUM_BYTES];
        file.read_exact(&mut checksum).map_err(|_| MetricsErrorV1::CorruptFrame)?;
        let digest = Digest32::of_bytes(&frame);
        if checksum != *digest.as_array() {
            return Err(MetricsErrorV1::CorruptFrame);
        }
        for item in body.chunks_exact(ENTRY_BYTES) {
            if item[..32].iter().all(|byte| *byte == 0) || !(1..=12).contains(&item[32]) {
                return Err(MetricsErrorV1::CorruptFrame);
            }
        }
        previous = digest;
        sequence = actual_seq;
        offset += (HEADER_BYTES + body_len + CHECKSUM_BYTES) as u64;
    }
    Ok((sequence, previous, length))
}

#[cfg(test)]
#[path = "metrics_batch_tests.rs"]
mod tests;
