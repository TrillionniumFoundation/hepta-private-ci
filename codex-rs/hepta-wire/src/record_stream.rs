//! Bounded HPTM framing for the existing, single authenticated session owner.
//!
//! This adapter owns no transport, authority, checkpoint or replay journal.
//! A completed record is admitted only by `ManagedAuthenticatedWireSession`.

use std::error::Error;
use std::fmt;

use crate::DecodeFeed;
use crate::DecodedEnvelope;
use crate::MAX_AUTHENTICATED_RECORD_BYTES;
use crate::MAX_WIRE_FRAME_BYTES;
use crate::ManagedAuthenticatedWireSession;
use crate::ManagedSessionError;
use crate::SessionLifecycleState;
use crate::WIRE_HEADER_BYTES;

// Frozen HPTM V1 framing; the authenticated owner revalidates the full record.
const PREFIX_BYTES: usize = 4 + 2 + 32 + 8 + 4;
const TAG_BYTES: usize = 32;

/// Independent per-call work limits and a per-record admission ceiling.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RecordStreamLimits {
    pub max_record_bytes: usize,
    pub max_feed_bytes: usize,
    pub max_records_per_feed: usize,
}

impl Default for RecordStreamLimits {
    fn default() -> Self {
        Self {
            max_record_bytes: MAX_AUTHENTICATED_RECORD_BYTES,
            max_feed_bytes: 64 * 1024,
            max_records_per_feed: 16,
        }
    }
}

/// Caller-owned allowance shared by streams during one scheduling turn.
///
/// This is work accounting, not authorization, a queue, or a scheduler. Charge
/// admitted source bytes, full-record authentication attempts and the complete
/// serialized HPTA bytes covered by those attempts, including failing attempts.
/// The third ceiling also bounds serialized bytes represented by returned frames:
/// a one-byte suffix can finish a much larger record buffered on an earlier turn.
/// Drain/account for returned frames before allocating another allowance.
/// Allocator overhead, caller-retained frames, transport queues, connection count
/// and I/O retries require independent bounds in their existing owners.
///
/// The allowance is deliberately not `Clone` or `Copy`. Exhaustion is a yield,
/// never permission to discard the unconsumed suffix or reset session state.
#[derive(Debug, Eq, PartialEq)]
pub struct RecordStreamBudget {
    remaining_bytes: usize,
    remaining_records: usize,
    remaining_frame_bytes: usize,
}

impl RecordStreamBudget {
    /// Zero source/record allowances cause a nonterminal, zero-consumption yield.
    pub const fn new(bytes: usize, records: usize) -> Self {
        Self::with_frame_bytes(bytes, records, MAX_WIRE_FRAME_BYTES)
    }

    /// Set an explicit aggregate serialized-envelope allowance for this turn.
    ///
    /// This counts the full HPTA frame, not just newly supplied source bytes or
    /// payload bytes. It is not an allocator/RSS measurement. Zero is valid and
    /// blocks body admission without retiring the session. A valid next frame
    /// that does not fit yields; inspect `required_frame_bytes()` before retrying.
    pub const fn with_frame_bytes(bytes: usize, records: usize, frame_bytes: usize) -> Self {
        Self {
            remaining_bytes: bytes,
            remaining_records: records,
            remaining_frame_bytes: frame_bytes,
        }
    }

    pub const fn remaining_bytes(&self) -> usize {
        self.remaining_bytes
    }

    pub const fn remaining_records(&self) -> usize {
        self.remaining_records
    }

    pub const fn remaining_frame_bytes(&self) -> usize {
        self.remaining_frame_bytes
    }
}

/// Frames before a terminal suffix remain deliverable, exactly once.
#[must_use = "deliver the accepted prefix before acting on the terminal error"]
pub struct RecordStreamBatch {
    frames: Vec<DecodedEnvelope>,
    terminal_error: Option<RecordStreamError>,
    yielded: bool,
    required_frame_bytes: Option<usize>,
}

impl RecordStreamBatch {
    pub fn frames(&self) -> &[DecodedEnvelope] {
        &self.frames
    }

    pub fn terminal_error(&self) -> Option<&RecordStreamError> {
        self.terminal_error.as_ref()
    }

    pub const fn yielded(&self) -> bool {
        self.yielded
    }

    /// Full serialized HPTA size of the next record blocked by frame capacity.
    /// This is an admitted but unauthenticated length, never trusted payload or
    /// authorization. Free/reserve capacity before retrying the exact suffix.
    pub const fn required_frame_bytes(&self) -> Option<usize> {
        self.required_frame_bytes
    }

    pub fn into_parts(self) -> (Vec<DecodedEnvelope>, Option<RecordStreamError>) {
        (self.frames, self.terminal_error)
    }
}

