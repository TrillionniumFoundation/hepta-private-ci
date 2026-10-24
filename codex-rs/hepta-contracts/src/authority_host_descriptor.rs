//! A terminal capability transfer on the already pinned original peer channel.
//! This carries one existing FD; it creates no identity, lease or authority.

use super::HostAuthorityPeerChannel;
use super::HostIssuerTransportError;
use super::io_error;
use rustix::event::PollFlags;
use rustix::net::RecvAncillaryBuffer;
use rustix::net::RecvAncillaryMessage;
use rustix::net::RecvFlags;
use rustix::net::ReturnFlags;
use rustix::net::SendAncillaryBuffer;
use rustix::net::SendAncillaryMessage;
use rustix::net::SendFlags;
use std::io::IoSlice;
use std::io::IoSliceMut;
use std::mem::MaybeUninit;
use std::net::Shutdown;
use std::os::fd::AsFd;
use std::os::fd::OwnedFd;

const MARKER: u8 = 0xa7;

impl HostAuthorityPeerChannel {
    /// Transfer exactly one already-held capability after the original framed
    /// handshake, then close this channel. The peer's original pidfd and the
    /// existing request/session deadlines bound the syscall. Error never
    /// rearms the channel or restores the caller's send opportunity.
    pub fn send_one_descriptor(mut self, descriptor: OwnedFd) -> Result<(), HostIssuerTransportError> {
        let stream = self.stream.take().ok_or(HostIssuerTransportError::Closed)?;
        let deadline = self.owner.deadline(self.policy.timeout);
        let result = (|| {
            loop {
                self.owner.wait(&stream, PollFlags::OUT, deadline)?;
                self.owner.check(deadline)?;
                let descriptors = [descriptor.as_fd()];
                let mut space = [MaybeUninit::uninit(); rustix::cmsg_space!(ScmRights(1))];
                let mut control = SendAncillaryBuffer::new(&mut space);
                if !control.push(SendAncillaryMessage::ScmRights(&descriptors)) {
                    return Err(HostIssuerTransportError::InvalidConfiguration);
                }
                match rustix::net::sendmsg(&stream, &[IoSlice::new(&[MARKER])], &mut control, SendFlags::NOSIGNAL) {
                    Ok(1) => break,
                    Ok(_) => return Err(HostIssuerTransportError::Unavailable),
                    Err(rustix::io::Errno::INTR | rustix::io::Errno::AGAIN) => continue,
                    Err(error) => return Err(io_error(error)),
                }
            }
            self.owner.check(deadline)
        })();
        let _ = stream.shutdown(Shutdown::Both);
        result
    }

    /// Receive exactly one terminal marker and FD from the same original
    /// pinned peer, then require EOF within the same absolute deadline. Extra
    /// rights/bytes, truncation, owner exit or an unclosed sender fail closed;
    /// all received capabilities close on every error, and no reconnect exists.
    pub fn receive_one_descriptor(mut self) -> Result<OwnedFd, HostIssuerTransportError> {
        let mut stream = self.stream.take().ok_or(HostIssuerTransportError::Closed)?;
        let deadline = self.owner.deadline(self.policy.timeout);
        let result = (|| {
            let descriptor = loop {
                self.owner.wait(&stream, PollFlags::IN, deadline)?;
                self.owner.check(deadline)?;
                let mut byte = [0_u8];
                let mut buffers = [IoSliceMut::new(&mut byte)];
                // A bounded surplus lets us explicitly close unwanted rights;
                // the kernel closes rights discarded on ancillary truncation.
                let mut space = [MaybeUninit::uninit(); rustix::cmsg_space!(ScmRights(8))];
                let mut control = RecvAncillaryBuffer::new(&mut space);
                let message = match rustix::net::recvmsg(&stream, &mut buffers, &mut control, RecvFlags::CMSG_CLOEXEC) {
                    Ok(message) => message,
                    Err(rustix::io::Errno::INTR | rustix::io::Errno::AGAIN) => continue,
                    Err(error) => return Err(io_error(error)),
                };
                let mut descriptors = Vec::new();
                let mut valid = true;
                for ancillary in control.drain() {
                    match ancillary {
                        RecvAncillaryMessage::ScmRights(rights) => descriptors.extend(rights),
                        _ => valid = false,
                    }
                }
                if !valid || message.bytes != 1 || byte != [MARKER]
                    || message.flags.intersects(ReturnFlags::CTRUNC | ReturnFlags::TRUNC)
                    || descriptors.len() != 1
                {
                    return Err(HostIssuerTransportError::Unavailable);
                }
                break descriptors.pop().ok_or(HostIssuerTransportError::Unavailable)?;
            };
            let mut trailing = [0_u8];
            if self.owner.read(&mut stream, &mut trailing, deadline)? != 0 {
                return Err(HostIssuerTransportError::Unavailable);
            }
            self.owner.check(deadline)?;
            Ok(descriptor)
        })();
        let _ = stream.shutdown(Shutdown::Both);
        result
    }
}

#[cfg(test)]
#[path = "authority_host_descriptor_tests.rs"]
mod tests;
