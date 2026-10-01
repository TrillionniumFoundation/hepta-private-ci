//! Work bounds for the existing blocking, offline/qualification frame reader.
//!
//! This wraps `stream::read_frame`; it is not a second parser or authenticator.
//! Live authenticated transports use their negotiated/managed session owner.

use std::error::Error;
use std::fmt;
use std::io;
use std::io::Read;

use crate::DecodedEnvelope;
use crate::MAX_WIRE_FRAME_BYTES;
use crate::ReadFrameError;

/// Non-cloneable work allowance that may be shared across blocking frame reads.
/// Every underlying read attempt is charged, including `Interrupted` failures.
/// Exhaustion does not refund partial I/O. Individual blocking calls still need
/// transport-owned deadlines; a call-count bound is not a wall-clock deadline.
#[derive(Debug)]
pub struct ReadFrameBudget {
    remaining_calls: usize,
    remaining_interrupts: usize,
}

impl Default for ReadFrameBudget {
    fn default() -> Self {
        // Permit one-byte delivery of a maximum-size frame, with a bounded
        // allowance for interruptions. No complete input chunk is required.
        Self::new(MAX_WIRE_FRAME_BYTES.saturating_add(32), 32)
    }
}

impl ReadFrameBudget {
    /// A zero allowance fails before touching the reader, not after consuming it.
    pub const fn new(read_calls: usize, interrupted_reads: usize) -> Self {
        Self {
            remaining_calls: read_calls,
            remaining_interrupts: interrupted_reads,
        }
    }

    pub const fn remaining_calls(&self) -> usize {
        self.remaining_calls
    }

    pub const fn remaining_interrupts(&self) -> usize {
        self.remaining_interrupts
    }
}

/// Structured cause stored inside `ReadFrameError::Io` on work exhaustion.
/// `bytes_read` is local to the current frame, even when the allowance is shared.
/// A partially read frame must not be retried as a fresh frame on that connection.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ReadFrameBudgetExceeded {
    pub bytes_read: usize,
    pub read_calls: usize,
    pub interrupted_reads: usize,
}

impl fmt::Display for ReadFrameBudgetExceeded {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "wire frame read budget exhausted after {} bytes, {} calls and {} interruptions",
            self.bytes_read, self.read_calls, self.interrupted_reads
        )
    }
}

impl Error for ReadFrameBudgetExceeded {}

struct BudgetedReader<'a, R: ?Sized> {
    reader: &'a mut R,
    budget: &'a mut ReadFrameBudget,
    progress: ReadFrameBudgetExceeded,
}

impl<R: Read + ?Sized> Read for BudgetedReader<'_, R> {
    fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
        if output.is_empty() {
            return Ok(0);
        }
        if self.budget.remaining_calls == 0 || self.budget.remaining_interrupts == 0 {
            return Err(io::Error::other(self.progress));
        }
        self.budget.remaining_calls -= 1;
        self.progress.read_calls += 1;
        match self.reader.read(output) {
            Ok(count) if count <= output.len() => {
                self.progress.bytes_read += count;
                Ok(count)
            }
            Ok(_) => Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "wire reader returned more bytes than requested",
            )),
            Err(error) if error.kind() == io::ErrorKind::Interrupted => {
                self.budget.remaining_interrupts -= 1;
                self.progress.interrupted_reads += 1;
                if self.budget.remaining_interrupts == 0 {
                    // Do not return Interrupted here: read_exact would retry it.
                    Err(io::Error::other(self.progress))
                } else {
                    Err(error)
                }
            }
            Err(error) => Err(error),
        }
    }
}

/// Read one offline/qualification frame through the canonical parser with
/// default work bounds. This does not authenticate a live peer or select a
/// negotiated version. Any error may follow partial consumption; discard the
/// affected read operation rather than blindly retrying it as a new frame.
pub fn read_frame<R: Read>(reader: &mut R) -> Result<DecodedEnvelope, ReadFrameError> {
    read_frame_with_budget(reader, &mut ReadFrameBudget::default())
}

/// Same public reader and parser, with a caller-owned aggregate work allowance.
/// Unlike incremental `feed`, this one-shot compatibility API cannot resume a
/// partially read frame after an error. Use incremental session feeds for fair,
/// resumable transport scheduling. Read deadlines remain the transport's job.
pub fn read_frame_with_budget<R: Read + ?Sized>(
    reader: &mut R,
    budget: &mut ReadFrameBudget,
) -> Result<DecodedEnvelope, ReadFrameError> {
    crate::stream::read_frame(&mut BudgetedReader {
        reader,
        budget,
        progress: ReadFrameBudgetExceeded {
            bytes_read: 0,
            read_calls: 0,
            interrupted_reads: 0,
        },
    })
}

#[cfg(test)]
#[path = "bounded_read_tests.rs"]
mod tests;
