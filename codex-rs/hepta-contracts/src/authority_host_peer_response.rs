//! One synchronous response on the original accepted channel. Application
//! authority remains in the caller; this owner supplies no grant or reconnect.
use super::HostAuthorityPeerCurrent;
use super::HostIssuerTransportError;
use super::io_error;
use rustix::event::PollFlags;
use std::cell::Cell;
use std::io;
use std::io::Write;

#[derive(Clone, Copy, PartialEq, Eq)]
enum ResponseState {
    Unsent,
    Entered,
    Complete,
}

/// The exact original frame, pidfd, socket and absolute deadline, borrowed only
/// for the synchronous handler. It is neither cloneable nor a serialized permit.
/// A private application fence can retain its locks through the actual writes.
pub struct HostAuthorityPeerResponse<'a> {
    current: HostAuthorityPeerCurrent<'a>,
    bound: usize,
    state: Cell<ResponseState>,
}

impl<'a> HostAuthorityPeerResponse<'a> {
    pub(super) fn new(current: HostAuthorityPeerCurrent<'a>, bound: usize) -> Self {
        Self {
            current,
            bound,
            state: Cell::new(ResponseState::Unsent),
        }
    }

    pub fn current(&self) -> &HostAuthorityPeerCurrent<'a> {
        &self.current
    }

    /// Send a complete, bounded frame once. The same synchronous fence runs
    /// after each potentially blocking writable poll and before each write,
    /// including the length prefix, and once after the final byte. A refusal
    /// or partial send cannot be resumed or converted to a successful response.
    pub fn write_response(
        &self,
        response: &[u8],
        mut fence: impl FnMut() -> Result<(), HostIssuerTransportError>,
    ) -> Result<(), HostIssuerTransportError> {
        if self.state.replace(ResponseState::Entered) != ResponseState::Unsent {
            return Err(HostIssuerTransportError::Closed);
        }
        if response.is_empty() || response.len() > self.bound {
            return Err(HostIssuerTransportError::Unavailable);
        }
        let mut stream = self.current.stream;
        let prefix = (response.len() as u32).to_be_bytes();
        for mut bytes in [prefix.as_slice(), response] {
            while !bytes.is_empty() {
                self.current
                    .owner
                    .wait(stream, PollFlags::OUT, self.current.deadline)?;
                self.current.owner.check(self.current.deadline)?;
                fence()?;
                // Even after an application check, retain the same monotonic
                // channel end and peer. No wait occurs between this and write.
                self.current.owner.check(self.current.deadline)?;
                let chunk = bytes.len().min(4096);
                match stream.write(&bytes[..chunk]) {
                    Ok(0) => return Err(HostIssuerTransportError::Closed),
                    Ok(count) => bytes = &bytes[count..],
                    Err(error)
                        if matches!(
                            error.kind(),
                            io::ErrorKind::Interrupted | io::ErrorKind::WouldBlock
                        ) => {}
                    Err(error) => return Err(io_error(error)),
                }
            }
        }
        fence()?;
        self.current.owner.check(self.current.deadline)?;
        self.state.set(ResponseState::Complete);
        Ok(())
    }

    pub(super) fn finish(&self) -> Result<(), HostIssuerTransportError> {
        if self.state.get() != ResponseState::Complete {
            return Err(HostIssuerTransportError::Unavailable);
        }
        self.current.owner.check(self.current.deadline)
    }
}
