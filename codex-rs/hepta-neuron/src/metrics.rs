//! A non-authorizing, generation-scoped group-commit metrics ledger.
//!
//! File locks fence cooperating writers. A digest chain detects damaged complete
//! records, and only a physically incomplete trailing frame may be truncated.
//! This is not an external anti-rollback oracle or a production release gate.

use std::fmt;
use std::fs::File;
use std::fs::TryLockError;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

const MAGIC: &[u8; 8] = b"HNMTV001";
const HEADER_LEN: usize = 48;
const FRAME_BODY_LEN: usize = 157;
const FRAME_LEN: usize = 4 + FRAME_BODY_LEN + 32;
const MAX_LEDGER_BYTES: usize = 64 * 1024 * 1024;
const MAX_GROUP_EVENTS: usize = 256;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NeuronMetricsErrorV1 {
    Busy,
    NotRegular,
    ScopeMismatch,
    Corrupt,
    InvalidEvent,
    Capacity,
    Poisoned,
    Io(std::io::ErrorKind),
}

impl fmt::Display for NeuronMetricsErrorV1 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl std::error::Error for NeuronMetricsErrorV1 {}

impl From<std::io::Error> for NeuronMetricsErrorV1 {
    fn from(error: std::io::Error) -> Self {
        Self::Io(error.kind())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronBatchMetricV1 {
    pub plan_digest: Digest32,
    pub execution_digest: Digest32,
    pub request_count: u32,
    pub elapsed_micros: u64,
    pub observed_cpu_micros: u64,
    pub observed_rss_bytes: u64,
    pub p95_micros: u64,
    pub p99_micros: u64,
    pub lock_wait_micros: u64,
    /// Bit 0=CPU, bit 1=RSS, bit 2=lock wait were really sampled.
    /// Unset means unavailable; the corresponding numeric field must be zero.
    pub measurements_mask: u8,
}

impl NeuronBatchMetricV1 {
    fn validate(&self) -> Result<(), NeuronMetricsErrorV1> {
        if self.plan_digest.is_zero()
            || self.execution_digest.is_zero()
            || !(1..=256).contains(&self.request_count)
            || self.p95_micros > self.p99_micros
            || self.measurements_mask & !0b111 != 0
            || (self.measurements_mask & 0b001 == 0 && self.observed_cpu_micros != 0)
            || (self.measurements_mask & 0b010 == 0 && self.observed_rss_bytes != 0)
            || (self.measurements_mask & 0b100 == 0 && self.lock_wait_micros != 0)
        {
            return Err(NeuronMetricsErrorV1::InvalidEvent);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NeuronMetricsCommitV1 {
    pub first_sequence: u64,
    pub final_sequence: u64,
    pub final_digest: Digest32,
    pub committed_events: usize,
    pub data_syncs: u32,
    pub recovered_partial_tail: bool,
}

/// One live writer owns the file lock for its lifetime. After any uncertain
/// write/sync, the owner poisons itself instead of acknowledging or retrying.
pub struct NeuronMetricsGroupCommitWriterV1 {
    file: File,
    scope_digest: Digest32,
    generation: Generation,
    length: usize,
    sequence: u64,
    head: Digest32,
    recovered_partial_tail: bool,
    poisoned: bool,
}

impl NeuronMetricsGroupCommitWriterV1 {
    pub fn open(
        mut file: File,
        scope_digest: Digest32,
        generation: Generation,
    ) -> Result<Self, NeuronMetricsErrorV1> {
        if scope_digest.is_zero() {
            return Err(NeuronMetricsErrorV1::ScopeMismatch);
        }
        if !file.metadata()?.is_file() {
            return Err(NeuronMetricsErrorV1::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => {}
            Err(TryLockError::WouldBlock) => return Err(NeuronMetricsErrorV1::Busy),
            Err(TryLockError::Error(error)) => return Err(error.into()),
        }

        let size = usize::try_from(file.metadata()?.len())
            .map_err(|_| NeuronMetricsErrorV1::Capacity)?;
        if size > MAX_LEDGER_BYTES {
            return Err(NeuronMetricsErrorV1::Capacity);
        }
        if size == 0 {
            let mut header = Vec::with_capacity(HEADER_LEN);
            header.extend_from_slice(MAGIC);
            header.extend_from_slice(scope_digest.as_array());
            header.extend_from_slice(&generation.get().to_be_bytes());
            file.write_all(&header)?;
            file.sync_data()?;
            return Ok(Self {
                file,
                scope_digest,
                generation,
                length: HEADER_LEN,
                sequence: 0,
                head: Digest32::ZERO,
                recovered_partial_tail: false,
                poisoned: false,
            });
        }

        file.seek(SeekFrom::Start(0))?;
        let mut data = Vec::with_capacity(size);
        file.read_to_end(&mut data)?;
        if data.len() != size || size < HEADER_LEN || &data[..8] != MAGIC
            || &data[8..40] != scope_digest.as_array()
            || data[40..48] != generation.get().to_be_bytes()
        {
            return Err(NeuronMetricsErrorV1::ScopeMismatch);
        }

        let mut offset = HEADER_LEN;
        let mut sequence = 0_u64;
        let mut head = Digest32::ZERO;
        while offset < data.len() {
            if data.len() - offset < 4 {
                break;
            }
            let stored_len = u32::from_be_bytes(
                data[offset..offset + 4]
                    .try_into()
                    .map_err(|_| NeuronMetricsErrorV1::Corrupt)?,
            ) as usize;
            if stored_len != FRAME_BODY_LEN {
                return Err(NeuronMetricsErrorV1::Corrupt);
            }
            if data.len() - offset < FRAME_LEN {
                break;
            }
            let body = &data[offset + 4..offset + 4 + FRAME_BODY_LEN];
            let checksum = Digest32::of_parts(&[b"hepta.neuron.metrics.frame.v1\0", body]);
            if &data[offset + 4 + FRAME_BODY_LEN..offset + FRAME_LEN]
                != checksum.as_array()
            {
                return Err(NeuronMetricsErrorV1::Corrupt);
            }
            let stored_sequence = u64::from_be_bytes(
                body[..8].try_into().map_err(|_| NeuronMetricsErrorV1::Corrupt)?,
            );
            if stored_sequence != sequence + 1 || &body[8..40] != head.as_array() {
                return Err(NeuronMetricsErrorV1::Corrupt);
            }
            sequence = stored_sequence;
            head = checksum;
            offset += FRAME_LEN;
        }

        let recovered = offset < size;
        if recovered {
            file.set_len(offset as u64)?;
            file.sync_data()?;
        }
        file.seek(SeekFrom::End(0))?;
        Ok(Self {
            file,
            scope_digest,
            generation,
            length: offset,
            sequence,
            head,
            recovered_partial_tail: recovered,
            poisoned: false,
        })
    }

    pub fn append_group(
        &mut self,
        events: &[NeuronBatchMetricV1],
    ) -> Result<NeuronMetricsCommitV1, NeuronMetricsErrorV1> {
        if self.poisoned {
            return Err(NeuronMetricsErrorV1::Poisoned);
        }
        if events.is_empty() || events.len() > MAX_GROUP_EVENTS {
            return Err(NeuronMetricsErrorV1::Capacity);
        }
        for event in events {
            event.validate()?;
        }
        let bytes_needed = events
            .len()
            .checked_mul(FRAME_LEN)
            .and_then(|len| len.checked_add(self.length))
            .ok_or(NeuronMetricsErrorV1::Capacity)?;
        if bytes_needed > MAX_LEDGER_BYTES {
            return Err(NeuronMetricsErrorV1::Capacity);
        }
        let mut buffer = Vec::with_capacity(events.len() * FRAME_LEN);
        let first = self.sequence.checked_add(1).ok_or(NeuronMetricsErrorV1::Capacity)?;
        let mut sequence = self.sequence;
        let mut previous = self.head;
        for event in events {
            sequence = sequence.checked_add(1).ok_or(NeuronMetricsErrorV1::Capacity)?;
            let mut body = Vec::with_capacity(FRAME_BODY_LEN);
            body.extend_from_slice(&sequence.to_be_bytes());
            body.extend_from_slice(previous.as_array());
            body.extend_from_slice(event.plan_digest.as_array());
            body.extend_from_slice(event.execution_digest.as_array());
            body.extend_from_slice(&event.request_count.to_be_bytes());
            for value in [
                event.elapsed_micros,
                event.observed_cpu_micros,
                event.observed_rss_bytes,
                event.p95_micros,
                event.p99_micros,
                event.lock_wait_micros,
            ] {
                body.extend_from_slice(&value.to_be_bytes());
            }
            body.push(event.measurements_mask);
            if body.len() != FRAME_BODY_LEN {
                return Err(NeuronMetricsErrorV1::Corrupt);
            }
            let checksum = Digest32::of_parts(&[b"hepta.neuron.metrics.frame.v1\0", &body]);
            buffer.extend_from_slice(&(FRAME_BODY_LEN as u32).to_be_bytes());
            buffer.extend_from_slice(&body);
            buffer.extend_from_slice(checksum.as_array());
            previous = checksum;
        }
        let result = (|| -> Result<(), std::io::Error> {
            if self.file.metadata()?.len() != self.length as u64 {
                return Err(std::io::Error::other("metrics length drift"));
            }
            self.file.write_all(&buffer)?;
            self.file.sync_data()
        })();
        if result.is_err() {
            self.poisoned = true;
            return Err(NeuronMetricsErrorV1::Poisoned);
        }
        self.length = bytes_needed;
        self.sequence = sequence;
        self.head = previous;
        Ok(NeuronMetricsCommitV1 {
            first_sequence: first,
            final_sequence: sequence,
            final_digest: previous,
            committed_events: events.len(),
            data_syncs: 1,
            recovered_partial_tail: self.recovered_partial_tail,
        })
    }

    pub fn scope_digest(&self) -> Digest32 {
        self.scope_digest
    }

    pub fn generation(&self) -> Generation {
        self.generation
    }
}

impl Drop for NeuronMetricsGroupCommitWriterV1 {
    fn drop(&mut self) {
        let _ = self.file.unlock();
    }
}

#[cfg(test)]
#[path = "metrics_tests.rs"]
mod tests;
