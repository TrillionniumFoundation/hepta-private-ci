//! A non-authorizing, generation-scoped group-commit metrics ledger.
//!
//! File locks fence cooperating writers. A digest chain detects damaged complete
//! records, and only a physically incomplete trailing frame may be truncated.
//! This is not an external anti-rollback oracle or a production release gate.

use std::collections::BTreeSet;
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
    DuplicatePlan,
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

fn dispatch_intent_digest(plan: Digest32) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.neuron.metrics.dispatch-intent.v1\0",
        plan.as_array(),
    ])
}

impl NeuronBatchMetricV1 {
    fn is_dispatch_intent(&self) -> bool {
        self.execution_digest == dispatch_intent_digest(self.plan_digest)
            && self.elapsed_micros == 0
            && self.observed_cpu_micros == 0
            && self.observed_rss_bytes == 0
            && self.p95_micros == 0
            && self.p99_micros == 0
            && self.lock_wait_micros == 0
            && self.measurements_mask == 0
    }

    fn validate(&self) -> Result<(), NeuronMetricsErrorV1> {
        if self.plan_digest.is_zero()
            || self.execution_digest.is_zero()
            || !(1..=256).contains(&self.request_count)
            || self.p95_micros > self.p99_micros
            || (self.execution_digest == dispatch_intent_digest(self.plan_digest)
                && !self.is_dispatch_intent())
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
    seen_plans: BTreeSet<Digest32>,
    completed_plans: BTreeSet<Digest32>,
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

        let size =
            usize::try_from(file.metadata()?.len()).map_err(|_| NeuronMetricsErrorV1::Capacity)?;
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
                seen_plans: BTreeSet::new(),
                completed_plans: BTreeSet::new(),
                recovered_partial_tail: false,
                poisoned: false,
            });
        }

        file.seek(SeekFrom::Start(0))?;
        let mut data = Vec::with_capacity(size);
        file.read_to_end(&mut data)?;
        if data.len() != size
            || size < HEADER_LEN
            || &data[..8] != MAGIC
            || &data[8..40] != scope_digest.as_array()
            || &data[40..48] != generation.get().to_be_bytes().as_slice()
        {
            return Err(NeuronMetricsErrorV1::ScopeMismatch);
        }

        let mut offset = HEADER_LEN;
        let mut sequence = 0_u64;
        let mut head = Digest32::ZERO;
        let mut seen_plans = BTreeSet::new();
        let mut completed_plans = BTreeSet::new();
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
            if &data[offset + 4 + FRAME_BODY_LEN..offset + FRAME_LEN] != checksum.as_array() {
                return Err(NeuronMetricsErrorV1::Corrupt);
            }
            let stored_sequence = u64::from_be_bytes(
                body[..8]
                    .try_into()
                    .map_err(|_| NeuronMetricsErrorV1::Corrupt)?,
            );
            if stored_sequence != sequence + 1 || &body[8..40] != head.as_array() {
                return Err(NeuronMetricsErrorV1::Corrupt);
            }
            // Complete durable frames must have unique batch identities and
            // valid shape, not merely a syntactically correct frame checksum.
            let plan_digest = Digest32::from_array(
                body[40..72]
                    .try_into()
                    .map_err(|_| NeuronMetricsErrorV1::Corrupt)?,
            );
            let execution_digest = Digest32::from_array(
                body[72..104]
                    .try_into()
                    .map_err(|_| NeuronMetricsErrorV1::Corrupt)?,
            );
            let requests = u32::from_be_bytes(
                body[104..108]
                    .try_into()
                    .map_err(|_| NeuronMetricsErrorV1::Corrupt)?,
            );
            let latency_p95 = u64::from_be_bytes(
                body[132..140]
                    .try_into()
                    .map_err(|_| NeuronMetricsErrorV1::Corrupt)?,
            );
            let latency_p99 = u64::from_be_bytes(
                body[140..148]
                    .try_into()
                    .map_err(|_| NeuronMetricsErrorV1::Corrupt)?,
            );
            let mask = body[156];
            let elapsed = u64::from_be_bytes(
                body[108..116]
                    .try_into()
                    .map_err(|_| NeuronMetricsErrorV1::Corrupt)?,
            );
            let cpu = u64::from_be_bytes(
                body[116..124]
                    .try_into()
                    .map_err(|_| NeuronMetricsErrorV1::Corrupt)?,
            );
            let rss = u64::from_be_bytes(
                body[124..132]
                    .try_into()
                    .map_err(|_| NeuronMetricsErrorV1::Corrupt)?,
            );
            let lock_wait = u64::from_be_bytes(
                body[148..156]
                    .try_into()
                    .map_err(|_| NeuronMetricsErrorV1::Corrupt)?,
            );
            if plan_digest.is_zero()
                || execution_digest.is_zero()
                || !(1..=256).contains(&requests)
                || latency_p95 > latency_p99
                || mask & !0b111 != 0
                || (mask & 0b001 == 0 && cpu != 0)
                || (mask & 0b010 == 0 && rss != 0)
                || (mask & 0b100 == 0 && lock_wait != 0)
            {
                return Err(NeuronMetricsErrorV1::Corrupt);
            }
            let is_intent = execution_digest == dispatch_intent_digest(plan_digest);
            if is_intent
                && (elapsed != 0
                    || cpu != 0
                    || rss != 0
                    || latency_p95 != 0
                    || latency_p99 != 0
                    || lock_wait != 0
                    || mask != 0)
            {
                return Err(NeuronMetricsErrorV1::Corrupt);
            }
            if !seen_plans.insert(plan_digest) {
                if is_intent || !completed_plans.insert(plan_digest) {
                    return Err(NeuronMetricsErrorV1::Corrupt);
                }
            } else if !is_intent {
                completed_plans.insert(plan_digest);
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
            seen_plans,
            completed_plans,
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
        let mut batch_plans = BTreeSet::new();
        let mut new_plans = BTreeSet::new();
        let mut new_completed = BTreeSet::new();
        for event in events {
            event.validate()?;
            if !batch_plans.insert(event.plan_digest) {
                return Err(NeuronMetricsErrorV1::DuplicatePlan);
            }
            if event.is_dispatch_intent() {
                if self.seen_plans.contains(&event.plan_digest) {
                    return Err(NeuronMetricsErrorV1::DuplicatePlan);
                }
                new_plans.insert(event.plan_digest);
            } else {
                if self.completed_plans.contains(&event.plan_digest) {
                    return Err(NeuronMetricsErrorV1::DuplicatePlan);
                }
                if !self.seen_plans.contains(&event.plan_digest) {
                    new_plans.insert(event.plan_digest);
                }
                new_completed.insert(event.plan_digest);
            }
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
        let first = self
            .sequence
            .checked_add(1)
            .ok_or(NeuronMetricsErrorV1::Capacity)?;
        let mut sequence = self.sequence;
        let mut previous = self.head;
        for event in events {
            sequence = sequence
                .checked_add(1)
                .ok_or(NeuronMetricsErrorV1::Capacity)?;
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
        self.seen_plans.extend(new_plans);
        self.completed_plans.extend(new_completed);
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

    pub fn recorded_sequence(&self) -> u64 {
        self.sequence
    }

    /// Write and fsync an intent witness before physical backend dispatch.
    /// An unknown outcome is non-redispatchable pending owner reconciliation.
    pub fn record_dispatch_intent(
        &mut self,
        plan_digest: Digest32,
        request_count: u32,
    ) -> Result<NeuronMetricsCommitV1, NeuronMetricsErrorV1> {
        self.append_group(&[NeuronBatchMetricV1 {
            plan_digest,
            execution_digest: dispatch_intent_digest(plan_digest),
            request_count,
            elapsed_micros: 0,
            observed_cpu_micros: 0,
            observed_rss_bytes: 0,
            p95_micros: 0,
            p99_micros: 0,
            lock_wait_micros: 0,
            measurements_mask: 0,
        }])
    }

    pub fn contains_recorded_plan(&self, plan_digest: Digest32) -> bool {
        self.seen_plans.contains(&plan_digest)
    }

    pub fn completed_execution_count(&self) -> usize {
        self.completed_plans.len()
    }

    pub fn recovered_partial_tail(&self) -> bool {
        self.recovered_partial_tail
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
