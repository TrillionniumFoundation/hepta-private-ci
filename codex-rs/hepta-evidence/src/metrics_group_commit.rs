//! Bounded append-only metrics group commit with one fsync per group.
//!
//! This journal is telemetry, not a signed evidence ledger. Its hash chain
//! detects torn/corrupt local lines; it cannot certify an operation or mint
//! authority. The caller must not retry an external effect after a telemetry
//! failure without independently reconciling that effect.

use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, Read, Write};
use std::path::Path;
use std::time::Instant;

use codex_hepta_types::Digest32;

const MAX_GROUP_ROWS: usize = 256;
const MAX_LINE_BYTES: usize = 65_536;
const MAX_JOURNAL_BYTES: u64 = 64 * 1024 * 1024;
const DOMAIN: &[u8] = b"hepta.metrics.group.v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MetricPhaseV1 {
    Admission = 1,
    Microbatch = 2,
    Cas = 3,
    Signature = 4,
    Cns = 5,
    NeuronFeature = 6,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MetricSampleV1 {
    pub scope_digest: Digest32,
    pub operation_digest: Digest32,
    pub phase: MetricPhaseV1,
    pub latency_micros: u64,
    pub succeeded: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MetricsCommitReceiptV1 {
    pub sequence: u64,
    pub head_digest: Digest32,
    pub rows: usize,
    pub sync_latency_micros: u64,
}

#[derive(Debug)]
pub enum MetricsJournalErrorV1 {
    Io(std::io::Error),
    Capacity,
    EmptyDigest,
    Corrupt,
    WriterUnavailable,
    Poisoned,
}
impl From<std::io::Error> for MetricsJournalErrorV1 {
    fn from(error: std::io::Error) -> Self { Self::Io(error) }
}
impl std::fmt::Display for MetricsJournalErrorV1 {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result { write!(f, "{self:?}") }
}
impl std::error::Error for MetricsJournalErrorV1 {}

/// The single writer keeps a bounded group in memory. A torn append poisons
/// the instance until inspection/reopen, never silently skipping a record.
pub struct MetricsGroupCommitV1 {
    file: File,
    staged: Vec<MetricSampleV1>,
    sequence: u64,
    head: Digest32,
    bytes: u64,
    poisoned: bool,
}

impl MetricsGroupCommitV1 {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, MetricsJournalErrorV1> {
        let path = path.as_ref();
        if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
            fs::create_dir_all(parent)?;
        }
        let mut options = OpenOptions::new();
        options.create(true).append(true).read(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let file = options.open(path)?;
        file.try_lock().map_err(|_| MetricsJournalErrorV1::WriterUnavailable)?;
        let mut reader = BufReader::new(file.try_clone()?);
        let mut line = Vec::new();
        let mut total = 0_u64;
        let mut sequence = 0_u64;
        let mut head = Digest32::ZERO;
        loop {
            line.clear();
            let remaining = MAX_JOURNAL_BYTES.saturating_sub(total).saturating_add(1);
            let read = (&mut reader).take(remaining.min(MAX_LINE_BYTES as u64 + 1))
                .read_until(b'\n', &mut line)?;
            if read == 0 { break; }
            total = total.checked_add(read as u64).ok_or(MetricsJournalErrorV1::Capacity)?;
            if read > MAX_LINE_BYTES || total > MAX_JOURNAL_BYTES || line.pop() != Some(b'\n') {
                return Err(MetricsJournalErrorV1::Corrupt);
            }
            let contents = std::str::from_utf8(&line).map_err(|_| MetricsJournalErrorV1::Corrupt)?;
            let (next_sequence, next_head) = parse_group(contents, sequence, head)?;
            sequence = next_sequence;
            head = next_head;
        }
        Ok(Self { file, staged: Vec::new(), sequence, head, bytes: total, poisoned: false })
    }

    pub fn stage(&mut self, sample: MetricSampleV1) -> Result<(), MetricsJournalErrorV1> {
        if self.poisoned { return Err(MetricsJournalErrorV1::Poisoned); }
        if sample.scope_digest.is_zero() || sample.operation_digest.is_zero() {
            return Err(MetricsJournalErrorV1::EmptyDigest);
        }
        if self.staged.len() >= MAX_GROUP_ROWS { return Err(MetricsJournalErrorV1::Capacity); }
        self.staged.push(sample);
        Ok(())
    }

    pub fn pending(&self) -> usize { self.staged.len() }

    pub fn flush(&mut self) -> Result<Option<MetricsCommitReceiptV1>, MetricsJournalErrorV1> {
        if self.poisoned { return Err(MetricsJournalErrorV1::Poisoned); }
        if self.staged.is_empty() { return Ok(None); }
        let sequence = self.sequence.checked_add(1).ok_or(MetricsJournalErrorV1::Capacity)?;
        let payload = self.staged.iter().map(encode_sample).collect::<Vec<_>>().join(";");
        let next_head = digest_group(sequence, self.head, &payload);
        let encoded = format!(
            "M1|{}|{}|{}|{}|{}\n",
            sequence, self.head, next_head, self.staged.len(), payload
        );
        let next_bytes = self.bytes.checked_add(encoded.len() as u64)
            .ok_or(MetricsJournalErrorV1::Capacity)?;
        if encoded.len() > MAX_LINE_BYTES || next_bytes > MAX_JOURNAL_BYTES {
            return Err(MetricsJournalErrorV1::Capacity);
        }
        let started = Instant::now();
        if let Err(error) = self.file.write_all(encoded.as_bytes())
            .and_then(|()| self.file.sync_all())
        {
            self.poisoned = true;
            return Err(MetricsJournalErrorV1::Io(error));
        }
        self.bytes = next_bytes;
        self.sequence = sequence;
        self.head = next_head;
        let receipt = MetricsCommitReceiptV1 {
            sequence, head_digest: next_head, rows: self.staged.len(),
            sync_latency_micros: u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX),
        };
        self.staged.clear();
        Ok(Some(receipt))
    }
}