impl fmt::Debug for RecordStreamBatch {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("RecordStreamBatch")
            .field("frame_count", &self.frames.len())
            .field("terminal_error", &self.terminal_error)
            .field("yielded", &self.yielded)
            .field("required_frame_bytes", &self.required_frame_bytes)
            .finish()
    }
}

/// Consumes the existing session owner, never clones authentication state.
///
/// The caller retains the suffix after `DecodeFeed::bytes_consumed()`, yields
/// its executor when requested, and imposes transport deadlines and connection
/// limits. Cancellation, EOF and framing failure retire the same owner. A new
/// connection must be negotiated rather than restarting this stream in place.
pub struct ManagedRecordStream {
    owner: ManagedAuthenticatedWireSession,
    limits: RecordStreamLimits,
    pending: Vec<u8>,
    expected: Option<usize>,
    terminal: bool,
    idle_buffer_limit_bytes: usize,
}

impl ManagedAuthenticatedWireSession {
    pub fn into_record_stream(
        self,
        limits: RecordStreamLimits,
    ) -> Result<ManagedRecordStream, RecordStreamError> {
        let minimum = PREFIX_BYTES + WIRE_HEADER_BYTES + TAG_BYTES;
        if !(minimum..=MAX_AUTHENTICATED_RECORD_BYTES).contains(&limits.max_record_bytes)
            || limits.max_feed_bytes == 0
            || limits.max_feed_bytes > MAX_AUTHENTICATED_RECORD_BYTES
            || limits.max_records_per_feed == 0
            || limits.max_records_per_feed > 1024
        {
            return Err(RecordStreamError::InvalidLimits);
        }
        if self.state() != SessionLifecycleState::Active {
            return Err(RecordStreamError::Terminated);
        }
        Ok(ManagedRecordStream {
            owner: self,
            limits,
            pending: Vec::new(),
            expected: None,
            terminal: false,
            idle_buffer_limit_bytes: limits.max_feed_bytes.min(limits.max_record_bytes),
        })
    }
}

impl ManagedRecordStream {
    pub fn buffered_bytes(&self) -> usize {
        self.pending.len()
    }

    /// Retained record-buffer capacity, not allocator overhead or process RSS.
    /// Completed frames and transport-owned buffers must be accounted separately.
    pub fn buffer_capacity_bytes(&self) -> usize {
        self.pending.capacity()
    }

    /// Maximum staging capacity retained at an idle record boundary.
    ///
    /// The default is the smaller of the per-feed and per-record byte limits.
    /// This excludes an incomplete record, returned frames, allocator overhead
    /// and transport buffers; it is not a connection-manager or RSS bound.
    ///
    /// Dependency classification: no-gRPC.
    pub const fn idle_buffer_limit_bytes(&self) -> usize {
        self.idle_buffer_limit_bytes
    }

    /// Change the idle staging limit without changing authentication or framing.
    ///
    /// The limit is clamped to the record ceiling. Zero disables idle retention.
    /// An incomplete record is never discarded: the new limit takes effect when
    /// that record completes. Return the capacity released immediately, if any.
    ///
    /// Dependency classification: no-gRPC.
    pub fn set_idle_buffer_limit_bytes(&mut self, limit: usize) -> usize {
        self.idle_buffer_limit_bytes = limit.min(self.limits.max_record_bytes);
        self.trim_idle_buffer_to_limit()
    }

    /// Release an empty staging allocation under owner-controlled memory pressure.
    ///
    /// Return released Vec capacity, not process RSS. An in-flight prefix/body
    /// makes this a no-op. Sequence, key, session identity, terminal state and
    /// already-delivered frames are unchanged; this never restarts a connection.
    ///
    /// Dependency classification: no-gRPC.
    pub fn release_idle_buffer(&mut self) -> usize {
        if !self.pending.is_empty() || self.expected.is_some() {
            return 0;
        }
        let released = self.pending.capacity();
        self.pending = Vec::new();
        released
    }

    fn trim_idle_buffer_to_limit(&mut self) -> usize {
        if self.pending.capacity() > self.idle_buffer_limit_bytes {
            self.release_idle_buffer()
        } else {
            0
        }
    }

    pub fn is_terminal(&self) -> bool {
        self.terminal || self.owner.state() != SessionLifecycleState::Active
    }

    pub fn retire(&mut self) {
        self.owner.retire();
        self.pending = Vec::new();
        self.expected = None;
        self.terminal = true;
    }

    pub fn seal_envelope(
        &mut self,
        envelope: &DecodedEnvelope,
    ) -> Result<Vec<u8>, RecordStreamError> {
        if self.is_terminal() {
            return Err(RecordStreamError::Terminated);
        }
        match self.owner.seal_envelope(envelope) {
            Ok(record) if record.len() <= self.limits.max_record_bytes => Ok(record),
            Ok(_) => {
                self.retire();
                Err(RecordStreamError::RecordLimit)
            }
            Err(error) => {
                self.retire();
                Err(RecordStreamError::Session(error))
            }
        }
    }

