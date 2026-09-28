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

/// Frames before a terminal suffix remain deliverable, exactly once.
#[must_use = "deliver the accepted prefix before acting on the terminal error"]
pub struct RecordStreamBatch {
    frames: Vec<DecodedEnvelope>,
    terminal_error: Option<RecordStreamError>,
    yielded: bool,
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
        })
    }
}

impl ManagedRecordStream {
    pub fn buffered_bytes(&self) -> usize {
        self.pending.len()
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

    pub fn feed(&mut self, input: &[u8]) -> DecodeFeed<RecordStreamBatch> {
        let mut batch = RecordStreamBatch {
            frames: Vec::new(),
            terminal_error: None,
            yielded: false,
        };
        if self.is_terminal() {
            batch.terminal_error = Some(RecordStreamError::Terminated);
            return DecodeFeed::new(batch, 0);
        }
        let budget = input.len().min(self.limits.max_feed_bytes);
        let mut consumed = 0;
        while consumed < budget && batch.frames.len() < self.limits.max_records_per_feed {
            let target = self.expected.unwrap_or(PREFIX_BYTES);
            let count = (target - self.pending.len()).min(budget - consumed);
            if self.pending.try_reserve_exact(target - self.pending.len()).is_err() {
                batch.terminal_error = Some(RecordStreamError::Allocation);
                break;
            }
            self.pending.extend_from_slice(&input[consumed..consumed + count]);
            consumed += count;
            if self.pending.len() != target {
                continue;
            }
            if self.expected.is_none() {
                if self.pending[..4] != *b"HPTM" || self.pending[4..6] != [0, 1] {
                    batch.terminal_error = Some(RecordStreamError::InvalidPrefix);
                    break;
                }
                let length = u32::from_be_bytes([
                    self.pending[46], self.pending[47], self.pending[48], self.pending[49],
                ]);
                let Ok(length) = usize::try_from(length) else {
                    batch.terminal_error = Some(RecordStreamError::RecordLimit);
                    break;
                };
                if !(WIRE_HEADER_BYTES..=MAX_WIRE_FRAME_BYTES).contains(&length)
                    || length > self.limits.max_record_bytes - PREFIX_BYTES - TAG_BYTES
                {
                    batch.terminal_error = Some(RecordStreamError::RecordLimit);
                    break;
                }
                self.expected = Some(PREFIX_BYTES + length + TAG_BYTES);
                continue;
            }
            match self.owner.open_record(&self.pending) {
                Ok(frame) => batch.frames.push(frame),
                Err(error) => {
                    batch.terminal_error = Some(RecordStreamError::Session(error));
                    break;
                }
            }
            self.pending.clear();
            self.expected = None;
        }
        if batch.terminal_error.is_some() {
            self.retire();
        } else {
            batch.yielded = consumed < input.len();
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
            .field("terminal", &self.is_terminal())
            .finish()
    }
}

#[derive(Debug)]
pub enum RecordStreamError {
    InvalidLimits,
    InvalidPrefix,
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
            Self::RecordLimit => formatter.write_str("authenticated record exceeds admission bounds"),
            Self::Allocation => formatter.write_str("authenticated stream allocation failed"),
            Self::Terminated => formatter.write_str("authenticated stream is terminal"),
            Self::UnexpectedEof { buffered, expected } => {
                write!(formatter, "authenticated stream ended after {buffered} of {expected} bytes")
            }
            Self::Session(error) => error.fmt(formatter),
        }
    }
}

impl Error for RecordStreamError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Session(error) => Some(error),
            Self::InvalidLimits | Self::InvalidPrefix | Self::RecordLimit | Self::Allocation
            | Self::Terminated | Self::UnexpectedEof { .. } => None,
        }
    }
}

#[cfg(test)]
#[path = "record_stream_tests.rs"]
mod tests;