/// Timed operation and its result stay together. Telemetry is separate so an
/// I/O failure cannot turn a successful CAS/signature/CNS effect into a retry.
pub fn measure_phase_v1<T, E>(
    scope_digest: Digest32,
    operation_digest: Digest32,
    phase: MetricPhaseV1,
    operation: impl FnOnce() -> Result<T, E>,
) -> (Result<T, E>, MetricSampleV1) {
    let start = Instant::now();
    let result = operation();
    let sample = MetricSampleV1 {
        scope_digest, operation_digest, phase,
        latency_micros: u64::try_from(start.elapsed().as_micros()).unwrap_or(u64::MAX),
        succeeded: result.is_ok(),
    };
    (result, sample)
}

fn encode_sample(sample: &MetricSampleV1) -> String {
    format!(
        "{}:{}:{}:{}:{}",
        sample.scope_digest, sample.operation_digest, sample.phase as u8,
        sample.latency_micros, u8::from(sample.succeeded)
    )
}

fn digest_group(sequence: u64, previous: Digest32, payload: &str) -> Digest32 {
    let mut bytes = DOMAIN.to_vec();
    bytes.extend_from_slice(&sequence.to_be_bytes());
    bytes.extend_from_slice(previous.as_array());
    bytes.extend_from_slice(&(payload.len() as u64).to_be_bytes());
    bytes.extend_from_slice(payload.as_bytes());
    Digest32::of_bytes(&bytes)
}

fn parse_group(
    line: &str,
    previous_sequence: u64,
    previous_head: Digest32,
) -> Result<(u64, Digest32), MetricsJournalErrorV1> {
    let mut fields = line.split('|');
    if fields.next() != Some("M1") { return Err(MetricsJournalErrorV1::Corrupt); }
    let sequence = fields.next().and_then(|s| s.parse::<u64>().ok())
        .ok_or(MetricsJournalErrorV1::Corrupt)?;
    if sequence != previous_sequence.checked_add(1).ok_or(MetricsJournalErrorV1::Corrupt)? {
        return Err(MetricsJournalErrorV1::Corrupt);
    }
    let predecessor_hex = previous_head.to_string();
    if fields.next() != Some(predecessor_hex.as_str()) {
        return Err(MetricsJournalErrorV1::Corrupt);
    }
    let head = fields.next().ok_or(MetricsJournalErrorV1::Corrupt)?;
    let count = fields.next().and_then(|s| s.parse::<usize>().ok())
        .ok_or(MetricsJournalErrorV1::Corrupt)?;
    let payload = fields.next().ok_or(MetricsJournalErrorV1::Corrupt)?;
    if fields.next().is_some() || count == 0 || count > MAX_GROUP_ROWS {
        return Err(MetricsJournalErrorV1::Corrupt);
    }
    let rows: Vec<_> = payload.split(';').collect();
    if rows.len() != count { return Err(MetricsJournalErrorV1::Corrupt); }
    for row in rows {
        let columns: Vec<_> = row.split(':').collect();
        if columns.len() != 5
            || !digest_hex(columns[0])
            || !digest_hex(columns[1])
            || !matches!(columns[2], "1" | "2" | "3" | "4" | "5" | "6")
            || columns[3].parse::<u64>().is_err()
            || !matches!(columns[4], "0" | "1")
        {
            return Err(MetricsJournalErrorV1::Corrupt);
        }
    }
    let expected = digest_group(sequence, previous_head, payload);
    if head != expected.to_string() { return Err(MetricsJournalErrorV1::Corrupt); }
    Ok((sequence, expected))
}

fn digest_hex(s: &str) -> bool {
    s.len() == 64 && s.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

#[cfg(test)]
#[path = "metrics_group_commit_tests.rs"]
mod tests;