    // A declared length is only a ceiling, not permission to allocate its body.
    // Grow geometrically with admitted bytes, avoiding both speculative body
    // allocation and quadratic reallocations for one-byte transport fragments.
    fn reserve_admitted(&mut self, additional: usize) -> Result<(), RecordStreamError> {
        let needed = self
            .pending
            .len()
            .checked_add(additional)
            .ok_or(RecordStreamError::RecordLimit)?;
        if needed > self.limits.max_record_bytes {
            return Err(RecordStreamError::RecordLimit);
        }
        if needed <= self.pending.capacity() {
            return Ok(());
        }
        let ceiling = self.expected.unwrap_or(PREFIX_BYTES);
        let capacity = needed
            .max(PREFIX_BYTES)
            .max(self.pending.capacity().saturating_mul(2))
            .min(ceiling);
        self.pending
            .try_reserve_exact(capacity - self.pending.len())
            .map_err(|_| RecordStreamError::Allocation)
    }

    // Both fragmented and contiguous records use the same admission checks.
    // These checks never replace the owner's MAC, sequence and schema checks.
    fn admitted_record_length(&self, prefix: &[u8]) -> Result<usize, RecordStreamError> {
        if prefix[..4] != *b"HPTM" || prefix[4..6] != [0, 1] {
            return Err(RecordStreamError::InvalidPrefix);
        }
        if &prefix[6..38] != self.owner.session_id().as_array() {
            return Err(RecordStreamError::SessionIdentityMismatch);
        }
        let length = u32::from_be_bytes([prefix[46], prefix[47], prefix[48], prefix[49]]);
        let length = usize::try_from(length).map_err(|_| RecordStreamError::RecordLimit)?;
        if !(WIRE_HEADER_BYTES..=MAX_WIRE_FRAME_BYTES).contains(&length)
            || length > self.limits.max_record_bytes - PREFIX_BYTES - TAG_BYTES
        {
            return Err(RecordStreamError::RecordLimit);
        }
        Ok(PREFIX_BYTES + length + TAG_BYTES)
    }

    /// Process one turn under the stream's configured limits.
    pub fn feed(&mut self, input: &[u8]) -> DecodeFeed<RecordStreamBatch> {
        let mut allowance = RecordStreamBudget::new(
            self.limits.max_feed_bytes,
            self.limits.max_records_per_feed,
        );
        self.feed_with_budget(input, &mut allowance)
    }

    /// Process under both this stream's limits and a shared scheduling allowance.
    ///
    /// Retain the suffix after `bytes_consumed()` and yield the executor on
    /// exhaustion. Passing one allowance across peers bounds aggregate admitted
    /// bytes, authentication attempts and complete serialized-frame work without
    /// transferring session ownership. A terminal error never refunds completed
    /// work. Cancellation and EOF remain independent of this allowance.
    pub fn feed_with_budget(
        &mut self,
        input: &[u8],
        allowance: &mut RecordStreamBudget,
    ) -> DecodeFeed<RecordStreamBatch> {
        let mut batch = RecordStreamBatch {
            frames: Vec::new(),
            terminal_error: None,
            yielded: false,
            required_frame_bytes: None,
        };
        if self.is_terminal() {
            self.retire();
            batch.terminal_error = Some(RecordStreamError::Terminated);
            return DecodeFeed::new(batch, 0);
        }
        let budget = input
            .len()
            .min(self.limits.max_feed_bytes)
            .min(allowance.remaining_bytes);
        let record_budget = self
            .limits
            .max_records_per_feed
            .min(allowance.remaining_records);
        let mut consumed = 0;
        let mut attempted = 0;
        let mut frame_bytes = 0;
        while consumed < budget && attempted < record_budget {
            // Complete, contiguous records can be authenticated directly from
            // the caller's slice. Only framing staging is avoided: decoding may
            // still allocate and the returned envelopes remain owned values.
            if self.pending.is_empty() && budget - consumed >= PREFIX_BYTES {
                let length = match self
                    .admitted_record_length(&input[consumed..consumed + PREFIX_BYTES])
                {
                    Ok(length) => length,
                    Err(error) => {
                        consumed += PREFIX_BYTES;
                        batch.terminal_error = Some(error);
                        break;
                    }
                };
                let required = length - PREFIX_BYTES - TAG_BYTES;
                if required > allowance.remaining_frame_bytes - frame_bytes {
                    batch.required_frame_bytes = Some(required);
                    break;
                }
                if length <= budget - consumed {
                    let start = consumed;
                    consumed += length;
                    attempted += 1;
                    frame_bytes += required;
                    match self.owner.open_record(&input[start..consumed]) {
                        Ok(frame) => batch.frames.push(frame),
                        Err(error) => {
                            batch.terminal_error = Some(RecordStreamError::Session(error));
                            break;
                        }
                    }
                    continue;
                }
            }

            let target = self.expected.unwrap_or(PREFIX_BYTES);
            if self.expected.is_some() {
                let required = target - PREFIX_BYTES - TAG_BYTES;
                if required > allowance.remaining_frame_bytes - frame_bytes {
                    batch.required_frame_bytes = Some(required);
                    break;
                }
            }
            let count = (target - self.pending.len()).min(budget - consumed);
            if let Err(error) = self.reserve_admitted(count) {
                batch.terminal_error = Some(error);
                break;
            }
            self.pending
                .extend_from_slice(&input[consumed..consumed + count]);
            consumed += count;
            if self.pending.len() != target {
                continue;
            }
            if self.expected.is_none() {
                match self.admitted_record_length(&self.pending) {
                    Ok(length) => self.expected = Some(length),
                    Err(error) => {
                        batch.terminal_error = Some(error);
                        break;
                    }
                }
                continue;
            }
            attempted += 1;
            frame_bytes += target - PREFIX_BYTES - TAG_BYTES;
            match self.owner.open_record(&self.pending) {
                Ok(frame) => batch.frames.push(frame),
                Err(error) => {
                    batch.terminal_error = Some(RecordStreamError::Session(error));
                    break;
                }
            }
            self.pending.clear();
            self.expected = None;
            // Reclaim before a following short prefix can pin the old allocation.
            // No incomplete record exists at this authenticated record boundary.
            self.trim_idle_buffer_to_limit();
        }
        allowance.remaining_bytes -= consumed;
        allowance.remaining_records -= attempted;
        allowance.remaining_frame_bytes -= frame_bytes;
        if batch.terminal_error.is_some() {
            self.retire();
        } else {
            batch.yielded = consumed < input.len();
            self.trim_idle_buffer_to_limit();
        }
        DecodeFeed::new(batch, consumed)
    }

