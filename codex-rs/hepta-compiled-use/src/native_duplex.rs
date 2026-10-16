//! Canonical 256-byte action frames over a bounded, data-only byte stream.
//! Real kernel transport is possible; grants and OS effects remain external.

use crate::{
    ActionErrorV1, ActionFrameV1, ActionVerifierV1, VerifiedActionV1, ACTION_FRAME_BYTES_V1,
};
use std::error::Error as StdError;
use std::fmt;
use std::io::{Read, Write};

const MAX_SESSION_FRAMES: u64 = 4096;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FrameWireErrorV1 {
    InvalidBound,
    SequenceMismatch,
    LimitExceeded,
    Poisoned,
    Io(std::io::ErrorKind),
    Action(ActionErrorV1),
}

impl fmt::Display for FrameWireErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for FrameWireErrorV1 {}
impl From<ActionErrorV1> for FrameWireErrorV1 {
    fn from(value: ActionErrorV1) -> Self {
        Self::Action(value)
    }
}

/// A data-only session. No socket peer authenticity, machine code, UI effect
/// or credential authority is inferred from a successfully decoded frame.
pub struct FrameDuplexV1<T: Read + Write> {
    io: T,
    verifier: ActionVerifierV1,
    max_frames: u64,
    next_send: u64,
    next_receive: u64,
    poisoned: bool,
}

impl<T: Read + Write> FrameDuplexV1<T> {
    pub fn new(
        io: T,
        verifier: ActionVerifierV1,
        max_frames: u64,
    ) -> Result<Self, FrameWireErrorV1> {
        if verifier.generation == 0
            || !verifier.grant.is_well_formed()
            || max_frames == 0
            || max_frames > MAX_SESSION_FRAMES
        {
            return Err(FrameWireErrorV1::InvalidBound);
        }
        Ok(Self {
            io,
            verifier,
            max_frames,
            next_send: 1,
            next_receive: 1,
            poisoned: false,
        })
    }

    /// Validate before writing bytes; partial write errors poison this stream.
    pub fn send(&mut self, action: &ActionFrameV1) -> Result<(), FrameWireErrorV1> {
        if self.poisoned {
            return Err(FrameWireErrorV1::Poisoned);
        }
        if self.next_send > self.max_frames {
            return Err(FrameWireErrorV1::LimitExceeded);
        }
        self.verifier.verify(action)?;
        if action.sequence != self.next_send {
            return Err(FrameWireErrorV1::SequenceMismatch);
        }
        let next = self
            .next_send
            .checked_add(1)
            .ok_or(FrameWireErrorV1::LimitExceeded)?;
        let bytes = action.encode()?;
        if let Err(error) = self.io.write_all(&bytes).and_then(|_| self.io.flush()) {
            self.poisoned = true;
            return Err(FrameWireErrorV1::Io(error.kind()));
        }
        self.next_send = next;
        Ok(())
    }

    /// Read exactly one frame, check exact generation/capability/sequence;
    /// malformed or partial input poisons the stream, never reaches a sandbox.
    pub fn receive(&mut self) -> Result<VerifiedActionV1, FrameWireErrorV1> {
        if self.poisoned {
            return Err(FrameWireErrorV1::Poisoned);
        }
        if self.next_receive > self.max_frames {
            return Err(FrameWireErrorV1::LimitExceeded);
        }
        let mut bytes = [0_u8; ACTION_FRAME_BYTES_V1];
        if let Err(error) = self.io.read_exact(&mut bytes) {
            self.poisoned = true;
            return Err(FrameWireErrorV1::Io(error.kind()));
        }
        let checked = ActionFrameV1::decode(&bytes)
            .map_err(FrameWireErrorV1::Action)
            .and_then(|action| {
                self.verifier
                    .verify_and_bind(&action)
                    .map_err(FrameWireErrorV1::Action)
            });
        let checked = match checked {
            Ok(action) => action,
            Err(error) => {
                self.poisoned = true;
                return Err(error);
            }
        };
        if checked.frame().sequence != self.next_receive {
            self.poisoned = true;
            return Err(FrameWireErrorV1::SequenceMismatch);
        }
        self.next_receive = self
            .next_receive
            .checked_add(1)
            .ok_or(FrameWireErrorV1::LimitExceeded)?;
        Ok(checked)
    }

    #[must_use]
    pub fn is_poisoned(&self) -> bool {
        self.poisoned
    }
}

#[cfg(test)]
#[path = "native_duplex_tests.rs"]
mod tests;