    /// Consuming, connection-wide EOF; this is not a half-close operation.
    pub fn finish(mut self) -> Result<(), RecordStreamError> {
        let result = if self.is_terminal() {
            Err(RecordStreamError::Terminated)
        } else if self.pending.is_empty() {
            Ok(())
        } else {
            Err(RecordStreamError::UnexpectedEof {
                buffered: self.pending.len(),
                expected: self.expected.unwrap_or(PREFIX_BYTES),
            })
        };
        self.retire();
        result
    }
}

impl fmt::Debug for ManagedRecordStream {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ManagedRecordStream")
            .field("session_id", &self.owner.session_id())
            .field("limits", &self.limits)
            .field("buffered_bytes", &self.pending.len())
            .field("buffer_capacity_bytes", &self.pending.capacity())
            .field("idle_buffer_limit_bytes", &self.idle_buffer_limit_bytes)
            .field("terminal", &self.is_terminal())
            .finish()
    }
}

#[derive(Debug)]
pub enum RecordStreamError {
    InvalidLimits,
    InvalidPrefix,
    SessionIdentityMismatch,
    RecordLimit,
    Allocation,
    Terminated,
    UnexpectedEof { buffered: usize, expected: usize },
    Session(ManagedSessionError),
}

impl fmt::Display for RecordStreamError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidLimits => formatter.write_str("invalid authenticated stream limits"),
            Self::InvalidPrefix => formatter.write_str("invalid HPTM V1 prefix"),
            Self::SessionIdentityMismatch => {
                formatter.write_str("HPTM record belongs to a different session")
            }
            Self::RecordLimit => formatter.write_str("authenticated record exceeds admission bounds"),
            Self::Allocation => formatter.write_str("authenticated stream allocation failed"),
            Self::Terminated => formatter.write_str("authenticated stream is terminal"),
            Self::UnexpectedEof { buffered, expected } => {
                write!(
                    formatter,
                    "authenticated stream ended after {buffered} of {expected} bytes"
                )
            }
            Self::Session(error) => error.fmt(formatter),
        }
    }
}

impl Error for RecordStreamError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Session(error) => Some(error),
            Self::InvalidLimits
            | Self::InvalidPrefix
            | Self::SessionIdentityMismatch
            | Self::RecordLimit
            | Self::Allocation
            | Self::Terminated
            | Self::UnexpectedEof { .. } => None,
        }
    }
}

#[cfg(test)]
#[path = "record_stream_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "record_stream_budget_tests.rs"]
mod budget_tests;

#[cfg(test)]
#[path = "record_stream_output_tests.rs"]
mod output_tests;

#[cfg(test)]
#[path = "record_stream_retention_tests.rs"]
mod retention_tests;
